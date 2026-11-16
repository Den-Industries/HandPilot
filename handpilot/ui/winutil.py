"""Overlay window helpers: topmost, never steals focus, optionally click-through."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

OVERLAY_FLAGS = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)


def make_overlay(w: QWidget, click_through: bool) -> None:
    flags = OVERLAY_FLAGS
    if click_through:
        flags |= Qt.WindowType.WindowTransparentForInput
    w.setWindowFlags(flags)
    w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    w.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    w.setFocusPolicy(Qt.FocusPolicy.NoFocus)


def apply_no_activate(w: QWidget) -> None:
    """Windows: clicks on the overlay must not take focus from the app being typed into."""
    if sys.platform != "win32":
        return
    import ctypes
    GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOPMOST, WS_EX_TOOLWINDOW = -20, 0x08000000, 0x00000008, 0x00000080
    user32 = ctypes.windll.user32
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t)
    hwnd = int(w.winId())
    style = user32.GetWindowLongPtrW(ctypes.c_void_p(hwnd), GWL_EXSTYLE)
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOPMOST | WS_EX_TOOLWINDOW)
