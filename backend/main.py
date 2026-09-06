"""
main.py — VoiceGuard FastAPI Application Entry Point.

Initializes:
  - Configuration loading
  - Database setup
  - Model preloading
  - Alert infrastructure (WebSocket notifier + webhook + alert manager)
  - API router registration
  - Static file serving (frontend)
  - CORS configuration

Run with:
  cd d:\\SIH\\voiceguard
  python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Ensure project root is on PYTHONPATH
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.config import get_settings

# Configure logging
settings = get_settings()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Application-level singletons ───────────────────────────────────────────────
# Use a single authoritative state dict so that every `from backend.main import …`
# call—across reloads and circular imports—always resolves to the same live object.
from backend.detection.detector import VoiceCloneDetector
from backend.alerts.alert_manager import AlertManager
from backend.alerts.websocket_notifier import WebSocketNotifier
from backend.alerts.webhook_notifier import WebhookNotifier

app_settings = get_settings()

_APP_STATE: dict = {
    "detector": None,
    "ws_notifier": None,
    "alert_manager": None,
}


def _get_state() -> dict:
    """Return the single authoritative application state dict."""
    return _APP_STATE


def get_app_detector() -> VoiceCloneDetector:
    """Return the live detector singleton."""
    return _APP_STATE["detector"]


def get_app_ws_notifier() -> WebSocketNotifier:
    """Return the live WebSocket notifier singleton."""
    return _APP_STATE["ws_notifier"]


def get_app_alert_manager() -> AlertManager:
    """Return the live alert manager singleton."""
    return _APP_STATE["alert_manager"]


# ---------------------------------------------------------------------------
# Backwards-compatible module-level properties:
# Route files that do `from backend.main import app_detector` will get a
# reference to the _APP_STATE dict value at call time via the getter above.
# For legacy attribute access we expose the same objects below, but they are
# re-resolved each request through the getter functions in each route file.
# ---------------------------------------------------------------------------


def _setup_alert_infrastructure():
    """Instantiate and register all notifiers with the alert manager."""
    # Instantiate singletons into the state dict (replaces any prior objects)
    _APP_STATE["ws_notifier"]    = WebSocketNotifier()
    _APP_STATE["alert_manager"]  = AlertManager()
    _APP_STATE["detector"]       = VoiceCloneDetector(app_settings)

    _APP_STATE["alert_manager"].register_notifier(_APP_STATE["ws_notifier"])

    if app_settings.webhooks.enabled and app_settings.webhooks.callback_url:
        webhook = WebhookNotifier(
            callback_url=app_settings.webhooks.callback_url,
            secret_token=app_settings.webhooks.secret_token,
            retry_attempts=app_settings.webhooks.retry_attempts,
            retry_delay_sec=app_settings.webhooks.retry_delay_sec,
            enabled=True,
        )
        _APP_STATE["alert_manager"].register_notifier(webhook)
        logger.info(f"Webhook notifier registered: {app_settings.webhooks.callback_url}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    logger.info("=" * 60)
    logger.info("VoiceGuard — AI Voice Cloning Detection System")
    logger.info("Starting up...")
    logger.info("=" * 60)

    # 1. Initialize database
    from backend.storage.database import init_db
    db_path = str(app_settings.abs_path(app_settings.storage.db_path))
    init_db(db_path)

    # 2. Create model weights directory
    weights_dir = app_settings.abs_path("backend/models/weights")
    weights_dir.mkdir(parents=True, exist_ok=True)

    # 3. Create data directory
    data_dir = app_settings.abs_path("data")
    data_dir.mkdir(parents=True, exist_ok=True)

    # 4. Set up alert infrastructure + create singletons
    _setup_alert_infrastructure()

    # 5. Initialize detector (loads models)
    logger.info("Initializing detection models (this may take a moment)...")
    try:
        _APP_STATE["detector"].initialize()
        logger.info("✓ Detection models initialized.")
    except Exception as exc:
        logger.error(f"Model initialization error: {exc}")
        logger.warning("Running in limited mode — detection pipeline may not be fully operational.")

    # 6. Set up Zeroconf for local network discovery
    zeroconf_instance = None
    try:
        from zeroconf import ServiceInfo, Zeroconf
        import socket
        
        # Determine active local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('10.255.255.255', 1))
            local_ip = s.getsockname()[0]
        except Exception:
            local_ip = '127.0.0.1'
        finally:
            s.close()
            
        if local_ip != '127.0.0.1' and app_settings.server.host == '0.0.0.0':
            desc = {'path': '/health', 'version': '1.0.0'}
            info = ServiceInfo(
                "_voiceguard._tcp.local.",
                f"VoiceGuard_{local_ip.replace('.', '-')}._voiceguard._tcp.local.",
                addresses=[socket.inet_aton(local_ip)],
                port=app_settings.server.port,
                properties=desc,
                server=f"voiceguard-{local_ip.replace('.', '-')}.local.",
            )
            zeroconf_instance = Zeroconf()
            zeroconf_instance.register_service(info)
            logger.info(f"Zeroconf mDNS service registered on {local_ip}:{app_settings.server.port}")
        else:
            logger.info("Zeroconf skipped: Server not bound to 0.0.0.0 or LAN IP unavailable.")
    except ImportError:
        logger.warning("Zeroconf not installed. Automatic network discovery will be unavailable.")
    except Exception as exc:
        logger.warning(f"Failed to start Zeroconf service: {exc}")

    logger.info("VoiceGuard is ready.")
    logger.info(f"  API:      http://{app_settings.server.host}:{app_settings.server.port}")
    logger.info(f"  Frontend: http://localhost:{app_settings.server.port}")
    logger.info(f"  Docs:     http://localhost:{app_settings.server.port}/docs")

    yield

    # Shutdown
    logger.info("VoiceGuard shutting down...")
    from backend.models.model_loader import unload_model
    unload_model()
    
    if zeroconf_instance:
        try:
            zeroconf_instance.unregister_all_services()
            zeroconf_instance.close()
            logger.info("Zeroconf service unregistered.")
        except Exception as exc:
            logger.error(f"Error unregistering Zeroconf: {exc}")
            
    logger.info("Goodbye.")


# ── FastAPI Application ────────────────────────────────────────────────────────
app = FastAPI(
    title="VoiceGuard — AI Voice Cloning Detection API",
    description=(
        "Real-time AI-powered detection of voice cloning impersonation attacks. "
        "Built for SIH 2026 | AICTE Cyber Security Cell."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS (configurable origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.server.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Route Registration ─────────────────────────────────────────────────────────
from backend.api.routes_stream import router as stream_router
from backend.api.routes_analyze import router as analyze_router
from backend.api.routes_enroll import router as enroll_router
from backend.api.routes_alerts_config import alerts_router, config_router

app.include_router(stream_router)     # WebSocket: /ws/stream
app.include_router(analyze_router)    # REST: /api/analyze
app.include_router(enroll_router)     # REST: /api/speakers/*
app.include_router(alerts_router)     # REST: /api/alerts/*
app.include_router(config_router)     # REST: /api/config/*

# ── Serve Frontend ─────────────────────────────────────────────────────────────
_FRONTEND_DIR = _PROJECT_ROOT / "frontend"
if _FRONTEND_DIR.exists():
    app.mount(
        "/static",
        StaticFiles(directory=str(_FRONTEND_DIR)),
        name="static",
    )

    @app.get("/", include_in_schema=False)
    async def serve_frontend():
        return FileResponse(str(_FRONTEND_DIR / "index.html"))

# ── Health Check ───────────────────────────────────────────────────────────────
@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "ok",
        "service": "VoiceGuard",
        "version": "1.0.0",
    }
