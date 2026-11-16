"""On-screen keyboard driven by the hand pointer (or the real mouse).

The window never takes focus, so text goes to whatever application is active.
Keys are large, the hovered key is "sticky" (it does not flicker between
neighbours when the hand trembles near a border), a pinch presses the key, and
holding the pinch on ⌫ or the arrows repeats. Optional dwell typing presses a
key after hovering over it. A suggestion bar completes words.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..config import KeyboardSettings
from ..text.predictor import WordPredictor
from . import sound, theme
from .winutil import apply_no_activate, make_overlay


@dataclass
class Key:
    label: str
    action: tuple
    width: float = 1.0
    rect: QRectF = None
    repeat: bool = False
    accent: bool = False


def _chars(s: str) -> list[Key]:
    return [Key(c, ("char", c)) for c in s]


def _bottom_row(lang_label: str) -> list[Key]:
    return [Key("123", ("layer", "sym"), 1.5), Key(lang_label, ("lang",), 1.3), Key(",", ("char", ",")),
            Key("пробел" if lang_label == "EN" else "space", ("char", " "), 5.0), Key(".", ("char", ".")),
            Key("↵", ("key", "enter"), 1.6, accent=True), Key("✕", ("close",), 1.2)]


LAYOUTS = {
    "ru": [_chars("йцукенгшщзхъ"), _chars("фывапролджэ"),
           [Key("⇧", ("shift",), 1.5), *_chars("ячсмитьбю"), Key("⌫", ("key", "backspace"), 1.5, repeat=True)],
           _bottom_row("EN")],
    "en": [_chars("qwertyuiop"), _chars("asdfghjkl'"),
           [Key("⇧", ("shift",), 1.5), *_chars("zxcvbnm"), Key("⌫", ("key", "backspace"), 1.5, repeat=True)],
           _bottom_row("RU")],
    "sym": [_chars("1234567890"), _chars("-/:;()₽&@\""),
            [Key("#+=", ("layer", "sym2"), 1.5), *_chars(".,?!'%*"), Key("⌫", ("key", "backspace"), 1.5, repeat=True)],
            [Key("абв", ("layer", "main"), 1.5), Key("⇥", ("key", "tab"), 1.3), Key("←", ("key", "left"), repeat=True),
             Key("пробел", ("char", " "), 4.0), Key("→", ("key", "right"), repeat=True),
             Key("↵", ("key", "enter"), 1.6, accent=True), Key("✕", ("close",), 1.2)]],
    "sym2": [_chars("[]{}#%^*+="), _chars("_\\|~<>$€£•"),
             [Key("123", ("layer", "sym"), 1.5), *_chars(".,?!'`§"), Key("⌫", ("key", "backspace"), 1.5, repeat=True)],
             [Key("абв", ("layer", "main"), 1.5), Key("↑", ("key", "up"), repeat=True), Key("↓", ("key", "down"), repeat=True),
              Key("пробел", ("char", " "), 4.0), Key("Esc", ("key", "esc"), 1.3),
              Key("↵", ("key", "enter"), 1.6, accent=True), Key("✕", ("close",), 1.2)]],
}

TOOLS = [Key("↶ Отменить", ("combo", "z", ("ctrl",))), Key("Копировать", ("combo", "c", ("ctrl",))),
         Key("Вставить", ("combo", "v", ("ctrl",))), Key("Выделить всё", ("combo", "a", ("ctrl",)))]


class KeyboardOverlay(QWidget):
    closed = Signal()
    REPEAT_DELAY, REPEAT_EVERY = 0.45, 0.08

    def __init__(self, cfg: KeyboardSettings, input_backend):
        super().__init__()
        make_overlay(self, click_through=False)
        self.cfg = cfg
        self.input = input_backend
        self.lang = cfg.layout if cfg.layout in ("ru", "en") else "ru"
        self.layer = "main"
        self.shift = False
        self.caps = False
        self.last_shift_t = 0.0
        self.word = ""
        self.predictors: dict[str, WordPredictor] = {}
        self.suggestions: list[str] = []
        self.keys: list[Key] = []
        self.suggestion_keys: list[Key] = []
        self.pointer: Optional[QPointF] = None
        self.pinch_level = 0.0
        self.hover: Optional[Key] = None
        self.hover_since = 0.0
        self.dwell_done = False
        self.pressed: dict[int, float] = {}
        self.repeat_key: Optional[Key] = None
        self.repeat_next = 0.0
        self.timer = QTimer(self, interval=16, timeout=self._tick)
        self._rebuild()

    # ------------------------------------------------------------------ layout
    def place(self) -> None:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        w = min(int(screen.width() * 0.72), 1500)
        h = int(screen.height() * self.cfg.height_fraction)
        self.setGeometry(screen.center().x() - w // 2, screen.bottom() - h - 12, w, h)
        self.setWindowOpacity(self.cfg.opacity)

    def showEvent(self, e):
        super().showEvent(e)
        apply_no_activate(self)
        self.timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.timer.stop()
        self.repeat_key = None

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout()

    def _rows(self) -> list[list[Key]]:
        return LAYOUTS[self.lang if self.layer == "main" else self.layer]

    def _rebuild(self) -> None:
        self.keys = [k for row in self._rows() for k in row]
        self._layout()
        self._update_suggestions()

    def _layout(self) -> None:
        W, H = self.width(), self.height()
        if W < 10:
            return
        pad, gap = 14.0, 7.0
        bar_h = H * 0.17
        rows = self._rows()
        units = max(sum(k.width for k in row) for row in rows)
        key_h = (H - bar_h - 2 * pad - gap * len(rows)) / len(rows)
        unit_w = (W - 2 * pad - gap * (units - 1)) / units
        y = pad + bar_h + gap
        for row in rows:
            row_w = sum(k.width for k in row) * unit_w + gap * (len(row) - 1)
            x = (W - row_w) / 2
            for k in row:
                k.rect = QRectF(x, y, k.width * unit_w + gap * (k.width - 1), key_h)
                x += k.rect.width() + gap
            y += key_h + gap
        # Suggestion bar: 3 suggestions on the left, edit tools on the right.
        tools_w = W * 0.42
        sx, sw = pad, (W - 2 * pad - tools_w - 3 * gap) / 3
        self.suggestion_keys = []
        for i in range(3):
            self.suggestion_keys.append(Key("", ("suggest", i), rect=QRectF(sx + i * (sw + gap), pad, sw, bar_h - 4)))
        tx = W - pad - tools_w
        tw = (tools_w - gap * (len(TOOLS) - 1)) / len(TOOLS)
        for i, k in enumerate(TOOLS):
            k.rect = QRectF(tx + i * (tw + gap), pad, tw, bar_h - 4)

    def _all_keys(self) -> list[Key]:
        return self.keys + self.suggestion_keys + TOOLS

    # ------------------------------------------------------------------ pointer
    def set_pointer(self, uv: Optional[tuple[float, float]], pinch_level: float, pinch_started: bool,
                    pinch_held: bool) -> None:
        if uv is None:
            self.pointer, self.hover, self.repeat_key = None, None, None
            self.update()
            return
        pt = QPointF(uv[0] * self.width(), uv[1] * self.height())
        self.pointer, self.pinch_level = pt, pinch_level
        self._set_hover(self._hit(pt))
        if pinch_started and self.hover is not None:
            self._press(self.hover)
            if self.hover.repeat:
                self.repeat_key, self.repeat_next = self.hover, time.perf_counter() + self.REPEAT_DELAY
        if not pinch_held or self.hover is not self.repeat_key:
            self.repeat_key = None
        self.update()

    def _hit(self, pt: QPointF) -> Optional[Key]:
        # Sticky hover: keep the current key while the pointer is near its border.
        if self.hover is not None and self.hover.rect is not None:
            r = self.hover.rect
            m = min(r.width(), r.height()) * 0.18
            if r.adjusted(-m, -m, m, m).contains(pt):
                return self.hover
        best, best_d = None, 1e9
        for k in self._all_keys():
            if k.rect is None or (k.action[0] == "suggest" and not k.label):
                continue
            if k.rect.contains(pt):
                return k
            d = (k.rect.center() - pt).manhattanLength()
            if d < best_d:
                best, best_d = k, d
        return best if best_d < 60 else None

    def _set_hover(self, k: Optional[Key]) -> None:
        if k is not self.hover:
            self.hover, self.hover_since, self.dwell_done = k, time.perf_counter(), False

    def _tick(self) -> None:
        now = time.perf_counter()
        if self.repeat_key is not None and now >= self.repeat_next:
            self._press(self.repeat_key, quiet=True)
            self.repeat_next = now + self.REPEAT_EVERY
        if (self.cfg.dwell_ms > 0 and self.hover is not None and not self.dwell_done
                and self.pointer is not None and (now - self.hover_since) * 1000 >= self.cfg.dwell_ms):
            self.dwell_done = True
            self._press(self.hover)
        if self.pressed or self.cfg.dwell_ms > 0:
            self.pressed = {k: t for k, t in self.pressed.items() if now - t < 0.18}
            self.update()

    # ------------------------------------------------------------------ mouse
    def mousePressEvent(self, e):
        k = self._hit(e.position())
        if k is not None:
            self._press(k)

    # ------------------------------------------------------------------ actions
    def _predictor(self) -> WordPredictor:
        if self.lang not in self.predictors:
            self.predictors[self.lang] = WordPredictor(self.lang)
        return self.predictors[self.lang]

    def _update_suggestions(self) -> None:
        self.suggestions = self._predictor().suggest(self.word) if (self.cfg.suggestions and self.word) else []
        for i, k in enumerate(self.suggestion_keys):
            k.label = self.suggestions[i] if i < len(self.suggestions) else ""

    def _press(self, k: Key, quiet: bool = False) -> None:
        self.pressed[id(k)] = time.perf_counter()
        if self.cfg.sound and not quiet:
            sound.play("tick")
        kind = k.action[0]
        if kind == "char":
            ch = k.action[1]
            if ch.isalpha() and (self.shift or self.caps):
                ch = ch.upper()
            self.input.type_text(ch)
            if ch.isalpha() or ch in "-'":
                self.word += ch
            else:
                self._finish_word()
            if self.shift and not self.caps:
                self.shift = False
        elif kind == "key":
            self.input.key(k.action[1])
            if k.action[1] == "backspace":
                self.word = self.word[:-1]
            else:
                self._finish_word()
        elif kind == "combo":
            self.input.key(k.action[1], k.action[2])
            self.word = ""
        elif kind == "shift":
            now = time.perf_counter()
            if now - self.last_shift_t < 0.4:
                self.caps, self.shift = True, True
            elif self.caps:
                self.caps = self.shift = False
            else:
                self.shift = not self.shift
            self.last_shift_t = now
        elif kind == "lang":
            self.lang = "en" if self.lang == "ru" else "ru"
            self.word = ""
            self._rebuild()
        elif kind == "layer":
            self.layer = k.action[1]
            self._rebuild()
        elif kind == "suggest":
            i = k.action[1]
            if i < len(self.suggestions):
                s = self.suggestions[i]
                self.input.type_text(s[len(self.word):] + " ")
                self.word = s
                self._finish_word()
        elif kind == "close":
            self.closed.emit()
        self._update_suggestions()
        self.update()

    def _finish_word(self) -> None:
        if len(self.word) > 1:
            self._predictor().learn(self.word)
        self.word = ""

    # ------------------------------------------------------------------ paint
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(theme.BORDER, 1))
        p.setBrush(theme.with_alpha(theme.BG, 245))
        p.drawRoundedRect(rect, 20, 20)
        now = time.perf_counter()
        upper = self.shift or self.caps

        for k in self._all_keys():
            if k.rect is None:
                continue
            is_sugg = k.action[0] == "suggest"
            if is_sugg and not k.label:
                continue
            hovered = k is self.hover and self.pointer is not None
            pressed = id(k) in self.pressed
            bg = theme.SURFACE
            if k.accent:
                bg = theme.with_alpha(theme.ACCENT, 70)
            if k.action[0] == "shift" and (self.shift or self.caps):
                bg = theme.with_alpha(theme.ACCENT_2, 140 if self.caps else 80)
            if is_sugg:
                bg = theme.with_alpha(theme.SURFACE_HI, 160)
            if hovered:
                bg = theme.SURFACE_HI.lighter(125)
            if pressed:
                bg = theme.ACCENT
            r = k.rect.adjusted(2, 2, -2, -2) if pressed else k.rect
            p.setPen(QPen(theme.with_alpha(theme.ACCENT, 200), 2) if hovered else Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(r, 10, 10)
            if hovered and self.cfg.dwell_ms > 0 and not self.dwell_done:
                frac = (now - self.hover_since) * 1000 / self.cfg.dwell_ms
                p.setPen(QPen(theme.ACCENT, 3))
                p.drawLine(QPointF(r.left() + 8, r.bottom() - 5),
                           QPointF(r.left() + 8 + (r.width() - 16) * min(frac, 1), r.bottom() - 5))
            label = k.label.upper() if (upper and k.action[0] == "char" and len(k.label) == 1) else k.label
            p.setPen(theme.BG if pressed else theme.TEXT)
            size = 20 if len(label) == 1 else 11.5
            p.setFont(theme.font(min(size, r.height() * 0.32), QFont.Weight.Medium))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, label)

        if self.pointer is not None:
            c = self.pointer
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.with_alpha(theme.ACCENT_2, 60 + int(120 * self.pinch_level)))
            p.drawEllipse(c, 16, 16)
            theme.draw_arc(p, QRectF(c.x() - 16, c.y() - 16, 32, 32), self.pinch_level, theme.ACCENT_2, 3)
            p.setBrush(theme.TEXT)
            p.drawEllipse(c, 4, 4)
        p.end()
