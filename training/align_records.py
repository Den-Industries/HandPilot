"""Recover per-frame labels for the archived recordings.

tools/dataset_manager.py saved each recording as .avi + per-frame landmarks
(.pkl), and the labelled windows as CSV rows — but not which frame each row
came from. The newest frame of every row is an exact copy of the landmarks in
the .pkl, so matching them restores frame-level labels. With these, the raw
videos can be re-processed by any tracker and the whole live pipeline can be
evaluated end to end (see tests/replay_eval.py).

Output: data/records/<record>_labels.json  {"frames": N, "labels": {frame_index: label}}
"""
from __future__ import annotations

import glob
import json
import os
import pickle

import numpy as np
import pandas as pd

from common import CODE_TO_LABEL, DATA_DIR, ROOT

REC_DIR = os.path.join(ROOT, "data", "records")


def pkl_landmarks(path: str) -> np.ndarray:
    with open(path, "rb") as f:
        frames = pickle.load(f)
    out = np.zeros((len(frames), 63), np.float32)
    for i, hands in enumerate(frames):
        if hands:
            out[i] = [v for lm in hands[0].landmark for v in (lm.x, lm.y, lm.z)]
    return out


def main():
    records = sorted(glob.glob(os.path.join(REC_DIR, "*_landmarks.pkl")))
    lms = {os.path.basename(p).replace("_landmarks.pkl", ""): pkl_landmarks(p) for p in records}
    for csv in sorted(glob.glob(os.path.join(DATA_DIR, "*.csv"))):
        df = pd.read_csv(csv)
        last = df.iloc[:, 1 + 5 * 63:].to_numpy(np.float32)
        best = None
        for name, arr in lms.items():
            keyed = {arr[i].tobytes(): i for i in range(len(arr)) if arr[i].any()}
            idx = [keyed.get(row.tobytes()) for row in last]
            hits = sum(i is not None for i in idx)
            if best is None or hits > best[1]:
                best = (name, hits, idx)
        name, hits, idx = best
        print(f"{os.path.basename(csv)} → {name}: matched {hits}/{len(df)} rows")
        if hits < 0.8 * len(df):
            continue
        labels = {int(i): CODE_TO_LABEL[int(c)] for i, c in zip(idx, df["Target"]) if i is not None}
        with open(os.path.join(REC_DIR, f"{name}_labels.json"), "w", encoding="utf-8") as f:
            json.dump({"frames": len(lms[name]), "labels": labels}, f, ensure_ascii=False)


if __name__ == "__main__":
    main()
