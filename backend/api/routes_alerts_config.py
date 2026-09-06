"""
routes_alerts.py — Alert history REST API.
routes_config.py — Threshold configuration REST API.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ── Alerts Router ──────────────────────────────────────────────────────────────
alerts_router = APIRouter(prefix="/api/alerts", tags=["Alerts"])


@alerts_router.get("/recent")
async def get_recent_alerts(limit: int = 50):
    """Get the most recent alerts across all sessions."""
    from backend.main import get_app_alert_manager
    return {"alerts": get_app_alert_manager().get_recent_alerts(limit=limit)}


@alerts_router.get("/session/{session_id}")
async def get_session_alerts(session_id: str):
    """Get all alerts for a specific session."""
    from backend.main import get_app_alert_manager
    alerts = get_app_alert_manager().get_session_history(session_id)
    return {"session_id": session_id, "alerts": alerts}


# ── Config Router ──────────────────────────────────────────────────────────────
config_router = APIRouter(prefix="/api/config", tags=["Configuration"])


class ThresholdUpdateRequest(BaseModel):
    low: float = Field(ge=0.0, le=1.0, description="LOW alert threshold")
    medium: float = Field(ge=0.0, le=1.0, description="MEDIUM alert threshold")
    high: float = Field(ge=0.0, le=1.0, description="HIGH alert threshold")


@config_router.get("/thresholds")
async def get_thresholds():
    """Get current alert threshold configuration."""
    from backend.main import app_settings
    return {
        "low": app_settings.risk.alert_thresholds.low,
        "medium": app_settings.risk.alert_thresholds.medium,
        "high": app_settings.risk.alert_thresholds.high,
    }


@config_router.put("/thresholds")
async def update_thresholds(body: ThresholdUpdateRequest):
    """Update alert thresholds at runtime (without restart)."""
    from backend.main import app_settings

    if not (body.low < body.medium < body.high):
        raise HTTPException(
            status_code=422,
            detail="Thresholds must satisfy: low < medium < high"
        )

    app_settings.risk.alert_thresholds.low = body.low
    app_settings.risk.alert_thresholds.medium = body.medium
    app_settings.risk.alert_thresholds.high = body.high

    return {
        "message": "Thresholds updated.",
        "low": body.low,
        "medium": body.medium,
        "high": body.high,
    }


@config_router.get("/status")
async def get_system_status():
    """Return current system health and model status."""
    from backend.main import get_app_detector, app_settings, get_app_ws_notifier
    from backend.features.wav2vec_extractor import is_wav2vec2_available
    from backend.features.speaker_extractor import is_ecapa_available

    app_detector    = get_app_detector()
    app_ws_notifier = get_app_ws_notifier()

    return {
        "status": "operational",
        "detector_initialized": app_detector.is_initialized if app_detector else False,
        "wav2vec2_available": is_wav2vec2_available(),
        "ecapa_available": is_ecapa_available(),
        "connected_clients": app_ws_notifier.connection_count if app_ws_notifier else 0,
        "config": {
            "sample_rate": app_settings.audio.sample_rate,
            "chunk_duration_sec": app_settings.audio.chunk_duration_sec,
            "device": app_settings.detection.device,
            "thresholds": {
                "low": app_settings.risk.alert_thresholds.low,
                "medium": app_settings.risk.alert_thresholds.medium,
                "high": app_settings.risk.alert_thresholds.high,
            },
        },
    }
