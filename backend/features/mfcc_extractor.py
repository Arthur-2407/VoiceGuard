"""
mfcc_extractor.py — MFCC feature extraction for VoiceGuard.

Extracts:
  - MFCC coefficients (default: 40)
  - Delta (velocity) features
  - Delta-delta (acceleration) features

Output shape: [3 * n_mfcc, time_frames]
Flattened to [n_features] for fusion.
"""

from __future__ import annotations

import logging
import numpy as np
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import librosa
    _LIBROSA_AVAILABLE = True
except ImportError:
    _LIBROSA_AVAILABLE = False
    logger.error("librosa required for MFCC extraction.")


def extract_mfcc(
    audio: np.ndarray,
    sr: int = 16000,
    n_mfcc: int = 40,
    n_fft: int = 512,
    hop_length: int = 160,
    win_length: int = 400,
    window: str = "hann",
    include_delta: bool = True,
    include_delta2: bool = True,
    mean_pool: bool = True,
) -> np.ndarray:
    """
    Extract MFCC features from a mono float32 audio chunk.

    Args:
        audio:          float32 mono waveform
        sr:             sample rate (Hz)
        n_mfcc:         number of MFCC coefficients
        n_fft:          FFT window size in samples
        hop_length:     hop size in samples (10ms @ 16kHz = 160)
        win_length:     analysis window in samples (25ms @ 16kHz = 400)
        include_delta:  include first-order delta features
        include_delta2: include second-order delta-delta features
        mean_pool:      if True, return mean over time → flat vector;
                        if False, return full [n_coeffs, T] matrix

    Returns:
        np.ndarray: feature vector or matrix depending on mean_pool
    """
    if not _LIBROSA_AVAILABLE:
        raise RuntimeError("librosa is required for MFCC extraction.")

    if len(audio) == 0:
        n_total = n_mfcc * (1 + int(include_delta) + int(include_delta2))
        logger.warning("Empty audio chunk passed to MFCC extractor; returning zeros.")
        return np.zeros(n_total, dtype=np.float32)

    mfcc = librosa.feature.mfcc(
        y=audio,
        sr=sr,
        n_mfcc=n_mfcc,
        n_fft=n_fft,
        hop_length=hop_length,
        win_length=win_length,
        window=window,
    )  # shape: [n_mfcc, T]

    features = [mfcc]

    if include_delta:
        delta = librosa.feature.delta(mfcc)
        features.append(delta)

    if include_delta2:
        delta2 = librosa.feature.delta(mfcc, order=2)
        features.append(delta2)

    stacked = np.vstack(features)  # [n_mfcc * num_feat_types, T]

    if mean_pool:
        return stacked.mean(axis=1).astype(np.float32)

    return stacked.astype(np.float32)


def extract_mfcc_sequence(
    audio: np.ndarray,
    sr: int = 16000,
    n_mfcc: int = 40,
    hop_length: int = 160,
    win_length: int = 400,
) -> np.ndarray:
    """
    Return MFCC as a full temporal sequence [T, n_mfcc] for RNN input.
    Includes deltas stacked to [T, 3*n_mfcc].
    """
    mfcc = librosa.feature.mfcc(
        y=audio, sr=sr, n_mfcc=n_mfcc,
        hop_length=hop_length, win_length=win_length,
    )  # [n_mfcc, T]
    delta = librosa.feature.delta(mfcc)
    delta2 = librosa.feature.delta(mfcc, order=2)
    stacked = np.vstack([mfcc, delta, delta2])  # [3*n_mfcc, T]
    return stacked.T.astype(np.float32)  # [T, 3*n_mfcc]
