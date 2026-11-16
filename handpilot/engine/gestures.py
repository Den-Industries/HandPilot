"""Turns a stream of hand poses into discrete, debounced gesture events.

Design notes
------------
* Pinches use hysteresis (on < off) on a rotation-invariant ratio
  (thumb–tip distance / palm size), so they neither flicker nor depend on
  how far the hand is from the camera.
* A pinch only counts when the index finger is not tucked into the palm:
  in a fist the thumb rests next to the index and would otherwise "click".
* Static poses (fist, thumbs-up…) must persist for a short time before they
  are reported, and "hold" gestures expose their progress (0..1) so the UI
  can draw a filling ring – the user always sees what is about to happen.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from ..config import GestureSettings
from ..core import geometry as g


@dataclass
class GestureState:
    pose: str = "none"            # debounced static pose
    raw_pose: str = "none"
    pinch: Optional[str] = None   # None | "left" | "right"  (currently held pinch)
    pinch_level: float = 0.0      # 0..1, how close the index pinch is to triggering
    pinch_started: bool = False   # events for this frame
    pinch_ended: bool = False
    hold_progress: float = 0.0    # progress of the menu (thumbs-up) hold
    menu_triggered: bool = False
    features: dict = field(default_factory=dict)


class GestureRecognizer:
    POSE_CONFIRM_FRAMES = 4       # majority window for static poses
    PINCH_MIN_INDEX_CURL = 0.55   # index tip must be this far from its MCP (palm sizes)

    def __init__(self, cfg: GestureSettings):
        self.cfg = cfg
        self.reset()

    def reset(self) -> None:
        self.pinch: Optional[str] = None
        self.poses: deque[str] = deque(maxlen=self.POSE_CONFIRM_FRAMES)
        self.pose = "none"
        self.hold_start: Optional[float] = None
        self.hold_fired = False

    def release(self) -> GestureState:
        """Hand lost: end any active pinch so no mouse button stays pressed."""
        st = GestureState()
        if self.pinch is not None:
            st.pinch_ended = True
        self.reset()
        return st

    def update(self, pts: np.ndarray, t: float, aspect: float) -> GestureState:
        p = g.aspect_correct(pts, aspect)
        f = g.hand_features(p)
        st = GestureState(features=f)

        # ---- static pose with majority vote ---------------------------------
        raw = g.classify_pose(f)
        self.poses.append(raw)
        counts = {k: self.poses.count(k) for k in set(self.poses)}
        best = max(counts, key=counts.get)
        if counts[best] >= (self.POSE_CONFIRM_FRAMES // 2 + 1):
            self.pose = best
        st.raw_pose, st.pose = raw, self.pose

        # ---- pinches ----------------------------------------------------------
        on, off = self.cfg.pinch_on, self.cfg.pinch_off
        pi, pm = f["pinch_index"], f["pinch_middle"]
        index_free = f["index_curl"] > self.PINCH_MIN_INDEX_CURL
        st.pinch_level = float(np.clip((off * 1.6 - pi) / (off * 1.6 - on), 0.0, 1.0)) if index_free else 0.0

        if self.pinch is None:
            if self.pose not in ("fist", "thumbs_up", "thumbs_down", "shaka", "rock", "three"):
                if index_free and pi < on and pi <= pm + 0.05:
                    self.pinch = "left"
                elif (self.cfg.right_click_enabled and pm < on and pi > pm + 0.12
                      and f["bend"][1] < 150):
                    self.pinch = "right"
                st.pinch_started = self.pinch is not None
        else:
            dist = pi if self.pinch == "left" else pm
            if dist > off or (self.pinch == "left" and not index_free and f["index_curl"] < 0.4):
                self.pinch = None
                st.pinch_ended = True
        st.pinch = self.pinch

        # ---- thumbs-up hold → mode menu ----------------------------------------
        if self.pose == "thumbs_up" and self.pinch is None:
            if self.hold_start is None:
                self.hold_start = t
            st.hold_progress = min(1.0, (t - self.hold_start) * 1000.0 / self.cfg.menu_hold_ms)
            if st.hold_progress >= 1.0 and not self.hold_fired:
                self.hold_fired = True
                st.menu_triggered = True
        else:
            self.hold_start = None
            self.hold_fired = False
        return st
