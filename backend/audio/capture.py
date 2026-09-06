"""
capture.py — Audio capture module for VoiceGuard.

Supports:
  - Real-time microphone capture (sounddevice)
  - WAV/audio file loading
  - Raw bytes ingestion (from WebSocket clients)

All captures yield float32 mono arrays at target_sr.
Never stores raw audio to disk (privacy-preserving).
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
from pathlib import Path
from typing import AsyncGenerator, Callable, Generator, Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import sounddevice as sd
    _SOUNDDEVICE_AVAILABLE = True
except (ImportError, OSError):
    _SOUNDDEVICE_AVAILABLE = False
    logger.warning("sounddevice not available — microphone capture disabled.")

from backend.audio.preprocessor import load_audio, bytes_to_float32, preprocess_audio


class MicrophoneCapture:
    """
    Real-time microphone capture using sounddevice.

    Produces audio in fixed-size float32 chunks via a thread-safe queue.
    Usage:
        cap = MicrophoneCapture(sr=16000, chunk_sec=2.0)
        cap.start()
        for chunk in cap.iter_chunks():
            process(chunk)
        cap.stop()
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_sec: float = 2.0,
        device: Optional[int] = None,
    ):
        if not _SOUNDDEVICE_AVAILABLE:
            raise RuntimeError(
                "sounddevice is not available. Install it with: pip install sounddevice"
            )
        self.sample_rate = sample_rate
        self.chunk_samples = int(sample_rate * chunk_sec)
        self.device = device
        self._queue: queue.Queue[Optional[np.ndarray]] = queue.Queue(maxsize=32)
        self._stream: Optional[sd.InputStream] = None
        self._buffer = np.array([], dtype=np.float32)
        self._running = False

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            logger.warning(f"Sounddevice status: {status}")
        # indata shape: (frames, channels) — take first channel
        mono = indata[:, 0].copy()
        self._buffer = np.concatenate([self._buffer, mono])

        while len(self._buffer) >= self.chunk_samples:
            chunk = self._buffer[: self.chunk_samples].copy()
            self._buffer = self._buffer[self.chunk_samples :]
            try:
                self._queue.put_nowait(chunk)
            except queue.Full:
                logger.warning("Audio capture queue full — dropping chunk.")

    def start(self) -> None:
        """Begin capturing from microphone."""
        self._running = True
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            device=self.device,
            callback=self._callback,
            blocksize=1024,
        )
        self._stream.start()
        logger.info(f"Microphone capture started (sr={self.sample_rate}, chunk={self.chunk_samples} samples)")

    def stop(self) -> None:
        """Stop microphone capture."""
        self._running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._queue.put(None)  # Sentinel to unblock iter_chunks
        logger.info("Microphone capture stopped.")

    def iter_chunks(self) -> Generator[np.ndarray, None, None]:
        """Block and yield audio chunks as they become available."""
        while self._running:
            chunk = self._queue.get(timeout=5.0)
            if chunk is None:
                break
            yield chunk

    async def aiter_chunks(self) -> AsyncGenerator[np.ndarray, None]:
        """Async generator version for use in FastAPI WebSocket handlers."""
        loop = asyncio.get_event_loop()
        while self._running:
            chunk = await loop.run_in_executor(None, self._queue.get)
            if chunk is None:
                break
            yield chunk

    @staticmethod
    def list_devices() -> list:
        """Return available audio input devices."""
        if not _SOUNDDEVICE_AVAILABLE:
            return []
        devices = sd.query_devices()
        inputs = [
            {"index": i, "name": d["name"], "channels": d["max_input_channels"]}
            for i, d in enumerate(devices)
            if d["max_input_channels"] > 0
        ]
        return inputs


class FileCapture:
    """
    Load audio from a file path or bytes object and yield chunks.

    Used for the /analyze endpoint and testing.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_sec: float = 2.0,
        overlap_ratio: float = 0.5,
    ):
        self.sample_rate = sample_rate
        self.chunk_sec = chunk_sec
        self.overlap_ratio = overlap_ratio

    def from_path(self, path: str) -> list[np.ndarray]:
        """Load an audio file and return list of float32 chunks."""
        from backend.audio.preprocessor import preprocess_audio, chunk_audio
        audio, sr = load_audio(path, target_sr=self.sample_rate)
        audio = preprocess_audio(
            audio, sr=self.sample_rate, target_sr=self.sample_rate,
            apply_vad=True, apply_noise_reduction=False,
        )
        return chunk_audio(audio, self.sample_rate, self.chunk_sec, self.overlap_ratio)

    def from_bytes(
        self,
        raw_bytes: bytes,
        src_sr: int = 16000,
        pcm_dtype: str = "int16",
        channels: int = 1,
    ) -> list[np.ndarray]:
        """Convert raw PCM bytes to chunks."""
        from backend.audio.preprocessor import preprocess_audio, chunk_audio
        audio = bytes_to_float32(raw_bytes, sr=src_sr, channels=channels, dtype=pcm_dtype)
        audio = preprocess_audio(
            audio, sr=src_sr, target_sr=self.sample_rate,
            apply_vad=True,
        )
        return chunk_audio(audio, self.sample_rate, self.chunk_sec, self.overlap_ratio)


class StreamCapture:
    """
    Accumulate audio bytes arriving over WebSocket and produce chunks
    when enough data has been buffered.

    Thread-safe. Designed for use in async FastAPI WebSocket handlers.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_sec: float = 2.0,
        overlap_ratio: float = 0.5,
        src_dtype: str = "int16",
        channels: int = 1,
    ):
        self.sample_rate = sample_rate
        self.chunk_samples = int(sample_rate * chunk_sec)
        self.hop_samples = int(self.chunk_samples * (1 - overlap_ratio))
        self.src_dtype = src_dtype
        self.channels = channels
        self._buffer = np.array([], dtype=np.float32)

    def push(self, raw_bytes: bytes) -> list[np.ndarray]:
        """
        Push raw PCM bytes into the buffer.
        Returns any complete chunks ready for inference.
        """
        audio = bytes_to_float32(
            raw_bytes, sr=self.sample_rate,
            channels=self.channels, dtype=self.src_dtype,
        )
        self._buffer = np.concatenate([self._buffer, audio])

        ready_chunks = []
        while len(self._buffer) >= self.chunk_samples:
            chunk = self._buffer[: self.chunk_samples].copy()
            ready_chunks.append(chunk)
            self._buffer = self._buffer[self.hop_samples :]

        return ready_chunks

    def flush(self) -> Optional[np.ndarray]:
        """Return any remaining partial chunk (zero-padded) and reset buffer."""
        if len(self._buffer) == 0:
            return None
        padded = np.zeros(self.chunk_samples, dtype=np.float32)
        padded[: len(self._buffer)] = self._buffer
        self._buffer = np.array([], dtype=np.float32)
        return padded

    def reset(self) -> None:
        """Clear the internal buffer."""
        self._buffer = np.array([], dtype=np.float32)
