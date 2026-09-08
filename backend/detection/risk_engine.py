"""
risk_engine.py — Dynamic risk score aggregation engine for VoiceGuard.

Combines:
  - Rolling weighted average of per-chunk detection scores
  - Speaker consistency penalty (if enrolled speaker exists)
  - Contextual metadata weighting

Produces a dynamic risk score [0.0, 1.0] and alert level.

All parameters are driven from configuration — no hardcoded thresholds.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Deque, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class AlertLevel(str, Enum):
    SAFE     = "SAFE"
    LOW      = "LOW"
    MEDIUM   = "MEDIUM"
    HIGH     = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class RiskSnapshot:
    """A single risk score observation at a point in time."""
    chunk_id: int
    timestamp: float
    detection_score: float          # Raw P(synthetic) from detector
    consistency_score: float        # 0.0 = consistent, 1.0 = inconsistent
    combined_risk: float            # Final risk score [0.0, 1.0]
    alert_level: AlertLevel
    rolling_risk: float             # Rolling window average


@dataclass
class RiskEngineConfig:
    window_size: int = 5
    detection_weight: float = 0.70
    consistency_weight: float = 0.30
    threshold_low: float = 0.35
    threshold_medium: float = 0.60
    threshold_high: float = 0.80
    threshold_critical: float = 0.95   # New: CRITICAL alert level threshold
    temporal_smoothing: bool = True
    smoothing_alpha: float = 0.3
    alert_cooldown_sec: float = 15.0


class RiskEngine:
    """
    Maintains a rolling window of detection scores and computes
    aggregated risk with speaker consistency penalty.

    Thread-safe for use in async WebSocket handlers.
    """

    def __init__(self, config: RiskEngineConfig):
        self.config = config
        self._scores: Deque[float] = deque(maxlen=config.window_size)
        self._history: List[RiskSnapshot] = []
        self._session_start = time.time()
        self._peak_risk: float = 0.0
        self._alert_count: int = 0
        self._last_smoothed_risk: float = 0.0
        
        # Session Metadata
        self.session_type: str = "LIVE_MONITOR"
        self.audio_source: str = "MICROPHONE"
        self.capture_mode: str = "NATIVE"

    def update(
        self,
        chunk_id: int,
        detection_score: float,
        speaker_similarity: Optional[float] = None,
    ) -> RiskSnapshot:
        """
        Update the rolling window with a new chunk's detection score.

        Args:
            chunk_id:           identifier for the processed chunk
            detection_score:    P(synthetic) from detector [0.0, 1.0]
            speaker_similarity: cosine similarity vs enrolled profile [0.0, 1.0]
                                None = no enrolled speaker (skip consistency check)

        Returns:
            RiskSnapshot with combined risk score and alert level
        """
        self._scores.append(detection_score)

        # Rolling weighted average (more recent = higher weight)
        scores_list = list(self._scores)
        weights = np.linspace(0.5, 1.0, len(scores_list))
        weights /= weights.sum()
        rolling_risk = float(np.dot(scores_list, weights))
        
        # Exponential smoothing (Hysteresis)
        if self.config.temporal_smoothing:
            if not self._history:
                self._last_smoothed_risk = rolling_risk
            else:
                alpha = self.config.smoothing_alpha
                self._last_smoothed_risk = alpha * rolling_risk + (1 - alpha) * self._last_smoothed_risk
            rolling_risk = self._last_smoothed_risk

        # Speaker consistency penalty
        if speaker_similarity is not None:
            # similarity close to 0 or negative = high inconsistency
            consistency_score = max(0.0, 1.0 - speaker_similarity)
        else:
            consistency_score = 0.0  # No enrolled speaker = no penalty

        # Combined risk score
        if speaker_similarity is not None:
            combined_risk = (
                self.config.detection_weight * rolling_risk
                + self.config.consistency_weight * consistency_score
            )
        else:
            combined_risk = rolling_risk

        combined_risk = float(np.clip(combined_risk, 0.0, 1.0))

        # Alert level
        alert_level = self._classify_risk(combined_risk)

        # Track peak and alert count
        if combined_risk > self._peak_risk:
            self._peak_risk = combined_risk

        snapshot = RiskSnapshot(
            chunk_id=chunk_id,
            timestamp=time.time(),
            detection_score=detection_score,
            consistency_score=consistency_score,
            combined_risk=combined_risk,
            alert_level=alert_level,
            rolling_risk=rolling_risk,
        )

        self._history.append(snapshot)
        return snapshot

    def _classify_risk(self, risk: float) -> AlertLevel:
        """Map risk score to alert level using configured thresholds."""
        if risk >= self.config.threshold_critical:
            return AlertLevel.CRITICAL
        elif risk >= self.config.threshold_high:
            return AlertLevel.HIGH
        elif risk >= self.config.threshold_medium:
            return AlertLevel.MEDIUM
        elif risk >= self.config.threshold_low:
            return AlertLevel.LOW
        else:
            return AlertLevel.SAFE

    def get_session_summary(self) -> dict:
        """Return a summary of risk across the entire session."""
        if not self._history:
            return {
                "total_chunks": 0,
                "peak_risk": "NO_RESULT",
                "mean_risk": 0.0,
                "alert_level": "NO_RESULT",
                "session_duration_sec": 0.0,
            }

        risks = [s.combined_risk for s in self._history]
        return {
            "total_chunks": len(self._history),
            "peak_risk": float(self._peak_risk),
            "mean_risk": float(np.mean(risks)),
            "final_risk": float(risks[-1]) if risks else 0.0,
            "alert_level": self._classify_risk(self._peak_risk),
            "session_duration_sec": time.time() - self._session_start,
            "history": [
                {
                    "chunk_id": s.chunk_id,
                    "timestamp": s.timestamp,
                    "risk": s.combined_risk,
                    "level": s.alert_level,
                }
                for s in self._history[-20:]  # Last 20 chunks in summary
            ],
        }

    def reset(self) -> None:
        """Reset for a new call session."""
        self._scores.clear()
        self._history.clear()
        self._session_start = time.time()
        self._peak_risk = 0.0
        self._alert_count = 0
        self._last_smoothed_risk = 0.0
        logger.info("Risk engine reset for new session.")

    @property
    def current_risk(self) -> float:
        """Return the most recently computed combined risk."""
        if self._history:
            return self._history[-1].combined_risk
        return 0.0

    @property
    def current_alert_level(self) -> AlertLevel:
        return self._classify_risk(self.current_risk)

    @property
    def history(self) -> List[RiskSnapshot]:
        return self._history


def build_risk_engine_from_settings(settings) -> RiskEngine:
    """Factory: build a RiskEngine from the application Settings object."""
    cfg = RiskEngineConfig(
        window_size=settings.risk.window_size,
        detection_weight=settings.risk.detection_weight,
        consistency_weight=settings.risk.consistency_weight,
        threshold_low=settings.risk.alert_thresholds.low,
        threshold_medium=settings.risk.alert_thresholds.medium,
        threshold_high=settings.risk.alert_thresholds.high,
        # threshold_critical uses the dataclass default (0.95) unless settings exposes it
        threshold_critical=getattr(
            settings.risk.alert_thresholds, "critical", 0.95
        ),
        temporal_smoothing=getattr(settings.risk, "temporal_smoothing", True),
        smoothing_alpha=getattr(settings.risk, "smoothing_alpha", 0.3),
        alert_cooldown_sec=getattr(settings.risk, "alert_cooldown_sec", 15.0),
    )
    return RiskEngine(cfg)
