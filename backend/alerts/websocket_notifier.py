"""
websocket_notifier.py — Real-time WebSocket alert push for VoiceGuard.

Manages connected WebSocket clients and broadcasts detection updates
and alerts to all connected frontend clients.
"""

from __future__ import annotations

import json
import logging
from typing import Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketNotifier:
    """
    Maintains a set of active WebSocket connections and
    broadcasts alert events to all connected clients.
    """

    def __init__(self):
        self._connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        self._connections.add(websocket)
        logger.info(f"WebSocket client connected. Total: {len(self._connections)}")

    async def disconnect(self, websocket: WebSocket) -> None:
        """Deregister a WebSocket connection."""
        self._connections.discard(websocket)
        logger.info(f"WebSocket client disconnected. Total: {len(self._connections)}")

    async def notify(self, event) -> None:
        """
        Broadcast an alert event to all connected WebSocket clients.
        Called by AlertManager.dispatch().
        """
        if not self._connections:
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

        dead_connections = set()
        for ws in list(self._connections):
            try:
                await ws.send_text(payload)
            except Exception:
                dead_connections.add(ws)

        for ws in dead_connections:
            self._connections.discard(ws)

    async def broadcast_raw(self, message: dict) -> None:
        """Send an arbitrary JSON message to all clients."""
        payload = json.dumps(message)
        dead = set()
        for ws in list(self._connections):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._connections.discard(ws)

    @property
    def connection_count(self) -> int:
        return len(self._connections)
