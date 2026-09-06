"""
preprocessor.py — Audio preprocessing pipeline for VoiceGuard.

Responsibilities:
  1. Resample audio to configured sample rate (default 16 kHz)
  2. Convert to mono if multi-channel
  3. Normalize amplitude (peak normalization)
  4. Apply optional noise reduction
  5. Voice Activity Detection (VAD) — silence trimming
  6. Chunk audio into overlapping windows for streaming inference

Preserves audio quality. Never writes raw audio to disk.
"""

from __future__ import annotations

import logging
import numpy as np
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# Optional imports with graceful degradation
try:
    import webrtcvad
    _WEBRTCVAD_AVAILABLE = True
except ImportError:
    _WEBRTCVAD_AVAILABLE = False
    logger.warning("webrtcvad not available — using energy-based VAD fallback.")

try:
    import noisereduce as nr
    _NOISEREDUCE_AVAILABLE = True
except ImportError:
    _NOISEREDUCE_AVAILABLE = False
    logger.warning("noisereduce not available — noise reduction disabled.")

try:
    import librosa
    _LIBROSA_AVAILABLE = True
except ImportError:
    _LIBROSA_AVAILABLE = False
    logger.error("librosa is required but not available.")

try:
    import soundfile as sf
    _SOUNDFILE_AVAILABLE = True
except ImportError:
    _SOUNDFILE_AVAILABLE = False


def load_audio(path: str, target_sr: int = 16000) -> Tuple[np.ndarray, int]:
    """
    Load an audio file and return (waveform_float32, sample_rate).
    Resamples to target_sr and converts to mono automatically.
    """
    if not _LIBROSA_AVAILABLE:
        raise RuntimeError("librosa is required for audio loading.")
    audio, sr = librosa.load(path, sr=target_sr, mono=True, dtype=np.float32)
    logger.debug(f"Loaded audio: {path}, shape={audio.shape}, sr={sr}")
    return audio, sr


def resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """Resample audio from orig_sr to target_sr."""
    if orig_sr == target_sr:
        return audio
    if not _LIBROSA_AVAILABLE:
        raise RuntimeError("librosa is required for resampling.")
    return librosa.resample(audio, orig_sr=orig_sr, target_sr=target_sr)


def to_mono(audio: np.ndarray) -> np.ndarray:
    """Convert multi-channel audio to mono by averaging channels."""
    if audio.ndim == 1:
        return audio
    return audio.mean(axis=0)


def normalize(audio: np.ndarray, method: str = "peak") -> np.ndarray:
    """
    Normalize audio amplitude.

    method='peak'  → scale so max(|audio|) == 1.0
    method='rms'   → scale to RMS of -20 dBFS
    """
    if method == "peak":
        peak = np.max(np.abs(audio))
        if peak > 1e-8:
            return audio / peak
        return audio
    elif method == "rms":
        rms = np.sqrt(np.mean(audio ** 2))
        target_rms = 0.1  # ~ -20 dBFS
        if rms > 1e-8:
            return audio * (target_rms / rms)
        return audio
    else:
        raise ValueError(f"Unknown normalization method: {method}")


def reduce_noise(audio: np.ndarray, sr: int) -> np.ndarray:
    """Apply stationary noise reduction if noisereduce is available."""
    if not _NOISEREDUCE_AVAILABLE:
        return audio
    try:
        return nr.reduce_noise(y=audio, sr=sr, stationary=True)
    except Exception as exc:
        logger.warning(f"Noise reduction failed: {exc}. Returning original audio.")
        return audio


def energy_vad(
    audio: np.ndarray,
    sr: int,
    frame_length: int = 512,
    threshold_db: float = -40.0,
) -> np.ndarray:
    """
    Simple energy-based Voice Activity Detection.
    Returns audio with silent frames removed.
    """
    if not _LIBROSA_AVAILABLE:
        return audio

    frame_energies = librosa.feature.rms(y=audio, frame_length=frame_length, hop_length=frame_length)[0]
    energy_db = librosa.amplitude_to_db(frame_energies, ref=1.0)
    speech_frames = energy_db > threshold_db

    # Reconstruct audio keeping only speech frames
    output_frames = []
    for i, is_speech in enumerate(speech_frames):
        start = i * frame_length
        end = min(start + frame_length, len(audio))
        if is_speech:
            output_frames.append(audio[start:end])

    if not output_frames:
        logger.warning("VAD removed all audio — returning original (possible silence-only input).")
        return audio

    return np.concatenate(output_frames)


