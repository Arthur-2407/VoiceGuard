"""
webhook_notifier.py — Enterprise REST webhook notifications for VoiceGuard.

Delivers alert events to external systems (banking, contact centers)
via configurable HTTP POST callbacks with retry logic.

Implements the SIH requirement:
"REST/gRPC APIs and SDKs for integration with banking applications,
enterprise communication systems, and telecom operator infrastructures"
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False
    logger.warning("httpx not available — webhook delivery disabled.")


class WebhookNotifier:
    """
    Delivers alert events to external webhook endpoints with retry logic.
    Only active when webhooks.enabled=true in config.
    """

    def __init__(
        self,
        callback_url: str,
        secret_token: str = "",
        retry_attempts: int = 3,
        retry_delay_sec: float = 2.0,
        enabled: bool = False,
    ):
        self.callback_url = callback_url
        self.secret_token = secret_token
        self.retry_attempts = retry_attempts
        self.retry_delay_sec = retry_delay_sec
        self.enabled = enabled

    def _sign_payload(self, payload: str) -> str:
        """HMAC-SHA256 signature for payload verification at receiver."""
        if not self.secret_token:
            return ""
        # Use hmac.HMAC() — the Python 3 constructor.
        # hmac.new() was a Python 2 API and does not exist in Python 3.
        sig = hmac.HMAC(
            self.secret_token.encode("utf-8"),
            payload.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        return f"sha256={sig}"

    async def notify(self, event) -> None:
        """
        Called by AlertManager.dispatch().
        Sends POST to webhook endpoint if enabled.
        Only sends for MEDIUM+ alerts to reduce noise.
        """
        if not self.enabled or not self.callback_url:
            return

        # Only webhook on elevated alerts (configurable)
        if event.alert_level in ("SAFE", "LOW"):
            return

        if not _HTTPX_AVAILABLE:
            logger.warning("httpx unavailable — skipping webhook delivery.")
            return

        payload = json.dumps({
            "event": "voice_clone_alert",
            "session_id": event.session_id,
            "timestamp": event.timestamp,
            "risk_score": event.risk_score,
            "alert_level": event.alert_level,
            "detection_score": event.detection_score,
            "recommendation": event.recommendation,
            "speaker_id": event.speaker_id,
        })

        signature = self._sign_payload(payload)
        headers = {
            "Content-Type": "application/json",
            "X-VoiceGuard-Signature": signature,
            "X-VoiceGuard-Timestamp": str(int(time.time())),
        }

        for attempt in range(1, self.retry_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(
                        self.callback_url,
                        content=payload,
                        headers=headers,
                    )
                    if response.status_code < 300:
                        logger.info(
                            f"Webhook delivered to {self.callback_url} "
                            f"(attempt {attempt}): HTTP {response.status_code}"
                        )
                        return
                    else:
                        logger.warning(
                            f"Webhook attempt {attempt} got HTTP {response.status_code}"
                        )
            except Exception as exc:
                logger.warning(f"Webhook attempt {attempt} failed: {exc}")

            if attempt < self.retry_attempts:
                await asyncio.sleep(self.retry_delay_sec * attempt)

        logger.error(
            f"Webhook delivery failed after {self.retry_attempts} attempts "
            f"to {self.callback_url}"
        )
