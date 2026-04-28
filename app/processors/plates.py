"""License plate detection and OCR processor.

Two-stage pipeline on every N frames:
  1. YOLO plate detector finds plate bounding boxes in the frame.
  2. EasyOCR reads the text from each cropped plate region.

On each newly-detected plate (edge-triggered with per-plate cooldown):
  - The raw and normalised text are logged to plate_events in the DB.
  - An annotated screenshot is saved when plate_save_screenshot is enabled.
  - A Telegram / email notification is sent when notify_on_plate_detected is on.

Allowlist / blocklist (global, managed via /api/plates/list):
  - Block list takes priority — matching plates are silently skipped.
  - Allow list (if non-empty) restricts notifications/saves to listed plates.
  - Both lists use normalised plate text for matching.

The YOLO model is downloaded once to models/<plate_model> on first use.
EasyOCR model files are cached by EasyOCR in ~/.EasyOCR/model/.
Both are loaded lazily in a background thread so the stream stays live.
"""
import asyncio
import concurrent.futures
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.processors.base import BaseProcessor, FrameState

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# HuggingFace repo + filename for the default plate detection model.
# Download is attempted via huggingface_hub (already a transitive dependency of
# ultralytics) so it benefits from HF_TOKEN auth, local caching, and resumable
# downloads.  Set HF_TOKEN in your .env to access gated repos.
_HF_REPO_ID  = "Koushim/yolov8-license-plate-detection"
_HF_FILENAME = "best.pt"

_COLOR_PLATE   = (0, 200, 255)   # amber (BGR)
_COLOR_ALLOWED = (0, 220, 80)    # green  — allowed plate
_COLOR_TARGET  = (0, 120, 255)   # orange — targeted/watched plate

# Seconds between repeated detections for the same plate text (in-processor)
_DETECT_COOLDOWN = 30.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def normalize_plate(text: str) -> str:
    """Uppercase + keep only alphanumeric characters for reliable comparison."""
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _resolve_model_path(name: str) -> str:
    """Return the full local path for a plate model, downloading if missing.

    Download strategy (in order):
    1. huggingface_hub.hf_hub_download — handles HF_TOKEN auth, caching,
       and resumable transfers.  This is the preferred path.
    2. If huggingface_hub is not available (should not happen since ultralytics
       already requires it), raises with clear instructions.

    To use a gated or private model set HF_TOKEN in your environment / .env.
    You can also skip the download entirely by placing the .pt file at
    models/<name> before enabling the plate processor.
    """
    p = Path("models") / name
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        return str(p)

    logger.info("Plate model not found locally — downloading to %s …", p)
    try:
        from huggingface_hub import hf_hub_download
        downloaded = hf_hub_download(
            repo_id=_HF_REPO_ID,
            filename=_HF_FILENAME,
            local_dir=str(p.parent),
            local_dir_use_symlinks=False,
        )
        # hf_hub_download saves as <local_dir>/<filename>; rename to the
        # model name the config expects (e.g. "yolov8n-lp.pt").
        src = Path(downloaded)
        if src.resolve() != p.resolve():
            src.rename(p)
        logger.info("Plate model downloaded: %s", p)
    except Exception as exc:
        # Clean up any partial file so the next attempt retries the download
        if p.exists():
            p.unlink(missing_ok=True)
        logger.error("Failed to download plate model: %s", exc)
        raise RuntimeError(
            f"Could not download the plate detection model automatically "
            f"({exc}). "
            f"Options:\n"
            f"  1. Set HF_TOKEN in .env and restart (if the repo is gated).\n"
            f"  2. Download '{_HF_FILENAME}' manually from "
            f"https://huggingface.co/{_HF_REPO_ID} "
            f"and place it at models/{name}."
        ) from exc
    return str(p)


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class PlateResult:
    plate_text:      str                    # raw OCR text
    plate_text_norm: str                    # normalised (uppercase alphanum only)
    ocr_confidence:  float                  # EasyOCR confidence 0–1
    det_confidence:  float                  # YOLO detection confidence 0–1
    bbox:            tuple[int, int, int, int]  # x1, y1, x2, y2 of plate in frame
    list_status:     str = "none"           # "target" | "allowed" | "none"


# ── Processor ─────────────────────────────────────────────────────────────────

