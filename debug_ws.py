import numpy as np
from backend.audio.capture import StreamCapture
from backend.audio.preprocessor import load_audio, normalize, to_mono, resample
from backend.detection.detector import VoiceCloneDetector
from backend.config import load_settings
from backend.features.feature_fusion import extract_all_features

settings = load_settings()
detector = VoiceCloneDetector(settings)

# Simulate microphone audio (say, a real file)
real_audio, sr = load_audio("d:\\SIH\\preview_rvc_e6e4419f.wav", 16000)

# Simulate browser capture: float32 -> int16 bytes -> WebSocket
# app.js does: int16[i] = Math.max(-32768, Math.min(32767, float32[i] * 32768));
int16_audio = np.clip(real_audio * 32768, -32768, 32767).astype(np.int16)
ws_bytes = int16_audio.tobytes()

stream = StreamCapture(
    sample_rate=16000,
    chunk_sec=2.0,
    overlap_ratio=0.5,
    src_dtype="int16",
    channels=1
)

chunks = stream.push(ws_bytes)
print(f"Produced {len(chunks)} chunks from WebSocket bytes.")

for i, chunk in enumerate(chunks[:2]):
    # Routes_stream.py logic
    chunk_norm = normalize(chunk, method="peak")
    
    bundle = extract_all_features(chunk_norm, 16000, use_wav2vec2=False, use_speaker_embedding=False)
    
    score = detector._heuristic_score(bundle)
    
    print(f"Chunk {i}:")
    print(f"  Max amp: {np.max(np.abs(chunk_norm))}")
    print(f"  F0 mean: {bundle.prosodic[0]:.2f}")
    print(f"  Jitter: {bundle.prosodic[2]:.4f}")
    print(f"  HNR: {bundle.prosodic[4]:.2f}")
    print(f"  MFCC Var: {np.mean(np.var(bundle.mfcc_seq[:, 13:40], axis=0)):.2f}")
    print(f"  Score: {score}")

