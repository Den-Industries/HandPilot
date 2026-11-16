"""Gesture shortcuts on top of the mouse mode: swipes, media keys and a volume "knob".

All of them hide behind a dedicated static pose, so they never fight the pointer:

    ✌  victory   swipe →/←  Alt+Tab / Alt+Shift+Tab     ↑ overview     ↓ show desktop
    🤟 three     swipe →/←  browser forward / back       ↑ refresh
    🤘 rock      swipe →/←  next / previous track         hold ~0.8 s: play / pause
    🤙 shaka     "take the knob" and tilt the hand right/left: volume up / down

While one of these poses is shown the cursor stays put (the engine freezes it).
Swipe distance is measured in palm sizes, so it does not depend on how far the
hand is from the camera. Image X grows to the user's right (the frame is mirrored).
"""
from __future__ import annotations

import math
import sys
from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..config import GestureSettings

SPECIAL_POSES = ("victory", "three", "rock", "shaka")
WIN = sys.platform == "win32"

Key = tuple[str, tuple[str, ...]]


@dataclass
class ShortcutEvent:
    text: str                   # toast text
    keys: tuple[Key, ...] = ()  # pressed one after another
    repeat: int = 1


_SWIPES: dict[str, dict[str, ShortcutEvent]] = {
    "victory": {
        "right": ShortcutEvent("Alt+Tab ▶", (("tab", ("alt",)),)),
        "left": ShortcutEvent("◀ Alt+Shift+Tab", (("tab", ("alt", "shift")),)),
        "up": ShortcutEvent("Обзор окон", (("tab", ("win",)),) if WIN else (("super", ()),)),
        "down": ShortcutEvent("Рабочий стол", (("d", ("win",)),) if WIN else (("d", ("super",)),)),
    },
    "three": {
        "right": ShortcutEvent("Вперёд ▶", (("right", ("alt",)),)),
        "left": ShortcutEvent("◀ Назад", (("left", ("alt",)),)),
        "up": ShortcutEvent("Обновить страницу", (("f5", ()),)),
    },
    "rock": {
        "right": ShortcutEvent("⏭ Следующий трек", (("next", ()),)),
        "left": ShortcutEvent("⏮ Предыдущий трек", (("prev", ()),)),
    },
}
_PLAY_PAUSE = ShortcutEvent("⏯ Пауза / воспроизведение", (("playpause", ()),))


def _wrap(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


class ShortcutDetector:
    WINDOW_S = 0.5          # a swipe must be completed within this time
    MIN_SWIPE_S = 0.07
    MIN_SPEED = 3.5         # palm sizes per second
    COOLDOWN_S = 0.9        # also swallows the hand returning to its start
    PLAY_HOLD_S = 0.8
    KNOB_ENGAGE_S = 0.25    # shaka must be steady this long before the knob "grabs"
    MAX_STEPS_PER_FRAME = 4

    def __init__(self, cfg: GestureSettings):
        self.cfg = cfg
        self.cooldown_until = 0.0
        self.reset()

    def reset(self) -> None:
        self.pose: Optional[str] = None
        self.pose_since = 0.0
        self.track: deque[tuple[float, float, float]] = deque()
        self.play_fired = False
        self.knob_ref: Optional[float] = None
        self.knob_vec: Optional[np.ndarray] = None
        self.knob_total = 0

    # ------------------------------------------------------------------
    def update(self, pose: str, pts: np.ndarray, palm: float, t: float) -> Optional[ShortcutEvent]:
        """pts: aspect-corrected landmarks (21, 3); palm: palm size in the same units."""
        if pose not in SPECIAL_POSES:
            if self.pose is not None:
                self.reset()
            return None
        if pose != self.pose:
            self.reset()
            self.pose, self.pose_since = pose, t
        if pose == "shaka":
            return self._knob(pts, t)
        ev = self._swipe(pose, pts, palm, t)
        if ev is None and pose == "rock":
            ev = self._play_pause(t)
        return ev

    # ------------------------------------------------------------------
    def _swipe(self, pose: str, pts: np.ndarray, palm: float, t: float) -> Optional[ShortcutEvent]:
        c = pts[[0, 5, 9, 13, 17], :2].mean(axis=0) / max(palm, 1e-6)
        self.track.append((t, float(c[0]), float(c[1])))
        while self.track and t - self.track[0][0] > self.WINDOW_S:
            self.track.popleft()
        if t < self.cooldown_until or len(self.track) < 3:
            return None
        t0, x0, y0 = self.track[0]
        dt = t - t0
        dx, dy = c[0] - x0, c[1] - y0
        dist = math.hypot(dx, dy)
        if dt < self.MIN_SWIPE_S or dist < self.cfg.swipe_distance or dist / dt < self.MIN_SPEED:
            return None
        if abs(dx) >= abs(dy):
            direction, off_axis = ("right" if dx > 0 else "left"), abs(dy)
        else:
            direction, off_axis = ("down" if dy > 0 else "up"), abs(dx)
        if off_axis > 0.5 * dist:                      # diagonal wobble, not a swipe
            return None
        self.track.clear()
        ev = _SWIPES.get(pose, {}).get(direction)
        if ev is not None:
            self.cooldown_until = t + self.COOLDOWN_S
            self.play_fired = True                      # a swipe cancels the play/pause hold
        return ev

    def _play_pause(self, t: float) -> Optional[ShortcutEvent]:
        if self.play_fired or t - self.pose_since < self.PLAY_HOLD_S:
            return None
        if self.track and math.hypot(self.track[-1][1] - self.track[0][1],
                                     self.track[-1][2] - self.track[0][2]) > 0.8:
            return None                                 # hand is moving: not a hold
        self.play_fired = True
        return _PLAY_PAUSE

    def _knob(self, pts: np.ndarray, t: float) -> Optional[ShortcutEvent]:
        # Hand axis (wrist → middle knuckle) as a smoothed unit vector, so the angle never jumps.
        v = pts[9, :2] - pts[0, :2]
        n = float(np.linalg.norm(v))
        if n < 1e-6:
            return None
        v = v / n
        self.knob_vec = v if self.knob_vec is None else 0.5 * v + 0.5 * self.knob_vec
        angle = math.degrees(math.atan2(self.knob_vec[0], -self.knob_vec[1]))   # clockwise = +
        if self.knob_ref is None:
            if t - self.pose_since >= self.KNOB_ENGAGE_S:
                self.knob_ref = angle
            return None
        step = max(self.cfg.knob_step_deg, 3.0)
        steps = int(_wrap(angle - self.knob_ref) / step)
        if steps == 0:
            return None
        steps = max(-self.MAX_STEPS_PER_FRAME, min(self.MAX_STEPS_PER_FRAME, steps))
        self.knob_ref = _wrap(self.knob_ref + steps * step)
        self.knob_total += steps
        key = "volup" if steps > 0 else "voldown"
        arrow = "🔊 +" if steps > 0 else "🔉 −"
        return ShortcutEvent(f"{arrow}  ({self.knob_total:+d})", ((key, ()),), repeat=abs(steps))
