"""Stream registry API.

Manages the list of video stream sources and provides per-stream sub-resources.

GET    /api/streams               — list all streams
POST   /api/streams               — register a new stream
PATCH  /api/streams/{id}          — update name, url, channel_number, or enabled flag
DELETE /api/streams/{id}          — remove a stream

GET    /api/streams/{id}/status               — live stats for one stream

POST   /api/streams/{id}/recording/start      — start recording on stream
POST   /api/streams/{id}/recording/stop       — stop recording on stream
POST   /api/streams/{id}/recording/screenshot — take screenshot from stream
GET    /api/streams/{id}/recording/status     — recording state for stream

GET    /api/streams/{id}/zones                — list zones for stream
POST   /api/streams/{id}/zones                — create zone on stream
DELETE /api/streams/{id}/zones/{zone_id}      — delete one zone
DELETE /api/streams/{id}/zones                — clear all zones on stream
"""
import asyncio
import logging

import aiosqlite
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.services import database as db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/streams")

MAX_STREAMS = 4

# Injected by main.py at startup
_registry = None
_loop = None
_notifier = None


def init(registry, loop, notifier) -> None:
    global _registry, _loop, _notifier
    _registry = registry
    _loop = loop
    _notifier = notifier


def _get_active_stack(stream_id: int):
    """Return the live PipelineStack for stream_id, or None if not running."""
    return _registry.get(stream_id) if _registry else None


async def _start_stack(stream: dict) -> None:
    """Start a pipeline stack for stream if not already running."""
    if not _registry or not _loop:
        return
    if _registry.get(stream["id"]):
        return  # already running
    try:
        await _registry.start(stream, _loop, _notifier)
        logger.info("Started pipeline for stream %d '%s'", stream["id"], stream.get("name"))
    except Exception as exc:
        logger.error("Failed to start stream %d: %s", stream["id"], exc)


async def _stop_stack(stream_id: int) -> None:
    """Stop the pipeline stack for stream_id if running."""
    if _registry:
        await _registry.stop(stream_id)


class StreamCreate(BaseModel):
    channel_number: int
    name: str
    url: str


class StreamUpdate(BaseModel):
    channel_number: int | None = None
    name: str | None = None
    url: str | None = None
    enabled: bool | None = None


@router.get("")
async def list_streams():
    return {"streams": await db.load_streams()}


@router.post("", status_code=201)
async def create_stream(body: StreamCreate):
    if await db.stream_count() >= MAX_STREAMS:
        raise HTTPException(
            status_code=409,
            detail=f"Maximum of {MAX_STREAMS} streams reached",
        )
    name = body.name.strip()
    url = body.url.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name must not be empty")
    if not url:
        raise HTTPException(status_code=422, detail="URL must not be empty")
    if body.channel_number < 1 or body.channel_number > MAX_STREAMS:
        raise HTTPException(status_code=422, detail=f"Channel number must be 1–{MAX_STREAMS}")

    try:
        stream = await db.insert_stream(body.channel_number, name, url)
    except aiosqlite.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=f"Channel number {body.channel_number} is already in use",
        )
    logger.info("Stream registered: ch%d '%s' → %s", body.channel_number, name, url)
    # Start the pipeline immediately — no restart needed
    await _start_stack(stream)
    return stream


@router.patch("/{stream_id}")
async def update_stream(stream_id: int, body: StreamUpdate):
    kwargs = {}
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Name must not be empty")
        kwargs["name"] = name
    if body.url is not None:
        url = body.url.strip()
        if not url:
            raise HTTPException(status_code=422, detail="URL must not be empty")
        kwargs["url"] = url
    if body.channel_number is not None:
        if body.channel_number < 1 or body.channel_number > MAX_STREAMS:
            raise HTTPException(status_code=422, detail=f"Channel number must be 1–{MAX_STREAMS}")
        kwargs["channel_number"] = body.channel_number
    if body.enabled is not None:
        kwargs["enabled"] = int(body.enabled)

    try:
        found = await db.update_stream(stream_id, **kwargs)
    except aiosqlite.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=f"Channel number {body.channel_number} is already in use",
        )
    if not found:
        raise HTTPException(status_code=404, detail="Stream not found")

    logger.info("Stream %d updated: %s", stream_id, kwargs)

    # If the URL changed, update the live reader so it reconnects immediately
    if body.url is not None:
        stack = _get_active_stack(stream_id)
        if stack:
            new_url = body.url.strip()
            source = 0 if new_url == "0" else new_url
            stack.reader.set_source(source)
            logger.info("Stream %d reader switched to new URL: %s", stream_id, new_url)

    # Sync live pipeline state when enabled flag changes
    if body.enabled is True:
        streams = await db.load_streams()
        stream = next((s for s in streams if s["id"] == stream_id), None)
        if stream:
            await _start_stack(stream)
    elif body.enabled is False:
        await _stop_stack(stream_id)

    return {"streams": await db.load_streams()}


