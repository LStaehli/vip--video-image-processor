"""YOLOv8 object detection processor.

On every frame (or every N frames for performance):
  1. Runs YOLOv8 inference with the configured model and confidence threshold
  2. Filters detections to the configured class allow-list (empty = all classes)
  3. Draws bounding boxes with label + confidence on the frame
  4. Populates state.detections for downstream processors

The model is loaded lazily in a background thread on the first processed frame
and reloaded automatically if settings.yolo_model changes at runtime.
While loading the model the frame is passed through unchanged and a
model_loading WebSocket event is sent to connected clients.
"""
import asyncio
import concurrent.futures
import logging

import cv2
import numpy as np

from app.config import settings
from app.processors.base import BaseProcessor, Detection, FrameState

logger = logging.getLogger(__name__)

# Visually distinct BGR colours — one assigned per class name by hash
_PALETTE = [
    (0,   200, 255),   # amber
    (0,   255, 127),   # spring green
    (147,  20, 255),   # violet
    (255,   0, 144),   # hot pink
    (255, 200,   0),   # sky blue
    (0,   255, 255),   # yellow
    (80,  127, 255),   # coral
    (200, 255,   0),   # lime
]


def _class_color(class_name: str) -> tuple[int, int, int]:
    return _PALETTE[hash(class_name) % len(_PALETTE)]


class DetectionProcessor(BaseProcessor):

    def __init__(self) -> None:
        self.enabled = False
        self._model = None
        self._loaded_model_name: str | None = None
        self._frame_count = 0
        self._cached: list[Detection] = []   # detections from last inference run
        self._loading = False
        self._ws_manager = None              # injected from main.py
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="yolo-loader"
        )

    # ── Public interface ──────────────────────────────────────────────────────

    def process(self, frame: np.ndarray, state: FrameState) -> np.ndarray:
        target = settings.yolo_model
        need_load = self._model is None or self._loaded_model_name != target

        if need_load and not self._loading:
            self._trigger_load(target)

        # Pass frame through unchanged while model is loading
        if self._loading or self._model is None:
            return frame

        self._frame_count += 1
        skip = max(1, settings.yolo_skip_frames)

        if self._frame_count % skip == 0:
            self._cached = self._infer(frame)
            logger.debug(
                "YOLOv8 inference: %d detection(s) (model=%s conf=%.2f skip=%d)",
                len(self._cached), settings.yolo_model,
                settings.yolo_confidence, skip,
            )

        self._draw(frame, self._cached)
        state.detections = list(self._cached)
        return frame

    # ── Model loading (non-blocking) ──────────────────────────────────────────

    def _trigger_load(self, target: str) -> None:
        """Schedule a background model load and broadcast the loading event."""
        self._loading = True
        self._model = None
        self._cached = []
        logger.info("Loading YOLO model in background: %s", target)

        if self._ws_manager:
            asyncio.ensure_future(
                self._ws_manager.broadcast_event({"type": "model_loading", "model": target})
            )

        loop = asyncio.get_event_loop()
        future = self._executor.submit(self._load_in_thread, target)
        future.add_done_callback(lambda f: self._on_loaded(f, target, loop))

    def _load_in_thread(self, target: str):
        """Blocking model load — runs in the thread pool."""
        from ultralytics import YOLO
        return YOLO(target)

    def _on_loaded(
        self,
        future: concurrent.futures.Future,
        target: str,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """Called from the thread pool when loading finishes (success or error)."""
        try:
            model = future.result()
            self._model = model
            self._loaded_model_name = target
            logger.info("YOLO model ready: %s", target)
            event: dict = {"type": "model_ready", "model": target}
        except Exception as exc:
            logger.error("Failed to load YOLO model '%s': %s", target, exc)
            self._model = None
            event = {"type": "model_error", "model": target, "error": str(exc)}
        finally:
            self._loading = False

        if self._ws_manager:
            asyncio.run_coroutine_threadsafe(
                self._ws_manager.broadcast_event(event), loop
            )

    # ── Inference ─────────────────────────────────────────────────────────────

    def _infer(self, frame: np.ndarray) -> list[Detection]:
        if self._model is None:
            return []

        allowed = set(settings.detect_class_list)   # empty set = all classes
        conf_threshold = settings.yolo_confidence
        detections: list[Detection] = []

        try:
            results = self._model(frame, verbose=False, conf=conf_threshold)
        except Exception as exc:
            logger.error("YOLO inference error: %s", exc)
            return []

        for result in results:
            for box in result.boxes:
                class_name = result.names[int(box.cls)]
                if allowed and class_name not in allowed:
                    continue
                conf = float(box.conf)
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                cx = (x1 + x2) // 2
                cy = (y1 + y2) // 2
                detections.append(Detection(
                    class_name=class_name,
                    confidence=conf,
                    bbox=(x1, y1, x2, y2),
                    center=(cx, cy),
                ))

        return detections

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw(self, frame: np.ndarray, detections: list[Detection]) -> None:
        for d in detections:
            x1, y1, x2, y2 = d.bbox
            color = _class_color(d.class_name)
            label = f"{d.class_name}  {d.confidence:.0%}"

            # Bounding box
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

            # Label background
            (tw, th), baseline = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
            )
            label_y = max(y1, th + 6)
            cv2.rectangle(
                frame,
                (x1, label_y - th - baseline - 4),
                (x1 + tw + 6, label_y),
                color, -1,
            )
            # Label text (dark on coloured background)
            cv2.putText(
                frame, label,
                (x1 + 3, label_y - baseline - 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA,
            )
