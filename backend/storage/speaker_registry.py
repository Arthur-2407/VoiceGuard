"""
speaker_registry.py — Speaker enrollment and profile management.

Provides CRUD operations for enrolled speaker profiles.
Profiles store averaged ECAPA speaker embeddings, not raw audio.
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    from sqlalchemy.orm import Session
    from backend.storage.database import SpeakerProfile
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False


class SpeakerRegistry:
    """CRUD interface for enrolled speaker profiles."""

    def __init__(self, db_path: str = "data/voiceguard.db"):
        self.db_path = db_path

    def _get_session(self):
        from backend.storage.database import get_session_factory
        return get_session_factory(self.db_path)()

    def enroll_speaker(
        self,
        name: str,
        embedding: np.ndarray,
        speaker_id: Optional[str] = None,
        organization: Optional[str] = None,
        role: Optional[str] = None,
        num_samples: int = 1,
    ) -> str:
        """
        Store a new speaker profile.

        Args:
            name:           display name
            embedding:      192-dim ECAPA embedding (averaged over samples)
            speaker_id:     custom ID (auto-generated if None)
            organization:   organization name
            role:           role/title
            num_samples:    number of audio samples used to create this profile

        Returns:
            speaker_id (str)
        """
        if speaker_id is None:
            speaker_id = str(uuid.uuid4())[:8]

        if not _DB_AVAILABLE:
            logger.warning("Database not available — speaker not persisted.")
            return speaker_id

        db = self._get_session()
        try:
            # Check for existing
            existing = db.query(SpeakerProfile).filter_by(speaker_id=speaker_id).first()
            if existing:
                existing.set_embedding(embedding)
                existing.num_samples = num_samples
                existing.name = name
                logger.info(f"Updated speaker profile: {speaker_id}")
            else:
                profile = SpeakerProfile(
                    speaker_id=speaker_id,
                    name=name,
                    organization=organization,
                    role=role,
                    num_samples=num_samples,
                    embedding_dim=len(embedding),
                )
                profile.set_embedding(embedding)
                db.add(profile)
                logger.info(f"Enrolled new speaker: {speaker_id} ({name})")

            db.commit()
            return speaker_id
        except Exception as exc:
            db.rollback()
            logger.error(f"Speaker enrollment failed: {exc}")
            raise
        finally:
            db.close()

    def get_embedding(self, speaker_id: str) -> Optional[np.ndarray]:
        """Retrieve stored embedding for a speaker."""
        if not _DB_AVAILABLE:
            return None
        db = self._get_session()
        try:
            profile = db.query(SpeakerProfile).filter_by(speaker_id=speaker_id).first()
            if profile:
                return profile.get_embedding()
            return None
        finally:
            db.close()

    def list_speakers(self) -> List[dict]:
        """Return a list of all enrolled speakers (metadata only, no embeddings)."""
        if not _DB_AVAILABLE:
            return []
        db = self._get_session()
        try:
            profiles = db.query(SpeakerProfile).all()
            return [
                {
                    "speaker_id": p.speaker_id,
                    "name": p.name,
                    "organization": p.organization,
                    "role": p.role,
                    "num_samples": p.num_samples,
                    "created_at": str(p.created_at),
                }
                for p in profiles
            ]
        finally:
            db.close()

    def delete_speaker(self, speaker_id: str) -> bool:
        """Delete a speaker profile (GDPR/PDP compliance)."""
        if not _DB_AVAILABLE:
            return False
        db = self._get_session()
        try:
            profile = db.query(SpeakerProfile).filter_by(speaker_id=speaker_id).first()
            if profile:
                db.delete(profile)
                db.commit()
                logger.info(f"Deleted speaker profile: {speaker_id}")
                return True
            return False
        except Exception as exc:
            db.rollback()
            logger.error(f"Speaker deletion failed: {exc}")
            return False
        finally:
            db.close()
