"""
test_pipeline.py — Integration test for the complete VoiceGuard detection pipeline.

Tests:
  1. Audio preprocessing
  2. Feature extraction (MFCC, log-mel, prosodic)
  3. Feature fusion
  4. Model inference (detector)
  5. Risk engine
  6. Threshold engine
  7. Alert system

Run with:
  cd d:\\SIH\\voiceguard
  python scripts/test_pipeline.py
"""

import sys
import logging
from pathlib import Path
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test_pipeline")

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PASS = "✓"
FAIL = "✗"

results = []


def run_test_fn(name, fn):
    try:
        fn()
        logger.info(f"{PASS} {name}")
        results.append((name, True, None))
    except Exception as exc:
        logger.error(f"{FAIL} {name}: {exc}")
        results.append((name, False, str(exc)))


def make_synthetic_audio(duration_sec=2.0, sr=16000, freq=440):
    """Generate a synthetic sine-wave audio chunk for testing."""
    t = np.linspace(0, duration_sec, int(sr * duration_sec), dtype=np.float32)
    audio = 0.3 * np.sin(2 * np.pi * freq * t)
    return audio


# ── Test 1: Preprocessor ──────────────────────────────────────────────────────
def test_preprocessor():
    from backend.audio.preprocessor import normalize, chunk_audio, to_mono
    audio = make_synthetic_audio()
    norm = normalize(audio)
    assert abs(np.max(np.abs(norm)) - 1.0) < 0.01, "Normalization failed"
    chunks = chunk_audio(audio, sr=16000, chunk_duration=2.0, overlap_ratio=0.5)
    assert len(chunks) >= 1, "Chunking produced no chunks"
    assert chunks[0].shape[0] == 32000, f"Chunk wrong size: {chunks[0].shape}"


# ── Test 2: MFCC ─────────────────────────────────────────────────────────────
def test_mfcc():
    from backend.features.mfcc_extractor import extract_mfcc
    audio = make_synthetic_audio()
    feat = extract_mfcc(audio, sr=16000, n_mfcc=40, mean_pool=True)
    assert feat.shape == (120,), f"MFCC shape wrong: {feat.shape}"
    assert not np.any(np.isnan(feat)), "MFCC contains NaN"


# ── Test 3: Log-Mel ───────────────────────────────────────────────────────────
def test_log_mel():
    from backend.features.mel_extractor import extract_log_mel
    audio = make_synthetic_audio()
    feat = extract_log_mel(audio, sr=16000, n_mels=80, mean_pool=True)
    assert feat.shape == (80,), f"Log-mel shape wrong: {feat.shape}"
    assert not np.any(np.isnan(feat)), "Log-mel contains NaN"


# ── Test 4: Prosodic ──────────────────────────────────────────────────────────
def test_prosodic():
    from backend.features.prosodic_extractor import extract_prosodic_features
    audio = make_synthetic_audio(freq=200)
    feat = extract_prosodic_features(audio, sr=16000)
    assert feat.shape == (7,), f"Prosodic shape wrong: {feat.shape}"
    assert not np.any(np.isnan(feat)), "Prosodic contains NaN"


# ── Test 5: Feature Fusion ────────────────────────────────────────────────────
def test_feature_fusion():
    from backend.features.feature_fusion import extract_all_features, FUSED_FEATURE_DIM
    audio = make_synthetic_audio()
    bundle = extract_all_features(
        audio, sr=16000,
        use_wav2vec2=False,      # Skip download in tests
        use_speaker_embedding=False,
    )
    assert bundle.fused_vector is not None, "Fused vector is None"
    assert bundle.mel_seq is not None, "mel_seq is None"
    assert not np.any(np.isnan(bundle.fused_vector[:207])), "Fused vector (no wav2vec) has NaN"


# ── Test 6: CNN-RNN Model ─────────────────────────────────────────────────────
def test_cnn_rnn_model():
    try:
        import torch
    except ImportError:
        logger.warning("torch not available, skipping model test")
        return

    from backend.models.cnn_rnn_detector import EnsembleDetector
    model = EnsembleDetector(n_mels=80, fused_dim=1167)
    model.eval()

    mel_in  = torch.zeros(1, 200, 80)  # [batch, time, n_mels]
    fuse_in = torch.zeros(1, 1167)      # [batch, fused_dim]
    with torch.no_grad():
        prob = model.predict_proba(mel_in, fuse_in)
    assert prob.shape == (1, 1), f"Model output shape wrong: {prob.shape}"
    val = prob.item()
    assert 0.0 <= val <= 1.0, f"Model output out of range: {val}"


