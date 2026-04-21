import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.stream.reader import StreamReader
from app.stream.pipeline import FramePipeline
from app.stream.websocket_manager import WebSocketManager

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


_HEALTH_INTERVAL = 30  # seconds between health log lines


async def _health_check_loop(reader, pipeline, ws_manager) -> None:
    """Logs stream health to the terminal every _HEALTH_INTERVAL seconds."""
    while True:
        await asyncio.sleep(_HEALTH_INTERVAL)
        status = "CONNECTED" if reader.connected else "DISCONNECTED"
        logger.info(
            "[health] stream=%s source=%s fps=%.1f clients=%d",
            status,
            settings.stream_url,
            pipeline.actual_fps,
            ws_manager.video_client_count,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    loop = asyncio.get_running_loop()

    ws_manager = WebSocketManager()
    reader = StreamReader(source=settings.stream_source, loop=loop)
    pipeline = FramePipeline(input_queue=reader.queue, ws_manager=ws_manager)

    # Always add all processors so runtime toggles work without restart.
    # Each processor checks its own .enabled flag before doing any work.
    from app.processors.motion import MotionProcessor
    motion_proc = MotionProcessor()
    motion_proc.enabled = settings.enable_motion
    pipeline.add_processor(motion_proc)
    logger.info("MotionProcessor added (enabled=%s)", motion_proc.enabled)

    from app.processors.zones import ZoneProcessor
    zone_proc = ZoneProcessor(ws_manager=ws_manager)
    zone_proc.enabled = settings.enable_zones
    pipeline.add_processor(zone_proc)
    logger.info("ZoneProcessor added (enabled=%s)", zone_proc.enabled)

    if settings.enable_detection:
        from app.processors.detection import DetectionProcessor
        pipeline.add_processor(DetectionProcessor())
        logger.info("DetectionProcessor enabled")

    # Inject dependencies into route handlers
    from app.api import stream as stream_api
    stream_api.init(ws_manager=ws_manager, pipeline=pipeline, reader=reader)

    from app.api import config as config_api
    config_api.init(pipeline=pipeline, reader=reader)

    from app.services.recording import RecordingService
    recorder = RecordingService()
    pipeline._recorder = recorder

    from app.api import recording as recording_api
    recording_api.init(recorder=recorder, pipeline=pipeline)

    # Start background tasks
    reader.start()
    pipeline_task = asyncio.create_task(pipeline.run(), name="frame-pipeline")
    health_task   = asyncio.create_task(
        _health_check_loop(reader, pipeline, ws_manager), name="health-check"
    )

    logger.info("VIP started — stream source: %s", settings.stream_url)

    yield  # ── Application runs here ──────────────────────────────────────────

    # ── Shutdown ─────────────────────────────────────────────────────────────
    pipeline.stop()
    for task in (pipeline_task, health_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    reader.stop()
    logger.info("VIP shut down cleanly")


app = FastAPI(title="VIP - Video Image Processor", lifespan=lifespan)

from app.api.stream import router as stream_router
from app.api.config import router as config_router
from app.api.recording import router as recording_router
from app.api.zones import router as zones_router

app.include_router(stream_router)
app.include_router(config_router)
app.include_router(recording_router)
app.include_router(zones_router)

app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
