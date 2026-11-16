from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

import numpy as np


@dataclass
class HandObservation:
    """One hand as reported by a tracker for a single frame."""
    norm: np.ndarray                 # (21, 3) normalized image coords of the frame given to the tracker
    world: Optional[np.ndarray]      # (21, 3) metric coords (meters) or None if unsupported
    handedness: str                  # "Left" | "Right" (the user's real hand for mirrored input)
    score: float


class HandTracker(Protocol):
    name: str

    def process(self, rgb: np.ndarray, timestamp_ms: int) -> list[HandObservation]:
        ...

    def close(self) -> None:
        ...
