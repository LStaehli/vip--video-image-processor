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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    loop = asyncio.get_running_loop()

    ws_manager = WebSocketManager()
    reader = StreamReader(source=settings.stream_source, loop=loop)
    pipeline = FramePipeline(input_queue=reader.queue, ws_manager=ws_manager)

    # Wire up processors based on feature flags
    if settings.enable_motion:
        from app.processors.motion import MotionProcessor
        pipeline.add_processor(MotionProcessor())
        logger.info("MotionProcessor enabled")

    if settings.enable_zones:
        from app.processors.zones import ZoneProcessor
        pipeline.add_processor(ZoneProcessor(ws_manager=ws_manager))
        logger.info("ZoneProcessor enabled")

    if settings.enable_detection:
        from app.processors.detection import DetectionProcessor
        pipeline.add_processor(DetectionProcessor())
        logger.info("DetectionProcessor enabled")

    # Inject dependencies into route handlers
    from app.api import stream as stream_api
    stream_api.init(ws_manager=ws_manager, pipeline=pipeline, reader=reader)

    from app.api import config as config_api
    config_api.init(pipeline=pipeline)

    # Start background tasks
    reader.start()
    pipeline_task = asyncio.create_task(pipeline.run(), name="frame-pipeline")

    logger.info("VIP started — stream source: %s", settings.stream_url)

    yield  # ── Application runs here ──────────────────────────────────────────

    # ── Shutdown ─────────────────────────────────────────────────────────────
    pipeline.stop()
    pipeline_task.cancel()
    try:
        await pipeline_task
    except asyncio.CancelledError:
        pass
    reader.stop()
    logger.info("VIP shut down cleanly")


app = FastAPI(title="VIP - Video Image Processor", lifespan=lifespan)

from app.api.stream import router as stream_router
from app.api.config import router as config_router

app.include_router(stream_router)
app.include_router(config_router)

app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
