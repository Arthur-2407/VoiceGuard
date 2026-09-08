"""
alert_manager.py — Alert orchestration for VoiceGuard.

Routes alerts to all registered notifiers (WebSocket, webhook).
Maintains in-memory alert history for the current session.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

from backend.detection.risk_engine import AlertLevel
from backend.detection.threshold_engine import AlertRecommendation

logger = logging.getLogger(__name__)


@dataclass
class AlertEvent:
    """A complete alert event dispatched to all subscribers."""
    session_id: str
    chunk_id: int
    timestamp: float
    risk_score: float
    alert_level: str
    recommendation: dict
    speaker_id: Optional[str]
    speaker_similarity: Optional[float]
    detection_score: float


class AlertManager:
    """
    Central alert dispatch hub.
    Notifiers register themselves; the manager calls them on each alert.
    """

    def __init__(self):
        self._notifiers = []
        self._history: List[AlertEvent] = []
        self._session_alerts: Dict[str, List[AlertEvent]] = {}
        self._last_alert_time: Dict[str, float] = {}
        
        # Load config safely
        from backend.config import get_settings
        settings = get_settings()
        self.cooldown_sec = getattr(settings.risk, "alert_cooldown_sec", 15.0)

    def register_notifier(self, notifier) -> None:
        """Register a notifier (WebSocket, webhook, etc.)."""
        self._notifiers.append(notifier)

    async def dispatch(
        self,
        session_id: str,
        chunk_id: int,
        risk_score: float,
        alert_level: AlertLevel,
        recommendation: AlertRecommendation,
        detection_score: float,
        speaker_id: Optional[str] = None,
        speaker_similarity: Optional[float] = None,
    ) -> None:
        """
        Dispatch an alert to all registered notifiers.
        """
        event = AlertEvent(
            session_id=session_id,
            chunk_id=chunk_id,
            timestamp=time.time(),
            risk_score=risk_score,
            alert_level=alert_level.value if hasattr(alert_level, 'value') else str(alert_level),
            recommendation={
                "title": recommendation.title,
                "message": recommendation.message,
                "actions": recommendation.actions,
                "color": recommendation.color,
            },
            speaker_id=speaker_id,
            speaker_similarity=speaker_similarity,
            detection_score=detection_score,
        )

        self._history.append(event)
        self._session_alerts.setdefault(session_id, []).append(event)
        
        # Alert Deduplication / Cooldown Logic for CRITICAL alerts
        is_critical = (event.alert_level == AlertLevel.CRITICAL.value if hasattr(AlertLevel.CRITICAL, 'value') else str(AlertLevel.CRITICAL))
        
        if is_critical:
            last_time = self._last_alert_time.get(session_id, 0.0)
            if time.time() - last_time < self.cooldown_sec:
                # Still within cooldown, suppress dispatching duplicate high-priority alerts
                logger.debug(f"Suppressing duplicate critical alert for session {session_id} due to cooldown.")
                # We can still send it as HIGH instead of dropping completely, or tag it as suppressed
                # For now, we update the event to indicate it's suppressed from major UI interruption
                event.recommendation["suppressed"] = True
            else:
                self._last_alert_time[session_id] = time.time()

        # Notify all registered notifiers
        for notifier in self._notifiers:
            try:
                await notifier.notify(event)
            except Exception as exc:
                logger.error(f"Notifier {type(notifier).__name__} failed: {exc}")

    def get_session_history(self, session_id: str) -> List[dict]:
        """Return all alerts for a given session."""
        events = self._session_alerts.get(session_id, [])
        return [
            {
                "chunk_id": e.chunk_id,
                "timestamp": e.timestamp,
                "risk_score": e.risk_score,
                "alert_level": e.alert_level,
                "recommendation": e.recommendation,
                "detection_score": e.detection_score,
                "speaker_similarity": e.speaker_similarity,
            }
            for e in events
        ]

    def get_recent_alerts(self, limit: int = 50) -> List[dict]:
        """Return most recent alerts across all sessions."""
        recent = self._history[-limit:]
        return [
            {
                "session_id": e.session_id,
                "chunk_id": e.chunk_id,
                "timestamp": e.timestamp,
                "risk_score": e.risk_score,
                "alert_level": e.alert_level,
                "recommendation_title": e.recommendation.get("title", ""),
            }
            for e in reversed(recent)
        ]

    def clear_session(self, session_id: str) -> None:
        """Remove alert history for a completed session."""
        self._session_alerts.pop(session_id, None)
        self._last_alert_time.pop(session_id, None)
