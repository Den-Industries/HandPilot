"""Interactive first-run tutorial: each step waits until the user actually
performs the gesture, with live feedback from the engine."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import sound, theme
from .winutil import apply_no_activate, make_overlay

STEPS = [
    ("🖐", "Покажите ладонь камере", "Держите руку в 40–70 см от камеры, ладонью к экрану.",
     lambda st, m: st.hand and st.quality > 0.7),
    ("↔", "Подвигайте курсор", "Ведите ладонью — курсор движется следом. Достаточно небольших движений.",
     lambda st, m: m.get("moved", 0) > 0.6),
    ("👌", "Клик: сведите большой и указательный", "Кольцо у курсора заполняется — когда пальцы сомкнутся, будет клик.",
     lambda st, m: m.get("clicks", 0) >= 2),
    ("✊", "Прокрутка: сожмите кулак", "…и двигайте кулаком вверх-вниз, будто тянете страницу.",
     lambda st, m: m.get("scroll", 0) > 0.4),
    ("👍", "Меню: держите большой палец вверх", "Удерживайте, пока не заполнится кольцо. Там — клавиатура и дактиль.",
     lambda st, m: st.menu_open),
]


class Onboarding(QWidget):
    finished = Signal()
    W, H = 560, 210

    def __init__(self):
        super().__init__()
        make_overlay(self, click_through=False)
        self.resize(self.W, self.H)
        self.step = 0
        self.metrics: dict[str, float] = {}
        self.done_flash = 0.0
        self.last_pos = None
        self.timer = QTimer(self, interval=30, timeout=self._anim)

    def start(self) -> None:
        self.step, self.metrics, self.last_pos = 0, {}, None
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - self.W // 2, screen.top() + 90)
        self.show()
        apply_no_activate(self)
        self.timer.start()

    def feed(self, st) -> None:
        if not self.isVisible() or self.step >= len(STEPS):
            return
        m = self.metrics
        if st.hand and st.landmarks is not None:
            c = st.landmarks[[0, 5, 9, 13, 17], :2].mean(axis=0)
            if self.last_pos is not None and self.step == 1:
                m["moved"] = m.get("moved", 0) + float(abs(c - self.last_pos).sum()) * 2
            if self.step == 3 and st.scrolling and self.last_pos is not None:
                m["scroll"] = m.get("scroll", 0) + float(abs(c[1] - self.last_pos[1])) * 4
            self.last_pos = c
        if st.gesture.pinch_started and self.step == 2:
            m["clicks"] = m.get("clicks", 0) + 1
        if self.done_flash <= 0 and STEPS[self.step][3](st, m):
            self.done_flash = 1.0
            sound.play("pop")
        self.update()

    def _anim(self) -> None:
        if self.done_flash > 0:
            self.done_flash -= 0.04
            if self.done_flash <= 0:
                self.step += 1
                self.metrics = {}
                if self.step >= len(STEPS):
                    self.timer.stop()
                    self.hide()
                    self.finished.emit()
                    return
            self.update()

    def mousePressEvent(self, e):
        # "Пропустить" in the corner.
        if e.position().x() > self.W - 120 and e.position().y() < 44:
            self.timer.stop()
            self.hide()
            self.finished.emit()

    def paintEvent(self, _):
        if self.step >= len(STEPS):
            return
        icon, title, desc, _ = STEPS[self.step]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        border = theme.ACCENT if self.done_flash > 0 else theme.BORDER
        p.setPen(QPen(border, 2 if self.done_flash > 0 else 1))
        p.setBrush(theme.with_alpha(theme.BG, 245))
        p.drawRoundedRect(rect, 22, 22)

        p.setPen(theme.TEXT_DIM)
        p.setFont(theme.font(9))
        p.drawText(QRectF(24, 16, 300, 20), Qt.AlignmentFlag.AlignLeft,
                   f"Знакомство · шаг {self.step + 1} из {len(STEPS)}")
        p.drawText(QRectF(self.W - 120, 16, 96, 20), Qt.AlignmentFlag.AlignRight, "Пропустить ✕")

        p.setFont(theme.font(40))
        p.setPen(theme.TEXT)
        p.drawText(QRectF(20, 52, 100, 100), Qt.AlignmentFlag.AlignCenter, "✓" if self.done_flash > 0 else icon)
        p.setFont(theme.font(15, QFont.Weight.DemiBold))
        p.drawText(QRectF(130, 56, self.W - 150, 34), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
        p.setFont(theme.font(10.5))
        p.setPen(theme.TEXT_DIM)
        p.drawText(QRectF(130, 94, self.W - 154, 60), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, desc)

        # Progress dots.
        for i in range(len(STEPS)):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.ACCENT if i < self.step or (i == self.step and self.done_flash > 0)
                       else theme.SURFACE_HI)
            p.drawRoundedRect(QRectF(24 + i * 30, self.H - 30, 22, 6), 3, 3)
        p.end()