@router.delete("/{stream_id}", status_code=204)
async def delete_stream(stream_id: int):
    if not await db.delete_stream(stream_id):
        raise HTTPException(status_code=404, detail="Stream not found")
    logger.info("Stream %d removed", stream_id)
    # Stop the live pipeline immediately
    await _stop_stack(stream_id)


# ── Per-stream live stats and recording ──────────────────────────────────────

@router.get("/{stream_id}/status")
async def stream_status(stream_id: int):
    stack = _get_active_stack(stream_id)
    if not stack:
        raise HTTPException(status_code=404, detail="Stream not active")
    return {
        "stream_id": stream_id,
        "stream_connected": stack.reader.connected,
        "video_clients": stack.ws_manager.video_client_count,
        "actual_fps": round(stack.pipeline.actual_fps, 1),
    }


@router.post("/{stream_id}/recording/start")
async def start_stream_recording(stream_id: int):
    stack = _get_active_stack(stream_id)
    if not stack:
        raise HTTPException(status_code=404, detail="Stream not active")
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


@router.post("/{stream_id}/recording/stop")
async def stop_stream_recording(stream_id: int):
    stack = _get_active_stack(stream_id)
    if not stack:
        raise HTTPException(status_code=404, detail="Stream not active")
    recorder = stack.recorder
    if not recorder.is_recording:
        raise HTTPException(status_code=409, detail="No recording in progress")
    try:
        filepath = recorder.stop()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"recording": False, "saved_to": filepath}


@router.post("/{stream_id}/recording/screenshot")
async def stream_screenshot(stream_id: int):
    stack = _get_active_stack(stream_id)
    if not stack:
        raise HTTPException(status_code=404, detail="Stream not active")
    frame = getattr(stack.pipeline, "_last_frame", None)
    if frame is None:
        raise HTTPException(status_code=503, detail="No frames received yet — stream not ready")
    try:
        filepath = stack.recorder.save_screenshot(frame)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"saved_to": filepath}


@router.get("/{stream_id}/recording/status")
async def stream_recording_status(stream_id: int):
    stack = _get_active_stack(stream_id)
    if not stack:
        raise HTTPException(status_code=404, detail="Stream not active")
    recorder = stack.recorder
    return {
        "recording": recorder.is_recording,
        "file": recorder.current_file,
        "elapsed_seconds": round(recorder.elapsed_seconds, 1),
    }


# ── Per-stream zones ──────────────────────────────────────────────────────────

class ZoneCreate(BaseModel):
    name: str
    polygon: list[list[float]]   # [[nx, ny], …] normalised 0–1


class ZoneSettingsUpdate(BaseModel):
    telegram_message: str = ""
    email_message: str = ""


def _get_zone_proc(stream_id: int):
    stack = _get_active_stack(stream_id)
    if not stack:
        raise HTTPException(status_code=404, detail="Stream not active")
    zp = stack.get_processor("ZoneProcessor")
    if not zp:
        raise HTTPException(status_code=404, detail="ZoneProcessor not found")
    return zp


@router.get("/{stream_id}/zones")
async def list_stream_zones(stream_id: int):
    return _get_zone_proc(stream_id).list_zones()


@router.post("/{stream_id}/zones", status_code=201)
async def create_stream_zone(stream_id: int, body: ZoneCreate):
    if len(body.polygon) < 3:
        raise HTTPException(status_code=422, detail="Polygon must have at least 3 points")
    zone_proc = _get_zone_proc(stream_id)
    zone = zone_proc.add_zone(name=body.name.strip(), polygon=body.polygon)
    return {"id": zone.id, "name": zone.name, "polygon": zone.polygon}


@router.delete("/{stream_id}/zones/{zone_id}", status_code=204)
async def delete_stream_zone(stream_id: int, zone_id: str):
    if not _get_zone_proc(stream_id).remove_zone(zone_id):
        raise HTTPException(status_code=404, detail="Zone not found")
    await db.delete_zone_settings(zone_id)


