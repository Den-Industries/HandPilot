"""Tiny synthesized UI sounds (no QtMultimedia dependency)."""
from __future__ import annotations

import os
import sys
import tempfile
import wave

import numpy as np

_files: dict[str, str] = {}


def _synth(name: str, freq: float, ms: int, volume: float) -> str:
    rate = 22050
    t = np.arange(int(rate * ms / 1000)) / rate
    env = np.exp(-t * 1000 / (ms * 0.35))
    sig = (np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(4 * np.pi * freq * t)) * env * volume
    path = os.path.join(tempfile.gettempdir(), f"handpilot_{name}.wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((sig * 32767).astype(np.int16).tobytes())
    return path


def play(name: str) -> None:
    """name: 'tick' (key press), 'pop' (mode change), 'click'."""
    try:
        if name not in _files:
            spec = {"tick": (1800, 35, 0.25), "pop": (880, 90, 0.3), "click": (1300, 30, 0.2)}[name]
            _files[name] = _synth(name, *spec)
        if sys.platform == "win32":
            import winsound
            winsound.PlaySound(_files[name], winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        else:
            import shutil
            import subprocess
            player = shutil.which("paplay") or shutil.which("aplay")
            if player:
                subprocess.Popen([player, _files[name]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
