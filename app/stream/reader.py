import asyncio
import logging
import os
import threading
import time

# Must be set before cv2 tries to use AVFoundation on macOS, otherwise the
# authorization request deadlocks when called from a background thread.
os.environ.setdefault("OPENCV_AVFOUNDATION_SKIP_AUTH", "1")

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_RECONNECT_INITIAL_DELAY = 1.0
_RECONNECT_MAX_DELAY = 30.0


class StreamReader:
    """Reads frames from a video source in a background thread and places them
    into an asyncio.Queue for the async pipeline to consume.

    The queue has maxsize=2 so that the pipeline never falls behind — excess
    frames are silently dropped rather than accumulated.
    """

    def __init__(self, source: int | str, loop: asyncio.AbstractEventLoop) -> None:
        self._source = source
        self._loop = loop
        self._queue: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=2)
        self._running = False
        self._thread: threading.Thread | None = None
        self._cap: cv2.VideoCapture | None = None
        self.connected = False

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="stream-reader")
        self._thread.start()
        logger.info("StreamReader started for source: %s", self._source)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        if self._cap:
            self._cap.release()
        logger.info("StreamReader stopped")

    def set_source(self, source: int | str) -> None:
        """Switch to a new video source without restarting the server.

        Releases the current capture immediately; the background thread's
        reconnection loop will open the new source on its next iteration.
        """
        self._source = source
        self.connected = False
        if self._cap:
            self._cap.release()
            self._cap = None
        logger.info("StreamReader source changed to: %s", source)

    @property
    def queue(self) -> asyncio.Queue:
        return self._queue

    def _open_capture(self) -> cv2.VideoCapture | None:
        cap = cv2.VideoCapture(self._source, cv2.CAP_FFMPEG if isinstance(self._source, str) else cv2.CAP_ANY)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not cap.isOpened():
            return None
        return cap

    def _run(self) -> None:
        delay = _RECONNECT_INITIAL_DELAY
        while self._running:
            self._cap = self._open_capture()
            if self._cap is None:
                logger.warning("Failed to open stream. Retrying in %.1fs…", delay)
                self.connected = False
                time.sleep(delay)
                delay = min(delay * 2, _RECONNECT_MAX_DELAY)
                continue

            self.connected = True
            delay = _RECONNECT_INITIAL_DELAY
            logger.info("Stream opened: %s", self._source)

            while self._running:
                ok, frame = self._cap.read()
                if not ok:
                    logger.warning("Stream read failed — reconnecting…")
                    self.connected = False
                    break

                # Drop the frame if the consumer (pipeline) is behind.
                # put_nowait is scheduled as an event-loop callback via
                # call_soon_threadsafe, so QueueFull must be caught inside
                # the callback rather than around call_soon_threadsafe itself.
                def _try_put(f=frame):
                    try:
                        self._queue.put_nowait(f)
                    except asyncio.QueueFull:
                        pass

                self._loop.call_soon_threadsafe(_try_put)

            self._cap.release()
            self._cap = None
