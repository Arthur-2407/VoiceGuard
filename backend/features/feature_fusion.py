"""
feature_fusion.py — Combines all feature extractors into a unified feature vector.

The fused feature vector is composed of:
  [0:120]     MFCC + delta + delta2 (40 * 3 = 120)
  [120:200]   Log-Mel spectrogram mean (80)
  [200:207]   Prosodic features (7)
  [207:975]   Wav2Vec2 embedding (768) — if available, else zeros
  [975:1167]  Speaker (ECAPA) embedding (192) — if available, else zeros

Total: 1167-dim when all extractors available, always same shape.

Also provides the sequence representation for CNN-RNN input:
  Shape: [T, n_mels] log-mel sequences + mfcc sequences
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

from backend.features.mfcc_extractor import extract_mfcc, extract_mfcc_sequence
from backend.features.mel_extractor import extract_log_mel, extract_log_mel_sequence
from backend.features.prosodic_extractor import extract_prosodic_features
from backend.features.wav2vec_extractor import extract_wav2vec2
from backend.features.speaker_extractor import extract_speaker_embedding


@dataclass
class FeatureBundle:
    """
    Container for all features extracted from a single audio chunk.

    fused_vector:       flat concatenated feature vector for non-sequence models
    mfcc_seq:           [T, 120] MFCC sequence for RNN input
    mel_seq:            [T, 80] log-Mel sequence for CNN input
    wav2vec2_emb:       [768] or [T', 768] Wav2Vec2 embedding
    speaker_emb:        [192] ECAPA speaker embedding
    prosodic:           [7] prosodic feature vector
    """
    fused_vector: np.ndarray
    mfcc_seq: np.ndarray
    mel_seq: np.ndarray
    wav2vec2_emb: np.ndarray
    speaker_emb: np.ndarray
    prosodic: np.ndarray


def extract_all_features(
    audio: np.ndarray,
    sr: int = 16000,
    n_mfcc: int = 40,
    n_mels: int = 80,
    hop_length: int = 160,
    win_length: int = 400,
    wav2vec2_model_name: str = "facebook/wav2vec2-base",
    ecapa_model_name: str = "speechbrain/spkrec-ecapa-voxceleb",
    use_wav2vec2: bool = True,
    use_speaker_embedding: bool = True,
    device: Optional[str] = None,
) -> FeatureBundle:
    """
    Run the complete feature extraction pipeline for one audio chunk.

    Args:
        audio:                  float32 mono waveform at target sr
        sr:                     sample rate
        n_mfcc:                 MFCC coefficient count
        n_mels:                 Mel filter bank count
        hop_length:             hop size in samples
        win_length:             analysis window in samples
        wav2vec2_model_name:    HuggingFace model identifier
        ecapa_model_name:       SpeechBrain model identifier
        use_wav2vec2:           whether to extract Wav2Vec2 embeddings
        use_speaker_embedding:  whether to extract ECAPA speaker embeddings
        device:                 torch device; None = auto

    Returns:
        FeatureBundle with all extracted features
    """
    # 1. MFCC (mean-pooled) → [3*n_mfcc]
    mfcc_vec = extract_mfcc(
        audio, sr=sr, n_mfcc=n_mfcc,
        hop_length=hop_length, win_length=win_length,
        mean_pool=True,
    )  # [120]

    # 2. MFCC sequence → [T, 3*n_mfcc]
    mfcc_seq = extract_mfcc_sequence(
        audio, sr=sr, n_mfcc=n_mfcc,
        hop_length=hop_length, win_length=win_length,
    )  # [T, 120]

    # 3. Log-Mel (mean-pooled) → [n_mels]
    mel_vec = extract_log_mel(
        audio, sr=sr, n_mels=n_mels,
        hop_length=hop_length, win_length=win_length,
        mean_pool=True,
    )  # [80]

    # 4. Log-Mel sequence → [T, n_mels]
    mel_seq = extract_log_mel_sequence(
        audio, sr=sr, n_mels=n_mels,
        hop_length=hop_length, win_length=win_length,
    )  # [T, 80]

    # 5. Prosodic features → [7]
    prosodic = extract_prosodic_features(audio, sr=sr, hop_length=hop_length)

    # 6. Wav2Vec2 (mean-pooled) → [768]
    if use_wav2vec2:
        wav2vec2_emb = extract_wav2vec2(
            audio, sr=sr, model_name=wav2vec2_model_name,
            device=device, mean_pool=True,
        )
    else:
        wav2vec2_emb = np.zeros(768, dtype=np.float32)

    # 7. ECAPA speaker embedding → [192]
    if use_speaker_embedding:
        speaker_emb = extract_speaker_embedding(
            audio, sr=sr, model_name=ecapa_model_name,
        )
    else:
        speaker_emb = np.zeros(192, dtype=np.float32)

    # 8. Fuse into single vector
    fused_vector = np.concatenate([
        mfcc_vec,        # [120]
        mel_vec,         # [80]
        prosodic,        # [7]
        wav2vec2_emb,    # [768]
        speaker_emb,     # [192]
    ]).astype(np.float32)  # [1167]

    return FeatureBundle(
        fused_vector=fused_vector,
        mfcc_seq=mfcc_seq,
        mel_seq=mel_seq,
        wav2vec2_emb=wav2vec2_emb,
        speaker_emb=speaker_emb,
        prosodic=prosodic,
    )


FUSED_FEATURE_DIM = 1167  # 120 + 80 + 7 + 768 + 192
MFCC_SEQ_DIM = 120         # 40 * 3 (mfcc + delta + delta2)
MEL_SEQ_DIM = 80
WAV2VEC_DIM = 768
SPEAKER_EMB_DIM = 192
PROSODIC_DIM = 7
