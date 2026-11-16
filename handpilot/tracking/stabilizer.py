"""Makes raw tracker output trustworthy enough to drive a mouse.

Hand trackers occasionally glitch: the skeleton collapses for a frame, jumps
onto the other hand or a face, or jitters at rest. This layer:

* locks onto one *active* hand and follows it (ignores other hands/false hits);
* rejects anatomically implausible frames by comparing metric bone lengths
  (stable for a given person regardless of hand rotation) with a running
  per-user reference, and holds the last good pose for a short time;
* rejects teleports (sudden jumps) unless confirmed by the next frame;
* smooths landmarks with a per-point One Euro filter.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..core import geometry as g
from .base import HandObservation

RIGID_BONES = ((0, 5), (0, 17), (5, 9), (9, 13), (13, 17), (0, 9))
ALL_BONES = RIGID_BONES + tuple(g.BONES)


@dataclass
class TrackedHand:
    norm: np.ndarray          # (21, 3) filtered landmarks, tracker-frame normalized coords
    raw: np.ndarray           # (21, 3) last accepted unfiltered landmarks
    world: Optional[np.ndarray]
    handedness: str
    quality: float            # 0..1, drops while frames are being rejected / held
    held: bool                # True when showing a held pose instead of a fresh one
    timestamp: float


class _PointsOneEuro:
    """One Euro filter with an independent adaptive cutoff per landmark."""

    def __init__(self, min_cutoff: float, beta: float, d_cutoff: float = 1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.x = self.dx = self.t = None

    @staticmethod
    def _a(cutoff, dt):
        return 1.0 / (1.0 + 1.0 / (2 * math.pi * cutoff * dt))

    def __call__(self, x: np.ndarray, t: float) -> np.ndarray:
        if self.x is None:
            self.x, self.dx, self.t = x.copy(), np.zeros_like(x), t
            return x.copy()
        dt = max(t - self.t, 1e-3)
        self.t = t
        a_d = self._a(self.d_cutoff, dt)
        self.dx = a_d * (x - self.x) / dt + (1 - a_d) * self.dx
        speed = np.linalg.norm(self.dx[:, :2], axis=1, keepdims=True)
        a = self._a(self.min_cutoff + self.beta * speed, dt)
        self.x = a * x + (1 - a) * self.x
        return self.x.copy()


class HandStabilizer:
    HOLD_S = 0.20           # how long a rejected frame may be bridged with the last pose
    LOST_S = 0.35           # after this without good frames the hand is reported lost
    REF_ALPHA = 0.03        # bone-length reference adaptation rate
    # MediaPipe's metric "world" skeleton legitimately stretches by ~45% on the palm
    # (p90 over the recorded signing data), so only gross collapses are rejected.
    RIGID_TOLERANCE = 0.85  # max relative deviation of a palm bone
    BONE_TOLERANCE = 0.35   # median relative deviation over all bones
    JUMP_PALMS = 1.6        # palm-center jump (in palm sizes) that needs confirmation

    def __init__(self, smoothing: float = 1.0, preferred_hand: str = "any"):
        self.preferred_hand = preferred_hand
        self.filter = _PointsOneEuro(min_cutoff=smoothing, beta=40.0)
        self.reset()

    def reset(self) -> None:
        self.filter.x = None
        self.last: Optional[TrackedHand] = None
        self.last_good_t = -1e9
        self.bone_ref: Optional[np.ndarray] = None
        self.pending_jump: Optional[np.ndarray] = None
        self.quality = 0.0
        self.active_side: Optional[str] = None

    # ------------------------------------------------------------------
    def _pick(self, hands: list[HandObservation], aspect: float) -> Optional[HandObservation]:
        if not hands:
            return None
        if self.last is not None:
            prev_c = g.palm_center(g.aspect_correct(self.last.raw, aspect))
            prev_s = g.palm_size(g.aspect_correct(self.last.raw, aspect))

            def dist(h):
                return np.linalg.norm(g.palm_center(g.aspect_correct(h.norm, aspect))[:2] - prev_c[:2]) / prev_s
            best = min(hands, key=dist)
            if dist(best) < 3.0:
                return best
        if self.preferred_hand in ("Left", "Right"):
            pref = [h for h in hands if h.handedness == self.preferred_hand]
            if pref:
                hands = pref
        return max(hands, key=lambda h: g.palm_size(g.aspect_correct(h.norm, aspect)))

    def _bones(self, world: np.ndarray) -> np.ndarray:
        return np.array([np.linalg.norm(world[a] - world[b]) for a, b in ALL_BONES])

    def _plausible(self, obs: HandObservation) -> bool:
        if obs.world is None:
            return True
        bones = self._bones(obs.world)
        if self.bone_ref is None:
            self.bone_ref = bones
            return True
        dev = np.abs(bones - self.bone_ref) / np.maximum(self.bone_ref, 1e-4)
        rigid_dev = float(np.max(dev[:len(RIGID_BONES)]))
        ok = rigid_dev < self.RIGID_TOLERANCE and float(np.median(dev)) < self.BONE_TOLERANCE
        if ok:
            self.bone_ref = (1 - self.REF_ALPHA) * self.bone_ref + self.REF_ALPHA * bones
        return ok

    # ------------------------------------------------------------------
    def update(self, hands: list[HandObservation], t: float, aspect: float) -> Optional[TrackedHand]:
        obs = self._pick(hands, aspect)
        accept = False
        if obs is not None:
            accept = self._plausible(obs)
            if accept and self.last is not None and t - self.last_good_t < 0.15:
                p = g.aspect_correct(obs.norm, aspect)
                jump = np.linalg.norm(g.palm_center(p)[:2] - g.palm_center(g.aspect_correct(self.last.raw, aspect))[:2])
                if jump / g.palm_size(p) > self.JUMP_PALMS:
                    # Accept the jump only if the next frame agrees with it.
                    c = g.palm_center(p)
                    if self.pending_jump is None or np.linalg.norm(c[:2] - self.pending_jump[:2]) / g.palm_size(p) > 0.5:
                        self.pending_jump = c
                        accept = False
                    else:
                        self.filter.x = None   # genuine fast move: restart smoothing
            if accept:
                self.pending_jump = None

        if accept:
            if self.last is not None and t - self.last_good_t > self.LOST_S:
                self.filter.x = None
            self.last_good_t = t
            self.quality = min(1.0, self.quality + 0.25)
            filt = self.filter(obs.norm.astype(np.float64), t).astype(np.float32)
            self.last = TrackedHand(norm=filt, raw=obs.norm.copy(), world=obs.world, handedness=obs.handedness,
                                    quality=self.quality, held=False, timestamp=t)
            return self.last

        # No acceptable observation this frame.
        self.quality = max(0.0, self.quality - 0.2)
        if self.last is not None and t - self.last_good_t < self.HOLD_S:
            self.last.held = True
            self.last.quality = self.quality
            return self.last
        if self.last is not None and t - self.last_good_t > self.LOST_S:
            # Forget the bone reference after a long absence – maybe another person.
            if t - self.last_good_t > 5.0:
                self.bone_ref = None
            self.last = None
        return None
