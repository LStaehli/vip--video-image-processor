import numpy as np

from app.processors.base import BaseProcessor, FrameState


class DetectionProcessor(BaseProcessor):
    """Phase 4 placeholder — implemented in Phase 4."""

    def process(self, frame: np.ndarray, state: FrameState) -> np.ndarray:
        return frame
