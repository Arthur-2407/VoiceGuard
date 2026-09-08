"""
database.py — SQLite database setup and session management for VoiceGuard.

Tables:
  - speakers: enrolled speaker profiles (embeddings, metadata)
  - audit_log: feature-only compliance log (NO raw audio stored)
  - sessions: call session records

Privacy-preserving: raw audio is never stored.
Only feature vectors and risk scores are persisted.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from sqlalchemy import (
        Column, DateTime, Float, Integer, String, Text, create_engine, event
    )
    from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
    from sqlalchemy.pool import StaticPool
    _SQLALCHEMY_AVAILABLE = True
except ImportError:
    _SQLALCHEMY_AVAILABLE = False
    logger.error("SQLAlchemy not available — database features disabled.")

import datetime
import numpy as np

def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


if _SQLALCHEMY_AVAILABLE:

    class Base(DeclarativeBase):
        pass

    class SpeakerProfile(Base):
        """Enrolled speaker profile with averaged ECAPA embedding."""
        __tablename__ = "speakers"

        id = Column(Integer, primary_key=True, autoincrement=True)
        speaker_id = Column(String(128), unique=True, nullable=False, index=True)
        name = Column(String(256), nullable=True)
        organization = Column(String(256), nullable=True)
        role = Column(String(128), nullable=True)
        # Stored as JSON-serialized list of floats
        embedding_json = Column(Text, nullable=False)
        embedding_dim = Column(Integer, default=192)
        num_samples = Column(Integer, default=1)
        created_at = Column(DateTime, default=_utcnow)
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

        def get_embedding(self) -> np.ndarray:
            return np.array(json.loads(self.embedding_json), dtype=np.float32)

        def set_embedding(self, emb: np.ndarray) -> None:
            self.embedding_json = json.dumps(emb.tolist())

    class AuditLogEntry(Base):
        """Compliance audit log — feature vectors and risk scores only, no raw audio."""
        __tablename__ = "audit_log"

        id = Column(Integer, primary_key=True, autoincrement=True)
        session_id = Column(String(64), nullable=False, index=True)
        chunk_id = Column(Integer, nullable=False)
        timestamp = Column(Float, nullable=False)
        detection_score = Column(Float, nullable=True)
        risk_score = Column(Float, nullable=True)
        alert_level = Column(String(16), nullable=True)
        speaker_id = Column(String(128), nullable=True)
        speaker_similarity = Column(Float, nullable=True)
        processing_ms = Column(Float, nullable=True)
        # Feature summary (NOT raw audio, NOT full embedding — just statistics)
        feature_summary_json = Column(Text, nullable=True)

    class CallSession(Base):
        """Records of call analysis sessions."""
        __tablename__ = "sessions"

        id = Column(Integer, primary_key=True, autoincrement=True)
        session_id = Column(String(64), unique=True, nullable=False, index=True)
        started_at = Column(DateTime, default=_utcnow)
        ended_at = Column(DateTime, nullable=True)
        total_chunks = Column(Integer, default=0)
        peak_risk = Column(Float, default=0.0)
        mean_risk = Column(Float, default=0.0)
        final_alert_level = Column(String(16), default="SAFE")
        speaker_id = Column(String(128), nullable=True)
        notes = Column(Text, nullable=True)

    _engine = None
    _SessionLocal = None

    def get_engine(db_path: str = "data/voiceguard.db"):
        """Get or create SQLAlchemy engine."""
        global _engine
        if _engine is None:
            db_file = Path(db_path)
            if not db_file.is_absolute():
                project_root = Path(__file__).resolve().parent.parent.parent
                db_file = project_root / db_path

            db_file.parent.mkdir(parents=True, exist_ok=True)
            db_url = f"sqlite:///{db_file}"

            _engine = create_engine(
                db_url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )

            # Enable WAL mode for better concurrent read performance
            @event.listens_for(_engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.close()

        return _engine

    def init_db(db_path: str = "data/voiceguard.db") -> None:
        """Create all tables if they don't exist."""
        engine = get_engine(db_path)
        Base.metadata.create_all(bind=engine)
        logger.info(f"Database initialized at {db_path}")

    def get_session_factory(db_path: str = "data/voiceguard.db"):
        """Return the session factory (create once, reuse)."""
        global _SessionLocal
        if _SessionLocal is None:
            engine = get_engine(db_path)
            _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        return _SessionLocal

    def get_db_session(db_path: str = "data/voiceguard.db"):
        """FastAPI dependency: yields a database session."""
        SessionLocal = get_session_factory(db_path)
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

else:
    # Stubs when SQLAlchemy is unavailable
    class SpeakerProfile:
        pass

    class AuditLogEntry:
        pass

    class CallSession:
        pass

    def init_db(*args, **kwargs):
        logger.warning("SQLAlchemy not available — database initialization skipped.")

    def get_db_session(*args, **kwargs):
        yield None
