"""
speaker_extractor.py — Speaker embedding extraction for VoiceGuard.

Uses SpeechBrain ECAPA-TDNN (spkrec-ecapa-voxceleb) to compute
192-dimensional speaker identity embeddings.

These embeddings are used for:
  1. Cross-session speaker consistency checking
  2. Speaker enrollment (building reference profiles)
  3. Identity anomaly detection (enrolled vs. current speaker)

Graceful degradation: returns zero-vector if SpeechBrain unavailable.
"""

from __future__ import annotations

import logging
import os
import tempfile
import numpy as np
from typing import List, Optional

logger = logging.getLogger(__name__)

_ECAPA_MODEL = None
_ECAPA_AVAILABLE = False
_ECAPA_LOAD_ATTEMPTED = False
_SPEECHBRAIN_AVAILABLE = False

try:
    import speechbrain  # noqa: F401
    _SPEECHBRAIN_AVAILABLE = True
except ImportError:
    logger.warning("SpeechBrain not available — speaker embeddings disabled.")

_TORCH_AVAILABLE = False
try:
    import torch
    _TORCH_AVAILABLE = True
except ImportError:
    pass

_SOUNDFILE_AVAILABLE = False
try:
    import soundfile as sf
    _SOUNDFILE_AVAILABLE = True
except ImportError:
    pass


def _load_ecapa(model_name: str = "speechbrain/spkrec-ecapa-voxceleb") -> bool:
    """Lazy-load ECAPA-TDNN model from SpeechBrain."""
    global _ECAPA_MODEL, _ECAPA_AVAILABLE, _ECAPA_LOAD_ATTEMPTED

    if _ECAPA_LOAD_ATTEMPTED:
        return _ECAPA_AVAILABLE

    _ECAPA_LOAD_ATTEMPTED = True

    if not _SPEECHBRAIN_AVAILABLE or not _TORCH_AVAILABLE:
        logger.warning("SpeechBrain or torch not available — ECAPA disabled.")
        return False

    try:
        from speechbrain.inference.speaker import EncoderClassifier

        savedir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "backend", "models", "weights", "ecapa_tdnn"
        )
        os.makedirs(savedir, exist_ok=True)

        logger.info(f"Loading ECAPA-TDNN model: {model_name} (may download on first run)...")
        _ECAPA_MODEL = EncoderClassifier.from_hparams(
            source=model_name,
            savedir=savedir,
            run_opts={"device": "cpu"},
        )
        _ECAPA_AVAILABLE = True
        logger.info("ECAPA-TDNN speaker model loaded successfully.")
        return True
    except Exception as exc:
        logger.error(f"Failed to load ECAPA-TDNN: {exc}. Speaker embeddings disabled.")
        _ECAPA_AVAILABLE = False
        return False


def get_speaker_embedding_dim() -> int:
    """Return speaker embedding dimension."""
    return 192  # ECAPA-TDNN embedding size


def extract_speaker_embedding(
    audio: np.ndarray,
    sr: int = 16000,
    model_name: str = "speechbrain/spkrec-ecapa-voxceleb",
) -> np.ndarray:
    """
    Extract a 192-dimensional ECAPA speaker embedding.

    Args:
        audio:      float32 mono waveform at 16kHz
        sr:         sample rate
        model_name: SpeechBrain model identifier

    Returns:
        np.ndarray shape [192], float32
        Returns zeros if unavailable.
    """
    if not _load_ecapa(model_name):
        return np.zeros(192, dtype=np.float32)

    if not _SOUNDFILE_AVAILABLE:
        logger.warning("soundfile required for ECAPA embedding — returning zeros.")
        return np.zeros(192, dtype=np.float32)

    try:
        import torch

        # SpeechBrain needs a temporary file — write to memory-mapped temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
            sf.write(tmp_path, audio, sr)

        with torch.no_grad():
            embedding = _ECAPA_MODEL.encode_file(tmp_path)

        os.unlink(tmp_path)  # Privacy: delete temp file immediately

        emb_np = embedding.squeeze().cpu().numpy()
        return emb_np.astype(np.float32)

    except Exception as exc:
        logger.error(f"ECAPA embedding failed: {exc}")
        return np.zeros(192, dtype=np.float32)


def average_embeddings(embeddings: List[np.ndarray]) -> np.ndarray:
    """
    Average a list of speaker embeddings into a single profile embedding.
    Used during speaker enrollment.
    """
    if not embeddings:
        return np.zeros(192, dtype=np.float32)
    stacked = np.vstack([e.reshape(1, -1) for e in embeddings])
    return stacked.mean(axis=0).astype(np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """
    Compute cosine similarity between two embedding vectors.
    Returns value in [-1, 1]; higher = more similar speaker.
    """
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a < 1e-8 or norm_b < 1e-8:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def preload_ecapa(model_name: str = "speechbrain/spkrec-ecapa-voxceleb") -> bool:
    """Eagerly load ECAPA model at application startup."""
    return _load_ecapa(model_name)


def is_ecapa_available() -> bool:
    return _ECAPA_AVAILABLE
