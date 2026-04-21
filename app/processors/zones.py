import numpy as np

from app.processors.base import BaseProcessor, FrameState


class ZoneProcessor(BaseProcessor):
    """Phase 3 placeholder — implemented in Phase 3."""

    def __init__(self, ws_manager=None) -> None:
        self._ws_manager = ws_manager

    def process(self, frame: np.ndarray, state: FrameState) -> np.ndarray:
        return frame
