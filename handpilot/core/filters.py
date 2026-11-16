"""One Euro filter (Casiez et al., 2012): low jitter at rest, low lag when moving."""
from __future__ import annotations

import math

import numpy as np


def _alpha(cutoff: float, dt: float) -> float:
    tau = 1.0 / (2.0 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


class OneEuroFilter:
    """Works on scalars or numpy arrays of any shape."""

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.0, d_cutoff: float = 1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.reset()

    def reset(self) -> None:
        self._x = None
        self._dx = None
        self._t = None

    def __call__(self, x, t: float):
        x = np.asarray(x, dtype=np.float64)
        if self._x is None:
            self._x, self._dx, self._t = x.copy(), np.zeros_like(x), t
            return x.copy()
        dt = max(t - self._t, 1e-4)
        self._t = t
        dx = (x - self._x) / dt
        a_d = _alpha(self.d_cutoff, dt)
        self._dx = a_d * dx + (1 - a_d) * self._dx
        # Cutoff adapts to the speed of the whole signal (norm), so all
        # coordinates of a point share one smoothing level.
        speed = float(np.linalg.norm(self._dx)) if self._dx.ndim else abs(float(self._dx))
        cutoff = self.min_cutoff + self.beta * speed
        a = _alpha(cutoff, dt)
        self._x = a * x + (1 - a) * self._x
        return self._x.copy()