class PlateProcessor(BaseProcessor):

    def __init__(self) -> None:
        self.enabled = False
        self._cfg       = None      # injected by registry
        self._model     = None      # YOLO model
        self._ocr       = None      # easyocr.Reader
        self._model_ready   = False
        self._loading       = False
        self._loaded_model  : str | None = None
        self._loaded_langs  : str | None = None
        self._frame_count   = 0
        self._cached        : list[PlateResult] = []
        self._last_detected : dict[str, float] = {}  # norm → monotonic ts
        # Injected by registry
        self._recorder      = None
        self._notifier      = None
        self._ws_manager    = None
        self._stream_id     : int | None = None
        self._stream_name   : str = "Channel"
        # In-memory target/allowed sets (refreshed from DB via reload_plate_list)
        self._target_plates:  set[str] = set()   # "target" list — trigger alerts
        self._allowed_plates: set[str] = set()   # "allowed" list — suppress alerts
        self._list_loaded   = False
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="plate-loader"
        )

    # ── Public interface ──────────────────────────────────────────────────────

    def reload_plate_list(self, entries: list[dict]) -> None:
        """Refresh the in-memory target/allowed lists from a list of DB dicts."""
        self._target_plates = {
            e["plate_text_norm"] for e in entries if e["list_type"] == "target"
        }
        self._allowed_plates = {
            e["plate_text_norm"] for e in entries if e["list_type"] == "allowed"
        }
        self._list_loaded = True
        logger.debug(
            "Plate list reloaded: %d target, %d allowed",
            len(self._target_plates), len(self._allowed_plates),
        )

    def process(self, frame: np.ndarray, state: FrameState) -> np.ndarray:
        cfg = self._cfg
        target_model = cfg.plate_model if cfg else "yolov8n-lp.pt"
        target_langs = cfg.plate_ocr_languages if cfg else "en"
        need_load = (
            not self._model_ready
            or self._loaded_model != target_model
            or self._loaded_langs != target_langs
        )
        if need_load and not self._loading:
            self._trigger_load(target_model, target_langs)

        if self._loading or not self._model_ready:
            return frame

        self._frame_count += 1
        skip = max(1, cfg.plate_skip_frames if cfg else 3)

        if self._frame_count % skip == 0:
            self._cached = self._detect_and_read(frame, cfg)
            notify = cfg.notify_on_plate_detected if cfg else False
            save_ss = cfg.plate_save_screenshot if cfg else True
            snapshot: bytes | None = None
            if self._notifier and notify and self._cached:
                ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                snapshot = buf.tobytes() if ok else None
            self._emit_events(self._cached, frame, snapshot, save_ss, notify)

        self._draw(frame, self._cached)
        return frame

    # ── Model loading ─────────────────────────────────────────────────────────

    def _trigger_load(self, model_name: str, langs: str) -> None:
        self._loading = True
        self._model_ready = False
        self._cached = []
        logger.info("Loading plate detection model '%s' and OCR (langs=%s)…", model_name, langs)
        if self._ws_manager:
            asyncio.ensure_future(
                self._ws_manager.broadcast_event({
                    "type": "plate_model_loading",
                    "model": model_name,
                })
            )
        loop = asyncio.get_event_loop()
        future = self._executor.submit(self._load_in_thread, model_name, langs)
        future.add_done_callback(lambda f: self._on_loaded(f, model_name, langs, loop))

    def _load_in_thread(self, model_name: str, langs: str):
        from ultralytics import YOLO
        import easyocr
        model_path = _resolve_model_path(model_name)
        yolo = YOLO(model_path)
        lang_list = [l.strip() for l in langs.split(",") if l.strip()] or ["en"]
        ocr = easyocr.Reader(lang_list, gpu=False, verbose=False)
        return yolo, ocr

    def _on_loaded(
        self,
        future: concurrent.futures.Future,
        model_name: str,
        langs: str,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        try:
            yolo, ocr = future.result()
            self._model = yolo
            self._ocr = ocr
            self._model_ready = True
            self._loaded_model = model_name
            self._loaded_langs = langs
            logger.info("Plate model and OCR ready (model=%s, langs=%s)", model_name, langs)
            event: dict = {"type": "plate_model_ready", "model": model_name}
        except Exception as exc:
            logger.error("Failed to load plate model/OCR: %s", exc)
            self._model_ready = False
            event = {"type": "plate_model_error", "model": model_name, "error": str(exc)}
        finally:
            self._loading = False
        if self._ws_manager:
            asyncio.run_coroutine_threadsafe(
                self._ws_manager.broadcast_event(event), loop
            )

    # ── Detection + OCR ───────────────────────────────────────────────────────

    def _detect_and_read(self, frame: np.ndarray, cfg) -> list[PlateResult]:
        if self._model is None or self._ocr is None:
            return []

        conf_threshold = cfg.plate_confidence if cfg else 0.5
        results: list[PlateResult] = []

        try:
            yolo_results = self._model(frame, verbose=False, conf=conf_threshold)
        except Exception as exc:
            logger.error("YOLO plate inference error: %s", exc)
            return []

        for result in yolo_results:
            for box in result.boxes:
                det_conf = float(box.conf)
                x1, y1, x2, y2 = map(int, box.xyxy[0])

                # Clamp to frame boundaries
                h, w = frame.shape[:2]
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w, x2), min(h, y2)
                if x2 <= x1 or y2 <= y1:
                    continue

                crop = frame[y1:y2, x1:x2]
                plate_text, ocr_conf = self._ocr_plate(crop)
                if not plate_text:
                    continue

                plate_norm = normalize_plate(plate_text)
                if not plate_norm:
                    continue

                list_status = self._check_list(plate_norm)
                results.append(PlateResult(
                    plate_text=plate_text,
                    plate_text_norm=plate_norm,
                    ocr_confidence=ocr_conf,
                    det_confidence=det_conf,
                    bbox=(x1, y1, x2, y2),
                    list_status=list_status,
                ))
                logger.debug(
                    "Plate: '%s' (norm=%s, det=%.2f, ocr=%.2f, list=%s)",
                    plate_text, plate_norm, det_conf, ocr_conf, list_status,
                )

        return results

    def _ocr_plate(self, crop: np.ndarray) -> tuple[str, float]:
        """Run EasyOCR on a cropped plate image.

        Returns (text, confidence). Returns ('', 0.0) if nothing is read.
        Uses the single highest-confidence result among all detected text regions.
        """
        try:
            ocr_results = self._ocr.readtext(crop, detail=1, paragraph=False)
        except Exception as exc:
            logger.error("EasyOCR error: %s", exc)
            return "", 0.0

        if not ocr_results:
            return "", 0.0

        # Pick the result with highest confidence
        best = max(ocr_results, key=lambda r: r[2])
        text = best[1].strip()
        conf = float(best[2])
        return text, conf

    def _check_list(self, plate_norm: str) -> str:
        """Return 'target', 'allowed', or 'none' based on in-memory lists."""
        if plate_norm in self._allowed_plates:
            return "allowed"                        # explicitly cleared — no alert
        if self._target_plates and plate_norm not in self._target_plates:
            return "none"                           # target list active but plate not listed
        if self._target_plates and plate_norm in self._target_plates:
            return "target"                         # explicitly targeted — alert
        return "none"                               # no target list — treat as normal

    def _should_notify(self, list_status: str) -> bool:
        """Return True when this plate should trigger notification/save."""
        if list_status == "allowed":
            return False                            # explicitly allowed — suppress alert
        # If target list is active, only targeted plates notify
        if self._target_plates and list_status != "target":
            return False
        return True

    # ── Events ────────────────────────────────────────────────────────────────

    def _emit_events(
        self,
        results: list[PlateResult],
        frame: np.ndarray,
        snapshot: bytes | None,
        save_screenshot: bool,
        notify: bool,
    ) -> None:
        from app.services import database as db
        now = time.monotonic()
        recording_id = self._recorder.recording_id if self._recorder else None
        recording_path = self._recorder.current_file if self._recorder else None

        for r in results:
            # Cooldown: don't flood for the same plate text
            if now - self._last_detected.get(r.plate_text_norm, 0.0) < _DETECT_COOLDOWN:
                continue
            self._last_detected[r.plate_text_norm] = now

            # WS broadcast
            if self._ws_manager:
                asyncio.ensure_future(
                    self._ws_manager.broadcast_event({
                        "type": "plate_detected",
                        "plate": r.plate_text,
                        "plate_norm": r.plate_text_norm,
                        "confidence": round(r.ocr_confidence, 2),
                        "list_status": r.list_status,
                    })
                )

            # Screenshot — only for plates that are "of interest":
            #   • always skip allowed plates (they are whitelisted)
            #   • if a target list is set, only snapshot target plates
            #   • otherwise (no lists, or only allowed list) snapshot everything else
            screenshot_path: str | None = None
            if save_screenshot and self._recorder and self._should_notify(r.list_status):
                try:
                    screenshot_path = self._recorder.save_screenshot(
                        frame, suffix=f"_plate_{r.plate_text_norm}"
                    )
                except Exception as exc:
                    logger.warning("Plate screenshot failed: %s", exc)

            # DB log
            asyncio.ensure_future(
                db.log_plate_event(
                    stream_id=self._stream_id or 0,
                    plate_text=r.plate_text,
                    plate_text_norm=r.plate_text_norm,
                    confidence=r.ocr_confidence,
                    recording_id=recording_id,
                    screenshot_path=screenshot_path,
                )
            )

            # Notification — only when list check passes
            if self._notifier and notify and self._should_notify(r.list_status):
                asyncio.ensure_future(
                    self._notifier.notify_plate_detected(
                        plate_text=r.plate_text,
                        plate_text_norm=r.plate_text_norm,
                        stream_name=self._stream_name,
                        recording_path=recording_path,
                        snapshot=snapshot,
                    )
                )

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw(self, frame: np.ndarray, results: list[PlateResult]) -> None:
        for r in results:
            x1, y1, x2, y2 = r.bbox
            if r.list_status == "allowed":
                color = _COLOR_ALLOWED
            elif r.list_status == "target":
                color = _COLOR_TARGET
            else:
                color = _COLOR_PLATE

            # Plate bounding box
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

            # Label: plate text + confidence
            label = f"{r.plate_text}  {r.ocr_confidence:.0%}"
            if r.list_status == "allowed":
                label = f"[OK] {label}"
            elif r.list_status == "target":
                label = f"[TARGET] {label}"

            (tw, th), baseline = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1
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
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA,
            )
