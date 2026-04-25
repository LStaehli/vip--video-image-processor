"""Face recognition processor.

On every frame (or every N frames):
  1. Detects faces using DeepFace (OpenCV backend for speed)
  2. Extracts embeddings for each detected face (Facenet512 / ArcFace)
  3. Compares embeddings against enrolled references (cosine similarity)
  4. Draws bounding boxes with name + similarity (green = known, grey = unknown)
  5. Broadcasts a face_recognized WebSocket event on first recognition (10 s cooldown)

The model is loaded lazily in a ThreadPoolExecutor so the video stream
stays live during download and initialisation.
"""
import asyncio
import concurrent.futures
import logging
import time
from dataclasses import dataclass
from datetime import datetime

import cv2
import numpy as np

from app.config import settings
from app.processors.base import BaseProcessor, FrameState
from app.services import database as db
from app.services import face_store

def _resolve_face_message(template: str, face_name: str, similarity: float) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (template
        .replace("{face_name}",         face_name)
        .replace("{similarity}",        f"{similarity:.0%}")
        .replace("{current_timestamp}", ts)
    )

logger = logging.getLogger(__name__)

_COLOR_KNOWN   = (80,  220,  80)   # green (BGR)
_COLOR_UNKNOWN = (130, 130, 130)   # grey  (BGR)

_NOTIF_COOLDOWN = 10.0  # seconds between repeated alerts for the same person


@dataclass
class FaceResult:
    name: str               # person name or "Unknown"
    similarity: float       # cosine similarity (0.0 if unknown)
    det_score: float        # detection confidence
    bbox: tuple[int, int, int, int]
    left_eye: tuple[int, int] | None = None   # pixel coords if detector provides them
    right_eye: tuple[int, int] | None = None


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


