"""Hand geometry shared by runtime and training.

All functions take a (21, 3) array of *aspect-corrected* landmarks:
    X = x * aspect, Y = y, Z = z * aspect      (aspect = frame width / height)
where x, y, z are MediaPipe-style normalized image landmarks. This keeps the
skeleton undistorted so that distances and angles are meaningful.

Landmark indices follow the MediaPipe / COCO-WholeBody hand layout.
"""
from __future__ import annotations

import numpy as np

WRIST = 0
THUMB = (1, 2, 3, 4)
INDEX = (5, 6, 7, 8)
MIDDLE = (9, 10, 11, 12)
RING = (13, 14, 15, 16)
PINKY = (17, 18, 19, 20)
FINGERS = (INDEX, MIDDLE, RING, PINKY)
TIPS = (4, 8, 12, 16, 20)

HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
)
BONES = tuple((a, b) for a, b in HAND_CONNECTIONS)
PALM_POINTS = (0, 5, 9, 13, 17)


def aspect_correct(norm: np.ndarray, aspect: float) -> np.ndarray:
    pts = np.asarray(norm, dtype=np.float32).copy()
    pts[:, 0] *= aspect
    if pts.shape[1] > 2:
        pts[:, 2] *= aspect
    return pts


def palm_size(p: np.ndarray) -> float:
    """Robust hand scale: mean of the palm triangle sides plus wrist→middle MCP."""
    d = (np.linalg.norm(p[0] - p[5]) + np.linalg.norm(p[0] - p[17])
         + np.linalg.norm(p[5] - p[17]) + np.linalg.norm(p[0] - p[9]))
    return float(max(d / 4.0, 1e-6))


def palm_center(p: np.ndarray) -> np.ndarray:
    """Point that barely moves when fingers pinch or curl: used as the cursor anchor."""
    return p[[0, 5, 9, 13, 17]].mean(axis=0)


def _bend(p: np.ndarray, a: int, b: int, c: int) -> float:
    v1 = p[b] - p[a]
    v2 = p[c] - p[b]
    n = np.linalg.norm(v1) * np.linalg.norm(v2)
    if n < 1e-9:
        return 0.0
    return float(np.degrees(np.arccos(np.clip(np.dot(v1, v2) / n, -1.0, 1.0))))


def finger_bend(p: np.ndarray, finger: tuple[int, int, int, int]) -> float:
    """Total bend of a finger in degrees: ~0 straight, ~200+ fully curled."""
    mcp, pip, dip, tip = finger
    base = WRIST
    return (_bend(p, base, mcp, pip) + _bend(p, mcp, pip, dip) + _bend(p, pip, dip, tip))


def finger_reach(p: np.ndarray, finger: tuple[int, int, int, int]) -> float:
    """Tip distance from wrist relative to PIP distance (>1.2 extended, <1 curled)."""
    mcp, pip, _, tip = finger
    return float(np.linalg.norm(p[tip] - p[WRIST]) / max(np.linalg.norm(p[pip] - p[WRIST]), 1e-6))


def thumb_extension(p: np.ndarray) -> float:
    """Thumb tip distance from the index MCP relative to palm size."""
    return float(np.linalg.norm(p[4] - p[5]) / palm_size(p))


def pinch_ratio(p: np.ndarray, tip: int) -> float:
    """Distance from thumb tip to another finger tip, in palm sizes."""
    return float(np.linalg.norm(p[4] - p[tip]) / palm_size(p))


def index_curl_ratio(p: np.ndarray) -> float:
    """Index tip distance from index MCP in palm sizes (small = tucked into fist)."""
    return float(np.linalg.norm(p[8] - p[5]) / palm_size(p))


def thumb_direction(p: np.ndarray) -> np.ndarray:
    """Unit 2D vector of the thumb (MCP→tip) in image space (y grows downward)."""
    v = p[4, :2] - p[2, :2]
    return v / max(np.linalg.norm(v), 1e-6)


def hand_features(p: np.ndarray) -> dict:
    s = palm_size(p)
    bends = [finger_bend(p, f) for f in FINGERS]
    reach = [finger_reach(p, f) for f in FINGERS]
    return {
        "palm": s,
        "bend": bends,
        "reach": reach,
        "thumb_ext": thumb_extension(p),
        "thumb_bend": _bend(p, 1, 2, 3) + _bend(p, 2, 3, 4),
        "thumb_dir": thumb_direction(p),
        "pinch_index": pinch_ratio(p, 8),
        "pinch_middle": pinch_ratio(p, 12),
        "pinch_ring": pinch_ratio(p, 16),
        "index_curl": index_curl_ratio(p),
        "spread_im": float(np.linalg.norm(p[8] - p[12]) / s),
    }


# ---------------------------------------------------------------------------
# Static control poses. Thresholds are calibrated on the labelled dataset
# (see training/calibrate_poses.py); keep them in sync with that report.
# ---------------------------------------------------------------------------
EXTENDED_BEND = 70.0     # finger counts as straight below this total bend
CURLED_BEND = 150.0      # and as curled above this
EXTENDED_REACH = 1.25
CURLED_REACH = 1.05


def finger_states(f: dict) -> list[int]:
    """Per finger (index..pinky): 1 extended, -1 curled, 0 undecided."""
    out = []
    for bend, reach in zip(f["bend"], f["reach"]):
        if bend < EXTENDED_BEND and reach > EXTENDED_REACH:
            out.append(1)
        elif bend > CURLED_BEND or reach < CURLED_REACH:
            out.append(-1)
        else:
            out.append(0)
    return out


POSES = ("open", "fist", "victory", "thumbs_up", "thumbs_down", "point", "shaka", "rock", "three", "none")


def classify_pose(f: dict) -> str:
    st = finger_states(f)
    thumb_out = f["thumb_ext"] > 0.7 and f["thumb_bend"] < 60
    if all(s == 1 for s in st):
        return "open"
    if all(s == -1 for s in st):
        dy = f["thumb_dir"][1]
        if thumb_out and dy < -0.75:
            return "thumbs_up"
        if thumb_out and dy > 0.75:
            return "thumbs_down"
        if not thumb_out:
            return "fist"
        return "none"
    if st == [1, 1, -1, -1] and f["spread_im"] > 0.45:
        return "victory"
    if st == [1, -1, -1, -1]:
        return "point"
    if st == [-1, -1, -1, 1] and f["thumb_ext"] > 0.7:
        return "shaka"          # thumb + pinky out
    if st == [1, -1, -1, 1]:
        return "rock"           # index + pinky out
    if st == [1, 1, 1, -1]:
        return "three"          # index, middle, ring out
    return "none"
