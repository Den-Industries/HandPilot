"""Linux input injection (X11 via python-xlib XTest; Wayland via ydotool).

It covers the same interface as the Windows backend. On X11 it needs `xdotool`
for typing and key presses. On Wayland, cursor control requires `ydotool`
(with `ydotoold` running) because Wayland forbids synthetic input from
regular clients.
"""
from __future__ import annotations

import os
import shutil
import subprocess


class XlibInput:
    def __init__(self):
        from Xlib import X, XK, display
        from Xlib.ext import xtest
        self._X, self._XK, self._xtest = X, XK, xtest
        self._d = display.Display()
        self._root = self._d.screen().root
        self._scroll_acc = [0.0, 0.0]

    def screen_rect(self):
        s = self._d.screen()
        return 0, 0, s.width_in_pixels, s.height_in_pixels

    primary_rect = screen_rect

    def cursor_pos(self):
        p = self._root.query_pointer()
        return p.root_x, p.root_y

    def move_to(self, x, y):
        self._xtest.fake_input(self._d, self._X.MotionNotify, x=int(x), y=int(y))
        self._d.sync()

    def button(self, button, down):
        code = {"left": 1, "middle": 2, "right": 3}[button]
        self._xtest.fake_input(self._d, self._X.ButtonPress if down else self._X.ButtonRelease, code)
        self._d.sync()

    def scroll(self, dx, dy):
        self._scroll_acc[0] += dx
        self._scroll_acc[1] += dy
        for axis, (pos, neg) in ((1, (4, 5)), (0, (7, 6))):
            while abs(self._scroll_acc[axis]) >= 1:
                step = 1 if self._scroll_acc[axis] > 0 else -1
                self._scroll_acc[axis] -= step
                btn = pos if step > 0 else neg
                self._xtest.fake_input(self._d, self._X.ButtonPress, btn)
                self._xtest.fake_input(self._d, self._X.ButtonRelease, btn)
        self._d.sync()

    def type_text(self, text):
        # xdotool handles keymap juggling for arbitrary Unicode; fall back to it.
        if shutil.which("xdotool"):
            subprocess.run(["xdotool", "type", "--clearmodifiers", "--delay", "0", "--", text], check=False)

    def key(self, name, modifiers=()):
        names = {"enter": "Return", "backspace": "BackSpace", "esc": "Escape", "tab": "Tab",
                 "left": "Left", "right": "Right", "up": "Up", "down": "Down", "home": "Home",
                 "end": "End", "delete": "Delete", "pageup": "Prior", "pagedown": "Next", "space": "space",
                 "f5": "F5", "super": "super", "win": "super", "volup": "XF86AudioRaiseVolume",
                 "voldown": "XF86AudioLowerVolume", "mute": "XF86AudioMute", "next": "XF86AudioNext",
                 "prev": "XF86AudioPrev", "playpause": "XF86AudioPlay"}
        combo = "+".join([*("super" if m == "win" else m for m in modifiers), names.get(name, name)])
        if shutil.which("xdotool"):
            subprocess.run(["xdotool", "key", "--clearmodifiers", combo], check=False)


class YdotoolInput(XlibInput):
    """Wayland: absolute moves are emulated by ydotool."""

    def __init__(self):  # noqa: D401 – no X connection on Wayland
        self._scroll_acc = [0.0, 0.0]
        self._pos = (0, 0)

    def screen_rect(self):
        if "HANDPILOT_SCREEN_W" in os.environ:
            return 0, 0, int(os.environ["HANDPILOT_SCREEN_W"]), int(os.environ.get("HANDPILOT_SCREEN_H", 1080))
        try:   # XWayland reports the logical desktop size
            from Xlib import display
            sc = display.Display().screen()
            return 0, 0, sc.width_in_pixels, sc.height_in_pixels
        except Exception:
            return 0, 0, 1920, 1080

    primary_rect = screen_rect

    def cursor_pos(self):
        return self._pos

    def move_to(self, x, y):
        self._pos = (int(x), int(y))
        subprocess.run(["ydotool", "mousemove", "--absolute", "-x", str(int(x)), "-y", str(int(y))], check=False)

    def button(self, button, down):
        # ydotool click codes: bit 0x40 = press, 0x80 = release, low bits = button index.
        code = (0x40 if down else 0x80) | {"left": 0, "right": 1, "middle": 2}[button]
        subprocess.run(["ydotool", "click", f"0x{code:02X}"], check=False)

    def scroll(self, dx, dy):
        self._scroll_acc[1] += dy
        steps = int(self._scroll_acc[1])
        if steps:
            self._scroll_acc[1] -= steps
            subprocess.run(["ydotool", "mousemove", "--wheel", "-x", "0", "-y", str(steps)], check=False)

    def type_text(self, text):
        subprocess.run(["ydotool", "type", "--", text], check=False)

    # Linux evdev keycodes (input-event-codes.h) for `ydotool key`.
    _CODES = {"esc": 1, "backspace": 14, "tab": 15, "enter": 28, "space": 57, "home": 102, "up": 103,
              "pageup": 104, "left": 105, "right": 106, "end": 107, "down": 108, "pagedown": 109,
              "delete": 111, "ctrl": 29, "shift": 42, "alt": 56, "win": 125, "super": 125, "f5": 63,
              "mute": 113, "voldown": 114, "volup": 115, "next": 163, "playpause": 164, "prev": 165}
    _LETTERS = dict(zip("qwertyuiop", range(16, 26))) | dict(zip("asdfghjkl", range(30, 39)))         | dict(zip("zxcvbnm", range(44, 51)))

    def key(self, name, modifiers=()):
        code = self._CODES.get(name) or (self._LETTERS.get(name.lower()) if len(name) == 1 else None)
        if code is None:
            return
        mods = [self._CODES[m] for m in modifiers if m in self._CODES]
        seq = [f"{c}:1" for c in mods] + [f"{code}:1", f"{code}:0"] + [f"{c}:0" for c in reversed(mods)]
        subprocess.run(["ydotool", "key", *seq], check=False)


def _ydotool_usable() -> bool:
    """ydotool 1.x (with ydotoold and a writable /dev/uinput). The 0.1.x package from the
    Ubuntu archive uses a different CLI and needs root, so it does not count."""
    return bool(shutil.which("ydotool") and shutil.which("ydotoold") and os.access("/dev/uinput", os.W_OK))


def create():
    import logging
    wayland = bool(os.environ.get("WAYLAND_DISPLAY")) or os.environ.get("XDG_SESSION_TYPE") == "wayland"
    if wayland and _ydotool_usable():
        return YdotoolInput()
    if wayland:
        logging.getLogger(__name__).warning(
            "Wayland session: the cursor and typing only reach XWayland windows (no usable "
            "ydotool 1.x). Log in with 'Ubuntu on Xorg' (recommended).")
    return XlibInput()
