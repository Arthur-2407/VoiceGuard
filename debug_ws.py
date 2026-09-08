"""
debug_ws.py — Manual pipeline test script for VoiceGuard.

Tests the streaming detection pipeline by simulating what the WebSocket
endpoint receives from the frontend: float32 audio converted to int16 bytes.

Usage:
  cd d:\\SIH\\voiceguard
  python debug_ws.py [path/to/audio.wav]

If no audio file is supplied, attempts to use the first .wav file found
under the data/ directory. If none exists, generates synthetic silence
as a fallback for pipeline smoke-testing.
"""

import sys
import os
from pathlib import Path

import numpy as np

# Add project root to PYTHONPATH
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Fixed C5: function is get_settings, not load_settings
from backend.config import get_settings
from backend.audio.capture import StreamCapture
from backend.audio.preprocessor import load_audio, normalize
from backend.detection.detector import VoiceCloneDetector
from backend.features.feature_fusion import extract_all_features


def _find_test_audio() -> str | None:
    """Locate a test audio file without hardcoding paths."""
    # 1. Command-line argument
    if len(sys.argv) > 1:
        path = sys.argv[1]
        if os.path.isfile(path):
            return path
        print(f"[WARN] Specified file not found: {path}")

    # 2. First WAV file in data/
    data_dir = _PROJECT_ROOT / "data"
    if data_dir.exists():
        for wav in sorted(data_dir.glob("**/*.wav")):
            return str(wav)
        for mp3 in sorted(data_dir.glob("**/*.mp3")):
            return str(mp3)

    return None


def main():
    settings = get_settings()
    detector = VoiceCloneDetector(settings)

    audio_path = _find_test_audio()

    if audio_path:
        print(f"[INFO] Using audio: {audio_path}")
        real_audio, sr = load_audio(audio_path, 16000)
    else:
        print("[WARN] No test audio file found — using 2s of synthetic silence.")
        sr = 16000
        real_audio = np.zeros(sr * 2, dtype=np.float32)

    # Simulate browser capture: float32 → int16 bytes → WebSocket
    # (app.js does: int16[i] = Math.max(-32768, Math.min(32767, float32[i] * 32768)))
    int16_audio = np.clip(real_audio * 32768, -32768, 32767).astype(np.int16)
    ws_bytes = int16_audio.tobytes()

    stream = StreamCapture(
        sample_rate=16000,
        chunk_sec=2.0,
        overlap_ratio=0.5,
        src_dtype="int16",
        channels=1,
    )

    chunks = stream.push(ws_bytes)
    print(f"[INFO] Produced {len(chunks)} chunk(s) from WebSocket bytes.")

    for i, chunk in enumerate(chunks[:2]):
        chunk_norm = normalize(chunk, method="peak")

        bundle = extract_all_features(
            chunk_norm, 16000,
            use_wav2vec2=False,
            use_speaker_embedding=False,
        )

        score = detector._heuristic_score(bundle)

        print(f"Chunk {i}:")
        print(f"  Max amp:     {np.max(np.abs(chunk_norm)):.4f}")
        print(f"  F0 mean:     {bundle.prosodic[0]:.2f}")
        print(f"  Jitter:      {bundle.prosodic[2]:.4f}")
        print(f"  HNR:         {bundle.prosodic[4]:.2f}")
        print(f"  MFCC Var:    {np.mean(np.var(bundle.mfcc_seq[:, :13], axis=0)):.2f}")
        print(f"  Score:       {score:.4f}")
        print(f"  Speaker emb: {'available' if bundle.speaker_emb_available else 'unavailable (ECAPA not loaded)'}")
        print(f"  Wav2Vec2:    {'available' if bundle.wav2vec2_emb_available else 'unavailable'}")


if __name__ == "__main__":
    main()
