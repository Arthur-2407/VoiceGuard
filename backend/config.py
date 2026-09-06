"""
config.py — Configuration loader for VoiceGuard.

Loads config.yaml from the project root and exposes a typed Settings dataclass.
All parameters are driven from config.yaml; nothing is hardcoded here.
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Project root = two levels up from this file (backend/config.py → voiceguard/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_yaml() -> dict:
    """Load config.yaml from the project root."""
    config_path = _PROJECT_ROOT / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(
            f"config.yaml not found at {config_path}. "
            "Please ensure you are running from the voiceguard project directory."
        )
    with open(config_path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@dataclass
class AudioConfig:
    sample_rate: int = 16000
    chunk_duration_sec: float = 2.0
    overlap_ratio: float = 0.5
    channels: int = 1
    format: str = "float32"
    vad_aggressiveness: int = 2


@dataclass
class AlertThresholds:
    low: float = 0.35
    medium: float = 0.60
    high: float = 0.80


@dataclass
class DetectionConfig:
    model_path: str = "backend/models/weights/detector.pt"
    device: str = "auto"
    batch_size: int = 1
    n_mels: int = 80
    n_mfcc: int = 40
    use_wav2vec2: bool = True
    wav2vec2_model: str = "facebook/wav2vec2-base"
    use_speaker_embedding: bool = True
    ecapa_model: str = "speechbrain/spkrec-ecapa-voxceleb"


@dataclass
class RiskConfig:
    window_size: int = 5
    detection_weight: float = 0.70
    consistency_weight: float = 0.30
    alert_thresholds: AlertThresholds = field(default_factory=AlertThresholds)


@dataclass
class SpeakerConfig:
    embedding_dim: int = 192
    consistency_threshold: float = 0.75


@dataclass
class PrivacyConfig:
    retain_audio: bool = False
    log_features_only: bool = True
    audit_log_path: str = "data/audit.log"


@dataclass
class StorageConfig:
    db_path: str = "data/voiceguard.db"


@dataclass
class UploadConfig:
    max_file_size_bytes: int = 209715200  # 200 MB default
    max_duration_sec: float = 600.0       # 10-minute default


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: List[str] = field(default_factory=lambda: ["*"])


@dataclass
class WebhookConfig:
    enabled: bool = False
    callback_url: str = ""
    secret_token: str = ""
    retry_attempts: int = 3
    retry_delay_sec: float = 2.0


@dataclass
class Settings:
    audio: AudioConfig = field(default_factory=AudioConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    speaker: SpeakerConfig = field(default_factory=SpeakerConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    upload: UploadConfig = field(default_factory=UploadConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    webhooks: WebhookConfig = field(default_factory=WebhookConfig)
    project_root: Path = field(default_factory=lambda: _PROJECT_ROOT)

    def abs_path(self, relative: str) -> Path:
        """Resolve a path relative to the project root."""
        return self.project_root / relative


def _build_settings(raw: dict) -> Settings:
    audio_raw = raw.get("audio", {})
    detection_raw = raw.get("detection", {})
    risk_raw = raw.get("risk", {})
    speaker_raw = raw.get("speaker", {})
    privacy_raw = raw.get("privacy", {})
    storage_raw = raw.get("storage", {})
    server_raw = raw.get("server", {})
    webhooks_raw = raw.get("webhooks", {})
    upload_raw = raw.get("upload", {})

    thresholds_raw = risk_raw.get("alert_thresholds", {})

    return Settings(
        audio=AudioConfig(
            sample_rate=audio_raw.get("sample_rate", 16000),
            chunk_duration_sec=audio_raw.get("chunk_duration_sec", 2.0),
            overlap_ratio=audio_raw.get("overlap_ratio", 0.5),
            channels=audio_raw.get("channels", 1),
            format=audio_raw.get("format", "float32"),
            vad_aggressiveness=audio_raw.get("vad_aggressiveness", 2),
        ),
        detection=DetectionConfig(
            model_path=detection_raw.get("model_path", "backend/models/weights/detector.pt"),
            device=detection_raw.get("device", "auto"),
            batch_size=detection_raw.get("batch_size", 1),
            n_mels=detection_raw.get("n_mels", 80),
            n_mfcc=detection_raw.get("n_mfcc", 40),
            use_wav2vec2=detection_raw.get("use_wav2vec2", True),
            wav2vec2_model=detection_raw.get("wav2vec2_model", "facebook/wav2vec2-base"),
            use_speaker_embedding=detection_raw.get("use_speaker_embedding", True),
            ecapa_model=detection_raw.get("ecapa_model", "speechbrain/spkrec-ecapa-voxceleb"),
        ),
        risk=RiskConfig(
            window_size=risk_raw.get("window_size", 5),
            detection_weight=risk_raw.get("detection_weight", 0.70),
            consistency_weight=risk_raw.get("consistency_weight", 0.30),
            alert_thresholds=AlertThresholds(
                low=thresholds_raw.get("low", 0.35),
                medium=thresholds_raw.get("medium", 0.60),
                high=thresholds_raw.get("high", 0.80),
            ),
        ),
        speaker=SpeakerConfig(
            embedding_dim=speaker_raw.get("embedding_dim", 192),
            consistency_threshold=speaker_raw.get("consistency_threshold", 0.75),
        ),
        privacy=PrivacyConfig(
            retain_audio=privacy_raw.get("retain_audio", False),
            log_features_only=privacy_raw.get("log_features_only", True),
            audit_log_path=privacy_raw.get("audit_log_path", "data/audit.log"),
        ),
        storage=StorageConfig(
            db_path=storage_raw.get("db_path", "data/voiceguard.db"),
        ),
        upload=UploadConfig(
            max_file_size_bytes=upload_raw.get("max_file_size_bytes", 209715200),
            max_duration_sec=float(upload_raw.get("max_duration_sec", 600.0)),
        ),
        server=ServerConfig(
            host=server_raw.get("host", "0.0.0.0"),
            port=int(server_raw.get("port", 8000)),
            cors_origins=server_raw.get("cors_origins", ["*"]),
        ),
        webhooks=WebhookConfig(
            enabled=webhooks_raw.get("enabled", False),
            callback_url=webhooks_raw.get("callback_url", ""),
            secret_token=os.getenv("WEBHOOK_SECRET", webhooks_raw.get("secret_token", "")),
            retry_attempts=webhooks_raw.get("retry_attempts", 3),
            retry_delay_sec=webhooks_raw.get("retry_delay_sec", 2.0),
        ),
    )


# Module-level singleton — loaded once at import time.
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Return the singleton Settings instance, loading from config.yaml on first call."""
    global _settings
    if _settings is None:
        try:
            raw = _load_yaml()
            _settings = _build_settings(raw)
            logger.info("Configuration loaded from config.yaml")
        except Exception as exc:
            logger.warning(f"Failed to load config.yaml ({exc}), using defaults.")
            _settings = Settings()
    return _settings
