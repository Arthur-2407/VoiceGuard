"""
routes_stream.py — WebSocket endpoint for real-time audio stream analysis.

Endpoint: GET /ws/stream

Protocol:
  Client → Server: raw PCM audio bytes (int16, 16kHz, mono)
  Server → Client: JSON risk update messages

Message format (server → client):
  {
    "type": "risk_update",
    "session_id": "...",
    "chunk_id": 0,
    "timestamp": 1234567890.0,
    "risk_score": 0.72,
    "alert_level": "MEDIUM",
    "detection_score": 0.68,
    "recommendation": { "title": "...", "message": "...", "actions": [...], "color": "..." }
  }
"""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/stream")
async def websocket_stream(websocket: WebSocket):
    """
    Real-time audio stream analysis WebSocket endpoint.

    Client sends raw PCM audio bytes continuously.
    Server responds with JSON risk updates after each complete chunk.
    """
    from backend.main import (
        get_app_detector,
        get_app_alert_manager,
        get_app_ws_notifier,
        app_settings,
    )
    app_detector    = get_app_detector()
    app_alert_manager = get_app_alert_manager()
    app_ws_notifier = get_app_ws_notifier()
    from backend.audio.capture import StreamCapture
    from backend.detection.risk_engine import build_risk_engine_from_settings
    from backend.detection.speaker_consistency import SpeakerConsistencyChecker
    from backend.detection.threshold_engine import ThresholdEngine
    from backend.storage.audit_log import AuditLogger

    await app_ws_notifier.connect(websocket)
    session_id = str(uuid.uuid4())[:12]

    logger.info(f"WebSocket stream session started: {session_id}")

    # Per-session objects
    stream = StreamCapture(
        sample_rate=app_settings.audio.sample_rate,
        chunk_sec=app_settings.audio.chunk_duration_sec,
        overlap_ratio=app_settings.audio.overlap_ratio,
        src_dtype="int16",
        channels=1,
    )
    risk_engine = build_risk_engine_from_settings(app_settings)
    consistency_checker = SpeakerConsistencyChecker(
        threshold=app_settings.speaker.consistency_threshold
    )
    threshold_engine = ThresholdEngine(
        threshold_low=app_settings.risk.alert_thresholds.low,
        threshold_medium=app_settings.risk.alert_thresholds.medium,
        threshold_high=app_settings.risk.alert_thresholds.high,
    )
    audit_logger = AuditLogger(
        db_path=str(app_settings.abs_path(app_settings.storage.db_path)),
        enabled=app_settings.privacy.log_features_only,
    )

    # Send session start message
    await websocket.send_text(json.dumps({
        "type": "session_start",
        "session_id": session_id,
    }))

    try:
        while True:
            # Receive audio bytes from client
            try:
                data = await websocket.receive_bytes()
            except Exception:
                # Also accept text control messages
                try:
                    text = await websocket.receive_text()
                    msg = json.loads(text)
                    if msg.get("type") == "enroll_speaker":
                        # Client sends speaker_id to use for consistency check
                        speaker_id = msg.get("speaker_id")
                        if speaker_id:
                            from backend.storage.speaker_registry import SpeakerRegistry
                            registry = SpeakerRegistry(
                                db_path=str(app_settings.abs_path(app_settings.storage.db_path))
                            )
                            emb = registry.get_embedding(speaker_id)
                            if emb is not None:
                                consistency_checker.set_enrolled_profile(emb, speaker_id)
                                await websocket.send_text(json.dumps({
                                    "type": "speaker_enrolled",
                                    "speaker_id": speaker_id,
                                }))
                    elif msg.get("type") == "reset":
                        risk_engine.reset()
                        consistency_checker.clear_profile()
                        stream.reset()
                    continue
                except Exception:
                    break

            # Push into stream buffer; get ready chunks
            chunks = stream.push(data)

            for chunk in chunks:
                # Apply VAD and normalization so heuristics don't get skewed by silence gaps in the live stream
                from backend.audio.preprocessor import preprocess_audio
                chunk = preprocess_audio(
                    chunk, sr=app_settings.audio.sample_rate,
                    target_sr=app_settings.audio.sample_rate,
                    apply_vad=True,
                )

                chunk_counter = getattr(stream, "chunk_counter", 0)
                setattr(stream, "chunk_counter", chunk_counter + 1)

                # Run detection
                result = app_detector.process_chunk(chunk, chunk_id=chunk_counter)

                # Speaker consistency check
                consistency_result = {"similarity": None, "enrolled": False}
                speaker_similarity = None
                if result.speaker_embedding is not None:
                    consistency_result = consistency_checker.check(result.speaker_embedding)
                    speaker_similarity = consistency_result.get("similarity")

                # Risk aggregation
                risk_snapshot = risk_engine.update(
                    chunk_id=result.chunk_id,
                    detection_score=result.synthetic_probability,
                    speaker_similarity=speaker_similarity,
                )

                # Get recommendation
                recommendation = threshold_engine.evaluate(risk_snapshot.combined_risk)

                # Dispatch alert
                await app_alert_manager.dispatch(
                    session_id=session_id,
                    chunk_id=result.chunk_id,
                    risk_score=risk_snapshot.combined_risk,
                    alert_level=risk_snapshot.alert_level,
                    recommendation=recommendation,
                    detection_score=result.synthetic_probability,
                    speaker_id=consistency_result.get("speaker_id"),
                    speaker_similarity=speaker_similarity,
                )

                # Audit log
                audit_logger.log_chunk(
                    session_id=session_id,
                    chunk_id=result.chunk_id,
                    detection_score=result.synthetic_probability,
                    risk_score=risk_snapshot.combined_risk,
                    alert_level=risk_snapshot.alert_level.value,
                    processing_ms=result.processing_time_ms,
                )

    except WebSocketDisconnect:
        logger.info(f"WebSocket session disconnected: {session_id}")
    except Exception as exc:
        logger.error(f"WebSocket session error: {exc}")
    finally:
        await app_ws_notifier.disconnect(websocket)
        # Send session summary
        summary = risk_engine.get_session_summary()
        logger.info(
            f"Session {session_id} ended: "
            f"peak_risk={summary.get('peak_risk', 0):.3f}, "
            f"chunks={summary.get('total_chunks', 0)}"
        )
