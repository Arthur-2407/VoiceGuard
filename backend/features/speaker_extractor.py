"""
speaker_extractor.py — Speaker embedding extraction for VoiceGuard.

Uses SpeechBrain ECAPA-TDNN (spkrec-ecapa-voxceleb) to compute
192-dimensional speaker identity embeddings.

These embeddings are used for:
  1. Cross-session speaker consistency checking
  2. Speaker enrollment (building reference profiles)
  3. Identity anomaly detection (enrolled vs. current speaker)

Graceful degradation: returns None if SpeechBrain unavailable or extraction fails.
The caller must handle None to avoid treating feature-unavailability as a mismatch.
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
) -> Optional[np.ndarray]:
    """
    Extract a 192-dimensional ECAPA speaker embedding.

    Args:
        audio:      float32 mono waveform at 16kHz
        sr:         sample rate
        model_name: SpeechBrain model identifier

    Returns:
        np.ndarray shape [192], float32 on success.
        None if ECAPA is unavailable or extraction fails.
        Callers MUST handle None to avoid false speaker-mismatch penalties.
    """
    if not _load_ecapa(model_name):
        # ECAPA unavailable — return None to signal "feature not available",
        # NOT zeros, which would be mistaken for a real embedding.
        return None

    if not _SOUNDFILE_AVAILABLE:
        logger.warning("soundfile required for ECAPA embedding — returning None.")
        return None

    tmp_path: Optional[str] = None
    try:
        import torch

        # SpeechBrain needs a temporary WAV file.
        # Use delete=False so we control deletion explicitly in the finally block.
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
            sf.write(tmp_path, audio, sr)

        with torch.no_grad():
            embedding = _ECAPA_MODEL.encode_file(tmp_path)

        emb_np = embedding.squeeze().cpu().numpy()
        return emb_np.astype(np.float32)

    except Exception as exc:
        logger.error(f"ECAPA embedding failed: {exc}")
        return None
    finally:
        # Privacy: always delete temp file, even if an exception occurred above.
        if tmp_path is not None and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError as unlink_exc:
                logger.warning(f"Failed to delete ECAPA temp file {tmp_path}: {unlink_exc}")


def is_zero_embedding(emb: Optional[np.ndarray]) -> bool:
    """
    Return True if the embedding is None or all-zeros.
    Used to detect ECAPA failure cases that returned zeros in legacy callers.
    """
    if emb is None:
        return True
    return bool(np.linalg.norm(emb) < 1e-8)


def average_embeddings(embeddings: List[np.ndarray]) -> np.ndarray:
    """
    Average a list of valid speaker embeddings into a single profile embedding.
    Used during speaker enrollment.
    Raises ValueError if embeddings list is empty.
    """
    if not embeddings:
        raise ValueError("Cannot average an empty list of embeddings.")
    stacked = np.vstack([e.reshape(1, -1) for e in embeddings])
    return stacked.mean(axis=0).astype(np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """
    Compute cosine similarity between two embedding vectors.
    Returns value in [-1, 1]; higher = more similar speaker.
    Returns 0.0 if either vector is degenerate (zero-norm).
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
