"""
audit_log.py — Privacy-preserving compliance audit logger.

Logs detection events with feature statistics and risk scores.
Never stores raw audio — only derived features and scores.

Implements the SIH requirement:
"Support for anonymization or feature-only logging to comply with
data protection and privacy requirements."
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_DB_AVAILABLE = False
try:
    from backend.storage.database import AuditLogEntry, get_session_factory
    _DB_AVAILABLE = True
except ImportError:
    pass


class AuditLogger:
    """
    Feature-only compliance audit logger.
    Logs detection events to SQLite without storing raw audio.
    """

    def __init__(self, db_path: str = "data/voiceguard.db", enabled: bool = True):
        self.db_path = db_path
        self.enabled = enabled

    def _get_session(self):
        from backend.storage.database import get_session_factory
        return get_session_factory(self.db_path)()

    def log_chunk(
        self,
        session_id: str,
        chunk_id: int,
        detection_score: float,
        risk_score: float,
        alert_level: str,
        speaker_id: Optional[str] = None,
        speaker_similarity: Optional[float] = None,
        processing_ms: Optional[float] = None,
        prosodic_features: Optional[np.ndarray] = None,
    ) -> None:
        """
        Log a detection event for a single audio chunk.

        Privacy: only scores and statistical summaries are stored.
        No raw audio, no full embeddings.
        """
        if not self.enabled:
            return

        feature_summary = {}
        if prosodic_features is not None:
            # Store prosodic statistics as compact summary
            feature_summary = {
                "f0_mean": float(prosodic_features[0]),
                "f0_std": float(prosodic_features[1]),
                "jitter": float(prosodic_features[2]),
                "shimmer": float(prosodic_features[3]),
                "hnr": float(prosodic_features[4]),
                "zcr": float(prosodic_features[5]),
                "energy": float(prosodic_features[6]),
            }

        if not _DB_AVAILABLE:
            # Fallback: log to Python logger only
            logger.info(
                f"AUDIT | session={session_id} chunk={chunk_id} "
                f"detect={detection_score:.4f} risk={risk_score:.4f} "
                f"level={alert_level} speaker={speaker_id}"
            )
            return

        db = self._get_session()
        try:
            entry = AuditLogEntry(
                session_id=session_id,
                chunk_id=chunk_id,
                timestamp=time.time(),
                detection_score=detection_score,
                risk_score=risk_score,
                alert_level=alert_level,
                speaker_id=speaker_id,
                speaker_similarity=speaker_similarity,
                processing_ms=processing_ms,
                feature_summary_json=json.dumps(feature_summary) if feature_summary else None,
            )
            db.add(entry)
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.error(f"Audit log write failed: {exc}")
        finally:
            db.close()

    def get_session_logs(self, session_id: str) -> list:
        """Retrieve all audit log entries for a session."""
        if not _DB_AVAILABLE:
            return []
        db = self._get_session()
        try:
            entries = (
                db.query(AuditLogEntry)
                .filter_by(session_id=session_id)
                .order_by(AuditLogEntry.chunk_id)
                .all()
            )
            return [
                {
                    "chunk_id": e.chunk_id,
                    "timestamp": e.timestamp,
                    "detection_score": e.detection_score,
                    "risk_score": e.risk_score,
                    "alert_level": e.alert_level,
                    "speaker_similarity": e.speaker_similarity,
                    "processing_ms": e.processing_ms,
                }
                for e in entries
            ]
        finally:
            db.close()
