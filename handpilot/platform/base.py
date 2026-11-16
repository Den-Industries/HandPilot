"""OS input injection interface. One implementation per platform."""
from __future__ import annotations

from typing import Protocol


class InputBackend(Protocol):
    def screen_rect(self) -> tuple[int, int, int, int]:
        """Virtual desktop (left, top, width, height) in physical pixels."""

    def primary_rect(self) -> tuple[int, int, int, int]:
        ...

    def cursor_pos(self) -> tuple[int, int]:
        ...

    def move_to(self, x: int, y: int) -> None:
        ...

    def button(self, button: str, down: bool) -> None:
        """button: 'left' | 'right' | 'middle'."""

    def scroll(self, dx: float, dy: float) -> None:
        """Wheel notches (1.0 = one notch); fractional values are accumulated."""

    def type_text(self, text: str) -> None:
        ...

    def key(self, name: str, modifiers: tuple[str, ...] = ()) -> None:
        """name: 'enter' | 'backspace' | 'tab' | 'esc' | 'left' | 'right' | 'up' | 'down' |
        'home' | 'end' | 'delete' | single letter for shortcuts (with modifiers)."""


class DryRunInput:
    """Wraps a real backend: reads (screen, cursor) pass through, nothing is injected."""

    def __init__(self, real):
        self._real = real
        self._pos = None

    def screen_rect(self):
        return self._real.screen_rect()

    def primary_rect(self):
        return self._real.primary_rect()

    def cursor_pos(self):
        return self._pos or self._real.cursor_pos()

    def move_to(self, x, y):
        self._pos = (int(x), int(y))

    def button(self, button, down):
        pass

    def scroll(self, dx, dy):
        pass

    def type_text(self, text):
        pass

    def key(self, name, modifiers=()):
        pass