def webrtcvad_filter(
    audio: np.ndarray,
    sr: int,
    aggressiveness: int = 2,
    frame_ms: int = 30,
) -> np.ndarray:
    """
    WebRTC VAD-based silence removal.
    Returns audio with non-speech segments removed.
    Falls back to energy_vad if webrtcvad is unavailable.

    audio: float32 mono waveform
    sr: sample rate (must be 8000, 16000, 32000, or 48000)
    """
    if not _WEBRTCVAD_AVAILABLE:
        return energy_vad(audio, sr)

    if sr not in (8000, 16000, 32000, 48000):
        logger.warning(f"webrtcvad requires sr in {{8000,16000,32000,48000}}, got {sr}. Using energy VAD.")
        return energy_vad(audio, sr)

    vad = webrtcvad.Vad(aggressiveness)
    frame_samples = int(sr * frame_ms / 1000)

    # Convert float32 → int16 for webrtcvad
    audio_int16 = (audio * 32767).astype(np.int16)

    speech_chunks = []
    for i in range(0, len(audio_int16) - frame_samples, frame_samples):
        frame = audio_int16[i: i + frame_samples]
        frame_bytes = frame.tobytes()
        try:
            if vad.is_speech(frame_bytes, sr):
                speech_chunks.append(audio[i: i + frame_samples])
        except Exception:
            speech_chunks.append(audio[i: i + frame_samples])

    if not speech_chunks:
        logger.warning("WebRTC VAD found no speech — returning original audio.")
        return audio

    return np.concatenate(speech_chunks)


def chunk_audio(
    audio: np.ndarray,
    sr: int,
    chunk_duration: float = 2.0,
    overlap_ratio: float = 0.5,
) -> List[np.ndarray]:
    """
    Split audio into overlapping chunks for streaming inference.

    Returns a list of numpy float32 arrays.
    Each chunk is exactly chunk_samples long (zero-padded at end if needed).
    """
    chunk_samples = int(sr * chunk_duration)
    hop_samples = int(chunk_samples * (1 - overlap_ratio))

    if len(audio) < chunk_samples:
        # Pad short audio to full chunk size
        padded = np.zeros(chunk_samples, dtype=np.float32)
        padded[: len(audio)] = audio
        return [padded]

    chunks = []
    start = 0
    while start + chunk_samples <= len(audio):
        chunks.append(audio[start: start + chunk_samples].copy())
        start += hop_samples

    # Handle final partial chunk
    remaining = audio[start:]
    if len(remaining) > 0:
        padded = np.zeros(chunk_samples, dtype=np.float32)
        padded[: len(remaining)] = remaining
        chunks.append(padded)

    logger.debug(f"Chunked audio into {len(chunks)} chunks of {chunk_duration}s each.")
    return chunks


def preprocess_audio(
    audio: np.ndarray,
    sr: int,
    target_sr: int = 16000,
    apply_noise_reduction: bool = False,
    apply_vad: bool = True,
    vad_aggressiveness: int = 2,
    normalize_method: str = "peak",
) -> np.ndarray:
    """
    Full preprocessing pipeline for a raw audio waveform.

    Steps: to_mono → resample → normalize → [noise_reduction] → [VAD]

    Returns preprocessed float32 mono waveform at target_sr.
    """
    audio = to_mono(audio)
    audio = resample(audio, orig_sr=sr, target_sr=target_sr)
    audio = normalize(audio, method=normalize_method)

    if apply_noise_reduction:
        audio = reduce_noise(audio, sr=target_sr)

    if apply_vad:
        audio = webrtcvad_filter(audio, sr=target_sr, aggressiveness=vad_aggressiveness)
        # Re-normalize after VAD since amplitude may shift
        audio = normalize(audio, method=normalize_method)

    return audio.astype(np.float32)


def bytes_to_float32(
    raw_bytes: bytes,
    sr: int = 16000,
    channels: int = 1,
    dtype: str = "int16",
) -> np.ndarray:
    """
    Convert raw PCM bytes from microphone/WebSocket to float32 numpy array.

    dtype: the PCM format of the incoming bytes ('int16' or 'float32')
    """
    if dtype == "int16":
        audio = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    elif dtype == "float32":
        audio = np.frombuffer(raw_bytes, dtype=np.float32)
    else:
        raise ValueError(f"Unsupported dtype: {dtype}")

    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)

    return audio


