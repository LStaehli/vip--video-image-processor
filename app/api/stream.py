import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# Injected by main.py at startup
_registry = None


def init(registry) -> None:
    global _registry
    _registry = registry


def _first_stack():
    if _registry:
        stacks = _registry.all()
        return stacks[0] if stacks else None
    return None


# ── Per-stream WebSocket routes ───────────────────────────────────────────────

@router.websocket("/ws/video/{stream_id}")
async def ws_video_stream(websocket: WebSocket, stream_id: int):
    stack = _registry.get(stream_id) if _registry else None
    if not stack:
        logger.warning("WS /ws/video/%d: stream not in registry — closing 4004", stream_id)
        await websocket.accept()
        await websocket.close(code=4004, reason="stream not active")
        return
    await stack.ws_manager.connect_video(websocket)
    try:
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        stack.ws_manager.disconnect_video(websocket)


@router.websocket("/ws/events/{stream_id}")
async def ws_events_stream(websocket: WebSocket, stream_id: int):
    stack = _registry.get(stream_id) if _registry else None
    if not stack:
        await websocket.accept()
        await websocket.close(code=4004, reason="stream not active")
        return
    await stack.ws_manager.connect_events(websocket)
    try:
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        stack.ws_manager.disconnect_events(websocket)


# ── Legacy single-stream routes (use first active stack) ─────────────────────

@router.websocket("/ws/video")
async def ws_video(websocket: WebSocket):
    stack = _first_stack()
    if not stack:
        await websocket.accept()
        await websocket.close(code=4004, reason="no active stream")
        return
    await stack.ws_manager.connect_video(websocket)
    try:
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        stack.ws_manager.disconnect_video(websocket)


@router.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    stack = _first_stack()
    if not stack:
        await websocket.accept()
        await websocket.close(code=4004, reason="no active stream")
        return
    await stack.ws_manager.connect_events(websocket)
    try:
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        stack.ws_manager.disconnect_events(websocket)


@router.get("/stream.mjpeg")
async def mjpeg_stream():
    stack = _first_stack()
    if not stack:
        return StreamingResponse(iter([]), media_type="multipart/x-mixed-replace; boundary=frame")
    q = stack.ws_manager.register_mjpeg_client()

    async def generate():
        try:
            while True:
                try:
                    jpeg_bytes = await asyncio.wait_for(q.get(), timeout=2.0)
                except asyncio.TimeoutError:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n\r\n"
                    continue
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + jpeg_bytes + b"\r\n"
                )
        finally:
            stack.ws_manager.unregister_mjpeg_client(q)

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.get("/api/status")
async def status(stream_id: int | None = None):
    stack = (_registry.get(stream_id) if stream_id else None) or _first_stack()
    if not stack:
        return {
            "stream_connected": False,
            "video_clients": 0,
            "actual_fps": 0.0,
            "target_fps": settings.target_fps,
            "jpeg_quality": settings.jpeg_quality,
            "source": str(settings.stream_url),
            "features": {
                "motion": settings.enable_motion,
                "zones": settings.enable_zones,
                "detection": settings.enable_detection,
            },
        }
    return {
        "stream_connected": stack.reader.connected,
        "video_clients": stack.ws_manager.video_client_count,
        "actual_fps": round(stack.pipeline.actual_fps, 1),
        "target_fps": settings.target_fps,
        "jpeg_quality": settings.jpeg_quality,
        "source": stack.url,
        "features": {
            "motion": settings.enable_motion,
            "zones": settings.enable_zones,
            "detection": settings.enable_detection,
        },
    }
