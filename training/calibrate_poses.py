"""Check the rule-based control poses and pinch thresholds against labelled data.

    .venv-app\\Scripts\\python training\\calibrate_poses.py

For every class prints the median geometric features and how often each control
pose fires. Use it after changing thresholds in handpilot/core/geometry.py or
handpilot/engine/gestures.py: "like" should mostly be thumbs_up, "dislike"
thumbs_down, the fist letter "а" must not look like a pinch, etc.
"""
from __future__ import annotations

import collections

import numpy as np

from common import DATA_ASPECT, load_windows
from handpilot.core import geometry as g
from handpilot.engine.gestures import GestureRecognizer


def main():
    x, y, _, valid = load_windows()
    feats = collections.defaultdict(list)
    poses = collections.defaultdict(collections.Counter)
    for p, lab, ok in zip(x[:, -1], y, valid[:, -1]):
        if not ok:
            continue
        f = g.hand_features(g.aspect_correct(p, DATA_ASPECT))
        feats[lab].append([f["pinch_index"], f["pinch_middle"], f["index_curl"], f["thumb_ext"]])
        poses[lab][g.classify_pose(f)] += 1

    print(f"{'class':8s} {'n':>5s}  pinchI pinchM idxCurl thumbExt  poses")
    for lab in sorted(feats):
        m = np.median(np.array(feats[lab]), axis=0)
        top = ", ".join(f"{k}:{v}" for k, v in poses[lab].most_common(3))
        print(f"{lab:8s} {len(feats[lab]):5d}  " + " ".join(f"{v:6.2f}" for v in m) + f"   {top}")

    # Would the fist-like letter "а" trigger a click?
    a = np.array(feats["а"])
    false_pinch = np.mean((a[:, 0] < 0.30) & (a[:, 2] > GestureRecognizer.PINCH_MIN_INDEX_CURL))
    print(f"\n'а' frames that would start a pinch: {false_pinch:.1%}")


if __name__ == "__main__":
    main()
