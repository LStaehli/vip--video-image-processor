import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    loop = asyncio.get_running_loop()

    # Initialise database first — other services depend on it
    from app.services import database as db_service
    await db_service.init(settings.db_path)

    # Restore persisted general settings (override env/defaults)
    _PERSISTED = {"recording_output_dir", "recording_project_name", "recording_filename_pattern"}
    for key, value in (await db_service.load_app_settings()).items():
        if key in _PERSISTED:
            setattr(settings, key, value)
            logger.info("Restored setting: %s = %r", key, value)

    # Face store — async init loads enrolled faces from DB
    from app.services import face_store
    await face_store.init()

    # Notification service
    from app.services import notifications as notifier
    logger.info(
        "Notifications: telegram=%s email=%s",
        bool(settings.telegram_bot_token),
        bool(settings.smtp_host and settings.notify_email),
    )

    # Stream registry — one PipelineStack per enabled stream
    from app.stream.registry import StreamRegistry
    registry = StreamRegistry()

    streams = await db_service.load_streams()
    enabled_streams = [s for s in streams if s.get("enabled", 1)]

    # Seed the DB with a default stream on first run
    if not streams:
        default = await db_service.insert_stream(
            channel_number=1,
            name="Channel 1",
            url=settings.stream_url,
        )
        enabled_streams = [default]
        logger.info("Stream registry seeded with default stream (url=%s)", settings.stream_url)

    for stream in enabled_streams:
        try:
            await registry.start(stream, loop, notifier)
        except Exception as exc:
            logger.error("Failed to start stream %d '%s': %s", stream["id"], stream.get("name", "?"), exc)

    logger.info("VIP started — %d stream(s) active", len(registry))

    # Inject registry into all API modules
    from app.api import stream as stream_api
    stream_api.init(registry=registry)

    from app.api import config as config_api
    config_api.init(registry=registry)

    from app.api import recording as recording_api
    recording_api.init(registry=registry)

    from app.api import faces as faces_api
    faces_api.init(registry=registry)

    from app.api import streams as streams_api
    streams_api.init(registry=registry, loop=loop, notifier=notifier)

    yield  # ── Application runs here ──────────────────────────────────────────

    # ── Shutdown ─────────────────────────────────────────────────────────────
    await registry.stop_all()
    await db_service.close()
    logger.info("VIP shut down cleanly")


app = FastAPI(title="VIP - Video Image Processor", lifespan=lifespan)

from app.api.stream import router as stream_router
from app.api.config import router as config_router
from app.api.recording import router as recording_router
from app.api.zones import router as zones_router
from app.api.faces import router as faces_router
from app.api.streams import router as streams_router

app.include_router(stream_router)
app.include_router(config_router)
app.include_router(recording_router)
app.include_router(zones_router)
app.include_router(faces_router)
app.include_router(streams_router)

app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