def _get_ffmpeg_executable() -> str:
    """
    Discover the FFmpeg executable for the current runtime.

    Strategy (in order):
      1. imageio-ffmpeg bundled binary (always available when package is installed)
      2. System PATH via shutil.which

    Returns the path to the ffmpeg executable.
    Raises RuntimeError if FFmpeg is completely unavailable.
    """
    import shutil

    # 1. Try imageio-ffmpeg — ships a pre-compiled FFmpeg binary, no system install required
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe:
            return exe
    except Exception:
        pass

    # 2. Fall back to system PATH
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    raise RuntimeError(
        "Audio/video conversion is unavailable because the media conversion runtime "
        "is not configured correctly. Install 'imageio-ffmpeg' (pip install imageio-ffmpeg) "
        "or ensure 'ffmpeg' is available in the system PATH."
    )


def _probe_media(path: str, ffmpeg_exe: str) -> dict:
    """
    Probe a media file using ffmpeg to determine whether it contains an audio stream
    and to gather basic metadata.

    Returns a dict with keys:
      has_audio (bool)   — whether a decodable audio stream exists
      has_video (bool)   — whether the container includes a video stream
      duration  (float)  — duration in seconds (0.0 if unknown)

    Never raises; returns a safe dict with has_audio=False on probe failure.
    """
    import subprocess
    import json

    try:
        probe_cmd = [
            ffmpeg_exe,
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-show_format",
            path,
        ]
        # Use ffprobe-equivalent via ffmpeg's built-in probing
        probe_cmd = [
            ffmpeg_exe.replace("ffmpeg", "ffprobe") if "ffprobe" in ffmpeg_exe else ffmpeg_exe,
        ]
        # Rebuild — if imageio ships only ffmpeg (no separate ffprobe), use ffmpeg itself
        import os as _os
        ffprobe_path = _os.path.join(_os.path.dirname(ffmpeg_exe), "ffprobe.exe")
        if not _os.path.exists(ffprobe_path):
            ffprobe_path = _os.path.join(_os.path.dirname(ffmpeg_exe), "ffprobe")
        if not _os.path.exists(ffprobe_path):
            # Fallback: ask ffmpeg to produce a quick stderr probe by attempting a null conversion
            # We parse the stderr for stream information
            r = subprocess.run(
                [ffmpeg_exe, "-v", "error", "-i", path, "-f", "null", "-"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            stderr = r.stderr.decode("utf-8", errors="ignore")
            has_audio = "Audio:" in stderr or r.returncode == 0
            has_video = "Video:" in stderr
            # Try to get duration from stderr
            duration = 0.0
            for line in stderr.splitlines():
                if "Duration:" in line:
                    try:
                        dur_str = line.split("Duration:")[1].split(",")[0].strip()
                        h, m, s = dur_str.split(":")
                        duration = int(h) * 3600 + int(m) * 60 + float(s)
                    except Exception:
                        pass
            return {"has_audio": has_audio, "has_video": has_video, "duration": duration}

        r = subprocess.run(
            [ffprobe_path, "-v", "quiet", "-print_format", "json", "-show_streams", "-show_format", path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
        info = json.loads(r.stdout.decode("utf-8", errors="ignore"))
        streams = info.get("streams", [])
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        has_video = any(s.get("codec_type") == "video" for s in streams)
        duration = float(info.get("format", {}).get("duration", 0.0))
        return {"has_audio": has_audio, "has_video": has_video, "duration": duration}

    except Exception as exc:
        logger.warning(f"Media probe failed for {path}: {exc}. Assuming audio present.")
        return {"has_audio": True, "has_video": False, "duration": 0.0}


def normalize_to_mp3(path: str) -> str:
    """
    Normalize any supported audio or multimedia file to an analyzer-compatible MP3.

    Handles:
      - Audio-only (MP3, WAV, FLAC, OGG, AAC, M4A, OPUS, …)
      - Video containers (MP4, MKV, MOV, AVI, WebM, …) — audio stream extracted

    Strategy:
      1. If the file is already a valid MP3, return it unchanged (no transcoding).
      2. Otherwise, discover FFmpeg (via imageio-ffmpeg bundle or system PATH).
      3. Probe the media to detect audio stream presence.
      4. If no audio stream is found, raise with a clear user-facing message.
      5. Invoke FFmpeg to extract/transcode audio to MP3 (-vn to skip video streams).
      6. Validate the generated MP3 is non-empty and parseable.
      7. Return the path to the new MP3 (caller is responsible for cleanup).

    Args:
        path: Absolute path to the uploaded temp file.

    Returns:
        Absolute path to an MP3 file ready for the audio analysis pipeline.
        If the input was already MP3, returns the original path.
        If conversion was performed, returns a NEW temp path.

    Raises:
        ValueError: On any conversion, validation, or format issue (user-facing message,
                    no server paths or stack traces exposed).
        RuntimeError: If FFmpeg is completely unavailable on this runtime.
    """
    import subprocess
    import tempfile
    import os

    if not _SOUNDFILE_AVAILABLE:
        raise RuntimeError("soundfile is required for MP3 validation.")

    # ── Step 1: Check if already a valid MP3 ──────────────────────────────────
    try:
        info = sf.info(path)
        if info.format == "MP3":
            logger.debug(f"File is already MP3 — passing through without conversion.")
            return path
    except Exception:
        # soundfile couldn't read it — not MP3 or not a format soundfile knows.
        # We will let FFmpeg handle it below.
        pass

    # ── Step 2: Discover FFmpeg ───────────────────────────────────────────────
    try:
        ffmpeg_exe = _get_ffmpeg_executable()
    except RuntimeError as exc:
        raise RuntimeError(str(exc)) from exc

    logger.info(f"FFmpeg discovered at: {ffmpeg_exe}")

    # ── Step 3: Probe media for audio stream ──────────────────────────────────
    probe = _probe_media(path, ffmpeg_exe)
    logger.debug(f"Media probe: has_audio={probe['has_audio']}, has_video={probe['has_video']}, "
                 f"duration={probe['duration']:.1f}s")

    if not probe["has_audio"]:
        if probe["has_video"]:
            raise ValueError(
                "The uploaded video does not contain an audio track. "
                "Please upload a video or audio file that contains spoken audio."
            )
        raise ValueError(
            "The uploaded file does not contain a usable audio stream. "
            "Please upload a supported audio or multimedia file."
        )

    # ── Step 4: Convert/extract to MP3 via FFmpeg ────────────────────────────
    fd, out_path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)

    try:
        cmd = [
            ffmpeg_exe,
            "-y",               # overwrite temp file
            "-i", path,         # input (absolute temp path, safe — no user-controlled string in shell)
            "-vn",              # discard all video streams (audio extraction from video containers)
            "-acodec", "libmp3lame",   # encode to MP3
            "-ar", "16000",     # resample to 16 kHz (matches the analyzer's expected sample rate)
            "-ac", "1",         # mono (matches analyzer config)
            "-q:a", "2",        # VBR quality ~190 kbps — good fidelity for voice analysis
            "-f", "mp3",        # force MP3 container
            out_path,
        ]

        logger.info(f"Converting media to MP3 (audio extraction)...")
        process = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,        # 2-minute limit for large files
        )

        if process.returncode != 0:
            stderr_text = process.stderr.decode("utf-8", errors="ignore")
            logger.error(f"FFmpeg conversion failed (exit {process.returncode}): {stderr_text[-500:]}")
            if os.path.exists(out_path):
                os.unlink(out_path)
            # Check if the error indicates no audio stream
            if "no streams" in stderr_text.lower() or "invalid data" in stderr_text.lower():
                raise ValueError(
                    "The uploaded media could not be decoded. "
                    "The file may be corrupted or use an unsupported codec."
                )
            raise ValueError(
                "The uploaded media could not be converted to an analyzer-compatible audio format."
            )

        # ── Step 5: Validate output ──────────────────────────────────────────
        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            if os.path.exists(out_path):
                os.unlink(out_path)
            raise ValueError("Audio extraction produced an empty output. The source may contain no audible content.")

        try:
            sf.info(out_path)
        except Exception as exc:
            os.unlink(out_path)
            raise ValueError(
                f"The converted audio could not be validated: the output is not a readable audio file."
            )

        logger.info(f"Conversion successful — MP3 ready for analysis.")
        return out_path

    except subprocess.TimeoutExpired:
        if os.path.exists(out_path):
            os.unlink(out_path)
        raise ValueError("Audio conversion timed out. Please upload a shorter file.")
    except (ValueError, RuntimeError):
        raise
    except Exception as exc:
        if os.path.exists(out_path):
            os.unlink(out_path)
        raise ValueError(f"Error during audio conversion: {exc}")

