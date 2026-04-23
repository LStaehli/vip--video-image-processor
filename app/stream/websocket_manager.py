import asyncio
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Maximum time to wait for a single WebSocket send before treating the client as dead
_SEND_TIMEOUT = 2.0  # seconds


class WebSocketManager:
    """Manages active WebSocket connections and per-client MJPEG queues.

    The pipeline calls broadcast_frame() once per encoded frame. This class
    fans it out to every registered video WebSocket client and every active
    MJPEG streaming response — each with its own private queue so clients
    never steal frames from one another.
    """

    def __init__(self) -> None:
        self._video_clients: list[WebSocket] = []
        self._event_clients: list[WebSocket] = []
        self._mjpeg_queues: list[asyncio.Queue[bytes]] = []

    # ── Video WebSocket ───────────────────────────────────────────────────────

    async def connect_video(self, ws: WebSocket) -> None:
        await ws.accept()
        self._video_clients.append(ws)
        logger.info("Video WS connected. Total: %d", len(self._video_clients))

    def disconnect_video(self, ws: WebSocket) -> None:
        try:
            self._video_clients.remove(ws)
        except ValueError:
            pass
        logger.info("Video WS disconnected. Total: %d", len(self._video_clients))

    # ── Event WebSocket ───────────────────────────────────────────────────────

    async def connect_events(self, ws: WebSocket) -> None:
        await ws.accept()
        self._event_clients.append(ws)
        logger.info("Event WS connected. Total: %d", len(self._event_clients))

    def disconnect_events(self, ws: WebSocket) -> None:
        try:
            self._event_clients.remove(ws)
        except ValueError:
            pass
        logger.info("Event WS disconnected. Total: %d", len(self._event_clients))

    # ── MJPEG ─────────────────────────────────────────────────────────────────

    def register_mjpeg_client(self) -> asyncio.Queue[bytes]:
        """Create and register a per-client frame queue for MJPEG streaming."""
        q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=2)
        self._mjpeg_queues.append(q)
        logger.info("MJPEG client registered. Total: %d", len(self._mjpeg_queues))
        return q

    def unregister_mjpeg_client(self, q: asyncio.Queue[bytes]) -> None:
        try:
            self._mjpeg_queues.remove(q)
        except ValueError:
            pass
        logger.info("MJPEG client unregistered. Total: %d", len(self._mjpeg_queues))

    # ── Broadcast ─────────────────────────────────────────────────────────────

    async def broadcast_frame(self, jpeg_bytes: bytes) -> None:
        """Send an encoded JPEG frame to all connected video clients.

        Each send is capped at _SEND_TIMEOUT seconds. Slow or unresponsive
        clients are evicted so they cannot stall the pipeline for others.
        """
        dead_ws: list[WebSocket] = []
        for ws in list(self._video_clients):  # snapshot to allow mutation
            try:
                await asyncio.wait_for(ws.send_bytes(jpeg_bytes), timeout=_SEND_TIMEOUT)
            except Exception:
                dead_ws.append(ws)
        for ws in dead_ws:
            try:
                self._video_clients.remove(ws)
            except ValueError:
                pass  # already removed by disconnect_video

        # MJPEG queues — non-blocking, drop frames if the client is too slow
        dead_q: list[asyncio.Queue] = []
        for q in list(self._mjpeg_queues):
            try:
                q.put_nowait(jpeg_bytes)
            except asyncio.QueueFull:
                pass
            except Exception:
                dead_q.append(q)
        for q in dead_q:
            try:
                self._mjpeg_queues.remove(q)
            except ValueError:
                pass

    async def broadcast_event(self, payload: dict) -> None:
        """Send a JSON event to all connected event clients."""
        dead: list[WebSocket] = []
        for ws in list(self._event_clients):
            try:
                await asyncio.wait_for(ws.send_json(payload), timeout=_SEND_TIMEOUT)
            except Exception:
                dead.append(ws)
        for ws in dead:
            try:
                self._event_clients.remove(ws)
            except ValueError:
                pass

    # ── Stats ─────────────────────────────────────────────────────────────────

    @property
    def video_client_count(self) -> int:
        return len(self._video_clients) + len(self._mjpeg_queues)
