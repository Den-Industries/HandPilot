"""Colors, fonts, the app icon and small painting helpers shared by all widgets."""
from __future__ import annotations

import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap

BG = QColor(18, 20, 28)
SURFACE = QColor(30, 33, 45)
SURFACE_HI = QColor(44, 48, 64)
BORDER = QColor(255, 255, 255, 28)
TEXT = QColor(236, 238, 245)
TEXT_DIM = QColor(150, 156, 175)
ACCENT = QColor(94, 234, 212)       # teal
ACCENT_2 = QColor(167, 139, 250)    # violet
WARN = QColor(251, 191, 36)
DANGER = QColor(248, 113, 113)

MODE_COLORS = {
    "mouse": ACCENT,
    "keyboard": ACCENT_2,
    "dactyl": QColor(96, 165, 250),
    "paused": TEXT_DIM,
}
MODE_TITLES = {"mouse": "Мышь", "keyboard": "Клавиатура", "dactyl": "Дактиль", "paused": "Пауза"}
MODE_ICONS = {"mouse": "🖱", "keyboard": "⌨", "dactyl": "🤟", "paused": "⏸"}

FONT_FAMILY = "Segoe UI Variable Text" if sys.platform == "win32" else "Ubuntu"


def font(size: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont(FONT_FAMILY)
    f.setPointSizeF(size)
    f.setWeight(weight)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return f


def with_alpha(c: QColor, a: int) -> QColor:
    c = QColor(c)
    c.setAlpha(a)
    return c


def draw_arc(p: QPainter, rect: QRectF, fraction: float, color: QColor, width: float) -> None:
    if fraction <= 0:
        return
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(rect, 90 * 16, int(-360 * 16 * min(fraction, 1.0)))


def app_icon(size: int = 256, color: QColor = ACCENT) -> QIcon:
    """A rounded tile with a stylized open hand and a cursor spark."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 256
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(SURFACE)
    p.drawRoundedRect(QRectF(8 * s, 8 * s, 240 * s, 240 * s), 56 * s, 56 * s)
    pen = QPen(color, 22 * s)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    # fingers
    for x, top in ((88, 70), (118, 52), (148, 58), (178, 86)):
        p.drawLine(QPointF(x * s, top * s), QPointF(x * s, 140 * s))
    # thumb
    p.drawLine(QPointF(62 * s, 128 * s), QPointF(88 * s, 160 * s))
    # palm
    path = QPainterPath()
    path.moveTo(88 * s, 140 * s)
    path.cubicTo(84 * s, 205 * s, 182 * s, 210 * s, 178 * s, 140 * s)
    p.drawPath(path)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(ACCENT_2)
    p.drawEllipse(QPointF(196 * s, 196 * s), 22 * s, 22 * s)
    p.end()
    return QIcon(pm)


STYLESHEET = f"""
QWidget {{ color: {TEXT.name()}; font-family: '{FONT_FAMILY}'; font-size: 10pt; }}
QMainWindow, QDialog {{ background: {BG.name()}; }}
QLabel#h1 {{ font-size: 17pt; font-weight: 600; }}
QLabel#h2 {{ font-size: 12pt; font-weight: 600; }}
QLabel#dim {{ color: {TEXT_DIM.name()}; }}
QFrame#card {{ background: {SURFACE.name()}; border: 1px solid rgba(255,255,255,0.07); border-radius: 14px; }}
QPushButton {{ background: {SURFACE_HI.name()}; border: 1px solid rgba(255,255,255,0.08);
               border-radius: 10px; padding: 8px 14px; }}
QPushButton:hover {{ background: #3a3f55; }}
QPushButton:checked {{ background: {ACCENT.name()}; color: #0b1220; font-weight: 600; }}
QPushButton#primary {{ background: {ACCENT.name()}; color: #0b1220; font-weight: 600; }}
QPushButton#primary:hover {{ background: #7ef0dd; }}
QPushButton#ghost {{ background: transparent; border: none; color: {TEXT_DIM.name()}; }}
QComboBox, QSpinBox, QDoubleSpinBox {{ background: {SURFACE_HI.name()}; border: 1px solid rgba(255,255,255,0.08);
               border-radius: 8px; padding: 5px 8px; }}
QComboBox QAbstractItemView {{ background: {SURFACE.name()}; selection-background-color: {SURFACE_HI.name()}; }}
QSlider::groove:horizontal {{ height: 6px; background: {SURFACE_HI.name()}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT.name()}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {TEXT.name()}; width: 16px; margin: -6px 0; border-radius: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; background: {SURFACE_HI.name()};
               border: 1px solid rgba(255,255,255,0.15); }}
QCheckBox::indicator:checked {{ background: {ACCENT.name()}; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; padding: 8px 14px; color: {TEXT_DIM.name()}; }}
QTabBar::tab:selected {{ color: {TEXT.name()}; border-bottom: 2px solid {ACCENT.name()}; }}
QMenu {{ background: {SURFACE.name()}; border: 1px solid rgba(255,255,255,0.1); padding: 6px; border-radius: 8px; }}
QMenu::item {{ padding: 6px 20px; border-radius: 6px; }}
QMenu::item:selected {{ background: {SURFACE_HI.name()}; }}
QToolTip {{ background: {SURFACE.name()}; color: {TEXT.name()}; border: 1px solid rgba(255,255,255,0.1); }}
"""