@router.delete("/{stream_id}/zones", status_code=204)
async def clear_stream_zones(stream_id: int):
    zp = _get_zone_proc(stream_id)
    zone_ids = [z["id"] for z in zp.list_zones()]
    zp.clear_zones()
    for zone_id in zone_ids:
        await db.delete_zone_settings(zone_id)


# ── Per-stream pipeline config ───────────────────────────────────────────────

class StreamConfigUpdate(BaseModel):
    # Pipeline
    target_fps: Optional[int] = None
    jpeg_quality: Optional[int] = None
    # Feature toggles
    enable_motion: Optional[bool] = None
    enable_zones: Optional[bool] = None
    enable_detection: Optional[bool] = None
    enable_faces: Optional[bool] = None
    # Zones
    zone_stop_mode: Optional[str] = None
    notify_on_zone_trigger: Optional[bool] = None
    # Motion tuning
    motion_min_area: Optional[int] = None
    motion_trail_length: Optional[int] = None
    motion_mog2_threshold: Optional[int] = None
    motion_dilate_kernel: Optional[int] = None
    # Motion visual
    motion_trail_enabled: Optional[bool] = None
    motion_trail_color: Optional[str] = None
    motion_trail_max_radius: Optional[int] = None
    motion_contour_enabled: Optional[bool] = None
    motion_contour_color: Optional[str] = None
    motion_contour_thickness: Optional[int] = None
    motion_arrow_color: Optional[str] = None
    motion_arrow_thickness: Optional[int] = None
    motion_arrow_enabled: Optional[bool] = None
    motion_center_color: Optional[str] = None
    motion_center_radius: Optional[int] = None
    motion_center_enabled: Optional[bool] = None
    # Detection
    yolo_model: Optional[str] = None
    yolo_confidence: Optional[float] = None
    yolo_skip_frames: Optional[int] = None
    detect_classes: Optional[str] = None
    # Faces
    face_model: Optional[str] = None
    face_similarity_threshold: Optional[float] = None
    face_skip_frames: Optional[int] = None
    face_show_landmarks: Optional[bool] = None
    face_auto_enroll: Optional[bool] = None
    face_auto_enroll_min_score: Optional[float] = None
    notify_on_face_recognized: Optional[bool] = None


@router.get("/{stream_id}/config")
async def get_stream_config(stream_id: int):
    stack = _get_active_stack(stream_id)
    if not stack:
        raise HTTPException(status_code=404, detail="Stream not active")
    return stack.stream_cfg.to_api_dict()


@router.put("/{stream_id}/config")
async def update_stream_config(stream_id: int, body: StreamConfigUpdate):
    stack = _get_active_stack(stream_id)
    if not stack:
        raise HTTPException(status_code=404, detail="Stream not active")

    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if not patch:
        return stack.stream_cfg.to_api_dict()

    stack.stream_cfg.apply_dict(patch)

    # Apply processor toggle changes immediately
    toggle_map = {
        "MotionProcessor":    body.enable_motion,
        "ZoneProcessor":      body.enable_zones,
        "DetectionProcessor": body.enable_detection,
        "FaceProcessor":      body.enable_faces,
    }
    for proc_name, val in toggle_map.items():
        if val is not None:
            proc = stack.get_processor(proc_name)
            if proc:
                proc.enabled = val

    # Apply FPS change immediately
    if body.target_fps is not None:
        stack.pipeline._frame_interval = 1.0 / body.target_fps

    # Persist to DB
    await db.save_stream_config(stream_id, stack.stream_cfg.to_db_dict())

    return stack.stream_cfg.to_api_dict()


# ── Per-zone notification settings ───────────────────────────────────────────

@router.get("/{stream_id}/zones/{zone_id}/settings")
async def get_stream_zone_settings(stream_id: int, zone_id: str):
    _get_zone_proc(stream_id)  # validates stream is active
    return await db.get_zone_settings(zone_id)


@router.put("/{stream_id}/zones/{zone_id}/settings")
async def update_stream_zone_settings(stream_id: int, zone_id: str, body: ZoneSettingsUpdate):
    _get_zone_proc(stream_id)  # validates stream is active
    await db.upsert_zone_settings(zone_id, body.telegram_message, body.email_message)
    return await db.get_zone_settings(zone_id)
