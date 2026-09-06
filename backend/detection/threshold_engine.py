"""
threshold_engine.py — Alert threshold evaluation and recommendation engine.

Evaluates the current risk score against configured thresholds and
produces actionable recommendations for frontline staff.

Implements the SIH requirement for:
"Threshold-based alerting logic configurable for different risk scenarios"
"Pre-transaction warning prompts recommending secondary verification"
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List

from backend.detection.risk_engine import AlertLevel


@dataclass
class AlertRecommendation:
    """Actionable recommendation produced when a threshold is crossed."""
    alert_level: AlertLevel
    risk_score: float
    title: str
    message: str
    actions: List[str]
    color: str      # For UI display


_RECOMMENDATIONS = {
    AlertLevel.SAFE: AlertRecommendation(
        alert_level=AlertLevel.SAFE,
        risk_score=0.0,
        title="Voice Verified",
        message="No signs of synthetic or cloned voice detected.",
        actions=["Continue conversation normally"],
        color="#22c55e",  # green
    ),
    AlertLevel.LOW: AlertRecommendation(
        alert_level=AlertLevel.LOW,
        risk_score=0.0,
        title="Low Risk Detected",
        message="Minor acoustic anomalies detected. Continue with awareness.",
        actions=[
            "Ask the caller a knowledge-based security question",
            "Verify caller ID through your internal directory",
        ],
        color="#f59e0b",  # amber
    ),
    AlertLevel.MEDIUM: AlertRecommendation(
        alert_level=AlertLevel.MEDIUM,
        risk_score=0.0,
        title="⚠️ Medium Risk — Possible Voice Cloning",
        message="Significant synthetic speech signatures detected. Do NOT approve any transactions.",
        actions=[
            "DO NOT approve financial transactions",
            "Initiate callback via a known verified number",
            "Request multi-factor authentication (OTP/email)",
            "Escalate to supervisor for secondary review",
        ],
        color="#f97316",  # orange
    ),
    AlertLevel.HIGH: AlertRecommendation(
        alert_level=AlertLevel.HIGH,
        risk_score=0.0,
        title="🚨 HIGH RISK — Likely Voice Cloning Attack",
        message=(
            "Strong indicators of AI-generated or cloned voice. "
            "This call is likely a social engineering attempt."
        ),
        actions=[
            "TERMINATE the call immediately",
            "DO NOT disclose any confidential information",
            "DO NOT approve any transactions",
            "Report to your security operations team NOW",
            "Document call details for incident response",
            "Initiate call-back protocol via official verified channel",
        ],
        color="#ef4444",  # red
    ),
}


class ThresholdEngine:
    """
    Evaluates risk scores against thresholds and produces
    alert recommendations.
    """

    def __init__(
        self,
        threshold_low: float = 0.35,
        threshold_medium: float = 0.60,
        threshold_high: float = 0.80,
    ):
        self.threshold_low = threshold_low
        self.threshold_medium = threshold_medium
        self.threshold_high = threshold_high
        self._previous_level: AlertLevel = AlertLevel.SAFE

    def evaluate(self, risk_score: float) -> AlertRecommendation:
        """
        Evaluate a risk score and return an ActionableRecommendation.
        """
        if risk_score >= self.threshold_high:
            level = AlertLevel.HIGH
        elif risk_score >= self.threshold_medium:
            level = AlertLevel.MEDIUM
        elif risk_score >= self.threshold_low:
            level = AlertLevel.LOW
        else:
            level = AlertLevel.SAFE

        rec = _RECOMMENDATIONS[level]
        # Return a copy with updated risk score
        return AlertRecommendation(
            alert_level=rec.alert_level,
            risk_score=risk_score,
            title=rec.title,
            message=rec.message,
            actions=rec.actions.copy(),
            color=rec.color,
        )

    def has_escalated(self, new_level: AlertLevel) -> bool:
        """Return True if alert level has increased since last call."""
        level_order = {
            AlertLevel.SAFE: 0,
            AlertLevel.LOW: 1,
            AlertLevel.MEDIUM: 2,
            AlertLevel.HIGH: 3,
        }
        escalated = level_order[new_level] > level_order[self._previous_level]
        self._previous_level = new_level
        return escalated

    def update_thresholds(
        self,
        low: float,
        medium: float,
        high: float,
    ) -> None:
        """Dynamically update thresholds (from config API)."""
        self.threshold_low = low
        self.threshold_medium = medium
        self.threshold_high = high
