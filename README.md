# VoiceGuard — AI-Powered Real-Time Voice Cloning Detection System

> **SIH 2026 | AICTE Cyber Security Cell**
> Smart India Hackathon Submission

## 🎯 Overview

VoiceGuard is a real-time AI detection system that identifies voice cloning impersonation attacks in live audio streams. It protects banking, telecom, and enterprise communication systems from social engineering attacks using synthesized/cloned voices.

### Key Capabilities
- **Real-time stream analysis** via WebSocket (< 2s per chunk)
- **Hybrid CNN-BiLSTM detector** with self-attention and wav2vec2 backbone
- **Dynamic risk scoring** with rolling window aggregation
- **Speaker identity verification** via ECAPA-TDNN embeddings
- **Privacy-preserving audit log** — no raw audio stored
- **Enterprise webhook integration** with HMAC-SHA256 signing
- **Responsive web dashboard** with live gauge and risk timeline

---

## 🏗️ Architecture

```
Audio Stream
    │
    ▼
[Preprocessor] → VAD, Resample (16kHz), Normalize, Chunk (2s)
    │
    ▼
[Feature Extractor]
    ├── MFCC (40 coeffs + Δ + ΔΔ) = 120-dim
    ├── Log-Mel Spectrogram (80 bands) = 80-dim
    ├── Prosodic (F0, Jitter, Shimmer, HNR, ZCR, Energy) = 7-dim
    ├── Wav2Vec2-base contextual embedding = 768-dim
    └── ECAPA-TDNN speaker embedding = 192-dim
                        → Fused: 1167-dim
    │
    ▼
[CNN-BiLSTM Detector]
    ├── CNN Encoder (3 Conv1D blocks + residual)
    ├── BiLSTM (2 layers, 256 hidden)
    ├── Self-Attention
    └── Classifier head → P(synthetic) ∈ [0,1]
    │
    ▼
[Risk Engine]
    ├── Rolling weighted window (last N chunks)
    ├── Speaker consistency penalty (cosine similarity)
    └── Combined risk score → Alert Level
    │
    ▼
[Alert System]
    ├── WebSocket push to frontend
    ├── Webhook POST to enterprise systems
    └── SQLite audit log (features only, no audio)
```

---

## 📱 Android Client & Local Network Architecture

VoiceGuard provides a lightweight, futuristic Android application that connects directly to the PC backend via a local wireless network.

### Architecture
```
[Android Device] ↔ [Wi-Fi / Mobile Hotspot] ↔ [VoiceGuard PC Server]
```

### Capabilities
- **Zero Heavy Processing**: The Android client acts purely as a UI layer. No ML models are loaded on the phone.
- **Local Network Discovery**: The app automatically discovers the FastAPI server on your local network (e.g., `192.168.x.x:8000`) using built-in network scanning.
- **Live Monitor**: Uses a WebSocket connection to stream 16kHz PCM audio directly from the Android microphone to the PC for instant deepfake risk scoring.
- **File Analysis**: Uploads audio files via REST API using standard multi-part file chunking for granular verification.

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.10+
- pip
- Internet connection (first run, for model downloads)

### 2. Install Dependencies
```powershell
cd d:\SIH\voiceguard
pip install -r backend\requirements.txt
```

### 3. Download Models
```powershell
python scripts\download_models.py
```

### 4. Run Tests
```powershell
python scripts\test_pipeline.py
```

### 5. Start the Server
```powershell
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### 6. Open the Dashboard
Navigate to `http://localhost:8000` in your browser.

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET`    | `/`                    | Frontend dashboard |
| `WS`     | `/ws/stream`           | Real-time audio stream analysis |
| `POST`   | `/api/analyze`         | Upload file for analysis |
| `POST`   | `/api/speakers/enroll` | Enroll a speaker profile |
| `GET`    | `/api/speakers`        | List enrolled speakers |
| `DELETE` | `/api/speakers/{id}`   | Delete speaker profile |
| `GET`    | `/api/alerts/recent`   | Recent alert history |
| `GET`    | `/api/config/status`   | System health status |
| `PUT`    | `/api/config/thresholds` | Update alert thresholds |
| `GET`    | `/docs`                | Interactive API documentation |

---

## 🔧 Configuration

All parameters are in `config.yaml` — no hardcoded values.

Key settings:
```yaml
audio:
  sample_rate: 16000
  chunk_duration_sec: 2.0

detection:
  use_wav2vec2: true
  use_speaker_embedding: true

risk:
  window_size: 5
  alert_thresholds:
    low: 0.35
    medium: 0.60
    high: 0.80

privacy:
  retain_audio: false      # Raw audio NEVER stored
  log_features_only: true
```

---

## 🧬 Model Details

| Component | Architecture | Dimension |
|-----------|-------------|-----------|
| MFCC Extractor | librosa + delta | 40 × 3 = 120 |
| Log-Mel Spectrogram | librosa | 80 bands |
| Prosodic Features | F0/Jitter/Shimmer/HNR | 7 |
| Wav2Vec2 | `facebook/wav2vec2-base` | 768 |
| Speaker Embedding | `speechbrain/spkrec-ecapa-voxceleb` | 192 |
| CNN Encoder | 3 × Conv1D + residual | — |
| BiLSTM | 2 layers, hidden=256, bidirectional | 512 |
| Self-Attention | Scaled dot-product | 512 |
| Classifier | 3-layer MLP | → 1 (P_synthetic) |

---

## 🔒 Privacy & Compliance

- Raw audio is **never** stored to disk
- Only feature vectors, risk scores, and prosodic statistics are logged
- GDPR/PDPB-compliant speaker profile deletion
- Webhook payloads are HMAC-SHA256 signed

---

## 📄 References

1. **Generalized End-to-End Loss for Speaker Verification** (Wan et al., NeurIPS 2018) — `1802.06006v3.pdf`
2. **Survey: Text-to-Speech and Voice Cloning** (2025) — `2505.00579v1.pdf`
3. **AI-Powered Voice Cloning Detection System** (IJERT 2026) — `IJERTV15IS020603.pdf`
4. **SIH Problem Statement** — AICTE Cyber Security Cell, SIH 2026

---

## 👥 Team

SIH 2026 Submission — Built with ❤️ for India's Cyber Security
