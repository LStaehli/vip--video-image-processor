"""Runtime configuration API.

Allows toggling features and adjusting pipeline parameters without restarting
the server. Changes affect the current process only — they are not persisted.
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/config")

# References injected by main.py
_pipeline = None
_reader = None


def init(pipeline, reader=None) -> None:
    global _pipeline, _reader
    _pipeline = pipeline
    _reader = reader


class ConfigUpdate(BaseModel):
    stream_url: Optional[str] = None   # "0" for webcam or an RTSP/MJPEG URL
    # Recording
    recording_output_dir: Optional[str] = None
    recording_filename_pattern: Optional[str] = None
    recording_project_name: Optional[str] = None
    target_fps: Optional[int] = Field(None, ge=1, le=60)
    jpeg_quality: Optional[int] = Field(None, ge=1, le=100)
    enable_motion: Optional[bool] = None
    enable_zones: Optional[bool] = None
    enable_detection: Optional[bool] = None
    zone_stop_mode: Optional[str] = None      # "zone" or "stream"
    # YOLOv8
    yolo_model: Optional[str] = None          # e.g. "yolov8n.pt"
    yolo_confidence: Optional[float] = Field(None, ge=0.05, le=0.95)
    yolo_skip_frames: Optional[int] = Field(None, ge=1, le=10)
    detect_classes: Optional[str] = None      # comma-separated, empty = all
    # Motion tuning
    motion_min_area: Optional[int] = Field(None, ge=0)
    motion_trail_length: Optional[int] = Field(None, ge=1, le=60)
    motion_mog2_threshold: Optional[int] = Field(None, ge=1, le=500)
    motion_dilate_kernel: Optional[int] = Field(None, ge=1, le=51)
    # Motion visual style
    motion_trail_enabled: Optional[bool] = None
    motion_trail_color: Optional[str] = None
    motion_trail_max_radius: Optional[int] = Field(None, ge=1, le=30)
    motion_contour_enabled: Optional[bool] = None
    motion_contour_color: Optional[str] = None
    motion_contour_thickness: Optional[int] = Field(None, ge=1, le=15)
    motion_arrow_color: Optional[str] = None
    motion_arrow_thickness: Optional[int] = Field(None, ge=1, le=15)
    motion_arrow_enabled: Optional[bool] = None
    motion_center_color: Optional[str] = None
    motion_center_radius: Optional[int] = Field(None, ge=1, le=30)
    motion_center_enabled: Optional[bool] = None
    # Face recognition
    enable_faces: Optional[bool] = None
    face_model: Optional[str] = None
    face_similarity_threshold: Optional[float] = Field(None, ge=0.1, le=0.9)
    face_skip_frames: Optional[int] = Field(None, ge=1, le=10)
    face_show_landmarks: Optional[bool] = None
    face_auto_enroll: Optional[bool] = None
    face_auto_enroll_min_score: Optional[float] = Field(None, ge=0.5, le=1.0)
    # Notifications
    notify_on_zone_trigger: Optional[bool] = None


@router.get("")
async def get_config():
    """Return current runtime configuration."""
    processor_states = {}
    if _pipeline:
        for p in _pipeline._processors:
            name = type(p).__name__
            processor_states[name] = getattr(p, "enabled", True)

    return {
        "stream_url": settings.stream_url,
        "recording_output_dir": settings.recording_output_dir,
        "recording_filename_pattern": settings.recording_filename_pattern,
        "recording_project_name": settings.recording_project_name,
        "target_fps": settings.target_fps,
        "jpeg_quality": settings.jpeg_quality,
        "enable_motion": settings.enable_motion,
        "enable_zones": settings.enable_zones,
        "enable_detection": settings.enable_detection,
        "zone_stop_mode": settings.zone_stop_mode,
        "yolo_model": settings.yolo_model,
        "yolo_confidence": settings.yolo_confidence,
        "yolo_skip_frames": settings.yolo_skip_frames,
        "detect_classes": settings.detect_classes,
        "motion_min_area": settings.motion_min_area,
        "motion_trail_length": settings.motion_trail_length,
        "motion_mog2_threshold": settings.motion_mog2_threshold,
        "motion_dilate_kernel": settings.motion_dilate_kernel,
        "motion_trail_enabled": settings.motion_trail_enabled,
        "motion_trail_color": settings.motion_trail_color,
        "motion_trail_max_radius": settings.motion_trail_max_radius,
        "motion_contour_enabled": settings.motion_contour_enabled,
        "motion_contour_color": settings.motion_contour_color,
        "motion_contour_thickness": settings.motion_contour_thickness,
        "motion_arrow_color": settings.motion_arrow_color,
        "motion_arrow_thickness": settings.motion_arrow_thickness,
        "motion_arrow_enabled": settings.motion_arrow_enabled,
        "motion_center_color": settings.motion_center_color,
        "motion_center_radius": settings.motion_center_radius,
        "motion_center_enabled": settings.motion_center_enabled,
        "enable_faces": settings.enable_faces,
        "face_model": settings.face_model,
        "face_similarity_threshold": settings.face_similarity_threshold,
        "face_skip_frames": settings.face_skip_frames,
        "face_show_landmarks": settings.face_show_landmarks,
        "face_auto_enroll": settings.face_auto_enroll,
        "face_auto_enroll_min_score": settings.face_auto_enroll_min_score,
        "notify_on_zone_trigger": settings.notify_on_zone_trigger,
        "processors": processor_states,
    }


@router.put("")
async def update_config(update: ConfigUpdate):
    """Update one or more runtime config values.

    Feature toggles (enable_*) set the `enabled` flag on the corresponding
    processor so it is skipped in the next frame cycle without restarting.
    """
    for field_name in ("recording_output_dir", "recording_filename_pattern", "recording_project_name"):
        val = getattr(update, field_name, None)
        if val is not None:
            setattr(settings, field_name, val)
            logger.info("%s updated to %s", field_name, val)

    if update.stream_url is not None:
        settings.stream_url = update.stream_url
        if _reader:
            _reader.set_source(settings.stream_source)
        logger.info("stream_url updated to %s", update.stream_url)

    if update.target_fps is not None:
        settings.target_fps = update.target_fps
        if _pipeline:
            _pipeline._frame_interval = 1.0 / update.target_fps
        logger.info("target_fps updated to %d", update.target_fps)

    if update.jpeg_quality is not None:
        settings.jpeg_quality = update.jpeg_quality
        logger.info("jpeg_quality updated to %d", update.jpeg_quality)

    if update.motion_min_area is not None:
        settings.motion_min_area = update.motion_min_area
        logger.info("motion_min_area updated to %d", update.motion_min_area)

    if update.motion_trail_length is not None:
        settings.motion_trail_length = update.motion_trail_length
        logger.info("motion_trail_length updated to %d", update.motion_trail_length)

    if update.motion_mog2_threshold is not None:
        settings.motion_mog2_threshold = update.motion_mog2_threshold
        logger.info("motion_mog2_threshold updated to %d", update.motion_mog2_threshold)

    if update.motion_dilate_kernel is not None:
        settings.motion_dilate_kernel = update.motion_dilate_kernel
        logger.info("motion_dilate_kernel updated to %d", update.motion_dilate_kernel)

    if update.zone_stop_mode is not None:
        if update.zone_stop_mode in ("zone", "stream"):
            settings.zone_stop_mode = update.zone_stop_mode
            logger.info("zone_stop_mode updated to %s", update.zone_stop_mode)

    for field_name in ("yolo_model", "yolo_confidence", "yolo_skip_frames", "detect_classes"):
        val = getattr(update, field_name, None)
        if val is not None:
            setattr(settings, field_name, val)
            logger.info("%s updated to %s", field_name, val)

    # Visual style — simply write through to settings; processor reads on every frame
    visual_fields = [
        "motion_trail_enabled", "motion_trail_color", "motion_trail_max_radius",
        "motion_contour_enabled", "motion_contour_color", "motion_contour_thickness",
        "motion_arrow_color", "motion_arrow_thickness", "motion_arrow_enabled",
        "motion_center_color", "motion_center_radius", "motion_center_enabled",
    ]
    for field_name in visual_fields:
        val = getattr(update, field_name, None)
        if val is not None:
            setattr(settings, field_name, val)
            logger.info("%s updated to %s", field_name, val)

    for field_name in ("face_model", "face_similarity_threshold", "face_skip_frames",
                       "face_show_landmarks", "face_auto_enroll", "face_auto_enroll_min_score"):
        val = getattr(update, field_name, None)
        if val is not None:
            setattr(settings, field_name, val)
            logger.info("%s updated to %s", field_name, val)

    # Boolean flags need explicit None-check so False is not treated as falsy
    if update.notify_on_zone_trigger is not None:
        settings.notify_on_zone_trigger = update.notify_on_zone_trigger
        logger.info("notify_on_zone_trigger updated to %s", update.notify_on_zone_trigger)

    if _pipeline:
        toggle_map = {
            "MotionProcessor": update.enable_motion,
            "ZoneProcessor": update.enable_zones,
            "DetectionProcessor": update.enable_detection,
            "FaceProcessor": update.enable_faces,
        }
        for processor in _pipeline._processors:
            name = type(processor).__name__
            val = toggle_map.get(name)
            if val is not None:
                processor.enabled = val
                logger.info("%s enabled=%s", name, val)

    return await get_config()
