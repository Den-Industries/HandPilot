"""Main control panel: live camera preview with skeleton, mode switcher, status
and a context-sensitive gesture cheat sheet."""
from __future__ import annotations

from typing import Optional

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from ..core.geometry import HAND_CONNECTIONS
from . import theme

CHEATSHEET = {
    "mouse": [("🖐", "Двигайте ладонью", "курсор следует за рукой"),
              ("👌", "Большой + указательный", "клик · держите и ведите — перетаскивание"),
              ("🖱", "Большой + средний", "правый клик"),
              ("✊", "Кулак и движение", "прокрутка страницы"),
              ("✌", "Победа + взмах", "→ ← Alt+Tab · ↑ обзор окон · ↓ рабочий стол"),
              ("🤙", "Шака и наклон кисти", "вправо/влево — громкость + / −"),
              ("🤘", "Рок + взмах · держать", "след./пред. трек · пауза"),
              ("🤟", "Три пальца + взмах", "← назад · → вперёд · ↑ обновить"),
              ("👍", "Держите большой палец вверх", "меню режимов")],
    "keyboard": [("🖐", "Наведите ладонью", "на нужную клавишу"),
                 ("👌", "Сведите пальцы", "нажать · держите на ⌫ — повтор"),
                 ("💡", "Подсказки сверху", "дополняют слово целиком"),
                 ("👍", "Держите большой палец вверх", "меню режимов")],
    "dactyl": [("🤟", "Показывайте буквы", "русской дактильной азбуки"),
               ("⏱", "Задержите жест", "на мгновение — буква напечатается"),
               ("👍", "Большой палец вверх", "пробел (держать — меню)"),
               ("👎", "Большой палец вниз", "стереть символ")],
    "paused": [("⏸", "Управление на паузе", "камера следит только за жестом меню"),
               ("👍", "Держите большой палец вверх", "чтобы вернуться")],
}


def describe(st) -> str:
    if not st.hand:
        return "Рука не видна"
    g = st.gesture
    if g.hold_progress > 0:
        return "Меню…"
    if st.mode == "mouse":
        if st.scrolling:
            return "Прокрутка"
        if st.dragging:
            return "Перетаскивание"
        if g.pinch == "left":
            return "Клик"
        if g.pinch == "right":
            return "Правый клик"
        special = {"shaka": "Громкость (наклоняйте кисть)", "victory": "Окна: взмах в сторону",
                   "rock": "Музыка: взмах / держать", "three": "Браузер: взмах"}
        return special.get(g.pose, "Указатель")
    if st.mode == "dactyl":
        return f"Буква: {st.dactyl.label}" if st.dactyl.label else "Покажите букву"
    if st.mode == "keyboard":
        return "Нажатие" if g.pinch else "Наведение"
    return "Пауза"


class PreviewView(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(400, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image: Optional[QImage] = None
        self.state = None
        self.message = "Запуск камеры…"

    def set_state(self, st) -> None:
        self.state = st
        if st.frame is not None:
            f = np.ascontiguousarray(st.frame[:, :, ::-1])   # BGR → RGB
            h, w = f.shape[:2]
            self.image = QImage(f.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        if st.message:
            self.message = st.message
        elif self.image is not None:
            self.message = ""
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        area = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.SURFACE)
        p.drawRoundedRect(area, 16, 16)
        st = self.state
        if self.image is not None:
            iw, ih = self.image.width(), self.image.height()
            scale = min(area.width() / iw, area.height() / ih)
            target = QRectF(0, 0, iw * scale, ih * scale)
            target.moveCenter(area.center())
            clip = QPainterPath()
            clip.addRoundedRect(target, 16, 16)
            p.setClipPath(clip)
            p.drawImage(target, self.image)
            p.fillRect(target, theme.with_alpha(theme.BG, 60))
            if st is not None and st.landmarks is not None:
                self._draw_hand(p, target, st)
            p.setClipping(False)
            if st is not None:
                self._draw_chips(p, target, st)
        if self.message:
            p.setPen(theme.TEXT_DIM)
            p.setFont(theme.font(12))
            p.drawText(area, Qt.AlignmentFlag.AlignCenter, self.message)
        p.end()

    def _draw_hand(self, p: QPainter, target: QRectF, st) -> None:
        pts = [QPointF(target.left() + x * target.width(), target.top() + y * target.height())
               for x, y, _ in st.landmarks]
        color = theme.MODE_COLORS.get(st.mode, theme.ACCENT)
        if st.gesture.pinch:
            color = theme.ACCENT_2
        alpha = int(120 + 135 * st.quality)
        pen = QPen(theme.with_alpha(color, alpha), 3.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        for a, b in HAND_CONNECTIONS:
            p.drawLine(pts[a], pts[b])
        p.setPen(Qt.PenStyle.NoPen)
        for i, pt in enumerate(pts):
            p.setBrush(theme.TEXT if i in (4, 8, 12, 16, 20) else theme.with_alpha(color, alpha))
            p.drawEllipse(pt, 4.2 if i in (4, 8, 12) else 3.0, 4.2 if i in (4, 8, 12) else 3.0)
        # Pinch indicator between thumb and index tips.
        lvl = st.gesture.pinch_level
        if lvl > 0.05:
            p.setPen(QPen(theme.with_alpha(theme.ACCENT_2, int(255 * lvl)), 2, Qt.PenStyle.DashLine))
            p.drawLine(pts[4], pts[8])

    def _draw_chips(self, p: QPainter, target: QRectF, st) -> None:
        chips = [f"{st.fps:4.0f} к/с", f"{st.latency_ms:3.0f} мс"]
        if st.hand:
            chips.append({"Right": "правая рука", "Left": "левая рука"}.get(st.handedness, "рука"))
        x = target.left() + 12
        p.setFont(theme.font(9, QFont.Weight.Medium))
        for text in chips:
            w = p.fontMetrics().horizontalAdvance(text) + 20
            r = QRectF(x, target.top() + 12, w, 24)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.with_alpha(theme.BG, 190))
            p.drawRoundedRect(r, 12, 12)
            p.setPen(theme.TEXT)
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
            x += w + 6
        # Big gesture caption at the bottom.
        cap = describe(st)
        r = QRectF(target.left() + 12, target.bottom() - 48, target.width() - 24, 36)
        p.setFont(theme.font(13, QFont.Weight.DemiBold))
        w = p.fontMetrics().horizontalAdvance(cap) + 32
        pill = QRectF(r.center().x() - w / 2, r.top(), w, 36)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.with_alpha(theme.BG, 210))
        p.drawRoundedRect(pill, 18, 18)
        p.setPen(theme.MODE_COLORS.get(st.mode, theme.TEXT) if st.hand else theme.TEXT_DIM)
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, cap)


