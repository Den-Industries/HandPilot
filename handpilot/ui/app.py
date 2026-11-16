"""Application shell: wires the engine to the overlays, tray icon and hotkeys."""
from __future__ import annotations

import copy
import logging
import os
import sys

from PySide6.QtCore import QLockFile, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from .. import platform as plat
from ..config import Settings, config_dir
from ..core.camera import list_cameras
from ..engine.engine import Engine, FrameState
from . import sound, theme
from .hud import CursorHud, DactylPanel, Toast
from .keyboard import KeyboardOverlay
from .menu import ModeMenu
from .onboarding import Onboarding
from .panel import ControlPanel
from .settings_dialog import SettingsDialog

log = logging.getLogger(__name__)

MODE_TOASTS = {
    "mouse": "Мышь — ведите ладонью, щипок = клик",
    "keyboard": "Клавиатура — наведите и сведите пальцы",
    "dactyl": "Дактиль — показывайте буквы",
    "paused": "Пауза — держите 👍, чтобы продолжить",
}
HOTKEYS = {"ctrl+alt+h": "pause", "ctrl+alt+m": "mouse", "ctrl+alt+k": "keyboard", "ctrl+alt+d": "dactyl"}


class Bridge(QObject):
    """Thread → GUI marshalling (engine and hotkey threads emit, the GUI thread handles)."""
    state = Signal(object)
    hotkey = Signal(str)


