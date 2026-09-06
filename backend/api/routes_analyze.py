"""
routes_analyze.py — REST endpoint for audio file analysis.

POST /api/analyze
  Accepts an uploaded audio file (WAV, MP3, FLAC, etc.)
  Runs the full detection pipeline
  Returns risk score, alert level, and recommendation

POST /api/analyze/url
  Accepts a public audio URL for analysis
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Analysis"])


class AnalysisResponse(BaseModel):
    session_id: str
    filename: str
    total_chunks: int
    peak_risk: float
    mean_risk: float
    final_risk: float
    alert_level: str
    recommendation: dict
    chunk_scores: list
    processing_time_ms: float


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze_audio_file(
    file: UploadFile = File(...),
    speaker_id: Optional[str] = Form(None),
):
    """
    Analyze an uploaded audio file for voice cloning.

    Returns:
      - risk score per chunk
      - overall peak and mean risk
      - alert level and recommendation
    """
    from backend.main import get_app_detector, app_settings
    from backend.audio.preprocessor import load_audio, preprocess_audio, chunk_audio
    from backend.detection.risk_engine import build_risk_engine_from_settings
    from backend.detection.speaker_consistency import SpeakerConsistencyChecker
    from backend.detection.threshold_engine import ThresholdEngine
    from backend.storage.speaker_registry import SpeakerRegistry
    import time

    # Always fetch via getter so we get the live singleton (not a stale import reference)
    app_detector = get_app_detector()

    # Lazy initialization: if the detector exists but wasn’t initialized yet,
    # attempt to initialize now (handles reload / deferred startup scenarios).
    if app_detector is None:
        raise HTTPException(
            status_code=503,
            detail="Detection subsystem not yet created. Please wait a moment and retry."
        )

    if not app_detector.is_initialized:
        logger.warning("Detector not initialized at request time — attempting lazy init...")
        try:
            app_detector.initialize()
            logger.info("Lazy detector initialization succeeded.")
        except Exception as exc:
            logger.error(f"Lazy detector initialization failed: {exc}")
            raise HTTPException(
                status_code=503,
                detail="Detector initialization failed. Please check server logs and retry."
            )

    # Read uploaded file to temp location
    # Use .dat suffix — the actual format is determined by FFmpeg/soundfile probing, not extension
    session_id = str(uuid.uuid4())[:12]

    t_start = time.perf_counter()

    try:
        content = await file.read()

        # File size guard (from config, default 200 MB)
        max_bytes = app_settings.upload.max_file_size_bytes
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Uploaded file is too large ({len(content) // (1024*1024)} MB). "
                       f"Maximum allowed size is {max_bytes // (1024*1024)} MB."
            )

        with tempfile.NamedTemporaryFile(suffix=".dat", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        # Normalization: detect container, extract audio if video, convert to MP3
        try:
            from backend.audio.preprocessor import normalize_to_mp3
            mp3_path = normalize_to_mp3(tmp_path)
            if mp3_path != tmp_path:
                os.unlink(tmp_path)  # delete original temp file; mp3_path is the working file
                tmp_path = mp3_path
        except (ValueError, RuntimeError) as exc:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception as exc:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise HTTPException(status_code=422, detail=f"Audio format error: {exc}")



        # Load and preprocess
        try:
            audio, sr = load_audio(tmp_path, target_sr=app_settings.audio.sample_rate)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Could not decode audio file: {exc}")
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)  # Privacy: delete temp file immediately

        audio = preprocess_audio(
            audio, sr=app_settings.audio.sample_rate,
            target_sr=app_settings.audio.sample_rate,
            apply_vad=True,
        )
        chunks = chunk_audio(
            audio,
            sr=app_settings.audio.sample_rate,
            chunk_duration=app_settings.audio.chunk_duration_sec,
            overlap_ratio=app_settings.audio.overlap_ratio,
        )

        if not chunks:
            raise HTTPException(status_code=422, detail="No audio content found in file.")

        # Set up per-request detection components
        risk_engine = build_risk_engine_from_settings(app_settings)
        consistency_checker = SpeakerConsistencyChecker(
            threshold=app_settings.speaker.consistency_threshold
        )
        threshold_engine = ThresholdEngine(
            threshold_low=app_settings.risk.alert_thresholds.low,
            threshold_medium=app_settings.risk.alert_thresholds.medium,
            threshold_high=app_settings.risk.alert_thresholds.high,
        )

        # Load speaker profile if specified
        if speaker_id:
            registry = SpeakerRegistry(
                db_path=str(app_settings.abs_path(app_settings.storage.db_path))
            )
            enrolled_emb = registry.get_embedding(speaker_id)
            if enrolled_emb is not None:
                consistency_checker.set_enrolled_profile(enrolled_emb, speaker_id)

        chunk_scores = []
        for i, chunk in enumerate(chunks):
            result = app_detector.process_chunk(chunk, chunk_id=i)
            speaker_sim = None
            if result.speaker_embedding is not None:
                c_result = consistency_checker.check(result.speaker_embedding)
                speaker_sim = c_result.get("similarity")

            snapshot = risk_engine.update(
                chunk_id=i,
                detection_score=result.synthetic_probability,
                speaker_similarity=speaker_sim,
            )

            chunk_scores.append({
                "chunk_id": i,
                "detection_score": result.synthetic_probability,
                "risk_score": snapshot.combined_risk,
                "alert_level": snapshot.alert_level.value,
                "processing_ms": result.processing_time_ms,
            })

        summary = risk_engine.get_session_summary()
        final_risk = chunk_scores[-1]["risk_score"] if chunk_scores else 0.0
        recommendation = threshold_engine.evaluate(summary["peak_risk"])

        t_end = time.perf_counter()

        return AnalysisResponse(
            session_id=session_id,
            filename=file.filename or "unknown",
            total_chunks=len(chunks),
            peak_risk=summary["peak_risk"],
            mean_risk=summary["mean_risk"],
            final_risk=final_risk,
            alert_level=recommendation.alert_level.value,
            recommendation={
                "title": recommendation.title,
                "message": recommendation.message,
                "actions": recommendation.actions,
                "color": recommendation.color,
            },
            chunk_scores=chunk_scores,
            processing_time_ms=(t_end - t_start) * 1000,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Analysis failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(exc)}")
