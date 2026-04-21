from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Detection:
    class_name: str
    confidence: float
    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2
    center: tuple[int, int]


@dataclass
class FrameState:
    """Shared state passed through the processor chain for one frame."""
    timestamp: float = 0.0
    centroids: list[tuple[int, int]] = field(default_factory=list)
    detections: list[Detection] = field(default_factory=list)
    zone_hits: list[str] = field(default_factory=list)


class BaseProcessor(ABC):
    """All feature processors implement this interface."""

    enabled: bool = True  # toggled at runtime via PUT /api/config

    @abstractmethod
    def process(self, frame: np.ndarray, state: FrameState) -> np.ndarray:
        """Annotate *frame* in-place (or on a copy) and update *state*.

        Args:
            frame: BGR numpy array from OpenCV.
            state: shared FrameState, already populated by earlier processors.

        Returns:
            Annotated frame (may be the same object as the input).
        """
        ...
