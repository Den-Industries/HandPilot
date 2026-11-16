"""Radial mode menu, opened by holding a thumbs-up.

Point at a sector with the hand and pinch to choose; pinch in the middle (or
hold the thumbs-up again) to cancel. The real mouse works too.
"""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from . import sound, theme
from .winutil import apply_no_activate, make_overlay

ITEMS = ("mouse", "keyboard", "dactyl", "paused")   # top, right, bottom, left


class ModeMenu(QWidget):
    chosen = Signal(str)
    cancelled = Signal()
    SIZE = 440

    def __init__(self):
        super().__init__()
        make_overlay(self, click_through=False)
        self.resize(self.SIZE, self.SIZE)
        self.current = "mouse"
        self.pointer: Optional[QPointF] = None
        self.pinch_level = 0.0
        self.hover: Optional[str] = None

    def open(self, current_mode: str) -> None:
        self.current = current_mode
        self.pointer, self.hover = None, None
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - self.SIZE // 2, screen.center().y() - self.SIZE // 2)
        self.show()
        apply_no_activate(self)
        sound.play("pop")

    def _item_at(self, pt: QPointF) -> Optional[str]:
        c = QPointF(self.SIZE / 2, self.SIZE / 2)
        d = pt - c
        r = math.hypot(d.x(), d.y())
        if r < 70:
            return None                 # center = cancel
        ang = (math.degrees(math.atan2(d.y(), d.x())) + 90 + 45) % 360   # 0 = top sector
        return ITEMS[int(ang // 90)]

    def set_pointer(self, uv, pinch_level: float, pinch_started: bool) -> None:
        if uv is None:
            self.pointer = None
            self.update()
            return
        # Map the central part of the hand range onto the menu so selection needs little motion.
        u, v = (uv[0] - 0.5) * 1.6 + 0.5, (uv[1] - 0.5) * 1.6 + 0.5
        self.pointer = QPointF(min(max(u, 0), 1) * self.SIZE, min(max(v, 0), 1) * self.SIZE)
        self.pinch_level = pinch_level
        self.hover = self._item_at(self.pointer)
        if pinch_started:
            self._choose(self.hover)
        self.update()

    def mousePressEvent(self, e):
        self._choose(self._item_at(e.position()))

    def _choose(self, item: Optional[str]) -> None:
        if item is None:
            self.cancelled.emit()
        else:
            self.chosen.emit(item)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        S = self.SIZE
        c = QPointF(S / 2, S / 2)
        outer, inner = S / 2 - 6, 70
        for i, item in enumerate(ITEMS):
            start = 90 + 45 - i * 90      # Qt angles: counter-clockwise from 3 o'clock
            path = QPainterPath()
            path.arcMoveTo(QRectF(c.x() - outer, c.y() - outer, 2 * outer, 2 * outer), start)
            path.arcTo(QRectF(c.x() - outer, c.y() - outer, 2 * outer, 2 * outer), start, -88)
            path.arcTo(QRectF(c.x() - inner, c.y() - inner, 2 * inner, 2 * inner), start - 88, 88)
            path.closeSubpath()
            color = theme.MODE_COLORS[item]
            hovered = item == self.hover and self.pointer is not None
            p.setPen(QPen(theme.with_alpha(color, 230), 2.5) if (hovered or item == self.current)
                     else QPen(theme.BORDER, 1))
            p.setBrush(theme.with_alpha(color.darker(230), 245) if hovered else theme.with_alpha(theme.BG, 235))
            p.drawPath(path)
            mid = math.radians(-(start - 44))
            lr = (outer + inner) / 2
            lc = QPointF(c.x() + lr * math.cos(mid), c.y() + lr * math.sin(mid))
            p.setPen(theme.TEXT)
            p.setFont(theme.font(22))
            p.drawText(QRectF(lc.x() - 60, lc.y() - 34, 120, 36), Qt.AlignmentFlag.AlignCenter, theme.MODE_ICONS[item])
            p.setFont(theme.font(11, QFont.Weight.DemiBold))
            p.drawText(QRectF(lc.x() - 70, lc.y() + 2, 140, 26), Qt.AlignmentFlag.AlignCenter, theme.MODE_TITLES[item])

        p.setPen(QPen(theme.BORDER, 1))
        p.setBrush(theme.with_alpha(theme.SURFACE, 240))
        p.drawEllipse(c, inner - 6, inner - 6)
        p.setPen(theme.TEXT_DIM)
        p.setFont(theme.font(9.5))
        p.drawText(QRectF(c.x() - 60, c.y() - 20, 120, 40), Qt.AlignmentFlag.AlignCenter, "отмена")

        if self.pointer is not None:
            pt = self.pointer
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.with_alpha(theme.TEXT, 70 + int(120 * self.pinch_level)))
            p.drawEllipse(pt, 13, 13)
            theme.draw_arc(p, QRectF(pt.x() - 13, pt.y() - 13, 26, 26), self.pinch_level, theme.ACCENT, 3)
        p.end()
