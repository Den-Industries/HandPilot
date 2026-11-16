"""Platform selection for input injection and global hotkeys."""
from __future__ import annotations

import sys


def create_input():
    if sys.platform == "win32":
        from .windows import WindowsInput
        return WindowsInput()
    if sys.platform.startswith("linux"):
        from .linux import create
        return create()
    raise RuntimeError(f"Платформа {sys.platform} пока не поддерживается")


def create_hotkeys(mapping: dict):
    """Returns an object with start()/stop() or None when unsupported."""
    if sys.platform == "win32":
        from .windows import HotkeyListener
        return HotkeyListener(mapping)
    try:  # Linux/X11: optional dependency
        from pynput import keyboard

        def fmt(combo):
            return "+".join(f"<{p}>" if len(p) > 1 else p for p in combo.lower().split("+"))

        class _Pynput:
            def __init__(self):
                self._l = keyboard.GlobalHotKeys({fmt(k): v for k, v in mapping.items()})

            def start(self):
                self._l.start()

            def stop(self):
                self._l.stop()
        return _Pynput()
    except Exception:
        return None


def prepare_process() -> None:
    if sys.platform == "win32":
        from .windows import enable_dpi_awareness
        enable_dpi_awareness()


def set_autostart(enabled: bool) -> bool:
    """Start HandPilot at login. Returns False when unsupported."""
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    launcher = os.path.join(root, "HandPilot.pyw")
    if sys.platform == "win32":
        from .windows import set_autostart as _set
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        _set(enabled, f'"{pyw}" "{launcher}"')
        return True
    if sys.platform.startswith("linux"):
        path = os.path.expanduser("~/.config/autostart/handpilot.desktop")
        if enabled:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write("[Desktop Entry]\nType=Application\nName=HandPilot\n"
                        f'Exec="{sys.executable}" "{launcher}"\n')
        elif os.path.exists(path):
            os.remove(path)
        return True
    return False
