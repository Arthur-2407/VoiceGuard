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

Architecture notes:
  - ML inference is offloaded to a thread pool via run_in_executor() so it never
    blocks the FastAPI async event loop during heavy model computation.
  - WebSocket alerts are delivered only to the originating session's client via
    the session-scoped WebSocketNotifier, preventing cross-session leakage.
  - WebSocketDisconnect is re-raised from the inner receive block so the outer
    try/finally always runs the disconnect cleanup.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import time
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
    Heavy ML inference is run in a thread pool to avoid blocking the event loop.
    """
    from backend.main import (
        get_app_detector,
        get_app_alert_manager,
        get_app_ws_notifier,
        app_settings,
    )
    app_detector      = get_app_detector()
    app_alert_manager = get_app_alert_manager()
    app_ws_notifier   = get_app_ws_notifier()

    # Lazy initialization guard: ensure detector is initialized before processing stream
    if app_detector is not None and not app_detector.is_initialized:
        logger.warning("Detector not initialized at WebSocket stream connect — attempting lazy init...")
        try:
            app_detector.initialize()
            if app_detector.is_initialized:
                logger.info("Lazy detector initialization succeeded.")
            else:
                logger.warning("Lazy detector initialization completed, but detection models are still unavailable (heuristic fallback).")
        except Exception as exc:
            logger.error(f"Lazy detector initialization failed: {exc}")

    from backend.audio.capture import StreamCapture
    from backend.detection.risk_engine import build_risk_engine_from_settings
    from backend.detection.speaker_consistency import SpeakerConsistencyChecker
    from backend.detection.threshold_engine import ThresholdEngine
    from backend.storage.audit_log import AuditLogger

    session_id = str(uuid.uuid4())[:12]

    # Register this WebSocket with its session_id so alerts are routed only here.
    await app_ws_notifier.connect(websocket, session_id)

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
        threshold_critical=app_settings.risk.alert_thresholds.critical,
    )
    audit_logger = AuditLogger(
        db_path=str(app_settings.abs_path(app_settings.storage.db_path)),
        enabled=app_settings.privacy.log_features_only,
    )

    # Chunk counter for this session
    chunk_counter = 0
    frames_received = 0
    valid_frames = 0
    empty_frames = 0

    # Send session start message
    await websocket.send_text(json.dumps({
        "type": "session_start",
        "session_id": session_id,
        "detector_ready": app_detector is not None and app_detector.is_initialized
    }))

    # Get the running event loop for run_in_executor calls
    loop = asyncio.get_event_loop()

    try:
        while True:
            # Receive websocket message securely (handles both text and bytes)
            message = await websocket.receive()

            if message["type"] == "websocket.disconnect":
                raise WebSocketDisconnect(message.get("code", 1000))
            
            if "text" in message and message["text"]:
                try:
                    msg = json.loads(message["text"])
                    if msg.get("type") == "enroll_speaker":
                        # Client selects a speaker profile for consistency checking
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
                        chunk_counter = 0
                    elif msg.get("type") == "start_call_monitor":
                        # Client explicitly tags this session as a call monitoring session
                        logger.info(f"Session {session_id} switched to CALL_MONITOR mode")
                        risk_engine.session_type = "CALL_MONITOR"
                        risk_engine.audio_source = msg.get("audio_source", "MIXED_ACOUSTIC")
                        risk_engine.capture_mode = msg.get("capture_mode", "ACOUSTIC_FALLBACK")
                    elif msg.get("type") == "stop_call_monitor":
                        logger.info(f"Session {session_id} stopped CALL_MONITOR mode")
                        risk_engine.session_type = "LIVE_MONITOR"
                except Exception as e:
                    logger.warning(f"Error parsing text message in stream: {e}")
                continue

            data = message.get("bytes")
            if not data:
                continue

            frames_received += 1
            logger.debug(f"Received raw audio data, length: {len(data)} bytes")

            try:
                # Push into stream buffer; get ready chunks
                chunks = stream.push(data)

                for chunk in chunks:
                    current_chunk_id = chunk_counter
                    chunk_counter += 1

                    # Track overall processing latency for this chunk
                    t_receive = time.monotonic()

                    # Apply VAD and normalization in the thread pool (CPU-bound preprocessing)
                    from backend.audio.preprocessor import preprocess_audio
                    
                    t_preprocess_start = time.monotonic()
                    chunk = await loop.run_in_executor(
                        None,
                        functools.partial(
                            preprocess_audio,
                            chunk,
                            sr=app_settings.audio.sample_rate,
                            target_sr=app_settings.audio.sample_rate,
                            apply_vad=True,
                        )
                    )
                    t_preprocess_end = time.monotonic()

                    if len(chunk) == 0:
                        empty_frames += 1
                        # VAD dropped the entire chunk (silence)
                        await websocket.send_text(json.dumps({
                            "type": "status_update",
                            "status": "WAITING_FOR_DATA"
                        }))
                        continue
                    
                    valid_frames += 1

                    # Run ML detection in thread pool — prevents blocking the async event loop
                    result = await loop.run_in_executor(
                        None,
                        functools.partial(
                            app_detector.process_chunk,
                            chunk,
                            chunk_id=current_chunk_id,
                        )
                    )
                    t_inference_end = time.monotonic()
                    
                    logger.debug(
                        f"Latency breakdown - pre-process: {(t_preprocess_end - t_preprocess_start)*1000:.1f}ms, "
                        f"inference: {(t_inference_end - t_preprocess_end)*1000:.1f}ms, "
                        f"total: {(t_inference_end - t_receive)*1000:.1f}ms"
                    )

                    # Speaker consistency check (uses already-extracted embedding, no heavy compute)
                    consistency_result = {
                        "similarity": None,
                        "enrolled": False,
                        "embedding_available": False,
                    }
                    speaker_similarity = None
                    # result.speaker_embedding is None when ECAPA was unavailable
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

                    # Dispatch alert (delivered only to this session's WebSocket)
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

            except Exception as frame_exc:
                logger.error(f"Error processing audio frame: {frame_exc}", exc_info=True)
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "status": "DETECTOR_UNAVAILABLE",
                    "message": f"Audio processing failed: {str(frame_exc)}"
                }))
                continue

    except WebSocketDisconnect:
        logger.info(f"WebSocket session disconnected: {session_id}")
    except Exception as exc:
        logger.error(f"WebSocket session error: {exc}")
    finally:
        await app_ws_notifier.disconnect(websocket)
        # Log session summary
        summary = risk_engine.get_session_summary()
        peak_risk = summary.get('peak_risk')
        peak_risk_display = f"{peak_risk:.3f}" if isinstance(peak_risk, (int, float)) else str(peak_risk)
        logger.info(
            f"Session {session_id} ended: "
            f"peak_risk={peak_risk_display}, "
            f"chunks={summary.get('total_chunks', 0)}, "
            f"frames_received={frames_received}, "
            f"valid_frames={valid_frames}, "
            f"empty_frames={empty_frames}"
        )
