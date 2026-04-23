"""Video recording service.

Writes annotated frames from the pipeline to an MP4 file.
The output path and filename are resolved from a configurable pattern
that supports the following variables:

    {project_name}       — settings.recording_project_name
    {channel_number}     — channel number (e.g. 1, 2)
    {channel_slug}       — slugified channel name (e.g. front-door)
    {current_date}       — YYYY-MM-DD
    {current_timestamp}  — YYYY-MM-DD_HH-MM-SS

Each recording session is logged to the database on start and finalised
(end_time, duration) on stop.
"""
import asyncio
import logging
import re
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from app.config import settings
from app.services import database as db

logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    """Convert a channel name to a URL-safe slug (e.g. 'Front Door' → 'front-door')."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    return text or "channel"


class RecordingService:

    def __init__(self, channel_number: int = 1, channel_name: str = "channel") -> None:
        self.is_recording = False
        self._writer: cv2.VideoWriter | None = None
        self._current_file: str | None = None
        self._started_at: float | None = None
        self._recording_id: str | None = None
        self._channel_number = channel_number
        self._channel_slug = _slugify(channel_name)

    # ── Public API ────────────────────────────────────────────────────────────

    def start(
        self,
        frame_width: int,
        frame_height: int,
        trigger: str = "manual",
        trigger_zone_id: str | None = None,
        trigger_face_name: str | None = None,
    ) -> str:
        """Begin recording. Returns the resolved output file path."""
        if self.is_recording:
            raise RuntimeError("Recording already in progress")

        filepath = self._resolve_path()
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        self._writer = cv2.VideoWriter(
            filepath, fourcc, settings.target_fps, (frame_width, frame_height)
        )

        if not self._writer.isOpened():
            self._writer = None
            raise RuntimeError(f"cv2.VideoWriter failed to open: {filepath}")

        self._current_file = filepath
        self._started_at = time.monotonic()
        self._recording_id = db.new_id()
        self.is_recording = True

        asyncio.ensure_future(
            db.insert_recording(
                self._recording_id,
                filepath,
                trigger,
                trigger_zone_id,
                trigger_face_name,
            )
        )

        logger.info("Recording started → %s (trigger=%s)", filepath, trigger)
        return filepath

    def stop(self) -> str:
        """Stop recording and flush the file. Returns the saved file path."""
        if not self.is_recording:
            raise RuntimeError("No recording in progress")

        self._writer.release()
        self._writer = None
        self.is_recording = False

        filepath = self._current_file
        duration = time.monotonic() - self._started_at
        recording_id = self._recording_id

        self._current_file = None
        self._started_at = None
        self._recording_id = None

        asyncio.ensure_future(db.finalize_recording(recording_id, duration))

        logger.info("Recording stopped — saved to %s (%.1fs)", filepath, duration)
        return filepath

    def write_frame(self, frame: np.ndarray) -> None:
        """Write a single annotated frame. No-op if not recording."""
        if self.is_recording and self._writer:
            self._writer.write(frame)

    def save_screenshot(self, frame: np.ndarray, suffix: str = "_screenshot") -> str:
        """Save a single annotated frame as a JPEG.

        Args:
            frame:  The image to save.
            suffix: Appended to the resolved filename before the extension.

        Returns:
            The saved file path.
        """
        base = self._resolve_path()
        filepath = base[:-4] + f"{suffix}.jpg"
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        ok = cv2.imwrite(filepath, frame)
        if not ok:
            raise RuntimeError(f"cv2.imwrite failed: {filepath}")
        logger.info("Screenshot saved → %s", filepath)
        return filepath

    @property
    def current_file(self) -> str | None:
        return self._current_file

    @property
    def recording_id(self) -> str | None:
        """DB recording UUID, available while is_recording is True."""
        return self._recording_id

    @property
    def elapsed_seconds(self) -> float:
        if self._started_at is None:
            return 0.0
        return time.monotonic() - self._started_at

    # ── Internals ─────────────────────────────────────────────────────────────

    def _resolve_path(self) -> str:
        now = datetime.now()
        variables = {
            "{project_name}":      settings.recording_project_name,
            "{channel_number}":    str(self._channel_number),
            "{channel_slug}":      self._channel_slug,
            "{current_date}":      now.strftime("%Y-%m-%d"),
            "{current_timestamp}": now.strftime("%Y-%m-%d_%H-%M-%S"),
        }
        filename = settings.recording_filename_pattern
        for key, value in variables.items():
            filename = filename.replace(key, value)

        filename = filename.replace("/", "_").replace("\\", "_")
        return str(Path(settings.recording_output_dir) / f"{filename}.mp4")
