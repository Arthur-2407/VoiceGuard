import numpy as np
import librosa
from backend.audio.preprocessor import load_audio, normalize, bytes_to_float32
from backend.audio.capture import StreamCapture
from backend.features.feature_fusion import extract_all_features
from backend.detection.detector import VoiceCloneDetector

try:
    real_audio, sr = load_audio("d:\\SIH\\preview_rvc_e6e4419f.wav", 16000)
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
    print(f"Total chunks: {len(chunks)}")

    detector = VoiceCloneDetector(None)

    for i, chunk in enumerate(chunks[:3]):
        chunk_norm = normalize(chunk, method="peak")
        bundle = extract_all_features(chunk_norm, 16000, use_wav2vec2=False, use_speaker_embedding=False)
        
        hnr = bundle.prosodic[4]
        jitter = bundle.prosodic[2]
        
        mfcc_seq = bundle.mfcc_seq
        mfcc_high_var = float(np.mean(np.var(mfcc_seq[:, 13:40], axis=0)))
        
        score = detector._heuristic_score(bundle)
        
        print(f"Chunk {i}: hnr={hnr:.4f}, jitter={jitter:.4f}, mfcc_var={mfcc_high_var:.4f}, score={score}")
except Exception as e:
    print(e)
