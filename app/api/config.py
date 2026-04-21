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

# Pipeline reference injected by main.py
_pipeline = None


def init(pipeline) -> None:
    global _pipeline
    _pipeline = pipeline


class ConfigUpdate(BaseModel):
    target_fps: Optional[int] = Field(None, ge=1, le=60)
    jpeg_quality: Optional[int] = Field(None, ge=1, le=100)
    enable_motion: Optional[bool] = None
    enable_zones: Optional[bool] = None
    enable_detection: Optional[bool] = None


@router.get("")
async def get_config():
    """Return current runtime configuration."""
    processor_states = {}
    if _pipeline:
        for p in _pipeline._processors:
            name = type(p).__name__
            processor_states[name] = getattr(p, "enabled", True)

    return {
        "target_fps": settings.target_fps,
        "jpeg_quality": settings.jpeg_quality,
        "enable_motion": settings.enable_motion,
        "enable_zones": settings.enable_zones,
        "enable_detection": settings.enable_detection,
        "processors": processor_states,
    }


@router.put("")
async def update_config(update: ConfigUpdate):
    """Update one or more runtime config values.

    Feature toggles (enable_*) set the `enabled` flag on the corresponding
    processor so it is skipped in the next frame cycle without restarting.
    """
    if update.target_fps is not None:
        settings.target_fps = update.target_fps
        if _pipeline:
            _pipeline._frame_interval = 1.0 / update.target_fps
        logger.info("target_fps updated to %d", update.target_fps)

    if update.jpeg_quality is not None:
        settings.jpeg_quality = update.jpeg_quality
        logger.info("jpeg_quality updated to %d", update.jpeg_quality)

    if _pipeline:
        toggle_map = {
            "MotionProcessor": update.enable_motion,
            "ZoneProcessor": update.enable_zones,
            "DetectionProcessor": update.enable_detection,
        }
        for processor in _pipeline._processors:
            name = type(processor).__name__
            val = toggle_map.get(name)
            if val is not None:
                processor.enabled = val
                logger.info("%s enabled=%s", name, val)

    return await get_config()