class FaceProcessor(BaseProcessor):

    def __init__(self) -> None:
        self.enabled = False
        self._cfg = None                       # injected by registry
        self._model_ready = False
        self._loaded_model_name: str | None = None
        self._frame_count = 0
        self._cached: list[FaceResult] = []
        self._loading = False
        self._ws_manager = None              # injected from main.py
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="face-loader"
        )
        self._last_notified: dict[str, float] = {}
        self._last_auto_enroll: float = 0.0   # monotonic timestamp of last auto-enrollment
        self._recorder = None                  # injected from registry
        self._notifier = None                  # injected from registry

    # ── Public interface ──────────────────────────────────────────────────────

    def process(self, frame: np.ndarray, state: FrameState) -> np.ndarray:
        cfg = self._cfg
        target = cfg.face_model if cfg else "Facenet512"
        need_load = not self._model_ready or self._loaded_model_name != target
        if need_load and not self._loading:
            self._trigger_load(target)

        if self._loading or not self._model_ready:
            return frame

        self._frame_count += 1
        if self._frame_count % max(1, cfg.face_skip_frames if cfg else 3) == 0:
            self._cached = self._detect_and_recognise(frame)
            notify = cfg.notify_on_face_recognized if cfg else False
            snapshot: bytes | None = None
            if self._notifier and notify:
                ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                snapshot = buf.tobytes() if ok else None
            self._emit_events(self._cached, snapshot=snapshot)

        self._draw(frame, self._cached)
        return frame

    def get_embedding_from_frame(self, frame: np.ndarray) -> np.ndarray | None:
        """Extract an embedding from the largest face in the frame.

        Called synchronously from the enrollment API. Returns None if
        the model is not ready or no face is detected.
        """
        if not self._model_ready:
            return None
        try:
            from deepface import DeepFace
            results = DeepFace.represent(
                img_path=frame,
                model_name=self._loaded_model_name,
                detector_backend="opencv",
                enforce_detection=False,
                align=True,
            )
        except Exception as exc:
            logger.error("DeepFace enrollment error: %s", exc)
            return None

        if not results:
            return None

        if len(results) > 1:
            logger.warning("Enrollment: %d faces detected — using the largest", len(results))
            # Pick the largest face by area
            results = [max(results, key=lambda r: (
                r["facial_area"]["w"] * r["facial_area"]["h"]
            ))]

        emb = results[0].get("embedding")
        if emb is None:
            return None
        return np.array(emb, dtype=np.float32)

    # ── Model loading (non-blocking) ──────────────────────────────────────────

    def _trigger_load(self, target: str) -> None:
        self._loading = True
        self._model_ready = False
        self._cached = []
        logger.info("Loading face recognition model in background: %s", target)
        if self._ws_manager:
            asyncio.ensure_future(
                self._ws_manager.broadcast_event({"type": "face_model_loading", "model": target})
            )
        loop = asyncio.get_event_loop()
        future = self._executor.submit(self._load_in_thread, target)
        future.add_done_callback(lambda f: self._on_loaded(f, target, loop))

    def _load_in_thread(self, target: str) -> None:
        """Trigger DeepFace model download and warm up the internal cache."""
        from deepface import DeepFace
        dummy = np.zeros((112, 112, 3), dtype=np.uint8)
        DeepFace.represent(
            img_path=dummy,
            model_name=target,
            detector_backend="skip",
            enforce_detection=False,
        )

    def _on_loaded(
        self,
        future: concurrent.futures.Future,
        target: str,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        try:
            future.result()
            self._model_ready = True
            self._loaded_model_name = target
            logger.info("Face recognition model ready: %s", target)
            event: dict = {"type": "face_model_ready", "model": target}
        except Exception as exc:
            logger.error("Failed to load face model '%s': %s", target, exc)
            self._model_ready = False
            event = {"type": "face_model_error", "model": target, "error": str(exc)}
        finally:
            self._loading = False
        if self._ws_manager:
            asyncio.run_coroutine_threadsafe(
                self._ws_manager.broadcast_event(event), loop
            )

    # ── Detection + recognition ───────────────────────────────────────────────

    def _detect_and_recognise(self, frame: np.ndarray) -> list[FaceResult]:
        try:
            from deepface import DeepFace
            raw = DeepFace.represent(
                img_path=frame,
                model_name=self._loaded_model_name,
                detector_backend="opencv",
                enforce_detection=False,
                align=True,
            )
        except Exception as exc:
            logger.error("DeepFace inference error: %s", exc)
            return []

        references = face_store.all_faces()
        cfg = self._cfg
        threshold = cfg.face_similarity_threshold if cfg else 0.4
        results: list[FaceResult] = []

        for entry in raw:
            det_score = float(entry.get("face_confidence", 0.0))
            if det_score <= 0.0:
                # DeepFace returns a zero-confidence dummy entry when no face
                # is found and enforce_detection=False — skip it entirely.
                continue

            area = entry.get("facial_area", {})
            x = int(area.get("x", 0))
            y = int(area.get("y", 0))
            w = int(area.get("w", 0))
            h = int(area.get("h", 0))
            emb = np.array(entry["embedding"], dtype=np.float32)

            best_name = "Unknown"
            best_sim = 0.0
            for ref_name, ref_emb in references.items():
                sim = _cosine_similarity(emb, ref_emb)
                if sim > best_sim:
                    best_sim = sim
                    best_name = ref_name if sim >= threshold else "Unknown"

            # Auto-enroll: unknown face with sufficient quality
            if (
                best_name == "Unknown"
                and (cfg.face_auto_enroll if cfg else False)
                and det_score >= (cfg.face_auto_enroll_min_score if cfg else 0.85)
                and time.monotonic() - self._last_auto_enroll >= 3.0
            ):
                auto_name = f"face_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                created_at = face_store.add_face(auto_name, emb)
                references[auto_name] = emb          # update local copy so next face isn't a dup
                self._last_auto_enroll = time.monotonic()
                best_name = auto_name
                best_sim = 1.0
                logger.info("Auto-enrolled face: '%s' (det_score=%.2f)", auto_name, det_score)

                # Save a screenshot of the frame that triggered enrollment
                if self._recorder is not None:
                    try:
                        path = self._recorder.save_screenshot(frame, suffix="_autoenroll")
                        logger.info("Auto-enroll screenshot saved → %s", path)
                    except Exception as exc:
                        logger.error("Auto-enroll screenshot failed: %s", exc)

                if self._ws_manager:
                    asyncio.ensure_future(
                        self._ws_manager.broadcast_event({
                            "type": "face_enrolled",
                            "name": auto_name,
                            "created_at": created_at,
                        })
                    )

            le = entry.get("facial_area", {}).get("left_eye")
            re = entry.get("facial_area", {}).get("right_eye")

            results.append(FaceResult(
                name=best_name,
                similarity=best_sim if best_name != "Unknown" else 0.0,
                det_score=det_score,
                bbox=(x, y, x + w, y + h),
                left_eye=(int(le[0]), int(le[1])) if le else None,
                right_eye=(int(re[0]), int(re[1])) if re else None,
            ))
            logger.debug("Face: %s sim=%.2f det=%.2f", best_name, best_sim, det_score)

        return results

    # ── WebSocket events ──────────────────────────────────────────────────────

    def _emit_events(self, results: list[FaceResult], snapshot: bytes | None = None) -> None:
        if not self._ws_manager:
            return
        now = time.monotonic()
        recording_id = self._recorder.recording_id if self._recorder else None
        recording_path = self._recorder.current_file if self._recorder else None
        for r in results:
            if r.name == "Unknown":
                continue
            if now - self._last_notified.get(r.name, 0.0) < _NOTIF_COOLDOWN:
                continue
            self._last_notified[r.name] = now
            asyncio.ensure_future(
                self._ws_manager.broadcast_event({
                    "type": "face_recognized",
                    "name": r.name,
                    "similarity": round(r.similarity, 2),
                })
            )
            asyncio.ensure_future(
                db.log_face_event(r.name, r.similarity, recording_id)
            )
            if self._notifier and snapshot is not None:
                asyncio.ensure_future(
                    self._notify_face(r.name, r.similarity, recording_path, snapshot)
                )

    async def _notify_face(
        self,
        face_name: str,
        similarity: float,
        recording_path: str | None,
        snapshot: bytes | None,
    ) -> None:
        """Load per-face custom messages from DB, resolve template variables, then send."""
        face_cfg = await db.get_face_notification_settings(face_name)
        tg_msg = face_cfg.get("telegram_message", "")
        em_msg = face_cfg.get("email_message", "")
        if tg_msg:
            tg_msg = _resolve_face_message(tg_msg, face_name, similarity)
        if em_msg:
            em_msg = _resolve_face_message(em_msg, face_name, similarity)
        await self._notifier.notify_face_recognized(
            face_name, similarity, recording_path, snapshot,
            telegram_message=tg_msg,
            email_message=em_msg,
        )

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw(self, frame: np.ndarray, results: list[FaceResult]) -> None:
        for r in results:
            x1, y1, x2, y2 = r.bbox
            color = _COLOR_KNOWN if r.name != "Unknown" else _COLOR_UNKNOWN

            # Bounding box
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

            # Label
            label = f"{r.name}  {r.similarity:.0%}" if r.name != "Unknown" else "Unknown"
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
            cv2.putText(
                frame, label,
                (x1 + 3, label_y - baseline - 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA,
            )

            # Landmarks
            if self._cfg.face_show_landmarks if self._cfg else True:
                self._draw_landmarks(frame, r, color)

    def _draw_landmarks(
        self,
        frame: np.ndarray,
        r: FaceResult,
        color: tuple[int, int, int],
    ) -> None:
        """Draw 5-point facial landmark mesh (eyes, nose, mouth corners).

        Uses actual eye coordinates from the detector when available;
        otherwise estimates all five points from bounding-box proportions.
        Standard facial geometry ratios are used for the estimate:
          eyes  ~ 35 % down, at 28 % / 72 % across
          nose  ~ 57 % down, at 50 % across
          mouth ~ 75 % down, at 32 % / 68 % across
        """
        x1, y1, x2, y2 = r.bbox
        w = x2 - x1
        h = y2 - y1

        # Eye positions — use detector output when present
        if r.left_eye and r.right_eye:
            le = r.left_eye
            re = r.right_eye
        else:
            le = (x1 + int(w * 0.28), y1 + int(h * 0.35))
            re = (x1 + int(w * 0.72), y1 + int(h * 0.35))

        # Estimate nose and mouth from eye positions + face height
        nose  = (x1 + int(w * 0.50), y1 + int(h * 0.57))
        ml    = (x1 + int(w * 0.32), y1 + int(h * 0.75))
        mr    = (x1 + int(w * 0.68), y1 + int(h * 0.75))

        # Connecting lines
        for pt_a, pt_b in ((le, re), (le, nose), (re, nose), (nose, ml), (nose, mr), (ml, mr)):
            cv2.line(frame, pt_a, pt_b, color, 1, cv2.LINE_AA)

        # Key-point dots
        for pt in (le, re, nose, ml, mr):
            cv2.circle(frame, pt, 3, color, -1, cv2.LINE_AA)
