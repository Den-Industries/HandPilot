"""End-to-end replay of recorded videos through the live pipeline.

    .venv-app\\Scripts\\python tests\\replay_eval.py [record_name ...] [--model path.npz]

Frames are mirrored like the live app (selfie view), so this also checks that
handedness canonicalization, resampling and features match training. Reports
tracking stability, frame-level fingerspelling accuracy against the recovered
labels (training/align_records.py), and the character error rate of the text
the speller would have typed versus the shown sign sequence.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from handpilot.config import Settings  # noqa: E402
from handpilot.engine import fingerspell  # noqa: E402
from handpilot.engine.fingerspell import Fingerspeller  # noqa: E402
from handpilot.engine.gestures import GestureRecognizer  # noqa: E402
from handpilot.tracking.mediapipe_tracker import MediaPipeTracker  # noqa: E402
from handpilot.tracking.stabilizer import HandStabilizer  # noqa: E402

REC_DIR = os.path.join(ROOT, "data", "records")


def edit_distance(a: list, b: list) -> int:
    d = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(b) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (a[i - 1] != b[j - 1]))
            prev = cur
    return d[-1]


def gt_sequence(labels: dict[int, str], n: int) -> list[str]:
    seq, last, gap = [], None, 0
    for i in range(n):
        lab = labels.get(i)
        if lab is None or lab == "none":
            gap += 1
            if gap > 3:
                last = None
            continue
        gap = 0
        if lab != last:
            seq.append(lab)
            last = lab
    return seq


def to_symbol(label: str) -> str:
    return fingerspell.COMMANDS.get(label, label)


def replay(name: str, s: Settings) -> dict:
    with open(os.path.join(REC_DIR, f"{name}_labels.json"), encoding="utf-8") as f:
        meta = json.load(f)
    labels = {int(k): v for k, v in meta["labels"].items()}
    cap = cv2.VideoCapture(os.path.join(REC_DIR, f"{name}.avi"))
    tracker = MediaPipeTracker(s.tracking)
    stab = HandStabilizer(s.tracking.landmark_smoothing)
    gest = GestureRecognizer(s.gestures)
    speller = Fingerspeller(s.dactyl)
    inv = {v: k for k, v in fingerspell.COMMANDS.items()}
    stats = dict(frames=0, tracked=0, held=0, pinches=0, menus=0, correct=0, scored=0)
    typed: list[str] = []
    t0 = time.perf_counter()
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = i / 30.0
        frame = cv2.flip(frame, 1)
        aspect = frame.shape[1] / frame.shape[0]
        hands = tracker.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), int(t * 1000))
        th = stab.update(hands, t, aspect)
        stats["frames"] += 1
        if th is not None:
            stats["tracked"] += 1
            stats["held"] += th.held
            gs = gest.update(th.norm, t, aspect)
            stats["pinches"] += gs.pinch_started
            stats["menus"] += gs.menu_triggered
            ds = speller.update(th.raw, th.handedness, True, aspect, t)
        else:
            gest.release()
            ds = speller.update(None, "", True, aspect, t)
        if ds.committed:
            typed.append(inv.get(ds.committed, ds.committed))
        gt = labels.get(i)
        if gt is not None and gt != "none" and th is not None:
            k = int(np.argmax(speller.probs)) if speller.probs is not None else -1
            pred = speller.model.classes[k] if k >= 0 else "none"
            stats["scored"] += 1
            stats["correct"] += pred == gt
        i += 1
    tracker.close()
    seq = gt_sequence(labels, i)
    stats["cer"] = edit_distance(typed, seq) / max(len(seq), 1)
    stats["fps"] = stats["frames"] / (time.perf_counter() - t0)
    stats["typed"] = "".join(to_symbol(x) for x in typed)
    stats["expected"] = "".join(to_symbol(x) for x in seq)
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("records", nargs="*")
    ap.add_argument("--model", default="")
    args = ap.parse_args()
    if args.model:
        fingerspell.MODEL_PATH = args.model
    names = args.records or sorted(os.path.basename(p)[:-12] for p in glob.glob(os.path.join(REC_DIR, "*_labels.json")))
    s = Settings()
    for name in names:
        st = replay(name, s)
        print(f"{name}: tracked {st['tracked'] / st['frames']:.1%} (held {st['held']}), "
              f"frame acc {st['correct'] / max(st['scored'], 1):.1%}, CER {st['cer']:.1%}, "
              f"pinch events {st['pinches']}, menu triggers {st['menus']}, {st['fps']:.0f} fps")
        print(f"   expected: {st['expected'][:120]}")
        print(f"   typed:    {st['typed'][:120]}")


if __name__ == "__main__":
    main()
