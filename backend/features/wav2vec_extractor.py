"""
wav2vec_extractor.py — Wav2Vec2 contextual embedding extraction.

Uses facebook/wav2vec2-base from HuggingFace Transformers as a frozen
feature extractor. This provides rich self-supervised speech representations
that are highly discriminative for detecting synthesis artifacts.

The model is downloaded on first use and cached locally.
Internet connection required only for the first run.

Graceful degradation: if transformers is unavailable, returns zero vectors.
"""

from __future__ import annotations

import logging
import numpy as np
from typing import Optional

logger = logging.getLogger(__name__)

_WAV2VEC2_MODEL = None
_WAV2VEC2_PROCESSOR = None
_WAV2VEC2_AVAILABLE = False
_WAV2VEC2_LOAD_ATTEMPTED = False

_TORCH_AVAILABLE = False
try:
    import torch
    _TORCH_AVAILABLE = True
except ImportError:
    logger.warning("torch not available — wav2vec2 features disabled.")


def _load_wav2vec2(model_name: str = "facebook/wav2vec2-base") -> bool:
    """
    Lazy-load Wav2Vec2 model and processor.
    Returns True if successful, False otherwise.
    """
    global _WAV2VEC2_MODEL, _WAV2VEC2_PROCESSOR, _WAV2VEC2_AVAILABLE, _WAV2VEC2_LOAD_ATTEMPTED

    if _WAV2VEC2_LOAD_ATTEMPTED:
        return _WAV2VEC2_AVAILABLE

    _WAV2VEC2_LOAD_ATTEMPTED = True

    if not _TORCH_AVAILABLE:
        logger.warning("torch not available — wav2vec2 cannot be loaded.")
        return False

    try:
        from transformers import Wav2Vec2Model, Wav2Vec2Processor
        logger.info(f"Loading Wav2Vec2 model: {model_name} (may download on first run)...")
        _WAV2VEC2_PROCESSOR = Wav2Vec2Processor.from_pretrained(model_name)
        _WAV2VEC2_MODEL = Wav2Vec2Model.from_pretrained(model_name)
        _WAV2VEC2_MODEL.eval()

        # Freeze all parameters (feature extraction only, no fine-tuning here)
        for param in _WAV2VEC2_MODEL.parameters():
            param.requires_grad = False

        _WAV2VEC2_AVAILABLE = True
        logger.info("Wav2Vec2 model loaded successfully.")
        return True
    except Exception as exc:
        logger.error(f"Failed to load Wav2Vec2: {exc}. Features will use MFCC+Mel only.")
        _WAV2VEC2_AVAILABLE = False
        return False


def get_wav2vec2_embedding_dim() -> int:
    """Return the embedding dimension of the loaded wav2vec2 model."""
    return 768  # wav2vec2-base hidden size


def extract_wav2vec2(
    audio: np.ndarray,
    sr: int = 16000,
    model_name: str = "facebook/wav2vec2-base",
    device: Optional[str] = None,
    mean_pool: bool = True,
) -> np.ndarray:
    """
    Extract Wav2Vec2 contextual embeddings from audio.

    Args:
        audio:      float32 mono waveform at 16kHz
        sr:         sample rate (must be 16000 for wav2vec2-base)
        model_name: HuggingFace model identifier
        device:     torch device string or None (auto-detect)
        mean_pool:  if True, return [768] mean vector;
                    if False, return [T', 768] sequence

    Returns:
        np.ndarray float32 — [768] if mean_pool else [T', 768]
        Returns zeros if wav2vec2 unavailable.
    """
    if not _load_wav2vec2(model_name):
        return np.zeros(768, dtype=np.float32)

    if sr != 16000:
        logger.warning(f"Wav2Vec2 requires 16kHz audio; got {sr}Hz. Results may be degraded.")

    try:
        import torch

        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"

        _WAV2VEC2_MODEL.to(device)

        inputs = _WAV2VEC2_PROCESSOR(
            audio,
            sampling_rate=16000,
            return_tensors="pt",
            padding=True,
        )

        input_values = inputs.input_values.to(device)

        with torch.no_grad():
            outputs = _WAV2VEC2_MODEL(input_values)
            hidden_states = outputs.last_hidden_state  # [1, T', 768]

        embeddings = hidden_states.squeeze(0).cpu().numpy()  # [T', 768]

        if mean_pool:
            return embeddings.mean(axis=0).astype(np.float32)  # [768]

        return embeddings.astype(np.float32)  # [T', 768]

    except Exception as exc:
        logger.error(f"Wav2Vec2 inference failed: {exc}")
        if mean_pool:
            return np.zeros(768, dtype=np.float32)
        return np.zeros((1, 768), dtype=np.float32)


def preload_wav2vec2(model_name: str = "facebook/wav2vec2-base") -> bool:
    """
    Eagerly load wav2vec2 at application startup.
    Call this from FastAPI startup event.
    """
    return _load_wav2vec2(model_name)


def is_wav2vec2_available() -> bool:
    """Check if wav2vec2 has been successfully loaded."""
    return _WAV2VEC2_AVAILABLE
