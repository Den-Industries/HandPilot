"""Maps hand motion to cursor motion.

Two mapping modes:
* relative – like a touchpad: hand *movement* moves the cursor, with a pointer
  acceleration curve (slow = precise, fast = cross the screen). Hiding the hand
  and bringing it back "re-centers" without moving the cursor (clutching).
  Small hand movements are enough, so the arm can rest on the desk.
* absolute – the active area of the camera frame maps onto the screen.

Clicks must not move the cursor: when a pinch starts the cursor is restored to
where it was just before the fingers started closing and then frozen until the
hand clearly moves (that movement turns the pinch into a drag).
"""
from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np

from ..config import CursorSettings, GestureSettings
from ..core.filters import OneEuroFilter


def _smoothstep(x: float, a: float, b: float) -> float:
    t = min(max((x - a) / (b - a), 0.0), 1.0)
    return t * t * (3 - 2 * t)


class CursorController:
    REWIND_S = 0.09              # how far back to restore the cursor on pinch onset
    RELEASE_FREEZE_S = 0.12      # opening the fingers also nudges the hand

    def __init__(self, cfg: CursorSettings, gcfg: GestureSettings, screen: tuple[int, int, int, int]):
        self.cfg, self.gcfg = cfg, gcfg
        self.set_screen(screen)
        self.filter = OneEuroFilter(cfg.smoothing, cfg.responsiveness)
        self.history: deque[tuple[float, float, float]] = deque(maxlen=30)
        self.pos: Optional[np.ndarray] = None
        self.prev_anchor: Optional[np.ndarray] = None
        self.frozen_until = 0.0
        self.freeze_anchor: Optional[np.ndarray] = None
        self.drag_free = True
        self.last_set: Optional[tuple[int, int]] = None

    def set_screen(self, screen):
        self.left, self.top, self.width, self.height = screen

    def apply_settings(self, cfg: CursorSettings):
        self.cfg = cfg
        self.filter.min_cutoff, self.filter.beta = cfg.smoothing, cfg.responsiveness

    def reset(self, current_pos: Optional[tuple[int, int]] = None):
        """Hand lost/regained: forget motion history (this is the 'clutch')."""
        self.filter.reset()
        self.prev_anchor = None
        self.freeze_anchor = None
        self.drag_free = True
        # None: pick up wherever the real cursor is on the next update.
        self.pos = np.array(current_pos, dtype=np.float64) if current_pos is not None else None
        self.last_set = None

    # ------------------------------------------------------------------
    def _gain(self, speed: float) -> float:
        """Pixels per frame-height of hand motion, as a function of hand speed."""
        base = self.height * 1.6 * self.cfg.speed
        acc = self.cfg.acceleration
        lo, hi = base * (1 - 0.45 * min(acc, 1.5)), base * (1 + 1.6 * acc)
        return lo + (hi - lo) * _smoothstep(speed, 0.06, 0.9)

    def _absolute_target(self, anchor: np.ndarray, aspect: float) -> np.ndarray:
        a = self.cfg.active_area
        cx, cy = 0.5 * aspect, 0.45
        u = (anchor[0] - cx) / (a * aspect) + 0.5
        v = (anchor[1] - cy) / a + 0.5
        u, v = np.clip(u, 0, 1), np.clip(v, 0, 1)
        return np.array([self.left + u * (self.width - 1), self.top + v * (self.height - 1)])

    def update(self, anchor_raw: np.ndarray, t: float, aspect: float, cursor_now: tuple[int, int],
               frozen: bool = False) -> Optional[tuple[int, int]]:
        """anchor_raw: palm center (aspect-corrected frame coords). Returns new cursor or None."""
        anchor = self.filter(anchor_raw[:2], t)
        if self.pos is None or (self.last_set is not None and
                                abs(cursor_now[0] - self.last_set[0]) + abs(cursor_now[1] - self.last_set[1]) > 4):
            # First frame, or the user moved the physical mouse: continue from there.
            self.pos = np.array(cursor_now, dtype=np.float64)
        if self.prev_anchor is None:
            self.prev_anchor = anchor
            if self.cfg.mode == "absolute":
                self.pos = self._absolute_target(anchor, aspect)
            return None
        delta = anchor - self.prev_anchor
        dt = max(t - self.history[-1][0], 1e-3) if self.history else 1 / 30
        self.prev_anchor = anchor

        if frozen or t < self.frozen_until:
            self._remember(t)
            return None

        if self.freeze_anchor is not None and not self.drag_free:
            # Pinch held: stay put until the hand clearly moves, then start dragging.
            moved = np.linalg.norm(anchor - self.freeze_anchor)
            if moved < self.gcfg.drag_threshold:
                self._remember(t)
                return None
            self.drag_free = True

        if self.cfg.mode == "absolute":
            self.pos = self._absolute_target(anchor, aspect)
        else:
            speed = float(np.linalg.norm(delta)) / dt
            self.pos = self.pos + delta * self._gain(speed)
        self.pos[0] = np.clip(self.pos[0], self.left, self.left + self.width - 1)
        self.pos[1] = np.clip(self.pos[1], self.top, self.top + self.height - 1)
        self._remember(t)
        self.last_set = (int(round(self.pos[0])), int(round(self.pos[1])))
        return self.last_set

    def _remember(self, t: float) -> None:
        self.history.append((t, float(self.pos[0]), float(self.pos[1])))

    # ------------------------------------------------------------------
    def on_pinch_start(self, t: float) -> Optional[tuple[int, int]]:
        """Rewind to the position before the fingers started closing and freeze."""
        target = None
        for ht, x, y in reversed(self.history):
            if t - ht >= self.REWIND_S:
                target = (x, y)
                break
        if target is not None:
            self.pos = np.array(target)
        self.freeze_anchor = self.prev_anchor.copy() if self.prev_anchor is not None else None
        self.drag_free = False
        self.frozen_until = t + self.gcfg.click_freeze_ms / 1000.0
        if self.pos is None:
            return None
        self.last_set = (int(round(self.pos[0])), int(round(self.pos[1])))
        return self.last_set

    def on_pinch_end(self, t: float) -> None:
        self.freeze_anchor = None
        self.drag_free = True
        self.frozen_until = t + self.RELEASE_FREEZE_S


class PointerMapper:
    """Absolute, smoothed mapping of the hand onto an overlay (keyboard, menu) in 0..1 coords."""

    def __init__(self, area: float = 0.55):
        self.area = area
        self.filter = OneEuroFilter(min_cutoff=1.2, beta=1.5)

    def reset(self):
        self.filter.reset()

    def update(self, anchor: np.ndarray, t: float, aspect: float, center=(0.5, 0.5)) -> tuple[float, float]:
        a = self.filter(anchor[:2], t)
        u = (a[0] - center[0] * aspect) / (self.area * aspect) + 0.5
        v = (a[1] - center[1]) / (self.area * 0.8) + 0.5
        return float(np.clip(u, 0, 1)), float(np.clip(v, 0, 1))
