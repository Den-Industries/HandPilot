"""Settings dialog. Every change applies live; the file is saved on close."""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton,
                               QSlider, QTabWidget, QVBoxLayout, QWidget)

from ..config import Settings
from . import theme


class SettingsDialog(QDialog):
    changed = Signal(object)          # emits a Settings copy
    camera_changed = Signal()

    def __init__(self, settings: Settings, cameras: list[int], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки HandPilot")
        self.setWindowIcon(theme.app_icon())
        self.setMinimumWidth(520)
        self.s = settings
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        lay.addWidget(tabs)

        # --- Cursor -------------------------------------------------------------
        cur = self._form(tabs, "Курсор")
        self._combo(cur, "Режим", self.s.cursor, "mode",
                    [("relative", "Тачпад (движение руки)"), ("absolute", "Указка (положение руки)")])
        self._slider(cur, "Скорость", self.s.cursor, "speed", 0.3, 3.0)
        self._slider(cur, "Ускорение", self.s.cursor, "acceleration", 0.0, 2.0)
        self._slider(cur, "Плавность", self.s.cursor, "smoothing", 3.0, 0.2,
                     hint="левее — отзывчивее, правее — плавнее")
        self._slider(cur, "Отзывчивость на быстрых движениях", self.s.cursor, "responsiveness", 0.05, 2.0)
        self._slider(cur, "Рабочая зона (режим «Указка»)", self.s.cursor, "active_area", 0.9, 0.3,
                     hint="правее — меньше движения руки")
        self._slider(cur, "Скорость прокрутки", self.s.cursor, "scroll_speed", 0.2, 3.0)
        self._check(cur, "Естественная прокрутка (страница следует за рукой)", self.s.cursor, "natural_scroll")

        # --- Gestures -----------------------------------------------------------
        ges = self._form(tabs, "Жесты")
        self._slider(ges, "Чувствительность щипка", self.s.gestures, "pinch_on", 0.18, 0.42,
                     hint="правее — срабатывает раньше", on_change=self._sync_pinch_off)
        self._slider(ges, "Порог начала перетаскивания", self.s.gestures, "drag_threshold", 0.005, 0.06)
        self._slider(ges, "Заморозка курсора при клике, мс", self.s.gestures, "click_freeze_ms", 0, 500, integer=True)
        self._slider(ges, "Удержание 👍 для меню, мс", self.s.gestures, "menu_hold_ms", 600, 2500, integer=True)
        self._check(ges, "Прокрутка кулаком", self.s.gestures, "scroll_enabled")
        self._check(ges, "Правый клик (большой + средний)", self.s.gestures, "right_click_enabled")
        self._check(ges, "Жесты-команды (✌ 🤟 🤘 🤙: окна, трек, громкость)", self.s.gestures, "shortcuts_enabled")
        self._slider(ges, "Длина взмаха, ладоней (меньше — чувствительнее)", self.s.gestures, "swipe_distance", 1.2, 4.0)
        self._slider(ges, "Градусов наклона на шаг громкости", self.s.gestures, "knob_step_deg", 5, 30)

        # --- Keyboard & dactyl ---------------------------------------------------
        kb = self._form(tabs, "Ввод текста")
        self._combo(kb, "Раскладка по умолчанию", self.s.keyboard, "layout", [("ru", "Русская"), ("en", "English")])
        self._slider(kb, "Набор наведением, мс (0 — выкл.)", self.s.keyboard, "dwell_ms", 0, 1500, integer=True)
        self._slider(kb, "Высота клавиатуры", self.s.keyboard, "height_fraction", 0.25, 0.55)
        self._slider(kb, "Непрозрачность", self.s.keyboard, "opacity", 0.6, 1.0)
        self._check(kb, "Подсказки слов", self.s.keyboard, "suggestions")
        self._check(kb, "Звук нажатия", self.s.keyboard, "sound")
        self._slider(kb, "Дактиль: время удержания буквы, мс", self.s.dactyl, "stable_ms", 60, 800, integer=True)
        self._slider(kb, "Дактиль: минимальная уверенность", self.s.dactyl, "min_confidence", 0.3, 0.9)

        # --- Camera -------------------------------------------------------------
        cam = self._form(tabs, "Камера")
        self._combo(cam, "Камера", self.s.camera, "index", [(i, f"Камера #{i}") for i in (cameras or [0])],
                    restart=True)
        self._combo(cam, "Разрешение", self.s.camera, "width", [(640, "640×480 (рекомендуется)"), (1280, "1280×720")],
                    restart=True, on_change=self._sync_height)
        self._check(cam, "Зеркальное изображение", self.s.camera, "mirror")
        self._combo(cam, "Управляющая рука", self.s.tracking, "preferred_hand",
                    [("any", "Любая"), ("Right", "Правая"), ("Left", "Левая")])
        self._slider(cam, "Сглаживание скелета", self.s.tracking, "landmark_smoothing", 4.0, 0.5)
        self._check(cam, "Показывать превью камеры", self.s.ui, "show_preview")
        self._check(cam, "Кольцо-подсказка у курсора", self.s.ui, "show_hud")
        self._check(cam, "Запускать вместе с системой", self.s.ui, "autostart")

        row = QHBoxLayout()
        reset = QPushButton("Сбросить всё")
        reset.setObjectName("ghost")
        reset.clicked.connect(self._reset)
        ok = QPushButton("Готово")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        row.addWidget(reset)
        row.addStretch(1)
        row.addWidget(ok)
        lay.addLayout(row)

    # ------------------------------------------------------------------ helpers
    def _form(self, tabs: QTabWidget, title: str) -> QFormLayout:
        w = QWidget()
        f = QFormLayout(w)
        f.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        f.setVerticalSpacing(12)
        f.setContentsMargins(12, 16, 12, 12)
        tabs.addTab(w, title)
        return f

    def _emit(self):
        self.changed.emit(copy.deepcopy(self.s))

    def _slider(self, form, label, obj, attr, lo, hi, integer=False, hint="", on_change=None):
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(0, 1000)
        val = QLabel()
        val.setObjectName("dim")
        val.setFixedWidth(46)

        def to_pos(v):
            return int(round((v - lo) / (hi - lo) * 1000))

        def from_pos(p):
            v = lo + (hi - lo) * p / 1000
            return int(round(v)) if integer else round(v, 3)

        def show(v):
            val.setText(str(v) if integer else f"{v:.2f}")

        s.setValue(to_pos(getattr(obj, attr)))
        show(getattr(obj, attr))

        def changed(p):
            v = from_pos(p)
            setattr(obj, attr, v)
            show(v)
            if on_change:
                on_change()
            self._emit()
        s.valueChanged.connect(changed)
        row = QHBoxLayout()
        row.addWidget(s, 1)
        row.addWidget(val)
        box = QWidget()
        box.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        lab = QLabel(label)
        if hint:
            lab.setToolTip(hint)
            s.setToolTip(hint)
        form.addRow(lab, box)

    def _check(self, form, label, obj, attr):
        c = QCheckBox(label)
        c.setChecked(bool(getattr(obj, attr)))

        def changed(v):
            setattr(obj, attr, bool(v))
            self._emit()
        c.toggled.connect(changed)
        form.addRow(c)

    def _combo(self, form, label, obj, attr, options, restart=False, on_change=None):
        c = QComboBox()
        for value, text in options:
            c.addItem(text, value)
        idx = max(0, c.findData(getattr(obj, attr)))
        c.setCurrentIndex(idx)

        def changed(i):
            setattr(obj, attr, c.itemData(i))
            if on_change:
                on_change()
            self._emit()
            if restart:
                self.camera_changed.emit()
        c.currentIndexChanged.connect(changed)
        form.addRow(QLabel(label), c)

    def _sync_pinch_off(self):
        self.s.gestures.pinch_off = round(self.s.gestures.pinch_on + 0.12, 3)

    def _sync_height(self):
        self.s.camera.height = {640: 480, 1280: 720}.get(self.s.camera.width, 480)

    def _reset(self):
        fresh = Settings()
        fresh.ui.first_run = False
        for name in ("camera", "tracking", "cursor", "gestures", "keyboard", "dactyl", "ui"):
            setattr(self.s, name, getattr(fresh, name))
        self._emit()
        self.camera_changed.emit()
        self.accept()
