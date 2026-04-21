"""Motion tracking processor.

For each frame:
  1. MOG2 background subtraction → binary motion mask
  2. Morphological cleanup (open + dilate) to remove noise
  3. findContours → filter by area → compute centroids
  4. Associate centroids with existing tracks (nearest-neighbour)
  5. Draw per-track: contour outline, fading position trail, direction arrow
  6. Populate FrameState.centroids for downstream processors (zones etc.)
"""
import math
from collections import deque
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.config import settings
from app.processors.base import BaseProcessor, FrameState

# ── Tuneable constants ────────────────────────────────────────────────────────

# MOG2 background subtractor
_MOG2_HISTORY = 500
_MOG2_VAR_THRESHOLD = 40

# Contour filtering
_MIN_CONTOUR_AREA = 800          # px² — ignore tiny blobs (noise, compression)

# Trail
_TRAIL_LENGTH = 20               # number of historical centroids to keep
_TRAIL_COLOR = (50, 220, 100)    # BGR — bright green
_TRAIL_MAX_RADIUS = 5

# Arrow
_ARROW_COLOR = (0, 200, 255)     # BGR — amber/yellow
_ARROW_THICKNESS = 2
_ARROW_LENGTH = 55               # pixels

# Contour outline
_CONTOUR_COLOR = (50, 220, 100)  # BGR
_CONTOUR_THICKNESS = 2

# Track management
_MAX_MATCH_DISTANCE = 80         # px — max distance to associate a centroid with a track
_MAX_MISSING_FRAMES = 8          # frames before a track is dropped


# ── Track dataclass ───────────────────────────────────────────────────────────

@dataclass
class _Track:
    track_id: int
    history: deque = field(default_factory=lambda: deque(maxlen=_TRAIL_LENGTH))
    missing: int = 0             # consecutive frames where no centroid matched
    contour: np.ndarray | None = None  # most recent contour points


# ── Processor ────────────────────────────────────────────────────────────────

