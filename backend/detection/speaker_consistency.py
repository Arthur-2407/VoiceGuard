"""
speaker_consistency.py — Cross-session speaker identity verification.

Compares the current speaker's embedding against an enrolled profile
to detect speaker identity anomalies (i.e., a different person pretending
to be an enrolled speaker).

This addresses the SIH requirement for:
"Cross-session consistency checks comparing ongoing call features against
historical genuine samples to detect anomalies in speaker identity."
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from backend.features.speaker_extractor import cosine_similarity

logger = logging.getLogger(__name__)


class SpeakerConsistencyChecker:
    """
    Maintains a reference speaker profile and checks ongoing
    audio chunks for speaker identity consistency.

    Usage:
        checker = SpeakerConsistencyChecker(threshold=0.75)
        checker.set_enrolled_profile(enrolled_embedding)
        result = checker.check(current_embedding)  # current_embedding may be None

    Important: check() now accepts None for current_embedding, which indicates
    that the ECAPA model was unavailable for this chunk. In that case the checker
    returns enrolled=True (no penalty) rather than treating zeros as a mismatch.
    """

    def __init__(self, threshold: float = 0.75):
        """
        Args:
            threshold: cosine similarity below this → speaker mismatch
        """
        self.threshold = threshold
        self._enrolled_profile: Optional[np.ndarray] = None
        self._enrolled_speaker_id: Optional[str] = None
        self._similarity_history: list = []

    def set_enrolled_profile(
        self,
        embedding: np.ndarray,
        speaker_id: Optional[str] = None,
    ) -> None:
        """Set the reference enrolled speaker profile."""
        self._enrolled_profile = embedding.astype(np.float32)
        self._enrolled_speaker_id = speaker_id
        self._similarity_history.clear()
        logger.info(f"Speaker profile set: speaker_id={speaker_id}")

    def clear_profile(self) -> None:
        """Remove enrolled profile (e.g., end of session)."""
        self._enrolled_profile = None
        self._enrolled_speaker_id = None
        self._similarity_history.clear()

    def check(self, current_embedding: Optional[np.ndarray]) -> dict:
        """
        Compare current chunk's speaker embedding against enrolled profile.

        Args:
            current_embedding: 192-dim float32 numpy array, or None when ECAPA
                               was unavailable for this chunk.

        Returns:
            dict with keys:
                - similarity: float cosine similarity [-1, 1], or None
                - is_consistent: bool (similarity >= threshold), or True when no data
                - speaker_id: enrolled speaker identifier
                - enrolled: bool (whether a profile is set)
                - embedding_available: bool (whether current_embedding was not None)
        """
        if self._enrolled_profile is None:
            return {
                "similarity": None,
                "is_consistent": True,   # No profile = no inconsistency
                "speaker_id": None,
                "enrolled": False,
                "embedding_available": current_embedding is not None,
            }

        # If current embedding is None (ECAPA unavailable), we cannot compare.
        # Return "consistent" with similarity=None rather than penalising the session
        # with a false mismatch from zeros.
        if current_embedding is None:
            logger.debug(
                "Speaker consistency check skipped: current embedding unavailable "
                "(ECAPA not loaded). No penalty applied."
            )
            return {
                "similarity": None,
                "is_consistent": True,
                "speaker_id": self._enrolled_speaker_id,
                "enrolled": True,
                "embedding_available": False,
            }

        similarity = cosine_similarity(current_embedding, self._enrolled_profile)
        self._similarity_history.append(similarity)
        is_consistent = similarity >= self.threshold

        if not is_consistent:
            logger.warning(
                f"Speaker identity mismatch: similarity={similarity:.3f} "
                f"(threshold={self.threshold}), enrolled speaker={self._enrolled_speaker_id}"
            )

        return {
            "similarity": float(similarity),
            "is_consistent": is_consistent,
            "speaker_id": self._enrolled_speaker_id,
            "enrolled": True,
            "embedding_available": True,
        }

    @property
    def mean_similarity(self) -> Optional[float]:
        """Mean cosine similarity across session (only over chunks where embedding was available)."""
        if not self._similarity_history:
            return None
        return float(np.mean(self._similarity_history))

    @property
    def has_enrolled_speaker(self) -> bool:
        return self._enrolled_profile is not None
