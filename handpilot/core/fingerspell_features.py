"""Feature extraction for the fingerspelling (dactyl) classifier.

Input is a window of WINDOW frames of *canonical* landmarks: normalized image
coordinates (x, y, z) as produced by MediaPipe on an un-mirrored frame of a
LEFT hand (that is how the training data was recorded). The runtime converts
any hand into this canonical form before calling `window_features`.
"""
from __future__ import annotations

import numpy as np

from . import geometry as g

WINDOW = 6
TRAJ_POINTS = (0, 4, 8, 12, 20)  # wrist + fingertips used for motion features


def _normalize(frame: np.ndarray, aspect: float) -> tuple[np.ndarray, float]:
    p = g.aspect_correct(frame, aspect)
    s = g.palm_size(p)
    return (p - p[0]) / s, s


def window_features(window: np.ndarray, valid: np.ndarray, aspect: float) -> np.ndarray:
    """window: (WINDOW, 21, 3) oldest→newest; valid: (WINDOW,) bool. Newest must be valid."""
    frames = window.copy()
    # Fill missing frames with the nearest later valid frame (newest is valid).
    for i in range(WINDOW - 2, -1, -1):
        if not valid[i]:
            frames[i] = frames[i + 1]
    cur = g.aspect_correct(frames[-1], aspect)
    scale = g.palm_size(cur)

    shapes = []
    for fr in frames:
        shape, _ = _normalize(fr, aspect)
        shapes.append(shape.reshape(-1))
    shapes = np.concatenate(shapes)

    abs_pts = np.stack([g.aspect_correct(fr, aspect)[list(TRAJ_POINTS), :2] for fr in frames])
    traj = ((abs_pts[:-1] - abs_pts[-1]) / scale).reshape(-1)

    f = g.hand_features(cur)
    eng = np.array([*np.array(f["bend"]) / 180.0, *f["reach"], f["thumb_ext"], f["thumb_bend"] / 180.0,
                    *f["thumb_dir"], f["pinch_index"], f["pinch_middle"], f["pinch_ring"],
                    f["index_curl"], f["spread_im"]], dtype=np.float32)
    return np.concatenate([shapes, traj, eng]).astype(np.float32)


def canonicalize(norm_pts: np.ndarray, mirrored_input: bool, handedness: str) -> np.ndarray:
    """Convert landmarks from the runtime frame into the canonical training form.

    norm_pts:      (21, 3) normalized landmarks from the frame given to the tracker.
    mirrored_input: True if that frame was flipped horizontally (selfie view).
    handedness:    'Left' / 'Right' as reported for the frame (true user hand when mirrored).
    """
    p = np.asarray(norm_pts, dtype=np.float32).copy()
    raw_left = (handedness == "Left") if mirrored_input else (handedness == "Right")
    # Raw (un-mirrored) coordinates of the hand:
    if mirrored_input:
        p[:, 0] = 1.0 - p[:, 0]
    # A right hand in the raw frame looks like a mirrored left hand.
    if not raw_left:
        p[:, 0] = 1.0 - p[:, 0]
    return p


class MLPClassifierNP:
    """Dependency-free inference for the exported MLP (see training/train_fingerspelling.py)."""

    def __init__(self, path: str):
        d = np.load(path, allow_pickle=False)
        self.mean = d["mean"]
        self.std = d["std"]
        self.classes = [str(c) for c in d["classes"]]
        n = int(d["n_layers"])
        self.weights = [d[f"W{i}"] for i in range(n)]
        self.biases = [d[f"b{i}"] for i in range(n)]

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        h = (np.atleast_2d(x) - self.mean) / self.std
        for i, (w, b) in enumerate(zip(self.weights, self.biases)):
            h = h @ w + b
            if i < len(self.weights) - 1:
                h = np.maximum(h, 0.0)
        h = h - h.max(axis=1, keepdims=True)
        e = np.exp(h)
        return e / e.sum(axis=1, keepdims=True)