class MotionProcessor(BaseProcessor):

    def __init__(self) -> None:
        self.enabled = True
        self._subtractor = cv2.createBackgroundSubtractorMOG2(
            history=_MOG2_HISTORY,
            varThreshold=settings.motion_mog2_threshold,
            detectShadows=False,
        )
        # Morphology kernels
        self._kernel_open  = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        self._kernel_dilate = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))

        self._tracks: dict[int, _Track] = {}
        self._next_id = 0

    # ── Public interface ──────────────────────────────────────────────────────

    def process(self, frame: np.ndarray, state: FrameState) -> np.ndarray:
        mask = self._build_mask(frame)
        contours = self._find_contours(mask)
        centroids = [self._centroid(c) for c in contours]

        self._update_tracks(centroids, contours)

        self._draw(frame)

        # Expose active centroids to downstream processors
        state.centroids = [
            t.history[-1] for t in self._tracks.values() if t.history
        ]

        return frame

    # ── Internal steps ────────────────────────────────────────────────────────

    def _build_mask(self, frame: np.ndarray) -> np.ndarray:
        mask = self._subtractor.apply(frame)
        # Remove noise and fill holes
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  self._kernel_open)
        mask = cv2.morphologyEx(mask, cv2.MORPH_DILATE, self._kernel_dilate)
        return mask

    def _find_contours(self, mask: np.ndarray) -> list[np.ndarray]:
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        return [c for c in contours if cv2.contourArea(c) >= settings.motion_min_area]

    @staticmethod
    def _centroid(contour: np.ndarray) -> tuple[int, int]:
        m = cv2.moments(contour)
        if m["m00"] == 0:
            x, y, w, h = cv2.boundingRect(contour)
            return (x + w // 2, y + h // 2)
        return (int(m["m10"] / m["m00"]), int(m["m01"] / m["m00"]))

    def _update_tracks(
        self,
        centroids: list[tuple[int, int]],
        contours: list[np.ndarray],
    ) -> None:
        """Nearest-neighbour centroid-to-track association."""
        matched_track_ids: set[int] = set()
        matched_centroid_ids: set[int] = set()

        # Match each detected centroid to the nearest existing track
        for ci, centroid in enumerate(centroids):
            best_id, best_dist = None, float("inf")
            for tid, track in self._tracks.items():
                if not track.history:
                    continue
                dist = _euclidean(track.history[-1], centroid)
                if dist < best_dist and dist < _MAX_MATCH_DISTANCE:
                    best_dist = dist
                    best_id = tid

            if best_id is not None:
                self._tracks[best_id].history.append(centroid)
                self._tracks[best_id].contour = contours[ci]
                self._tracks[best_id].missing = 0
                matched_track_ids.add(best_id)
                matched_centroid_ids.add(ci)

        # Create new tracks for unmatched centroids
        for ci, centroid in enumerate(centroids):
            if ci not in matched_centroid_ids:
                t = _Track(track_id=self._next_id)
                t.history.append(centroid)
                t.contour = contours[ci]
                self._tracks[self._next_id] = t
                self._next_id += 1

        # Age unmatched tracks; prune stale ones
        stale = []
        for tid, track in self._tracks.items():
            if tid not in matched_track_ids:
                track.missing += 1
                if track.missing > _MAX_MISSING_FRAMES:
                    stale.append(tid)
        for tid in stale:
            del self._tracks[tid]

    def _draw(self, frame: np.ndarray) -> None:
        # Read all visual settings once per frame so changes apply immediately
        trail_color      = _hex_to_bgr(settings.motion_trail_color)
        trail_max_radius = settings.motion_trail_max_radius
        contour_color    = _hex_to_bgr(settings.motion_contour_color)
        contour_thick    = settings.motion_contour_thickness
        arrow_color      = _hex_to_bgr(settings.motion_arrow_color)
        arrow_thick      = settings.motion_arrow_thickness
        arrow_enabled    = settings.motion_arrow_enabled
        center_color     = _hex_to_bgr(settings.motion_center_color)
        center_radius    = settings.motion_center_radius
        center_enabled   = settings.motion_center_enabled

        for track in self._tracks.values():
            if not track.history:
                continue

            history = list(track.history)
            n = len(history)
            cx, cy = history[-1]

            # ── Contour outline ───────────────────────────────────────────────
            if track.contour is not None:
                cv2.drawContours(frame, [track.contour], -1, contour_color, contour_thick)

            # ── Fading trail ──────────────────────────────────────────────────
            for i, (tx, ty) in enumerate(history):
                intensity = (i + 1) / n          # oldest=dim, newest=bright
                color  = tuple(int(c * intensity) for c in trail_color)
                radius = max(1, int(trail_max_radius * intensity))
                cv2.circle(frame, (tx, ty), radius, color, -1)

            # ── Center dot ───────────────────────────────────────────────────
            if center_enabled:
                cv2.circle(frame, (cx, cy), center_radius, center_color, -1)

            # ── Direction arrow ───────────────────────────────────────────────
            if arrow_enabled and n >= 4:
                quarter = max(1, n // 4)
                px, py = history[-quarter - 1]
                dx, dy = cx - px, cy - py
                length = math.hypot(dx, dy)
                if length > 5:
                    nx, ny = dx / length, dy / length
                    ex = int(cx + nx * _ARROW_LENGTH)
                    ey = int(cy + ny * _ARROW_LENGTH)
                    cv2.arrowedLine(
                        frame, (cx, cy), (ex, ey),
                        arrow_color, arrow_thick, tipLength=0.35,
                    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _euclidean(a: tuple[int, int], b: tuple[int, int]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _hex_to_bgr(hex_color: str) -> tuple[int, int, int]:
    """Convert a CSS hex color string (#rrggbb) to an OpenCV BGR tuple."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b, g, r)
