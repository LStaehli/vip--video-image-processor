import numpy as np

from app.processors.base import BaseProcessor, FrameState


class MotionProcessor(BaseProcessor):
    """Phase 2 placeholder — implemented in Phase 2."""

    def process(self, frame: np.ndarray, state: FrameState) -> np.ndarray:
        return frame
