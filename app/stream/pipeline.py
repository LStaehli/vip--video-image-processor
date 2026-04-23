import asyncio
import logging
import time
from collections import deque

import cv2
import numpy as np

from app.config import settings
from app.processors.base import FrameState
from app.stream.websocket_manager import WebSocketManager

logger = logging.getLogger(__name__)

# How many recent frame timestamps to keep for FPS calculation
_FPS_WINDOW = 30


class FramePipeline:
    """Pulls raw frames from the StreamReader queue, runs enabled processors in
    sequence, JPEG-encodes the result, and broadcasts it to all clients via
    WebSocketManager.

    Each enabled processor is called as:
        frame = processor.process(frame, state)

    Processors that are disabled at runtime are skipped without restarting.
    """

    def __init__(self, input_queue: asyncio.Queue, ws_manager: WebSocketManager) -> None:
        self._input = input_queue
        self._ws = ws_manager
        self._processors: list = []
        self._running = False
        self._cfg = None   # injected by registry
        self._frame_interval = 1.0 / settings.target_fps  # overwritten by registry

        # FPS tracking — rolling window of recent frame timestamps
        self._frame_times: deque[float] = deque(maxlen=_FPS_WINDOW)

        # Last known frame dimensions — used by the recording service
        self._last_frame_size: tuple[int, int] | None = None  # (width, height)
        # Last processed (annotated) frame — used for screenshots
        self._last_frame: np.ndarray | None = None

        # Optional recording service — set by main.py after startup
        self._recorder = None

    def add_processor(self, processor) -> None:
        self._processors.append(processor)

    @property
    def actual_fps(self) -> float:
        """Frames per second measured over the last _FPS_WINDOW frames."""
        if len(self._frame_times) < 2:
            return 0.0
        span = self._frame_times[-1] - self._frame_times[0]
        return (len(self._frame_times) - 1) / span if span > 0 else 0.0

    async def run(self) -> None:
        self._running = True
        logger.info("FramePipeline started (target %d fps, quality %d)", settings.target_fps, settings.jpeg_quality)
        last_sent = 0.0

        while self._running:
            try:
                frame: np.ndarray = await asyncio.wait_for(self._input.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            # Throttle to target FPS — skip processing if we're ahead of schedule
            now = time.monotonic()
            if (now - last_sent) < self._frame_interval:
                continue
            last_sent = now
            self._frame_times.append(now)

            # Track frame dimensions for the recording service
            h, w = frame.shape[:2]
            self._last_frame_size = (w, h)

            state = FrameState(timestamp=time.time())

            # Run processor chain — each processor is individually guarded
            for processor in self._processors:
                if not getattr(processor, "enabled", True):
                    continue
                try:
                    frame = processor.process(frame, state)
                except Exception:
                    logger.exception("Processor %s raised an error", type(processor).__name__)

            # Keep a reference to the latest annotated frame
            self._last_frame = frame

            # Record annotated frame if recording is active
            if self._recorder:
                self._recorder.write_frame(frame)

            # Encode and broadcast
            quality = self._cfg.jpeg_quality if self._cfg else settings.jpeg_quality
            ok, jpeg_buf = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality]
            )
            if not ok:
                continue

            await self._ws.broadcast_frame(jpeg_buf.tobytes())

    def stop(self) -> None:
        self._running = False
