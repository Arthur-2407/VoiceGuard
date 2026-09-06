import numpy as np
from backend.audio.preprocessor import load_audio, preprocess_audio, chunk_audio
from backend.features.feature_fusion import extract_all_features
import json

def analyze_file(filepath):
    audio, sr = load_audio(filepath, 16000)
    audio = preprocess_audio(audio, sr=16000, target_sr=16000, apply_vad=True)
    chunks = chunk_audio(audio, 16000, 2.0, 0.5)
    
    results = []
    for chunk in chunks:
        bundle = extract_all_features(
            chunk, 16000, n_mfcc=40, n_mels=80,
            hop_length=160, win_length=400,
            use_wav2vec2=False, use_speaker_embedding=False, device="cpu"
        )
        prosodic = bundle.prosodic
        mfcc = bundle.mfcc_seq  # [T, 120]
        
        res = {
            "f0_mean": float(prosodic[0]),
            "f0_std": float(prosodic[1]),
            "jitter": float(prosodic[2]),
            "shimmer": float(prosodic[3]),
            "hnr": float(prosodic[4]),
            "zcr": float(prosodic[5]),
            "energy": float(prosodic[6]),
            # Calculate variance of higher-order MFCCs (13-39) across time
            "mfcc_high_var": float(np.mean(np.var(mfcc[:, 13:40], axis=0))),
            # High frequency energy in Mel
            "mel_high_ratio": float(np.sum(bundle.mel_seq[:, 60:]) / (np.sum(bundle.mel_seq) + 1e-8)),
        }
        results.append(res)
        
    return results

real_results = analyze_file("d:\\SIH\\WhatsApp Audio 2026-08-26 at 12.23.57 PM.mp3")
fake_results = analyze_file("d:\\SIH\\preview_rvc_e6e4419f.wav")

def avg_stat(res_list, key):
    vals = [r[key] for r in res_list if r[key] != 0.0]
    return float(np.mean(vals)) if vals else 0.0

keys = real_results[0].keys()
print("Feature | Real | Fake")
print("---|---|---")
for k in keys:
    print(f"{k} | {avg_stat(real_results, k):.4f} | {avg_stat(fake_results, k):.4f}")
