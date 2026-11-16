"""Dataset loading helpers shared by the training scripts."""
from __future__ import annotations

import glob
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DATA_DIR = os.path.join(ROOT, "data", "datasets")
WINDOW = 6            # frames per sample (oldest first)
DATA_ASPECT = 640 / 480  # all records were captured at 640x480

# Target codes used by tools/dataset_manager.py: cp1251 letter codes,
# ASCII digits, 'L' (like), 'D' (dislike), ' ' (none).
CODE_TO_LABEL = {**{c: bytes([c]).decode("cp1251") for c in range(224, 256)},
                 49: "1", 50: "2", 51: "3", 52: "4", 53: "5",
                 76: "like", 68: "dislike", 32: "none"}


def load_windows(data_dir: str = DATA_DIR, exclude: str = ""):
    """Returns (windows[N, 6, 21, 3], labels[N] (str), groups[N] (file id), valid[N, 6])."""
    xs, ys, gs = [], [], []
    paths = [p for p in sorted(glob.glob(os.path.join(data_dir, "*.csv")))
             if not exclude or os.path.basename(p) != exclude]
    for gi, path in enumerate(paths):
        df = pd.read_csv(path)
        xs.append(df.iloc[:, 1:].to_numpy(np.float32))
        ys.extend(CODE_TO_LABEL[int(c)] for c in df["Target"])
        gs.append(np.full(len(df), gi))
    x = np.concatenate(xs).reshape(-1, WINDOW, 21, 3)
    valid = np.abs(x).sum(axis=(2, 3)) > 0
    return x, np.array(ys), np.concatenate(gs), valid
