"""Train the fingerspelling (Russian dactyl alphabet) classifier.

    .venv-app\\Scripts\\python training\\train_fingerspelling.py            # CV report + export
    .venv-app\\Scripts\\python training\\train_fingerspelling.py --no-cv    # export only

Data: data/datasets/*.csv produced by tools/dataset_manager.py (6-frame windows
of MediaPipe landmarks). Evaluation is leave-one-recording-out, because frames
inside one recording are nearly identical and a random split overstates accuracy.
The exported model is a small MLP stored as .npz and run with plain numpy.
"""
from __future__ import annotations

import argparse
import os
import time

import numpy as np
from sklearn.metrics import accuracy_score, classification_report
from sklearn.neural_network import MLPClassifier

from common import DATA_ASPECT, ROOT, WINDOW, load_windows
from handpilot.core.fingerspell_features import window_features

OUT_PATH = os.path.join(ROOT, "handpilot", "assets", "models", "fingerspell_mlp.npz")
RNG = np.random.default_rng(7)


def augment(win: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Random in-plane rotation, scale, translation, jitter and frame-rate warp."""
    w = win.copy()
    w[..., 0] *= DATA_ASPECT
    w[..., 2] *= DATA_ASPECT
    center = w[-1, 0, :2].copy()
    a = np.radians(RNG.uniform(-15, 15))
    rot = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]], dtype=np.float32)
    s = RNG.uniform(0.75, 1.3)
    w[..., :2] = (w[..., :2] - center) @ rot.T * s + center + RNG.normal(0, 0.03, 2)
    w[..., 2] *= s
    w += RNG.normal(0, 0.004, w.shape).astype(np.float32)
    w[..., 0] /= DATA_ASPECT
    w[..., 2] /= DATA_ASPECT
    # Frame-rate warp: emulate a slower camera by repeating frames.
    if RNG.random() < 0.3:
        idx = np.clip(np.round(np.linspace(0, WINDOW - 1, WINDOW) * RNG.uniform(0.5, 1.0)
                               + (WINDOW - 1) * (1 - RNG.uniform(0.5, 1.0))), 0, WINDOW - 1).astype(int)
        idx = np.maximum.accumulate(idx)
        idx[-1] = WINDOW - 1
        w, valid = w[idx], valid[idx]
    return w, valid


def build(x, valid, n_aug=0):
    feats = [window_features(w, v, DATA_ASPECT) for w, v in zip(x, valid)]
    for _ in range(n_aug):
        for w, v in zip(x, valid):
            wa, va = augment(w, v)
            feats.append(window_features(wa, va, DATA_ASPECT))
    return np.stack(feats)


def make_model():
    return MLPClassifier(hidden_layer_sizes=(256, 128), alpha=3e-3, batch_size=256,
                         learning_rate_init=1e-3, max_iter=200, early_stopping=True,
                         validation_fraction=0.1, n_iter_no_change=12, random_state=0)


def fit(x, y, valid, n_aug):
    feats = build(x, valid, n_aug)
    labels = np.concatenate([y] * (n_aug + 1))
    mean, std = feats.mean(0), feats.std(0) + 1e-6
    model = make_model().fit((feats - mean) / std, labels)
    return model, mean, std


def export(model, mean, std, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    arrays = {f"W{i}": w.astype(np.float32) for i, w in enumerate(model.coefs_)}
    arrays.update({f"b{i}": b.astype(np.float32) for i, b in enumerate(model.intercepts_)})
    np.savez_compressed(path, mean=mean.astype(np.float32), std=std.astype(np.float32),
                        classes=np.array(model.classes_), n_layers=len(model.coefs_), **arrays)
    print(f"Exported {path} ({os.path.getsize(path) / 1024:.0f} KB)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-cv", action="store_true")
    ap.add_argument("--aug", type=int, default=2, help="augmented copies per sample")
    ap.add_argument("--holdout", default="", help="leave this CSV out and export to --out (for replay tests)")
    ap.add_argument("--out", default=OUT_PATH)
    args = ap.parse_args()

    x, y, groups, valid = load_windows(exclude=args.holdout)
    keep = valid[:, -1]
    x, y, groups, valid = x[keep], y[keep], groups[keep], valid[keep]
    print(f"{len(y)} windows, {len(set(y))} classes, {len(set(groups))} recordings")

    if not args.no_cv:
        preds = np.empty_like(y)
        t0 = time.time()
        for g in np.unique(groups):
            tr, te = groups != g, groups == g
            model, mean, std = fit(x[tr], y[tr], valid[tr], args.aug)
            preds[te] = model.predict((build(x[te], valid[te]) - mean) / std)
            print(f"  recording {g}: acc={accuracy_score(y[te], preds[te]):.3f} (n={te.sum()})")
        signs = y != "none"
        print(f"Leave-one-recording-out accuracy: all={accuracy_score(y, preds):.3f} "
              f"signs-only={accuracy_score(y[signs], preds[signs]):.3f}  ({time.time() - t0:.0f}s)")
        print(classification_report(y, preds, zero_division=0))

    model, mean, std = fit(x, y, valid, args.aug)
    export(model, mean, std, args.out)


if __name__ == "__main__":
    main()