class ControlPanel(QMainWindow):
    mode_requested = Signal(str)
    settings_requested = Signal()
    tutorial_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("HandPilot")
        self.setWindowIcon(theme.app_icon())
        self.resize(1080, 640)
        root = QWidget()
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(18)

        self.preview = PreviewView()
        lay.addWidget(self.preview, 3)

        side = QVBoxLayout()
        side.setSpacing(12)
        lay.addLayout(side, 2)

        title = QLabel("HandPilot")
        title.setObjectName("h1")
        sub = QLabel("Управление компьютером жестами")
        sub.setObjectName("dim")
        side.addWidget(title)
        side.addWidget(sub)

        modes = QGridLayout()
        modes.setSpacing(6)
        self.mode_group = QButtonGroup(self)
        self.mode_buttons = {}
        for m in ("mouse", "keyboard", "dactyl", "paused"):
            b = QPushButton(f"{theme.MODE_ICONS[m]}  {theme.MODE_TITLES[m]}")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, mode=m: self.mode_requested.emit(mode))
            self.mode_group.addButton(b)
            self.mode_buttons[m] = b
            b.setMinimumHeight(44)
            n = len(self.mode_buttons) - 1
            modes.addWidget(b, n // 2, n % 2)
        side.addLayout(modes)

        self.cheat = QFrame()
        self.cheat.setObjectName("card")
        self.cheat_layout = QVBoxLayout(self.cheat)
        self.cheat_layout.setContentsMargins(16, 14, 16, 14)
        self.cheat_layout.setSpacing(10)
        side.addWidget(self.cheat, 1)

        hot = QLabel("Ctrl+Alt+H — пауза · Ctrl+Alt+M — мышь\nCtrl+Alt+K — клавиатура · Ctrl+Alt+D — дактиль")
        hot.setObjectName("dim")
        side.addWidget(hot)

        btns = QHBoxLayout()
        b_set = QPushButton("⚙  Настройки")
        b_set.clicked.connect(self.settings_requested)
        b_tut = QPushButton("🎓  Обучение")
        b_tut.clicked.connect(self.tutorial_requested)
        b_hide = QPushButton("Свернуть в трей")
        b_hide.setObjectName("ghost")
        b_hide.clicked.connect(self.hide)
        btns.addWidget(b_set)
        btns.addWidget(b_tut)
        btns.addStretch(1)
        btns.addWidget(b_hide)
        side.addLayout(btns)
        self._mode = None
        self.set_mode("mouse")

    def set_mode(self, mode: str) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        self.mode_buttons[mode].setChecked(True)
        while self.cheat_layout.count():
            item = self.cheat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        head = QLabel(f"Жесты · {theme.MODE_TITLES[mode]}")
        head.setObjectName("h2")
        self.cheat_layout.addWidget(head)
        for icon, title, desc in CHEATSHEET[mode]:
            row = QHBoxLayout()
            ic = QLabel(icon)
            ic.setFont(theme.font(20))
            ic.setFixedWidth(40)
            txt = QLabel(f"<b>{title}</b><br><span style='color:{theme.TEXT_DIM.name()}'>{desc}</span>")
            txt.setWordWrap(True)
            row.addWidget(ic)
            row.addWidget(txt, 1)
            w = QWidget()
            w.setLayout(row)
            row.setContentsMargins(0, 0, 0, 0)
            self.cheat_layout.addWidget(w)
        self.cheat_layout.addStretch(1)

    def set_state(self, st) -> None:
        if self.isVisible():
            self.preview.set_state(st)
        self.set_mode(st.mode)

    def closeEvent(self, e):
        # Closing the panel keeps the app running in the tray.
        e.ignore()
        self.hide()
