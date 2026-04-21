"""Video recording service.

Writes annotated frames from the pipeline to an MP4 file.
The output path and filename are resolved from a configurable pattern
that supports the following variables:

    {project_name}       — settings.recording_project_name
    {current_date}       — YYYY-MM-DD
    {current_timestamp}  — YYYY-MM-DD_HH-MM-SS
"""
import logging
import os
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)


class RecordingService:

    def __init__(self) -> None:
        self.is_recording = False
        self._writer: cv2.VideoWriter | None = None
        self._current_file: str | None = None
        self._started_at: float | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self, frame_width: int, frame_height: int) -> str:
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
        self.is_recording = True
        logger.info("Recording started → %s", filepath)
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
        self._started_at = None
        self._current_file = None
        logger.info("Recording stopped — saved to %s (%.1fs)", filepath, duration)
        return filepath

    def write_frame(self, frame: np.ndarray) -> None:
        """Write a single annotated frame. No-op if not recording."""
        if self.is_recording and self._writer:
            self._writer.write(frame)

    def save_screenshot(self, frame: np.ndarray) -> str:
        """Save a single annotated frame as a JPEG. Returns the saved file path."""
        base = self._resolve_path()  # e.g. recordings/vip_2026-04-21_14-31-42.mp4
        # Replace .mp4 extension with _screenshot.jpg
        filepath = base[:-4] + "_screenshot.jpg"
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
    def elapsed_seconds(self) -> float:
        if self._started_at is None:
            return 0.0
        return time.monotonic() - self._started_at

    # ── Internals ─────────────────────────────────────────────────────────────

    def _resolve_path(self) -> str:
        now = datetime.now()
        variables = {
            "{project_name}":      settings.recording_project_name,
            "{current_date}":      now.strftime("%Y-%m-%d"),
            "{current_timestamp}": now.strftime("%Y-%m-%d_%H-%M-%S"),
        }
        filename = settings.recording_filename_pattern
        for key, value in variables.items():
            filename = filename.replace(key, value)

        # Strip any path separators that slipped in from the pattern
        filename = filename.replace("/", "_").replace("\\", "_")

        output_dir = Path(settings.recording_output_dir)
        return str(output_dir / f"{filename}.mp4")