class HandPilotApp(QObject):
    def __init__(self, qapp: QApplication, video: str = "", inject: bool = True):
        super().__init__()
        self.qapp = qapp
        self.video, self.inject = video, inject
        self.settings = Settings.load()
        self.input = plat.create_input()
        if not inject:
            from ..platform.base import DryRunInput
            self.input = DryRunInput(self.input)   # demo: recognise everything, inject nothing
        self.bridge = Bridge()
        self.bridge.state.connect(self.on_state, Qt.ConnectionType.QueuedConnection)
        self.bridge.hotkey.connect(self.on_hotkey, Qt.ConnectionType.QueuedConnection)
        self.mode = None
        self.engine: Engine | None = None
        self.last_message = ""

        self.panel = ControlPanel()
        self.panel.mode_requested.connect(self.set_mode)
        self.panel.settings_requested.connect(self.open_settings)
        self.panel.tutorial_requested.connect(self.start_tutorial)
        self.hud = CursorHud()
        self.toast = Toast()
        self.keyboard = KeyboardOverlay(self.settings.keyboard, self.input)
        self.keyboard.closed.connect(lambda: self.set_mode("mouse"))
        self.menu = ModeMenu()
        self.menu.chosen.connect(self._menu_chosen)
        self.menu.cancelled.connect(self._menu_cancelled)
        self.dactyl = DactylPanel()
        self.onboarding = Onboarding()
        self.onboarding.finished.connect(self._tutorial_done)
        self._build_tray()

        self.hotkeys = plat.create_hotkeys({k: (lambda a=a: self.bridge.hotkey.emit(a)) for k, a in HOTKEYS.items()}) \
            if self.settings.ui.hotkeys else None
        if self.hotkeys:
            self.hotkeys.start()

        self.start_engine()
        self.panel.show()
        if self.settings.ui.first_run:
            QTimer.singleShot(800, self.start_tutorial)

    # ------------------------------------------------------------------ engine
    def start_engine(self) -> None:
        if self.engine is not None:
            self.engine.stop()
        self.engine = Engine(self.settings, self.input, self.bridge.state.emit, video_source=self.video)
        self.engine.inject = self.inject
        self.engine.start()

    def set_mode(self, mode: str) -> None:
        if self.engine:
            self.engine.set_mode(mode)

    def _menu_chosen(self, mode: str) -> None:
        sound.play("pop")
        self.set_mode(mode)

    def _menu_cancelled(self) -> None:
        if self.engine:
            self.engine.close_menu()

    def on_hotkey(self, action: str) -> None:
        if action == "pause":
            self.engine.toggle_pause()
        else:
            self.set_mode(action)

    # ------------------------------------------------------------------ state
    def on_state(self, st: FrameState) -> None:
        if st.mode != self.mode:
            self._mode_changed(st.mode)
        if st.message and st.message != self.last_message:
            self.toast.show_message(st.message, theme.DANGER, 3.0)
        self.last_message = st.message
        if st.notice:
            self.toast.show_message(st.notice, theme.ACCENT, 1.0)

        self.panel.set_state(st)
        overlay_mode = not st.menu_open
        self.hud.set_state(st, active=overlay_mode and st.mode == "mouse" and self.settings.ui.show_hud)

        if st.menu_open:
            if not self.menu.isVisible():
                self.menu.open(st.mode)
            self.menu.set_pointer(st.pointer if st.hand else None, st.gesture.pinch_level, st.gesture.pinch_started)
        elif self.menu.isVisible():
            self.menu.hide()

        if st.mode == "keyboard":
            uv = st.pointer if (st.hand and overlay_mode) else None
            self.keyboard.set_pointer(uv, st.gesture.pinch_level, st.gesture.pinch_started and overlay_mode,
                                      st.gesture.pinch is not None)
        if st.mode == "dactyl":
            self.dactyl.set_state(st)
        self.onboarding.feed(st)

    def _mode_changed(self, mode: str) -> None:
        first = self.mode is None
        self.mode = mode
        self.keyboard.cfg = self.settings.keyboard
        if mode == "keyboard":
            self.keyboard.place()
            self.keyboard.show()
        else:
            self.keyboard.hide()
        if mode == "dactyl":
            self.dactyl.place()
            self.dactyl.show()
        else:
            self.dactyl.hide()
        for m, act in self.mode_actions.items():
            act.setChecked(m == mode)
        self.tray.setIcon(theme.app_icon(color=theme.MODE_COLORS[mode]))
        self.tray.setToolTip(f"HandPilot — {theme.MODE_TITLES[mode]}")
        if not first:
            self.toast.show_message(MODE_TOASTS[mode], theme.MODE_COLORS[mode])
            if mode == "dactyl" and self.engine and not self.engine.speller.available:
                self.toast.show_message("Модель дактиля не найдена — запустите обучение", theme.WARN, 3.0)

    # ------------------------------------------------------------------ tray
    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(theme.app_icon(), self)
        menu = QMenu()
        menu.addAction("Показать панель", self._show_panel)
        menu.addSeparator()
        group = QActionGroup(menu)
        self.mode_actions = {}
        for m in ("mouse", "keyboard", "dactyl", "paused"):
            a = QAction(f"{theme.MODE_ICONS[m]}  {theme.MODE_TITLES[m]}", menu, checkable=True)
            a.triggered.connect(lambda _=False, mode=m: self.set_mode(mode))
            group.addAction(a)
            menu.addAction(a)
            self.mode_actions[m] = a
        menu.addSeparator()
        menu.addAction("Настройки…", self.open_settings)
        menu.addAction("Обучение", self.start_tutorial)
        menu.addSeparator()
        menu.addAction("Выход", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self._show_panel() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()

    def _show_panel(self) -> None:
        self.panel.showNormal()
        self.panel.raise_()
        self.panel.activateWindow()

    # ------------------------------------------------------------------ dialogs
    def open_settings(self) -> None:
        dlg = SettingsDialog(copy.deepcopy(self.settings), list_cameras() if not self.video else [0], self.panel)
        restart = {"needed": False}
        dlg.changed.connect(self._apply_settings)
        dlg.camera_changed.connect(lambda: restart.__setitem__("needed", True))
        autostart_before = self.settings.ui.autostart
        dlg.exec()
        self.settings.save()
        if self.settings.ui.autostart != autostart_before:
            try:
                plat.set_autostart(self.settings.ui.autostart)
            except OSError as e:
                self.toast.show_message(f"Автозапуск: {e}", theme.WARN, 3.0)
        if restart["needed"]:
            self.start_engine()

    def _apply_settings(self, s: Settings) -> None:
        s.ui.first_run = self.settings.ui.first_run
        self.settings = s
        self.keyboard.cfg = s.keyboard
        if self.engine:
            self.engine.apply_settings(copy.deepcopy(s))

    def start_tutorial(self) -> None:
        self.set_mode("mouse")
        self.onboarding.start()

    def _tutorial_done(self) -> None:
        self.settings.ui.first_run = False
        self.settings.save()
        if self.engine and self.engine.menu_open:
            self.engine.close_menu()
        self.toast.show_message("Готово! Подсказки по жестам — в панели HandPilot", theme.ACCENT, 3.0)

    def quit(self) -> None:
        if self.engine:
            self.engine.stop()
        if self.hotkeys:
            self.hotkeys.stop()
        self.settings.save()
        self.tray.hide()
        self.qapp.quit()


def run(video: str = "", inject: bool = True) -> int:
    plat.prepare_process()
    if sys.platform.startswith("linux"):
        # Overlays (always-on-top, click-through) only work reliably on X11/XWayland.
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    qapp = QApplication(sys.argv)
    qapp.setApplicationName("HandPilot")
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setStyleSheet(theme.STYLESHEET)
    qapp.setWindowIcon(theme.app_icon())

    lock = QLockFile(os.path.join(config_dir(), "handpilot.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, "HandPilot", "HandPilot уже запущен — ищите значок в трее.")
        return 0
    app = HandPilotApp(qapp, video=video, inject=inject)
    qapp.aboutToQuit.connect(lambda: app.engine and app.engine.stop())
    code = qapp.exec()
    lock.unlock()
    return code
