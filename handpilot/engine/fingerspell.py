"""Real-time fingerspelling → text.

Keeps a short landmark history, resamples it to the 30 fps window the model was
trained on, classifies every frame, smooths probabilities and commits a symbol
once it has been shown steadily. A symbol is typed again only after the hand
has left it (another sign or a neutral pose), so holding a letter never spams.

Character deletion: in addition to the normal "dislike" (thumbs-down) commit,
while the hand is held in that pose, a vertical "down→up" nod of the whole
hand emits one extra backspace per nod (tolerating classifier dropouts). This lets the user delete several
characters by rocking the hand instead of repeatedly leaving the gesture.
"""
from __future__ import annotations

import os
from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..config import MODELS_DIR, DactylSettings
from ..core.fingerspell_features import WINDOW, MLPClassifierNP, canonicalize, window_features

MODEL_PATH = os.path.join(MODELS_DIR, "fingerspell_mlp.npz")
FRAME_DT = 1 / 30
COMMANDS = {"like": " ", "dislike": "\b"}   # thumbs up = space, thumbs down = backspace


@dataclass
class DactylState:
    label: str = ""          # current best guess (display form)
    confidence: float = 0.0
    progress: float = 0.0    # 0..1 until the guess is committed
    committed: Optional[str] = None   # text to type this frame ("\b" = backspace)


def display_label(label: str) -> str:
    return {"like": "␣", "dislike": "⌫", "none": ""}.get(label, label.upper())


class FlickDownUp:
    """Detects repeated "down then up" nods of the hand.

    Y convention matches MediaPipe normalized image coordinates: larger Y =
    further down. Distances are in units of hand size (`scale`), so the nod
    feels the same near to and far from the camera. There is no "hold still"
    precondition: the detector follows the hand's trough/peak continuously, so
    nods can follow each other without pause.

    Tunables (fractions of hand size):
        down_frac:  how far down from the last peak the hand must travel
        up_frac:    how far back up from the trough it must come to fire
        cooldown_s: minimum time between two nods
        max_cycle_s: a down-move older than this is forgotten (slow drift)
    """

    def __init__(self, down_frac: float = 0.25, up_frac: float = 0.18,
                 cooldown_s: float = 0.12, max_cycle_s: float = 1.2):
        self.down_frac = down_frac
        self.up_frac = up_frac
        self.cooldown_s = cooldown_s
        self.max_cycle_s = max_cycle_s
        self.reset()

    def reset(self) -> None:
        self._top: Optional[float] = None      # highest point (smallest y) since last nod
        self._bottom: Optional[float] = None   # lowest point reached after going down
        self._bottom_t: float = 0.0
        self._last_fire_t: float = -1e9

    def update(self, y: float, t: float, scale: float) -> bool:
        scale = max(scale, 1e-3)
        if self._top is None:
            self._top = y
            return False
        if self._bottom is None:
            if y < self._top:
                self._top = y
            elif y - self._top >= self.down_frac * scale:
                self._bottom, self._bottom_t = y, t
            return False
        # going down phase done; wait for the way back up
        if y > self._bottom:
            self._bottom, self._bottom_t = y, t
        if t - self._bottom_t > self.max_cycle_s:
            self._top, self._bottom = y, None
            return False
        if self._bottom - y >= self.up_frac * scale:
            fire = (t - self._last_fire_t) >= self.cooldown_s
            if fire:
                self._last_fire_t = t
            self._top, self._bottom = y, None
            return fire
        return False


