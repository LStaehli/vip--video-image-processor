"""Recording API.

POST /api/recording/start  — begin recording
POST /api/recording/stop   — stop and flush the file
GET  /api/recording/status — current state
"""
import logging

from fastapi import APIRouter, HTTPException

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/recording")

# Injected by main.py
_recorder = None
_pipeline = None


def init(recorder, pipeline) -> None:
    global _recorder, _pipeline
    _recorder = recorder
    _pipeline = pipeline


@router.post("/start")
async def start_recording():
    if _recorder.is_recording:
        raise HTTPException(status_code=409, detail="Recording already in progress")

    frame_size = getattr(_pipeline, "_last_frame_size", None)
    if frame_size is None:
        raise HTTPException(status_code=503, detail="No frames received yet — stream not ready")

    try:
        filepath = _recorder.start(frame_width=frame_size[0], frame_height=frame_size[1])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"recording": True, "file": filepath}


@router.post("/stop")
async def stop_recording():
    if not _recorder.is_recording:
        raise HTTPException(status_code=409, detail="No recording in progress")

    try:
        filepath = _recorder.stop()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"recording": False, "saved_to": filepath}


@router.post("/screenshot")
async def take_screenshot():
    frame = getattr(_pipeline, "_last_frame", None)
    if frame is None:
        raise HTTPException(status_code=503, detail="No frames received yet — stream not ready")

    try:
        filepath = _recorder.save_screenshot(frame)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"saved_to": filepath}


@router.get("/status")
async def recording_status():
    return {
        "recording": _recorder.is_recording,
        "file": _recorder.current_file,
        "elapsed_seconds": round(_recorder.elapsed_seconds, 1),
        "output_dir": settings.recording_output_dir,
        "filename_pattern": settings.recording_filename_pattern,
        "project_name": settings.recording_project_name,
    }