# ── Test 7: Risk Engine ───────────────────────────────────────────────────────
def test_risk_engine():
    from backend.detection.risk_engine import RiskEngine, RiskEngineConfig, AlertLevel
    cfg = RiskEngineConfig(window_size=3, threshold_low=0.35, threshold_medium=0.6, threshold_high=0.8)
    engine = RiskEngine(cfg)

    s1 = engine.update(chunk_id=0, detection_score=0.1)
    assert s1.alert_level == AlertLevel.SAFE, f"Expected SAFE, got {s1.alert_level}"

    s2 = engine.update(chunk_id=1, detection_score=0.9)
    s3 = engine.update(chunk_id=2, detection_score=0.9)
    assert s3.alert_level in (AlertLevel.LOW, AlertLevel.MEDIUM, AlertLevel.HIGH), f"Expected LOW/HIGH/MEDIUM: {s3.alert_level}"


# ── Test 8: Threshold Engine ──────────────────────────────────────────────────
def test_threshold_engine():
    from backend.detection.threshold_engine import ThresholdEngine
    # Use explicit threshold_critical so test behavior is deterministic
    engine = ThresholdEngine(
        threshold_low=0.35,
        threshold_medium=0.6,
        threshold_high=0.8,
        threshold_critical=0.95,
    )

    r_safe     = engine.evaluate(0.1)
    r_high     = engine.evaluate(0.9)     # 0.8 <= 0.9 < 0.95 → HIGH
    r_critical = engine.evaluate(0.97)    # 0.97 >= 0.95 → CRITICAL

    assert r_safe.alert_level.value     == "SAFE",     f"Expected SAFE, got {r_safe.alert_level}"
    assert r_high.alert_level.value     == "HIGH",     f"Expected HIGH, got {r_high.alert_level}"
    assert r_critical.alert_level.value == "CRITICAL", f"Expected CRITICAL, got {r_critical.alert_level}"
    assert len(r_high.actions) > 0,     "HIGH alert should have actions"
    assert len(r_critical.actions) > 0, "CRITICAL alert should have actions"


# ── Test 9: Speaker Consistency ───────────────────────────────────────────────
def test_speaker_consistency():
    from backend.detection.speaker_consistency import SpeakerConsistencyChecker
    checker = SpeakerConsistencyChecker(threshold=0.75)

    ref_emb  = np.ones(192, dtype=np.float32)
    same_emb = np.ones(192, dtype=np.float32) * 0.99
    diff_emb = np.zeros(192, dtype=np.float32)

    checker.set_enrolled_profile(ref_emb, speaker_id="test")
    res_same = checker.check(same_emb)
    res_diff = checker.check(diff_emb)

    assert res_same["is_consistent"] == True, "Same speaker should be consistent"
    assert res_diff["is_consistent"] == False, "Zero vector should be inconsistent"


# ── Run all tests ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("VoiceGuard Pipeline Integration Tests")
    logger.info("=" * 60)

    test("Audio Preprocessor",   test_preprocessor)
    test("MFCC Extractor",       test_mfcc)
    test("Log-Mel Extractor",    test_log_mel)
    test("Prosodic Extractor",   test_prosodic)
    test("Feature Fusion",       test_feature_fusion)
    test("CNN-RNN Model",        test_cnn_rnn_model)
    test("Risk Engine",          test_risk_engine)
    test("Threshold Engine",     test_threshold_engine)
    test("Speaker Consistency",  test_speaker_consistency)

    logger.info("=" * 60)
    passed = sum(1 for _, ok, _ in results if ok)
    logger.info(f"Results: {passed}/{len(results)} tests passed")

    failed = [(n, e) for n, ok, e in results if not ok]
    if failed:
        logger.error("Failed tests:")
        for name, err in failed:
            logger.error(f"  {name}: {err}")
        sys.exit(1)
    else:
        logger.info("All tests passed! ✓")
        sys.exit(0)
