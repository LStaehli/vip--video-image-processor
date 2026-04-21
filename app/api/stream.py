import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# Injected by main.py at startup
_ws_manager = None
_pipeline = None
_reader = None


def init(ws_manager, pipeline, reader) -> None:
    global _ws_manager, _pipeline, _reader
    _ws_manager = ws_manager
    _pipeline = pipeline
    _reader = reader


@router.websocket("/ws/video")
async def ws_video(websocket: WebSocket):
    """Binary JPEG frame stream. The pipeline broadcasts to all connected
    clients directly — this endpoint just registers the connection and keeps
    it alive until the client disconnects."""
    await _ws_manager.connect_video(websocket)
    try:
        # receive_text() blocks until the client sends a message or disconnects.
        # We use it purely for disconnect detection — clients never send video data.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        _ws_manager.disconnect_video(websocket)


@router.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    """JSON event stream (zone alarms, status updates). Events are pushed by
    the pipeline/processors via WebSocketManager.broadcast_event()."""
    await _ws_manager.connect_events(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        _ws_manager.disconnect_events(websocket)


@router.get("/stream.mjpeg")
async def mjpeg_stream():
    """MJPEG fallback endpoint for clients that don't support WebSocket.
    Each connection gets its own frame queue so clients never steal frames
    from one another."""
    q = _ws_manager.register_mjpeg_client()

    async def generate():
        try:
            while True:
                try:
                    jpeg_bytes = await asyncio.wait_for(q.get(), timeout=2.0)
                except asyncio.TimeoutError:
                    # Send an empty boundary to keep the connection alive
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n\r\n"
                    continue
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + jpeg_bytes + b"\r\n"
                )
        finally:
            _ws_manager.unregister_mjpeg_client(q)

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.get("/api/status")
async def status():
    return {
        "stream_connected": _reader.connected if _reader else False,
        "video_clients": _ws_manager.video_client_count if _ws_manager else 0,
        "actual_fps": round(_pipeline.actual_fps, 1) if _pipeline else 0.0,
        "target_fps": settings.target_fps,
        "jpeg_quality": settings.jpeg_quality,
        "source": str(settings.stream_url),
        "features": {
            "motion": settings.enable_motion,
            "zones": settings.enable_zones,
            "detection": settings.enable_detection,
        },
    }
