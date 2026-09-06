"""
routes_enroll.py — Speaker enrollment REST API.

POST /api/speakers/enroll  — Enroll a new speaker
GET  /api/speakers         — List enrolled speakers
DELETE /api/speakers/{id}  — Delete a speaker profile (GDPR)
"""

from __future__ import annotations

import io
import logging
import os
import tempfile
import uuid
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/speakers", tags=["Speaker Enrollment"])


class SpeakerInfo(BaseModel):
    speaker_id: str
    name: str
    organization: Optional[str] = None
    role: Optional[str] = None
    num_samples: int = 0
    created_at: Optional[str] = None


class EnrollResponse(BaseModel):
    speaker_id: str
    name: str
    num_samples: int
    message: str


@router.post("/enroll", response_model=EnrollResponse)
async def enroll_speaker(
    name: str = Form(...),
    files: List[UploadFile] = File(...),
    speaker_id: Optional[str] = Form(None),
    organization: Optional[str] = Form(None),
    role: Optional[str] = Form(None),
):
    """
    Enroll a speaker by uploading 1–N audio reference files.

    Per the Baidu NeurIPS paper, ≥5 samples significantly improves
    speaker embedding accuracy (see 1802.06006v3 Figure 9).

    Audio files are processed to embeddings immediately.
    Raw audio is NOT stored.
    """
    from backend.main import app_settings
    from backend.audio.preprocessor import load_audio, preprocess_audio
    from backend.features.speaker_extractor import extract_speaker_embedding, average_embeddings
    from backend.storage.speaker_registry import SpeakerRegistry
    import numpy as np

    if not files:
        raise HTTPException(status_code=422, detail="At least one audio file is required.")

    if len(files) < 3:
        logger.warning(
            f"Only {len(files)} enrollment files provided for speaker '{name}'. "
            "5+ files recommended for better accuracy (per 1802.06006v3)."
        )

    embeddings = []
    processed_count = 0

    for upload in files:
        suffix = os.path.splitext(upload.filename or "audio")[1] or ".wav"
        content = await upload.read()

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            audio, sr = load_audio(tmp_path, target_sr=app_settings.audio.sample_rate)
            audio = preprocess_audio(
                audio, sr=app_settings.audio.sample_rate,
                target_sr=app_settings.audio.sample_rate,
                apply_vad=True,
            )
            emb = extract_speaker_embedding(
                audio,
                sr=app_settings.audio.sample_rate,
                model_name=app_settings.detection.ecapa_model,
            )
            embeddings.append(emb)
            processed_count += 1
        except Exception as exc:
            logger.warning(f"Failed to process enrollment file {upload.filename}: {exc}")
        finally:
            os.unlink(tmp_path)  # Privacy: delete temp file immediately

    if not embeddings:
        raise HTTPException(
            status_code=422,
            detail="Could not extract speaker embeddings from any uploaded file."
        )

    # Average embeddings into profile
    avg_embedding = average_embeddings(embeddings)

    # Store in registry
    registry = SpeakerRegistry(
        db_path=str(app_settings.abs_path(app_settings.storage.db_path))
    )
    final_speaker_id = registry.enroll_speaker(
        name=name,
        embedding=avg_embedding,
        speaker_id=speaker_id,
        organization=organization,
        role=role,
        num_samples=processed_count,
    )

    return EnrollResponse(
        speaker_id=final_speaker_id,
        name=name,
        num_samples=processed_count,
        message=(
            f"Speaker '{name}' enrolled successfully with {processed_count} samples. "
            f"Speaker ID: {final_speaker_id}"
        ),
    )


@router.get("", response_model=List[SpeakerInfo])
async def list_speakers():
    """List all enrolled speaker profiles (metadata only)."""
    from backend.main import app_settings
    from backend.storage.speaker_registry import SpeakerRegistry

    registry = SpeakerRegistry(
        db_path=str(app_settings.abs_path(app_settings.storage.db_path))
    )
    return registry.list_speakers()


@router.delete("/{speaker_id}")
async def delete_speaker(speaker_id: str):
    """Delete a speaker profile (GDPR/PDP compliance)."""
    from backend.main import app_settings
    from backend.storage.speaker_registry import SpeakerRegistry

    registry = SpeakerRegistry(
        db_path=str(app_settings.abs_path(app_settings.storage.db_path))
    )
    deleted = registry.delete_speaker(speaker_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Speaker '{speaker_id}' not found.")
    return {"message": f"Speaker '{speaker_id}' deleted.", "speaker_id": speaker_id}
