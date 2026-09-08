"""
download_models.py — Downloads/verifies pre-trained models for VoiceGuard.

Downloads:
  1. facebook/wav2vec2-base — from HuggingFace (cached via transformers)
  2. speechbrain/spkrec-ecapa-voxceleb — ECAPA speaker embeddings

The CNN-RNN detector weights are initialized randomly for demo purposes.
For production, train using scripts/train_detector.py on ASVspoof2019.

Usage:
  cd d:\\SIH\\voiceguard
  python scripts/download_models.py
"""

import os
import sys
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("download_models")

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

WEIGHTS_DIR = Path(__file__).resolve().parent.parent / "backend" / "models" / "weights"
WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)


def download_wav2vec2():
    logger.info("Downloading Wav2Vec2 model (facebook/wav2vec2-base)...")
    try:
        from transformers import Wav2Vec2Model, Wav2Vec2Processor
        logger.info("  Downloading processor...")
        Wav2Vec2Processor.from_pretrained("facebook/wav2vec2-base")
        logger.info("  Downloading model weights...")
        Wav2Vec2Model.from_pretrained("facebook/wav2vec2-base")
        logger.info("✓ Wav2Vec2 downloaded and cached.")
        return True
    except Exception as exc:
        logger.error(f"✗ Wav2Vec2 download failed: {exc}")
        return False


def download_ecapa():
    logger.info("Downloading ECAPA-TDNN speaker model (speechbrain/spkrec-ecapa-voxceleb)...")
    try:
        from speechbrain.inference.speaker import EncoderClassifier
        savedir = str(WEIGHTS_DIR / "ecapa_tdnn")
        os.makedirs(savedir, exist_ok=True)
        EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir=savedir,
            run_opts={"device": "cpu"},
        )
        logger.info("✓ ECAPA-TDNN downloaded.")
        return True
    except Exception as exc:
        logger.error(f"✗ ECAPA-TDNN download failed: {exc}")
        return False





if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("VoiceGuard Model Downloader")
    logger.info("=" * 60)

    results = {}
    results["wav2vec2"]  = download_wav2vec2()
    results["ecapa"]     = download_ecapa()


    logger.info("=" * 60)
    logger.info("Download Summary:")
    for name, ok in results.items():
        logger.info(f"  {name:20s} {'✓ OK' if ok else '✗ FAILED'}")

    # Use dynamic path so the script works from any installation location
    _project_root = Path(__file__).resolve().parent.parent

    if not all(results.values()):
        logger.warning(
            "\nSome downloads failed. The system will still run with graceful fallbacks.\n"
            "Check your internet connection and retry."
        )
    else:
        logger.info("\nAll models ready. Run the server with:")
        logger.info(f"  cd {_project_root}")
        logger.info(f"  python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000")

