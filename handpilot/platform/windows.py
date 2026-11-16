"""Windows input injection via SendInput (ctypes, no extra dependencies)."""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x0020, 0x0040
MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x0800, 0x1000
KEYEVENTF_KEYUP, KEYEVENTF_UNICODE, KEYEVENTF_EXTENDEDKEY = 0x0002, 0x0004, 0x0001
WHEEL_DELTA = 120
INJECTED_TAG = 0x48504C54  # "HPLT": lets us recognise our own events if ever needed

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT

VK = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "shift": 0x10, "ctrl": 0x11, "alt": 0x12,
    "esc": 0x1B, "space": 0x20, "pageup": 0x21, "pagedown": 0x22, "end": 0x23, "home": 0x24,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "delete": 0x2E, "win": 0x5B,
    "f5": 0x74, "mute": 0xAD, "voldown": 0xAE, "volup": 0xAF, "next": 0xB0, "prev": 0xB1, "playpause": 0xB3,
}
EXTENDED = {"pageup", "pagedown", "end", "home", "left", "up", "right", "down", "delete", "win", "mute", "voldown", "volup", "next", "prev", "playpause"}

_BUTTON_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


def _send(*inputs: INPUT) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _mouse(flags: int, data: int = 0) -> INPUT:
    inp = INPUT(type=INPUT_MOUSE)
    inp.mi = MOUSEINPUT(0, 0, ctypes.c_ulong(data & 0xFFFFFFFF).value, flags, 0, INJECTED_TAG)
    return inp


def _key(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.ki = KEYBDINPUT(vk, scan, flags, 0, INJECTED_TAG)
    return inp


def enable_dpi_awareness() -> None:
    """Work in physical pixels so cursor coordinates match the screen exactly."""
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass


class WindowsInput:
    def __init__(self):
        self._scroll_acc = [0.0, 0.0]

    def screen_rect(self):
        return (user32.GetSystemMetrics(76), user32.GetSystemMetrics(77),
                user32.GetSystemMetrics(78), user32.GetSystemMetrics(79))

    def primary_rect(self):
        return (0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))

    def cursor_pos(self):
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    def move_to(self, x: int, y: int) -> None:
        user32.SetCursorPos(int(x), int(y))

    def button(self, button: str, down: bool) -> None:
        flags = _BUTTON_FLAGS[button][0 if down else 1]
        _send(_mouse(flags))

    def scroll(self, dx: float, dy: float) -> None:
        self._scroll_acc[0] += dx * WHEEL_DELTA
        self._scroll_acc[1] += dy * WHEEL_DELTA
        events = []
        for axis, flag in ((1, MOUSEEVENTF_WHEEL), (0, MOUSEEVENTF_HWHEEL)):
            amount = int(self._scroll_acc[axis])
            if amount:
                self._scroll_acc[axis] -= amount
                events.append(_mouse(flag, amount))
        if events:
            _send(*events)

    def type_text(self, text: str) -> None:
        events = []
        for ch in text:
            if ch == "\n":
                events += [_key(VK["enter"]), _key(VK["enter"], flags=KEYEVENTF_KEYUP)]
                continue
            data = ch.encode("utf-16-le")
            for i in range(0, len(data), 2):     # surrogate pairs for emoji etc.
                code = int.from_bytes(data[i:i + 2], "little")
                events += [_key(scan=code, flags=KEYEVENTF_UNICODE),
                           _key(scan=code, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]
        if events:
            _send(*events)

    def key(self, name: str, modifiers: tuple[str, ...] = ()) -> None:
        vk = VK.get(name) or (ord(name.upper()) if len(name) == 1 else None)
        if vk is None:
            return
        ext = KEYEVENTF_EXTENDEDKEY if name in EXTENDED else 0
        events = [_key(VK[m]) for m in modifiers]
        events += [_key(vk, flags=ext), _key(vk, flags=ext | KEYEVENTF_KEYUP)]
        events += [_key(VK[m], flags=KEYEVENTF_KEYUP) for m in reversed(modifiers)]
        _send(*events)


# ---------------------------------------------------------------------------
# Global hotkeys (RegisterHotKey on a dedicated message-loop thread)
# ---------------------------------------------------------------------------
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
_MODS = {"ctrl": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT, "win": MOD_WIN}


class HotkeyListener:
    """hotkeys: {"ctrl+alt+h": callback}. Callbacks run on the listener thread."""

    def __init__(self, hotkeys: dict):
        self._hotkeys = hotkeys
        self._thread_id = None
        self._thread = threading.Thread(target=self._run, name="hotkeys", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        kernel32 = ctypes.WinDLL("kernel32")
        self._thread_id = kernel32.GetCurrentThreadId()
        callbacks = {}
        for i, (combo, cb) in enumerate(self._hotkeys.items(), start=1):
            *mods, key = combo.lower().split("+")
            mod = MOD_NOREPEAT
            for m in mods:
                mod |= _MODS[m]
            vk = VK.get(key) or ord(key.upper())
            if user32.RegisterHotKey(None, i, mod, vk):
                callbacks[i] = cb
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in callbacks:
                try:
                    callbacks[msg.wParam]()
                except Exception:  # never let a callback kill the hotkey thread
                    pass
        for i in callbacks:
            user32.UnregisterHotKey(None, i)

    def stop(self) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)


# ---------------------------------------------------------------------------
# Autostart (HKCU Run key – per user, no admin rights needed)
# ---------------------------------------------------------------------------
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def set_autostart(enabled: bool, command: str, name: str = "HandPilot") -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass
