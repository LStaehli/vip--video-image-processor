"""Stream registry — manages N independent pipeline stacks.

Each stack owns its own StreamReader, asyncio.Queue, FramePipeline,
processor instances, WebSocketManager, and RecordingService.

All stacks share global Settings (feature flags, processor tuning) and
the global FaceStore. Zone definitions and (future) per-stream settings
are scoped to each stack (Phase C+).
"""
import asyncio
import logging
from dataclasses import dataclass, field

from app.config import settings
from app.stream.reader import StreamReader
from app.stream.pipeline import FramePipeline
from app.stream.websocket_manager import WebSocketManager
from app.services.recording import RecordingService

logger = logging.getLogger(__name__)


@dataclass
class PipelineStack:
    stream_id: int
    channel_number: int
    name: str
    url: str
    reader: StreamReader
    pipeline: FramePipeline
    ws_manager: WebSocketManager
    recorder: RecordingService
    # Processor references for API access
    processors: dict = field(default_factory=dict)
    pipeline_task: asyncio.Task | None = None

    def get_processor(self, name: str):
        return self.processors.get(name)


class StreamRegistry:
    """Lifecycle manager for all active pipeline stacks."""

    def __init__(self) -> None:
        self._stacks: dict[int, PipelineStack] = {}

    def get(self, stream_id: int) -> PipelineStack | None:
        return self._stacks.get(stream_id)

    def all(self) -> list[PipelineStack]:
        return list(self._stacks.values())

    def __len__(self) -> int:
        return len(self._stacks)

    async def start(
        self,
        stream: dict,
        loop: asyncio.AbstractEventLoop,
        notifier,
    ) -> PipelineStack:
        """Create and start a pipeline stack for the given stream dict."""
        from app.services import database as db
        from app.processors.zones import Zone

        stream_id = stream["id"]
        if stream_id in self._stacks:
            raise RuntimeError(f"Stream {stream_id} is already running")

        url = stream["url"]
        source = 0 if url.strip() == "0" else url

        ws_manager = WebSocketManager()
        reader = StreamReader(source=source, loop=loop)
        pipeline = FramePipeline(input_queue=reader.queue, ws_manager=ws_manager)

        # ── Processors ────────────────────────────────────────────────────────
        from app.processors.motion import MotionProcessor
        motion_proc = MotionProcessor()
        motion_proc.enabled = settings.enable_motion
        pipeline.add_processor(motion_proc)

        from app.processors.zones import ZoneProcessor
        zone_proc = ZoneProcessor(ws_manager=ws_manager)
        zone_proc.enabled = settings.enable_zones
        zone_proc._stream_id = stream_id
        # Load this stream's zones from DB into the per-stack zone store
        saved_zones = await db.load_zones(stream_id)
        zone_proc._zones = {
            z["id"]: Zone(id=z["id"], name=z["name"], polygon=z["polygon"])
            for z in saved_zones
        }
        logger.info("Stream %d: loaded %d zone(s)", stream_id, len(zone_proc._zones))
        pipeline.add_processor(zone_proc)

        from app.processors.detection import DetectionProcessor
        det_proc = DetectionProcessor()
        det_proc.enabled = settings.enable_detection
        det_proc._ws_manager = ws_manager
        pipeline.add_processor(det_proc)

        from app.processors.faces import FaceProcessor
        face_proc = FaceProcessor()
        face_proc.enabled = settings.enable_faces
        face_proc._ws_manager = ws_manager
        pipeline.add_processor(face_proc)

        # ── Services ──────────────────────────────────────────────────────────
        recorder = RecordingService(
            channel_number=stream["channel_number"],
            channel_name=stream["name"],
        )
        pipeline._recorder = recorder
        zone_proc._recorder = recorder
        face_proc._recorder = recorder
        zone_proc._notifier = notifier

        # ── Start ─────────────────────────────────────────────────────────────
        reader.start()
        pipeline_task = asyncio.create_task(
            pipeline.run(), name=f"pipeline-{stream_id}"
        )

        stack = PipelineStack(
            stream_id=stream_id,
            channel_number=stream["channel_number"],
            name=stream["name"],
            url=url,
            reader=reader,
            pipeline=pipeline,
            ws_manager=ws_manager,
            recorder=recorder,
            processors={
                "MotionProcessor":    motion_proc,
                "ZoneProcessor":      zone_proc,
                "DetectionProcessor": det_proc,
                "FaceProcessor":      face_proc,
            },
            pipeline_task=pipeline_task,
        )
        self._stacks[stream_id] = stack
        logger.info(
            "Stream %d started — CH%d '%s' → %s",
            stream_id, stream["channel_number"], stream["name"], url,
        )
        return stack

    async def stop(self, stream_id: int) -> None:
        stack = self._stacks.pop(stream_id, None)
        if not stack:
            return
        stack.pipeline.stop()
        if stack.pipeline_task:
            stack.pipeline_task.cancel()
            try:
                await stack.pipeline_task
            except asyncio.CancelledError:
                pass
        stack.reader.stop()
        logger.info("Stream %d stopped", stream_id)

    async def stop_all(self) -> None:
        for stream_id in list(self._stacks):
            await self.stop(stream_id)
