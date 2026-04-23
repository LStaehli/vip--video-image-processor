"""Recording API.

POST /api/recording/start  — begin recording (first active stream)
POST /api/recording/stop   — stop and flush the file
GET  /api/recording/status — current state
"""
import logging

from fastapi import APIRouter, HTTPException

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/recording")

# Injected by main.py
_registry = None


def init(registry) -> None:
    global _registry
    _registry = registry


def _get_stack():
    if not _registry:
        return None
    stacks = _registry.all()
    return stacks[0] if stacks else None


@router.post("/start")
async def start_recording():
    stack = _get_stack()
    if not stack:
        raise HTTPException(status_code=503, detail="No active stream")

    recorder = stack.recorder
    pipeline = stack.pipeline

    if recorder.is_recording:
        raise HTTPException(status_code=409, detail="Recording already in progress")

    frame_size = getattr(pipeline, "_last_frame_size", None)
    if frame_size is None:
        raise HTTPException(status_code=503, detail="No frames received yet — stream not ready")

    try:
        filepath = recorder.start(frame_width=frame_size[0], frame_height=frame_size[1])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"recording": True, "file": filepath}


@router.post("/stop")
async def stop_recording():
    stack = _get_stack()
    if not stack:
        raise HTTPException(status_code=503, detail="No active stream")

    recorder = stack.recorder
    if not recorder.is_recording:
        raise HTTPException(status_code=409, detail="No recording in progress")

    try:
        filepath = recorder.stop()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"recording": False, "saved_to": filepath}


@router.post("/screenshot")
async def take_screenshot():
    stack = _get_stack()
    if not stack:
        raise HTTPException(status_code=503, detail="No active stream")

    frame = getattr(stack.pipeline, "_last_frame", None)
    if frame is None:
        raise HTTPException(status_code=503, detail="No frames received yet — stream not ready")

    try:
        filepath = stack.recorder.save_screenshot(frame)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"saved_to": filepath}


@router.get("/status")
async def recording_status():
    stack = _get_stack()
    if not stack:
        return {
            "recording": False,
            "file": None,
            "elapsed_seconds": 0.0,
            "output_dir": settings.recording_output_dir,
            "filename_pattern": settings.recording_filename_pattern,
            "project_name": settings.recording_project_name,
        }
    recorder = stack.recorder
    return {
        "recording": recorder.is_recording,
        "file": recorder.current_file,
        "elapsed_seconds": round(recorder.elapsed_seconds, 1),
        "output_dir": settings.recording_output_dir,
        "filename_pattern": settings.recording_filename_pattern,
        "project_name": settings.recording_project_name,
    }
