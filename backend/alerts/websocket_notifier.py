"""
websocket_notifier.py — Real-time WebSocket alert push for VoiceGuard.

Manages connected WebSocket clients and delivers detection updates
to the specific session that produced them — NOT to all clients.

Session isolation design:
  - Each WebSocket connection is registered with its session_id on connect().
  - notify() delivers the alert only to the WebSocket that owns the session.
  - broadcast_raw() remains available for system-wide messages (health, etc.).
"""

from __future__ import annotations

import json
import logging
from typing import Dict, Optional, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketNotifier:
    """
    Manages active WebSocket connections with per-session routing.

    Alerts are delivered ONLY to the originating session's WebSocket,
    preventing cross-session data leakage when multiple clients are connected.
    """

    def __init__(self):
        # ws → session_id mapping (one-to-one)
        self._ws_to_session: Dict[WebSocket, str] = {}
        # session_id → ws mapping (for fast lookup by session)
        self._session_to_ws: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, session_id: str) -> None:
        """
        Accept and register a new WebSocket connection bound to session_id.

        Args:
            websocket:  the incoming WebSocket connection
            session_id: the unique session identifier for this connection
        """
        await websocket.accept()
        self._ws_to_session[websocket] = session_id
        self._session_to_ws[session_id] = websocket
        logger.info(
            f"WebSocket client connected (session={session_id}). "
            f"Total: {len(self._ws_to_session)}"
        )

    async def disconnect(self, websocket: WebSocket) -> None:
        """Deregister a WebSocket connection and its session mapping."""
        session_id = self._ws_to_session.pop(websocket, None)
        if session_id is not None:
            self._session_to_ws.pop(session_id, None)
        logger.info(
            f"WebSocket client disconnected (session={session_id}). "
            f"Total: {len(self._ws_to_session)}"
        )

    async def notify(self, event) -> None:
        """
        Deliver an alert event only to the WebSocket that owns event.session_id.

        This replaces the old broadcast-to-all design. Each client receives
        only its own session's risk updates, preventing cross-session leakage.
        """
        session_id = getattr(event, "session_id", None)
        if not session_id:
            logger.warning("notify() called with event missing session_id — skipping.")
            return

        ws = self._session_to_ws.get(session_id)
        if ws is None:
            # Session's WebSocket already disconnected; nothing to do.
            return

        payload = json.dumps({
            "type": "risk_update",
            "session_id": event.session_id,
            "chunk_id": event.chunk_id,
            "timestamp": event.timestamp,
            "risk_score": event.risk_score,
            "alert_level": event.alert_level,
            "detection_score": event.detection_score,
            "speaker_id": event.speaker_id,
            "speaker_similarity": event.speaker_similarity,
            "recommendation": event.recommendation,
        })

        try:
            await ws.send_text(payload)
        except Exception as exc:
            logger.debug(f"Failed to send to session {session_id}: {exc}. Removing stale connection.")
            # Clean up stale connection
            self._ws_to_session.pop(ws, None)
            self._session_to_ws.pop(session_id, None)

    async def broadcast_raw(self, message: dict) -> None:
        """
        Send an arbitrary JSON message to ALL connected clients.
        Use only for system-wide messages (health pings, server shutdowns, etc.).
        Do NOT use for session-specific data.
        """
        payload = json.dumps(message)
        dead: Set[WebSocket] = set()
        for ws in list(self._ws_to_session.keys()):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        for ws in dead:
            session_id = self._ws_to_session.pop(ws, None)
            if session_id:
                self._session_to_ws.pop(session_id, None)

    @property
    def connection_count(self) -> int:
        return len(self._ws_to_session)
