"""Synthetic checks for the gesture shortcuts (no camera needed): python tests/test_shortcuts.py"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from handpilot.config import GestureSettings  # noqa: E402
from handpilot.engine.shortcuts import ShortcutDetector  # noqa: E402

PALM = 0.15   # palm size in frame heights


def hand(cx, cy, tilt_deg=0.0):
    """Minimal skeleton: wrist at (cx, cy), knuckles a palm above it, rotated by tilt (clockwise +)."""
    pts = np.zeros((21, 3), np.float32)
    a = math.radians(tilt_deg)
    up = np.array([math.sin(a), -math.cos(a)])
    side = np.array([math.cos(a), math.sin(a)])
    pts[:, 0], pts[:, 1] = cx, cy
    for i, off in ((5, -0.5), (9, -0.15), (13, 0.2), (17, 0.5)):
        p = np.array([cx, cy]) + up * PALM + side * off * PALM
        pts[i, :2] = p
    return pts


def run(pose, path, fps=30, tilt=None):
    det = ShortcutDetector(GestureSettings())
    events = []
    for i, (x, y) in enumerate(path):
        ev = det.update(pose, hand(x, y, tilt(i) if tilt else 0.0), PALM, i / fps)
        if ev:
            events.append((i, ev))
    return events


def line(x0, y0, x1, y1, n):
    return [(x0 + (x1 - x0) * k / (n - 1), y0 + (y1 - y0) * k / (n - 1)) for k in range(n)]


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    return ok


def main():
    results = []
    still = [(0.5, 0.5)] * 10
    # fast swipes: 0.45 frame heights (= 3 palms) in 0.27 s
    for pose, d, (x1, y1), text in [
        ("victory", "right", (0.95, 0.5), "Alt+Tab"), ("victory", "left", (0.05, 0.5), "Alt+Shift+Tab"),
        ("victory", "up", (0.5, 0.05), "Обзор"), ("victory", "down", (0.5, 0.95), "Рабочий"),
        ("three", "left", (0.05, 0.5), "Назад"), ("rock", "right", (0.95, 0.5), "Следующий"),
    ]:
        ev = run(pose, still + line(0.5, 0.5, x1, y1, 9))
        results.append(check(f"{pose} swipe {d} fires exactly once", len(ev) == 1 and text in ev[0][1].text))

    ev = run("victory", still + line(0.5, 0.5, 0.95, 0.5, 9) + line(0.95, 0.5, 0.5, 0.5, 9))
    results.append(check("swipe and the hand coming back = one event (cooldown)", len(ev) == 1))

    ev = run("victory", line(0.2, 0.5, 0.8, 0.5, 90))
    results.append(check("slow drift (3 s across the frame) does not fire", len(ev) == 0))

    ev = run("victory", still + line(0.5, 0.5, 0.8, 0.8, 9))
    results.append(check("diagonal move does not fire", len(ev) == 0))

    ev = run("victory", still + line(0.5, 0.5, 0.58, 0.5, 9))
    results.append(check("small jitter does not fire", len(ev) == 0))

    ev = run("three", still + line(0.5, 0.5, 0.5, 0.95, 9))
    results.append(check("three has no 'down' action", len(ev) == 0))

    # play/pause: hold the rock pose still for 1.2 s
    ev = run("rock", [(0.5, 0.5)] * 36)
    results.append(check("rock held still = play/pause once", len(ev) == 1 and "Пауза" in ev[0][1].text))

    # knob: engage 0.25 s, then tilt +30 deg -> 2 steps up (12 deg per step), then back -30 -> 2 steps down
    tilt = lambda i: 0.0 if i < 12 else (30.0 if i < 30 else 0.0)  # noqa: E731
    ev = run("shaka", [(0.5, 0.5)] * 48, tilt=lambda i: min(30.0, max(0.0, (i - 12) * 6.0)) if i < 40 else 0.0)
    ups = sum(e.repeat for _, e in ev if e.keys[0][0] == "volup")
    downs = sum(e.repeat for _, e in ev if e.keys[0][0] == "voldown")
    results.append(check(f"knob: tilt right ~30deg -> volume up ({ups} steps)", 1 <= ups <= 3))
    results.append(check(f"knob: tilt back -> volume down ({downs} steps)", 1 <= downs <= 3))
    ev = run("shaka", [(0.5, 0.5)] * 40, tilt=lambda i: 3.0 * math.sin(i))   # wobble within +-3 deg
    results.append(check("knob: hand wobble does not change volume", len(ev) == 0))
    ev = run("shaka", [(0.5, 0.5)] * 40, tilt=lambda i: -40.0 if i > 12 else 0.0)
    results.append(check("knob: tilt left -> volume down", any(e.keys[0][0] == "voldown" for _, e in ev)))

    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
