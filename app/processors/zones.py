"""Detection zone processor.

Zones are closed polygons stored in normalised coordinates (0–1 relative to
frame size) so they survive stream resolution changes.

Zone definitions are persisted in SQLite (per stream) and reloaded on startup.

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
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime

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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return re.sub(r"-{2,}", "-", text) or "channel"


def _resolve_message(template: str, zone_name: str, channel_number: int, channel_slug: str) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (template
        .replace("{zone_name}",        zone_name)
        .replace("{channel_number}",   str(channel_number))
        .replace("{channel_slug}",     channel_slug)
        .replace("{current_timestamp}", ts)
    )


# ── Zone model ────────────────────────────────────────────────────────────────

@dataclass
class Zone:
    id: str
    name: str
    polygon: list[list[float]]   # [[nx, ny], …] normalised 0–1


# ── Processor ─────────────────────────────────────────────────────────────────

class ZoneProcessor(BaseProcessor):

    def __init__(self, ws_manager=None) -> None:
        self.enabled = False
        self._ws = ws_manager
        self._recorder = None             # injected by registry
        self._notifier = None             # injected by registry
        self._zone_recording = False      # True when this processor started recording
        self._inactive_since: float | None = None
        self._active_zones: set[str] = set()  # zone IDs currently being hit (edge detection)
        self._cfg = None                       # injected by registry
        self._zones: dict[str, Zone] = {}     # per-stream zone store
        self._stream_id: int | None = None    # set by registry
        self._channel_number: int = 1         # set by registry
        self._channel_slug: str = "channel"   # set by registry

    # ── Zone CRUD (instance-scoped, stream-aware) ─────────────────────────────

    def add_zone(self, name: str, polygon: list[list[float]]) -> Zone:
        zid = str(uuid.uuid4())
        z = Zone(id=zid, name=name, polygon=polygon)
        self._zones[zid] = z
        asyncio.ensure_future(db.insert_zone(self._stream_id, zid, name, polygon))
        logger.info("Zone created: %s (%s, %d pts) on stream %s", name, zid, len(polygon), self._stream_id)
        return z

    def remove_zone(self, zone_id: str) -> bool:
        if zone_id in self._zones:
            del self._zones[zone_id]
            self._active_zones.discard(zone_id)
            asyncio.ensure_future(db.delete_zone(zone_id))
            logger.info("Zone removed: %s", zone_id)
            return True
        return False

    def clear_zones(self) -> None:
        self._zones.clear()
        self._active_zones.clear()
        asyncio.ensure_future(db.delete_all_zones(self._stream_id))
        logger.info("All zones cleared for stream %s", self._stream_id)

    def list_zones(self) -> list[dict]:
        return [{"id": z.id, "name": z.name, "polygon": z.polygon} for z in self._zones.values()]

    # ── Frame processing ──────────────────────────────────────────────────────

    def process(self, frame: np.ndarray, state: FrameState) -> np.ndarray:
        if not self._zones:
            return frame

        h, w = frame.shape[:2]
        overlay = frame.copy()
        stop_mode = self._cfg.zone_stop_mode if self._cfg else "zone"

        logger.debug(
            "ZoneProcessor: %d zone(s), %d centroid(s), stop_mode=%s",
            len(self._zones), len(state.centroids), stop_mode,
        )

        # ── Draw zones and test centroids ─────────────────────────────────────
        any_zone_hit = False
        newly_hit: list[Zone] = []   # zones that transitioned inactive → active this frame

        for zone in self._zones.values():
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
            notify = self._cfg.notify_on_zone_trigger if self._cfg else False
            snapshot: bytes | None = None
            if self._notifier and notify:
                ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                snapshot = buf.tobytes() if ok else None

            for zone in newly_hit:
                asyncio.ensure_future(db.log_zone_event(zone.id, zone.name, recording_id))
                if self._notifier and notify:
                    asyncio.ensure_future(
                        self._notify_zone(zone, recording_path, snapshot)
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

    async def _notify_zone(self, zone: "Zone", recording_path: str | None, snapshot: bytes | None) -> None:
        """Load per-zone custom messages from DB, resolve template variables, then send."""
        zone_cfg = await db.get_zone_settings(zone.id)
        tg_msg = zone_cfg.get("telegram_message", "")
        em_msg = zone_cfg.get("email_message", "")
        if tg_msg:
            tg_msg = _resolve_message(tg_msg, zone.name, self._channel_number, self._channel_slug)
        if em_msg:
            em_msg = _resolve_message(em_msg, zone.name, self._channel_number, self._channel_slug)
        await self._notifier.notify_zone_trigger(
            zone.id, zone.name, recording_path, snapshot,
            telegram_message=tg_msg,
            email_message=em_msg,
        )


def _denorm(polygon: list[list[float]], w: int, h: int) -> list[tuple[int, int]]:
    return [(int(nx * w), int(ny * h)) for nx, ny in polygon]
