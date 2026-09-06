"""
model_loader.py — Load and manage VoiceGuard detection models.

Handles:
  1. Loading pre-trained weights from .pt files
  2. Creating fresh model instances (for demo with random weights)
  3. Device management (auto, cpu, cuda)
  4. Weight download coordination
  5. Model caching (loaded once, reused)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_TORCH_AVAILABLE = False
try:
    import torch
    _TORCH_AVAILABLE = True
except ImportError:
    logger.error("PyTorch not available — model loading disabled.")

_LOADED_MODEL = None
_MODEL_DEVICE: Optional[str] = None


def resolve_device(device_cfg: str = "auto") -> str:
    """
    Resolve the actual torch device string from config.

    'auto' → 'cuda' if GPU available, else 'cpu'
    'cuda' → verified 'cuda' or fallback 'cpu'
    'cpu'  → 'cpu'
    """
    if not _TORCH_AVAILABLE:
        return "cpu"

    if device_cfg == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    elif device_cfg == "cuda":
        if torch.cuda.is_available():
            return "cuda"
        else:
            logger.warning("CUDA requested but not available — using CPU.")
            return "cpu"
    else:
        return "cpu"


def create_model(
    n_mels: int = 80,
    fused_dim: int = 1167,
    device: str = "cpu",
) -> "EnsembleDetector":
    """
    Instantiate a fresh EnsembleDetector (random weights).
    Used when no pre-trained weights exist.
    """
    from backend.models.cnn_rnn_detector import EnsembleDetector

    model = EnsembleDetector(n_mels=n_mels, fused_dim=fused_dim)
    model.to(device)
    model.eval()
    logger.info(f"Created new EnsembleDetector on device={device}")
    return model


def load_model(
    model_path: str,
    n_mels: int = 80,
    fused_dim: int = 1167,
    device_cfg: str = "auto",
) -> "EnsembleDetector":
    """
    Load detector model from .pt weights file.

    Falls back to creating a fresh model if the weights file doesn't exist.
    This allows the system to run immediately for demo purposes even without
    pre-trained weights (scores will be random but the pipeline will work).

    Args:
        model_path:  path to .pt weights file (relative to project root)
        n_mels:      mel bands (must match model trained with)
        fused_dim:   fused feature dimension
        device_cfg:  'auto' | 'cpu' | 'cuda'

    Returns:
        Loaded (or fresh) EnsembleDetector in eval mode.
    """
    global _LOADED_MODEL, _MODEL_DEVICE

    if not _TORCH_AVAILABLE:
        logger.warning("PyTorch is required to load the detection model. Returning None.")
        return None

    device = resolve_device(device_cfg)

    # Check if we already have the model loaded on the right device
    if _LOADED_MODEL is not None and _MODEL_DEVICE == device:
        return _LOADED_MODEL

    from backend.models.cnn_rnn_detector import EnsembleDetector

    model = EnsembleDetector(n_mels=n_mels, fused_dim=fused_dim)

    weights_path = Path(model_path)
    if not weights_path.is_absolute():
        # Resolve relative to project root
        project_root = Path(__file__).resolve().parent.parent.parent
        weights_path = project_root / model_path

    if weights_path.exists():
        try:
            state_dict = torch.load(weights_path, map_location=device, weights_only=True)
            model.load_state_dict(state_dict)
            logger.info(f"Loaded model weights from {weights_path}")
        except Exception as exc:
            logger.error(
                f"Failed to load weights from {weights_path}: {exc}. "
                "Returning None to trigger heuristic fallback."
            )
            return None
    else:
        logger.warning(
            f"Model weights not found at {weights_path}. "
            "Returning None to trigger genuine acoustic heuristic fallback. "
            "Run scripts/train_detector.py to train a model on ASVspoof."
        )
        return None

    model.to(device)
    model.eval()

    _LOADED_MODEL = model
    _MODEL_DEVICE = device

    return model


def get_loaded_model() -> Optional["EnsembleDetector"]:
    """Return the currently loaded model (or None if not yet loaded)."""
    return _LOADED_MODEL


def unload_model() -> None:
    """Release model from memory."""
    global _LOADED_MODEL, _MODEL_DEVICE
    _LOADED_MODEL = None
    _MODEL_DEVICE = None
    if _TORCH_AVAILABLE:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    logger.info("Model unloaded from memory.")
