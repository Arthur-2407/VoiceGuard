"""
detector.py — Core detection orchestrator for VoiceGuard.

Orchestrates the full pipeline per audio chunk:
  audio → features → model inference → raw synthetic probability

This module does NOT do risk aggregation (see risk_engine.py).
It outputs a raw P(synthetic) score for a single chunk.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_TORCH_AVAILABLE = False
try:
    import torch
    _TORCH_AVAILABLE = True
except ImportError:
    pass


@dataclass
class ChunkDetectionResult:
    """Result of processing one audio chunk."""
    chunk_id: int
    timestamp: float
    synthetic_probability: float   # [0.0, 1.0] — higher = more likely synthetic
    processing_time_ms: float
    features_available: dict       # which feature types were extracted
    speaker_embedding: Optional[np.ndarray] = None


class VoiceCloneDetector:
    """
    Main detector that runs the full pipeline for each audio chunk.

    Typical usage:
        detector = VoiceCloneDetector(settings)
        detector.initialize()
        result = detector.process_chunk(audio_float32, chunk_id=0)
    """

    def __init__(self, settings):
        """
        Args:
            settings: Settings object from config.py
        """
        self.settings = settings
        self._model = None
        self._device: str = "cpu"
        self._initialized = False
        self._chunk_counter = 0

    def initialize(self) -> None:
        """
        Load all models at startup.
        Called once by FastAPI startup event.
        """
        from backend.models.model_loader import load_model, resolve_device
        from backend.features.wav2vec_extractor import preload_wav2vec2
        from backend.features.speaker_extractor import preload_ecapa

        self._device = resolve_device(self.settings.detection.device)
        logger.info(f"Detector initializing on device: {self._device}")

        try:
            # Load CNN-RNN detector model
            self._model = load_model(
                model_path=self.settings.detection.model_path,
                n_mels=self.settings.detection.n_mels,
                device_cfg=self.settings.detection.device,
            )
            
            if self._model is not None:
                # Preload wav2vec2 if configured
                if self.settings.detection.use_wav2vec2:
                    preload_wav2vec2(self.settings.detection.wav2vec2_model)

                # Preload ECAPA if configured
                if self.settings.detection.use_speaker_embedding:
                    preload_ecapa(self.settings.detection.ecapa_model)

                self._initialized = True
                logger.info("VoiceCloneDetector initialized successfully.")
            else:
                self._initialized = False
                logger.warning("VoiceCloneDetector could not initialize: Model is None.")
        except Exception as e:
            self._initialized = False
            logger.warning(f"VoiceCloneDetector failed to initialize: {e}")

    def process_chunk(
        self,
        audio: np.ndarray,
        chunk_id: Optional[int] = None,
    ) -> ChunkDetectionResult:
        """
        Process a single preprocessed audio chunk through the full pipeline.

        Args:
            audio:    float32 mono waveform at configured sample rate
            chunk_id: optional identifier for this chunk

        Returns:
            ChunkDetectionResult with synthetic_probability
        """
        if chunk_id is None:
            chunk_id = self._chunk_counter
            self._chunk_counter += 1

        t_start = time.perf_counter()

        # 1. Extract all features
        from backend.features.feature_fusion import extract_all_features

        bundle = extract_all_features(
            audio=audio,
            sr=self.settings.audio.sample_rate,
            n_mfcc=self.settings.detection.n_mfcc,
            n_mels=self.settings.detection.n_mels,
            hop_length=160,
            win_length=400,
            wav2vec2_model_name=self.settings.detection.wav2vec2_model,
            ecapa_model_name=self.settings.detection.ecapa_model,
            use_wav2vec2=self.settings.detection.use_wav2vec2,
            use_speaker_embedding=self.settings.detection.use_speaker_embedding,
            device=self._device,
        )

        # 2. Run model inference
        synthetic_prob = self._run_inference(bundle)

        t_end = time.perf_counter()
        processing_ms = (t_end - t_start) * 1000.0

        features_available = {
            "mfcc": True,
            "log_mel": True,
            "prosodic": True,
            "wav2vec2": self.settings.detection.use_wav2vec2,
            "speaker_embedding": self.settings.detection.use_speaker_embedding,
        }

        logger.debug(
            f"Chunk {chunk_id}: P(synthetic)={synthetic_prob:.4f}, "
            f"latency={processing_ms:.1f}ms"
        )

        return ChunkDetectionResult(
            chunk_id=chunk_id,
            timestamp=time.time(),
            synthetic_probability=float(synthetic_prob),
            processing_time_ms=float(processing_ms),
            features_available=features_available,
            speaker_embedding=bundle.speaker_emb,
        )

    def _run_inference(self, bundle) -> float:
        """
        Run model inference on extracted features.

        Returns P(synthetic) as float in [0.0, 1.0].
        """
        if not _TORCH_AVAILABLE or self._model is None or not self._initialized:
            # Fallback: heuristic from acoustic features only
            logger.warning("ML detector unavailable. Using acoustic heuristic fallback.")
            return self._heuristic_score(bundle)

        try:
            import torch

            # Prepare mel sequence tensor [1, T, n_mels]
            mel_seq = torch.tensor(
                bundle.mel_seq, dtype=torch.float32
            ).unsqueeze(0).to(self._device)

            # Prepare fused feature tensor [1, fused_dim]
            fused_vec = torch.tensor(
                bundle.fused_vector, dtype=torch.float32
            ).unsqueeze(0).to(self._device)

            with torch.no_grad():
                prob = self._model.predict_proba(mel_seq, fused_vec)

            return float(prob.squeeze().cpu().item())

        except Exception as exc:
            logger.error(f"Model inference failed: {exc}. Using heuristic score.")
            return self._heuristic_score(bundle)

    def _heuristic_score(self, bundle) -> float:
        """
        Acoustic heuristic score when model is unavailable.
        Based on HNR, jitter, shimmer thresholds typical of synthetic speech.
        This is a fallback — not a reliable detector.
        """
        prosodic = bundle.prosodic
        # prosodic: [f0_mean, f0_std, jitter, shimmer, hnr, zcr, energy]
        hnr = prosodic[4]        # HNR in dB
        jitter = prosodic[2]     # Relative jitter
        shimmer = prosodic[3]    # Relative shimmer

        # If no voiced frames were detected (jitter is exactly 0.0),
        # we cannot assess synthetic voicing. Return 0.0 to prevent a hallucinated 0.600 score.
        if jitter == 0.0:
            return 0.0

        # Heuristic 1: very high HNR + very low jitter/shimmer = more likely basic TTS
        hnr_score = max(0.0, min(1.0, (hnr - 10) / 30.0))  # 10dB → 0, 40dB → 1
        jitter_score = max(0.0, min(1.0, 1.0 - jitter * 100))  # lower jitter = more synthetic
        shimmer_score = max(0.0, min(1.0, 1.0 - shimmer * 10))

        basic_tts_score = 0.4 * hnr_score + 0.3 * jitter_score + 0.3 * shimmer_score

        # Heuristic 2: MFCC high-order variance (detects RVC / GAN vocoders)
        # Deepfakes often have periodic artifacts in high frequencies causing high variance
        mfcc_seq = getattr(bundle, "mfcc_seq", None)
        vocoder_score = 0.0
        if mfcc_seq is not None and mfcc_seq.shape[0] > 0 and mfcc_seq.shape[1] >= 40:
            # Variance of MFCCs 13-39 (excluding lower order formants)
            mfcc_high_var = float(np.mean(np.var(mfcc_seq[:, 13:40], axis=0)))
            vocoder_score = max(0.0, min(1.0, (mfcc_high_var - 45) / 35.0)) # 45 -> 0, 80 -> 1.0

        # Combine scores (either basic TTS or advanced vocoder triggers it)
        score = max(basic_tts_score, vocoder_score)
        
        return float(np.clip(score, 0.0, 1.0))

    @property
    def is_initialized(self) -> bool:
        return self._initialized
