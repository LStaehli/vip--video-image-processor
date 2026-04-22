"""Detection zone processor.

Zones are closed polygons stored in normalised coordinates (0–1 relative to
frame size) so they survive stream resolution changes.

Zone definitions are persisted in SQLite and reloaded on startup.

On every frame:
  1. Zones are drawn (semi-transparent fill + outline + label)
  2. state.centroids (from MotionProcessor) are tested against each polygon
  3. When a centroid enters a zone for the first time (edge trigger), a
     zone_event row is written to the DB and video recording starts
  4. Recording stops after a grace period once the stop condition is met:
       zone_stop_mode == "zone"   → no centroids inside any zone
       zone_stop_mode == "stream" → no centroids anywhere in the stream
"""
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass

import cv2
import numpy as np

from app.config import settings
from app.processors.base import BaseProcessor, FrameState
from app.services import database as db

logger = logging.getLogger(__name__)

_STOP_GRACE = 10.0              # seconds of inactivity before stopping recording

_COLOR_FILL    = (0, 149, 255)  # orange (BGR)
_COLOR_OUTLINE = (0, 149, 255)
_COLOR_LABEL   = (255, 255, 255)
_COLOR_HIT     = (0, 0, 220)    # red when triggered


# ── Zone model ────────────────────────────────────────────────────────────────

@dataclass
class Zone:
    id: str
    name: str
    polygon: list[list[float]]   # [[nx, ny], …] normalised 0–1


# ── Shared in-memory store — imported by the API module ──────────────────────

zones: dict[str, Zone] = {}


def add_zone(name: str, polygon: list[list[float]]) -> Zone:
    zid = str(uuid.uuid4())
    z = Zone(id=zid, name=name, polygon=polygon)
    zones[zid] = z
    asyncio.ensure_future(db.insert_zone(zid, name, polygon))
    logger.info("Zone created: %s (%s, %d pts)", name, zid, len(polygon))
    return z


def remove_zone(zone_id: str) -> bool:
    if zone_id in zones:
        del zones[zone_id]
        asyncio.ensure_future(db.delete_zone(zone_id))
        logger.info("Zone removed: %s", zone_id)
        return True
    return False


def clear_zones() -> None:
    zones.clear()
    asyncio.ensure_future(db.delete_all_zones())
    logger.info("All zones cleared")


# ── Processor ─────────────────────────────────────────────────────────────────

class ZoneProcessor(BaseProcessor):

    def __init__(self, ws_manager=None) -> None:
        self.enabled = False
        self._ws = ws_manager
        self._recorder = None             # injected by main.py
        self._notifier = None             # injected by main.py
        self._zone_recording = False      # True when this processor started recording
        self._inactive_since: float | None = None
        self._active_zones: set[str] = set()  # zone IDs currently being hit (for edge detection)

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
        newly_hit: list[Zone] = []   # zones that transitioned inactive → active this frame

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
                if zone.id not in self._active_zones:
                    newly_hit.append(zone)
                    self._active_zones.add(zone.id)
            else:
                self._active_zones.discard(zone.id)

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

        if stop_mode == "stream":
            activity = len(state.centroids) > 0
        else:
            activity = any_zone_hit

        if newly_hit:
            # Start recording on first zone hit (if not already recording)
            if not self._recorder.is_recording:
                first_zone = newly_hit[0]
                try:
                    filepath = self._recorder.start(
                        frame_width=w,
                        frame_height=h,
                        trigger="zone",
                        trigger_zone_id=first_zone.id,
                    )
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

            # Log DB event and send notifications for each newly-hit zone
            recording_id = self._recorder.recording_id if self._recorder else None
            recording_path = self._recorder.current_file if self._recorder else None

            # Always save a local screenshot on zone trigger
            if self._recorder:
                try:
                    self._recorder.save_screenshot(frame, suffix="_zonetrigger")
                except Exception as exc:
                    logger.warning("Zone trigger screenshot failed: %s", exc)

            # Encode snapshot for notifications only when notifications are enabled
            snapshot: bytes | None = None
            if self._notifier and settings.notify_on_zone_trigger:
                ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                snapshot = buf.tobytes() if ok else None

            for zone in newly_hit:
                asyncio.ensure_future(db.log_zone_event(zone.id, zone.name, recording_id))
                if self._notifier and settings.notify_on_zone_trigger:
                    asyncio.ensure_future(
                        self._notifier.notify_zone_trigger(
                            zone.id, zone.name, recording_path, snapshot
                        )
                    )

        elif self._zone_recording and self._recorder.is_recording:
            if activity:
                self._inactive_since = None
            else:
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
