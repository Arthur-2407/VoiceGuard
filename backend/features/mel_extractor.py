"""
mel_extractor.py — Log-Mel spectrogram feature extraction for VoiceGuard.

Produces 80-band log-Mel spectrograms matching the hyperparameters described
in the 1802.06006v3 paper (Table 6) and IJERT detection system.

Default: 80 mel bands, 16kHz, hop=160, win=400.
"""

from __future__ import annotations

from typing import Optional

import logging
import numpy as np

logger = logging.getLogger(__name__)

try:
    import librosa
    _LIBROSA_AVAILABLE = True
except ImportError:
    _LIBROSA_AVAILABLE = False
    logger.error("librosa required for mel extraction.")


def extract_log_mel(
    audio: np.ndarray,
    sr: int = 16000,
    n_mels: int = 80,
    n_fft: int = 512,
    hop_length: int = 160,
    win_length: int = 400,
    fmin: float = 0.0,
    fmax: Optional[float] = None,
    mean_pool: bool = True,
) -> np.ndarray:
    """
    Compute log-Mel spectrogram from a float32 mono audio chunk.

    Args:
        audio:      float32 mono waveform
        sr:         sample rate
        n_mels:     number of Mel filter banks (80 per paper specs)
        n_fft:      FFT size
        hop_length: hop size in samples
        win_length: window size in samples
        fmin:       lowest frequency (Hz)
        fmax:       highest frequency (Hz); None → sr/2
        mean_pool:  if True, return mean over time → [n_mels] vector;
                    if False, return full [n_mels, T] matrix

    Returns:
        np.ndarray float32
    """
    if not _LIBROSA_AVAILABLE:
        raise RuntimeError("librosa is required for mel extraction.")

    if len(audio) == 0:
        logger.warning("Empty audio chunk — returning zero mel features.")
        return np.zeros(n_mels, dtype=np.float32)

    mel = librosa.feature.melspectrogram(
        y=audio,
        sr=sr,
        n_mels=n_mels,
        n_fft=n_fft,
        hop_length=hop_length,
        win_length=win_length,
        fmin=fmin,
        fmax=fmax,
    )  # [n_mels, T]  — linear scale

    log_mel = librosa.power_to_db(mel, ref=np.max)  # [n_mels, T]

    if mean_pool:
        return log_mel.mean(axis=1).astype(np.float32)  # [n_mels]

    return log_mel.astype(np.float32)  # [n_mels, T]


def extract_log_mel_sequence(
    audio: np.ndarray,
    sr: int = 16000,
    n_mels: int = 80,
    hop_length: int = 160,
    win_length: int = 400,
) -> np.ndarray:
    """
    Return full log-Mel spectrogram as [T, n_mels] for sequence model input.
    """
    log_mel = extract_log_mel(
        audio, sr=sr, n_mels=n_mels,
        hop_length=hop_length, win_length=win_length,
        mean_pool=False,
    )
    return log_mel.T.astype(np.float32)  # [T, n_mels]
