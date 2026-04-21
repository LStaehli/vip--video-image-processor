"""Detection zone processor.

Zones are closed polygons stored in normalised coordinates (0–1 relative to
frame size) so they survive stream resolution changes.

On every frame:
  1. Zones are drawn (semi-transparent fill + outline + label)
  2. state.centroids (populated by MotionProcessor) are tested against each polygon
  3. When a centroid is inside a zone a zone_alert event is broadcast via WS,
     rate-limited per zone to avoid notification spam
"""
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.processors.base import BaseProcessor, FrameState

logger = logging.getLogger(__name__)

_ALERT_COOLDOWN = 5.0          # seconds between alerts for the same zone

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
    _last_alert: float = field(default=0.0, repr=False)


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

    def process(self, frame: np.ndarray, state: FrameState) -> np.ndarray:
        if not zones:
            return frame

        logger.debug(
            "ZoneProcessor: %d zone(s), %d centroid(s) to test",
            len(zones), len(state.centroids),
        )

        h, w = frame.shape[:2]
        overlay = frame.copy()
        now = time.monotonic()

        for zone in zones.values():
            pts = _denorm(zone.polygon, w, h)
            if len(pts) < 3:
                continue
            pts_arr = np.array(pts, dtype=np.int32)

            # Hit-test every active centroid against this zone
            triggered = any(
                cv2.pointPolygonTest(pts_arr, (float(cx), float(cy)), False) >= 0
                for cx, cy in state.centroids
            )

            color = _COLOR_HIT if triggered else _COLOR_FILL

            # Semi-transparent fill (applied via addWeighted below)
            cv2.fillPoly(overlay, [pts_arr], color)
            # Solid outline directly on frame
            cv2.polylines(frame, [pts_arr], True, color, 2)

            # Zone name label at centroid
            lx = int(sum(p[0] for p in pts) / len(pts))
            ly = int(sum(p[1] for p in pts) / len(pts))
            cv2.putText(
                frame, zone.name, (lx, ly),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, _COLOR_LABEL, 1, cv2.LINE_AA,
            )

            # Fire alert (rate-limited)
            if triggered and (now - zone._last_alert) >= _ALERT_COOLDOWN:
                zone._last_alert = now
                state.zone_hits.append(zone.name)
                if self._ws:
                    asyncio.ensure_future(
                        self._ws.broadcast_event({
                            "type": "zone_alert",
                            "zone_id": zone.id,
                            "zone": zone.name,
                        })
                    )
                logger.info("Zone alert: %s", zone.name)

        cv2.addWeighted(overlay, 0.2, frame, 0.8, 0, frame)
        return frame


def _denorm(polygon: list[list[float]], w: int, h: int) -> list[tuple[int, int]]:
    return [(int(nx * w), int(ny * h)) for nx, ny in polygon]
