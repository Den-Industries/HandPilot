"""Always-on-top, click-through feedback overlays.

* CursorHud   – a ring around the mouse cursor: fills as the fingers close
                (so a click never comes as a surprise), shows drag/scroll and
                the thumbs-up hold progress.
* Toast       – short notifications at the top of the screen (mode changes…).
* DactylPanel – the fingerspelling read-out: recognised sign, confidence and
                what has been typed.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import theme
from .winutil import make_overlay


class CursorHud(QWidget):
    SIZE = 96

    def __init__(self):
        super().__init__()
        make_overlay(self, click_through=True)
        self.resize(self.SIZE, self.SIZE)
        self.state = None
        self.opacity = 0.0
        self.target_opacity = 0.0
        self.click_flash = 0.0
        self.timer = QTimer(self, interval=12, timeout=self._tick)
        self.timer.start()

    def set_state(self, st, active: bool) -> None:
        prev = self.state
        self.state = st
        self.target_opacity = 1.0 if (active and st.hand) else 0.0
        if prev is not None and st.gesture.pinch_started:
            self.click_flash = 1.0

    def _tick(self) -> None:
        self.opacity += (self.target_opacity - self.opacity) * 0.25
        self.click_flash = max(0.0, self.click_flash - 0.08)
        if self.opacity < 0.02:
            if self.isVisible():
                self.hide()
            return
        pos = QCursor.pos()
        self.move(pos.x() - self.SIZE // 2, pos.y() - self.SIZE // 2)
        if not self.isVisible():
            self.show()
        self.update()

    def paintEvent(self, _):
        st = self.state
        if st is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self.opacity)
        c = QPointF(self.SIZE / 2, self.SIZE / 2)
        gs = st.gesture
        r = 17.0
        ring = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)

        # Base ring – dims when tracking quality drops.
        base = theme.with_alpha(theme.TEXT, int(70 + 60 * st.quality))
        p.setPen(QPen(base, 2.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(ring)

        accent = theme.ACCENT
        if gs.pinch == "right":
            accent = theme.ACCENT_2
        if gs.pinch or st.dragging:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.with_alpha(accent, 90))
            p.drawEllipse(ring)
            theme.draw_arc(p, ring, 1.0, accent, 3.5)
        else:
            theme.draw_arc(p, ring, gs.pinch_level, theme.with_alpha(accent, 220), 3.5)

        if self.click_flash > 0:
            rr = r + 4 + 14 * (1 - self.click_flash)
            p.setPen(QPen(theme.with_alpha(accent, int(200 * self.click_flash)), 2.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, rr, rr)

        if gs.hold_progress > 0:
            outer = QRectF(c.x() - 27, c.y() - 27, 54, 54)
            theme.draw_arc(p, outer, gs.hold_progress, theme.ACCENT_2, 4.0)

        if st.scrolling:
            pen = QPen(theme.TEXT, 2.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            for sgn in (-1, 1):
                y = c.y() + sgn * 7
                p.drawLine(QPointF(c.x() - 5, y), QPointF(c.x(), y + sgn * 5))
                p.drawLine(QPointF(c.x() + 5, y), QPointF(c.x(), y + sgn * 5))
        p.end()


class Toast(QWidget):
    def __init__(self):
        super().__init__()
        make_overlay(self, click_through=True)
        self.text = ""
        self.color = theme.ACCENT
        self.shown_at = 0.0
        self.duration = 1.6
        self.timer = QTimer(self, interval=16, timeout=self._tick)

    def show_message(self, text: str, color: QColor = theme.ACCENT, duration: float = 1.6) -> None:
        self.text, self.color, self.duration = text, color, duration
        self.shown_at = time.perf_counter()
        fm_w = max(260, 26 * 2 + len(text) * 11)
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.setGeometry(screen.center().x() - fm_w // 2, screen.top() + 28, fm_w, 52)
        self.setWindowOpacity(1.0)
        self.show()
        self.update()
        self.timer.start()

    def _tick(self) -> None:
        el = time.perf_counter() - self.shown_at
        if el > self.duration:
            fade = 1 - (el - self.duration) / 0.3
            if fade <= 0:
                self.hide()
                self.timer.stop()
                return
            self.setWindowOpacity(fade)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(theme.with_alpha(self.color, 160), 1.5))
        p.setBrush(theme.with_alpha(theme.BG, 235))
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        p.setBrush(self.color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(26, rect.center().y()), 6, 6)
        p.setPen(theme.TEXT)
        p.setFont(theme.font(12, QFont.Weight.DemiBold))
        p.drawText(rect.adjusted(42, 0, -16, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text)
        p.end()


class DactylPanel(QWidget):
    W, H = 460, 150

    def __init__(self):
        super().__init__()
        make_overlay(self, click_through=True)
        self.resize(self.W, self.H)
        self.state = None
        self.typed = ""

    def place(self) -> None:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - self.W // 2, screen.bottom() - self.H - 24)

    def set_state(self, st) -> None:
        self.state = st
        c = st.dactyl.committed
        if c == "\b":
            self.typed = self.typed[:-1]
        elif c:
            self.typed = (self.typed + c)[-40:]
        self.update()

    def paintEvent(self, _):
        st = self.state
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(theme.BORDER, 1))
        p.setBrush(theme.with_alpha(theme.BG, 238))
        p.drawRoundedRect(rect, 22, 22)

        # Recognised sign with confidence ring.
        circle = QRectF(22, 22, 92, 92)
        p.setPen(QPen(theme.SURFACE_HI, 6))
        p.setBrush(theme.SURFACE)
        p.drawEllipse(circle)
        color = theme.MODE_COLORS["dactyl"]
        if st is not None and st.hand:
            d = st.dactyl
            theme.draw_arc(p, circle, d.progress, color if d.progress < 1 else theme.ACCENT, 6)
            p.setPen(theme.TEXT)
            p.setFont(theme.font(34, QFont.Weight.DemiBold))
            p.drawText(circle, Qt.AlignmentFlag.AlignCenter, d.label or "·")
            p.setFont(theme.font(9))
            p.setPen(theme.TEXT_DIM)
            p.drawText(QRectF(22, 118, 92, 20), Qt.AlignmentFlag.AlignCenter,
                       f"{int(d.confidence * 100)}%" if d.label else "")
        else:
            p.setPen(theme.TEXT_DIM)
            p.setFont(theme.font(10))
            p.drawText(circle, Qt.AlignmentFlag.AlignCenter, "нет руки")

        p.setPen(theme.TEXT)
        p.setFont(theme.font(17))
        text = self.typed[-22:] + "▏"
        p.drawText(QRectF(132, 26, self.W - 150, 50), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        p.setPen(theme.TEXT_DIM)
        p.setFont(theme.font(9.5))
        p.drawText(QRectF(132, 84, self.W - 150, 50), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
                   "👍 пробел   👎 стереть\nдержите 👍 — меню режимов")
        if st is not None and st.gesture.hold_progress > 0:
            theme.draw_arc(p, circle.adjusted(-8, -8, 8, 8), st.gesture.hold_progress, theme.ACCENT_2, 4)
        p.end()