class Fingerspeller:
    def __init__(self, cfg: DactylSettings):
        self.cfg = cfg
        self.model = MLPClassifierNP(MODEL_PATH) if os.path.exists(MODEL_PATH) else None
        self.flick = FlickDownUp()
        self.reset()

    @property
    def available(self) -> bool:
        return self.model is not None

    def reset(self) -> None:
        self.history: deque[tuple[float, np.ndarray]] = deque(maxlen=24)
        self.probs: Optional[np.ndarray] = None
        self.candidate: Optional[str] = None
        self.candidate_since = 0.0
        self.last_committed: Optional[str] = None
        self.away_since: Optional[float] = None
        self.released = True
        self.nod_last: Optional[float] = None
        self.flick.reset()

    def _window(self, t: float):
        times = np.array([h[0] for h in self.history])
        frames = np.stack([h[1] for h in self.history])
        win = np.empty((WINDOW, 21, 3), np.float32)
        valid = np.ones(WINDOW, bool)
        for i in range(WINDOW):
            target = t - (WINDOW - 1 - i) * FRAME_DT
            j = int(np.argmin(np.abs(times - target)))
            win[i] = frames[j]
            valid[i] = abs(times[j] - target) < 0.1
        valid[-1] = True
        return win, valid

    def update(self, norm_pts: Optional[np.ndarray], handedness: str, mirrored: bool,
               aspect: float, t: float) -> DactylState:
        st = DactylState()
        if self.model is None:
            return st
        if norm_pts is None:
            self.history.clear()
            self._leave(t)
            self.probs = None
            self.candidate = None
            return st
        self.history.append((t, canonicalize(norm_pts, mirrored, handedness)))
        win, valid = self._window(t)
        p = self.model.predict_proba(window_features(win, valid, aspect))[0]
        self.probs = p if self.probs is None else 0.55 * p + 0.45 * self.probs
        k = int(np.argmax(self.probs))
        label, conf = self.model.classes[k], float(self.probs[k])
        st.label, st.confidence = display_label(label), conf

        confident = label != "none" and conf >= self.cfg.min_confidence

        # ---- nod-to-delete -------------------------------------------------------
        # Nod mode starts when thumbs-down has been typed and lasts while the hand
        # stays in view. The classifier often loses the pose mid-motion, so short
        # dropouts (NOD_GRACE_S) neither end the mode nor re-arm a normal commit.
        # Another confident sign ends it at once.
        if confident and label == "dislike":
            if self.last_committed == "dislike":
                self.nod_last = t
        elif confident:
            self.nod_last = None
            self.flick.reset()
        in_nod = self.nod_last is not None and t - self.nod_last < self.NOD_GRACE_S
        if in_nod:
            pts = norm_pts[[0, 5, 9, 13, 17]]
            palm_y = float(np.mean(pts[:, 1]))
            scale = float(np.linalg.norm(norm_pts[0, :2] - norm_pts[9, :2]))
            if self.flick.update(palm_y, t, scale):
                self.nod_last = t   # a nod is itself proof the user is still deleting
                st.committed = ""
                st.progress = 1.0
                return st
            if not confident:
                st.progress = 1.0
                return st
        else:
            self.nod_last = None
            self.flick.reset()

        if not confident:
            self.candidate = None
            self._leave(t)
            return st

        if label != self.candidate:
            self.candidate, self.candidate_since = label, t
        if label == self.last_committed:
            self._back(t)
        else:
            self._leave(t)
        st.progress = min(1.0, (t - self.candidate_since) * 1000 / self.cfg.stable_ms)
        free_to_type = label != self.last_committed or self.released

        if st.progress >= 1.0 and free_to_type:
            self.last_committed = label
            self.released = False
            self.away_since = None
            st.committed = COMMANDS.get(label, label)
            if label == "dislike":
                self.nod_last = t
                self.flick.reset()
        elif not free_to_type:
            st.progress = 1.0
        return st

    NOD_GRACE_S = 0.8   # how long a lost thumbs-down keeps nod mode alive
    RELEASE_S = 0.15   # the hand must leave a sign this long before it can be typed again

    def _leave(self, t: float) -> None:
        """The last typed sign is not shown right now."""
        if self.away_since is None:
            self.away_since = t
        elif t - self.away_since > self.RELEASE_S:
            self.released = True

    def _back(self, t: float) -> None:
        """The last typed sign is shown again; a short flicker does not count as leaving."""
        if self.away_since is not None and t - self.away_since > self.RELEASE_S:
            self.released = True
        self.away_since = None