"""Detection zone processor.

Zones are closed polygons stored in normalised coordinates (0–1 relative to
frame size) so they survive stream resolution changes.

On every frame:
  1. Zones are drawn (semi-transparent fill + outline + label)
  2. state.centroids (from MotionProcessor) are tested against each polygon
  3. When a centroid enters a zone, video recording starts automatically
  4. Recording stops after a grace period once the stop condition is met:
       zone_stop_mode == "zone"   → no centroids inside any zone
       zone_stop_mode == "stream" → no centroids anywhere in the stream
"""
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.config import settings
from app.processors.base import BaseProcessor, FrameState

logger = logging.getLogger(__name__)

_STOP_GRACE = 10.0             # seconds of inactivity before stopping recording

_COLOR_FILL    = (0, 149, 255) # orange (BGR)
_COLOR_OUTLINE = (0, 149, 255)
_COLOR_LABEL   = (255, 255, 255)
_COLOR_HIT     = (0, 0, 220)   # red when triggered


# ── Zone model ────────────────────────────────────────────────────────────────

@dataclass
class Zone:
    id: str
    name: str
    polygon: list[list[float]]           # [[nx, ny], …] normalised 0–1


# ── Shared store — imported by the API module ─────────────────────────────────

zones: dict[str, Zone] = {}


def add_zone(name: str, polygon: list[list[float]]) -> Zone:
    zid = str(uuid.uuid4())
    z = Zone(id=zid, name=name, polygon=polygon)
    zones[zid] = z
    logger.info("Zone created: %s (%s, %d pts)", name, zid, len(polygon))
    return z


def remove_zone(zone_id: str) -> bool:
    if zone_id in zones:
        del zones[zone_id]
        logger.info("Zone removed: %s", zone_id)
        return True
    return False


def clear_zones() -> None:
    zones.clear()
    logger.info("All zones cleared")


# ── Processor ─────────────────────────────────────────────────────────────────

class ZoneProcessor(BaseProcessor):

    def __init__(self, ws_manager=None) -> None:
        self.enabled = False
        self._ws = ws_manager
        self._recorder = None            # injected by main.py after recorder creation
        self._zone_recording = False     # True when this processor started recording
        self._inactive_since: float | None = None  # monotonic time when activity stopped

    def process(self, frame: np.ndarray, state: FrameState) -> np.ndarray:
        if not zones:
            return frame

        h, w = frame.shape[:2]
        overlay = frame.copy()
        stop_mode = settings.zone_stop_mode

        logger.debug(
            "ZoneProcessor: %d zone(s), %d centroid(s), stop_mode=%s",
            len(zones), len(state.centroids), stop_mode,
        )

        # ── Draw zones and test centroids ─────────────────────────────────────
        any_zone_hit = False

        for zone in zones.values():
            pts = _denorm(zone.polygon, w, h)
            if len(pts) < 3:
                continue
            pts_arr = np.array(pts, dtype=np.int32)

            triggered = any(
                cv2.pointPolygonTest(pts_arr, (float(cx), float(cy)), False) >= 0
                for cx, cy in state.centroids
            )
            if triggered:
                any_zone_hit = True

            color = _COLOR_HIT if triggered else _COLOR_FILL
            cv2.fillPoly(overlay, [pts_arr], color)
            cv2.polylines(frame, [pts_arr], True, color, 2)

            lx = int(sum(p[0] for p in pts) / len(pts))
            ly = int(sum(p[1] for p in pts) / len(pts))
            cv2.putText(
                frame, zone.name, (lx, ly),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, _COLOR_LABEL, 1, cv2.LINE_AA,
            )

        cv2.addWeighted(overlay, 0.2, frame, 0.8, 0, frame)

        # ── Recording control ─────────────────────────────────────────────────
        if self._recorder is None:
            return frame

        # Determine whether the stop condition is currently met
        if stop_mode == "stream":
            activity = len(state.centroids) > 0   # any movement in whole stream
        else:
            activity = any_zone_hit                # movement inside a zone

        if any_zone_hit and not self._recorder.is_recording:
            # Zone triggered — start recording
            try:
                filepath = self._recorder.start(frame_width=w, frame_height=h)
                self._zone_recording = True
                self._inactive_since = None
                logger.info("Zone triggered — recording started → %s", filepath)
                if self._ws:
                    asyncio.ensure_future(self._ws.broadcast_event({
                        "type": "recording_started",
                        "file": filepath,
                        "trigger": "zone",
                    }))
            except RuntimeError as exc:
                logger.warning("Could not start zone recording: %s", exc)

        elif self._zone_recording and self._recorder.is_recording:
            if activity:
                # Still active — reset the grace-period timer
                self._inactive_since = None
            else:
                # No activity — start or advance the grace-period timer
                if self._inactive_since is None:
                    self._inactive_since = time.monotonic()
                    logger.info(
                        "Zone inactive (mode=%s) — grace period started (%.0fs)",
                        stop_mode, _STOP_GRACE,
                    )
                elif time.monotonic() - self._inactive_since >= _STOP_GRACE:
                    try:
                        saved = self._recorder.stop()
                        logger.info("Grace period elapsed — recording stopped → %s", saved)
                        if self._ws:
                            asyncio.ensure_future(self._ws.broadcast_event({
                                "type": "recording_stopped",
                                "file": saved,
                                "trigger": "zone",
                            }))
                    except RuntimeError as exc:
                        logger.warning("Could not stop zone recording: %s", exc)
                    finally:
                        self._zone_recording = False
                        self._inactive_since = None

        return frame


def _denorm(polygon: list[list[float]], w: int, h: int) -> list[tuple[int, int]]:
    return [(int(nx * w), int(ny * h)) for nx, ny in polygon]
