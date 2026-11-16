"""The processing loop: camera → tracker → stabilizer → gestures → actions.

Runs on its own thread. Mouse actions are injected directly from here (lowest
latency); everything the UI needs is published as an immutable `FrameState`
through the `on_state` callback once per processed frame.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import cv2
import numpy as np

from ..config import Settings
from ..core import geometry as g
from ..core.camera import Camera
from ..tracking.mediapipe_tracker import MediaPipeTracker
from ..tracking.stabilizer import HandStabilizer
from .cursor import CursorController, PointerMapper
from .fingerspell import DactylState, Fingerspeller
from .gestures import GestureRecognizer, GestureState
from .shortcuts import SPECIAL_POSES, ShortcutDetector, ShortcutEvent

log = logging.getLogger(__name__)

MODES = ("mouse", "keyboard", "dactyl", "paused")
MENU_TIMEOUT_S = 8.0


@dataclass
class FrameState:
    t: float = 0.0
    fps: float = 0.0
    latency_ms: float = 0.0
    mode: str = "mouse"
    menu_open: bool = False
    hand: bool = False
    landmarks: Optional[np.ndarray] = None   # (21, 3) filtered, mirrored-frame normalized
    handedness: str = ""
    quality: float = 0.0
    gesture: GestureState = field(default_factory=GestureState)
    pointer: Optional[tuple[float, float]] = None   # 0..1 overlay coords (keyboard/menu)
    scrolling: bool = False
    dragging: bool = False
    dactyl: DactylState = field(default_factory=DactylState)
    frame: Optional[np.ndarray] = None     # small mirrored BGR preview
    aspect: float = 4 / 3
    message: str = ""
    notice: str = ""         # one-shot toast text (shortcut fired, volume changed...)


class Engine:
    def __init__(self, settings: Settings, input_backend, on_state: Callable[[FrameState], None],
                 video_source: str = ""):
        self.s = settings
        self.input = input_backend
        self.on_state = on_state
        self.video_source = video_source
        self.mode = "mouse"
        self.menu_open = False
        self.menu_opened_at = 0.0
        self.preview_enabled = settings.ui.show_preview
        self.inject = True           # False in demo/test runs: compute everything, touch nothing
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._pending_settings: Optional[Settings] = None
        self._build()

    # ------------------------------------------------------------------ setup
    def _build(self) -> None:
        s = self.s
        self.stabilizer = HandStabilizer(s.tracking.landmark_smoothing, s.tracking.preferred_hand)
        self.gestures = GestureRecognizer(s.gestures)
        self.cursor = CursorController(s.cursor, s.gestures, self.input.screen_rect())
        self.pointer = PointerMapper()
        self.speller = Fingerspeller(s.dactyl)
        self.shortcuts = ShortcutDetector(s.gestures)
        self.button_down = False
        self.scrolling = False
        self.scroll_ref: Optional[np.ndarray] = None
        self.last_dactyl_space_t = -10.0

    def apply_settings(self, settings: Settings) -> None:
        with self._lock:
            self._pending_settings = settings

    # ------------------------------------------------------------------ control
    def set_mode(self, mode: str) -> None:
        with self._lock:
            if mode not in MODES:
                return
            self._release_all()
            self.mode = mode
            self.menu_open = False
            self.gestures.reset()
            self.speller.reset()
            self.shortcuts.reset()
            self.pointer.reset()
            self.cursor.reset(self.input.cursor_pos())

    def toggle_pause(self) -> None:
        self.set_mode("mouse" if self.mode == "paused" else "paused")

    def open_menu(self) -> None:
        with self._lock:
            self._release_all()
            self.menu_open = True
            self.menu_opened_at = time.perf_counter()
            self.pointer.reset()

    def close_menu(self) -> None:
        with self._lock:
            self.menu_open = False
            self.cursor.reset(self.input.cursor_pos())

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, name="engine", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._release_all()

    # ------------------------------------------------------------------ actions
    def _release_all(self) -> None:
        if self.button_down:
            if self.inject:
                self.input.button("left", False)
            self.button_down = False
        self.scrolling = False

    def _move(self, pos) -> None:
        if pos is not None and self.inject:
            self.input.move_to(*pos)

    # ------------------------------------------------------------------ loop
    def _run(self) -> None:
        cam_cfg = self.s.camera
        camera = Camera(cam_cfg.index, cam_cfg.width, cam_cfg.height, cam_cfg.fps, source=self.video_source)
        if not camera.start():
            self.on_state(FrameState(mode=self.mode, message=camera.error))
            self._running = False
            return
        try:
            tracker = MediaPipeTracker(self.s.tracking)
        except Exception as e:  # model download / runtime problems
            log.exception("tracker init failed")
            self.on_state(FrameState(mode=self.mode, message=f"Ошибка трекера: {e}"))
            camera.stop()
            return

        last_id, fps, t_prev = -1, 0.0, time.perf_counter()
        try:
            while self._running:
                item = camera.read(last_id)
                if item is None:
                    self.on_state(FrameState(mode=self.mode, message=camera.error or "Нет кадров с камеры"))
                    continue
                last_id, t_frame, frame = item
                with self._lock:
                    if self._pending_settings is not None:
                        self._reconfigure(self._pending_settings)
                    state = self._process(frame, t_frame, tracker)
                now = time.perf_counter()
                fps = 0.9 * fps + 0.1 / max(now - t_prev, 1e-3) if fps else 1 / max(now - t_prev, 1e-3)
                t_prev = now
                state.fps, state.latency_ms = fps, (now - t_frame) * 1000
                self.on_state(state)
        except Exception:
            log.exception("engine crashed")
        finally:
            self._release_all()
            tracker.close()
            camera.stop()

    def _reconfigure(self, settings: Settings) -> None:
        self.s = settings
        self._pending_settings = None
        self.gestures.cfg = settings.gestures
        self.cursor.gcfg = settings.gestures
        self.cursor.apply_settings(settings.cursor)
        self.speller.cfg = settings.dactyl
        self.shortcuts.cfg = settings.gestures
        self.stabilizer.preferred_hand = settings.tracking.preferred_hand
        self.stabilizer.filter.min_cutoff = settings.tracking.landmark_smoothing
        self.preview_enabled = settings.ui.show_preview

    def _process(self, frame: np.ndarray, t: float, tracker) -> FrameState:
        mirror = self.s.camera.mirror
        if mirror:
            frame = cv2.flip(frame, 1)
        h, w = frame.shape[:2]
        aspect = w / h
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        hands = tracker.process(rgb, int(t * 1000))
        tracked = self.stabilizer.update(hands, t, aspect)

        st = FrameState(t=t, mode=self.mode, aspect=aspect)
        if self.preview_enabled:
            pw = 480
            st.frame = cv2.resize(frame, (pw, int(pw * h / w)), interpolation=cv2.INTER_AREA)

        if self.menu_open and t - self.menu_opened_at > MENU_TIMEOUT_S:
            self.menu_open = False

        if tracked is None:
            gs = self.gestures.release()
            if gs.pinch_ended and self.mode == "mouse" and not self.menu_open:
                self._release_all()
            self.cursor.reset()
            self.pointer.reset()
            self.scrolling = False
            self.shortcuts.reset()
            if self.mode == "dactyl":
                st.dactyl = self.speller.update(None, "", mirror, aspect, t)
            st.gesture = gs
            st.menu_open = self.menu_open
            return st

        st.hand, st.landmarks, st.handedness, st.quality = True, tracked.norm, tracked.handedness, tracked.quality
        gs = self.gestures.update(tracked.norm, t, aspect)
        st.gesture = gs
        pts = g.aspect_correct(tracked.raw, aspect)
        anchor = g.palm_center(pts)

        if gs.menu_triggered:
            if self.menu_open:
                self.menu_open = False
            else:
                if self.mode == "dactyl" and t - self.last_dactyl_space_t < self.s.gestures.menu_hold_ms / 1000 + 0.6:
                    if self.inject:
                        self.input.key("backspace")    # undo the space typed by the same thumbs-up
                self.open_menu()

        if self.menu_open:
            st.pointer = self.pointer.update(anchor, t, aspect, center=(0.5, 0.5))
        elif self.mode == "mouse":
            self._mouse(gs, anchor, pts, t, aspect, st)
        elif self.mode == "keyboard":
            st.pointer = self.pointer.update(anchor, t, aspect, center=(0.5, 0.55))
        elif self.mode == "dactyl":
            ds = self.speller.update(tracked.raw, tracked.handedness, mirror, aspect, t)
            if ds.committed and gs.hold_progress == 0:
                self._type_dactyl(ds.committed, t)
            elif ds.committed:
                ds.committed = None      # thumbs-up is being held for the menu
            st.dactyl = ds
        st.menu_open = self.menu_open
        st.scrolling, st.dragging = self.scrolling, self.button_down and self.cursor.drag_free
        return st

    # ------------------------------------------------------------------ modes
    def _mouse(self, gs: GestureState, anchor: np.ndarray, pts: np.ndarray, t: float, aspect: float,
               st: FrameState) -> None:
        cur = self.input.cursor_pos()
        special = self.s.gestures.shortcuts_enabled and gs.pose in SPECIAL_POSES
        if self.s.gestures.shortcuts_enabled:
            ev = self.shortcuts.update(gs.pose, pts, gs.features.get("palm", 0.1), t)
            if ev is not None:
                self._fire(ev, st)
        if not self.inject and self.cursor.last_set is not None:
            cur = self.cursor.last_set          # engine-level dry run: the real cursor never moves
        # Scrolling: closed fist + move ("grab the page").
        fist = gs.pose == "fist" and gs.pinch is None and self.s.gestures.scroll_enabled
        if fist:
            if not self.scrolling:
                self.scrolling, self.scroll_ref = True, anchor[:2].copy()
            delta = anchor[:2] - self.scroll_ref
            self.scroll_ref = anchor[:2].copy()
            k = 28.0 * self.s.cursor.scroll_speed            # wheel notches per frame-height
            sign = 1.0 if self.s.cursor.natural_scroll else -1.0
            if np.linalg.norm(delta) > 0.002 and self.inject:
                self.input.scroll(-sign * delta[0] * k, sign * delta[1] * k)
            self.cursor.update(anchor, t, aspect, cur, frozen=True)
            return
        if self.scrolling:
            self.scrolling = False
            self.cursor.on_pinch_end(t)   # brief freeze while the hand reopens

        if gs.pinch_started:
            pos = self.cursor.on_pinch_start(t)
            self._move(pos)
            if gs.pinch == "left":
                if self.inject:
                    self.input.button("left", True)
                self.button_down = True
            elif gs.pinch == "right" and self.inject:
                self.input.button("right", True)
                self.input.button("right", False)
        if gs.pinch_ended:
            if self.button_down:
                if self.inject:
                    self.input.button("left", False)
                self.button_down = False
            self.cursor.on_pinch_end(t)

        frozen = gs.pinch == "right" or gs.hold_progress > 0 or special
        self._move(self.cursor.update(anchor, t, aspect, cur, frozen=frozen))

    def _fire(self, ev: ShortcutEvent, st: FrameState) -> None:
        st.notice = ev.text
        if not self.inject:
            return
        for _ in range(ev.repeat):
            for name, mods in ev.keys:
                self.input.key(name, mods)

    def _type_dactyl(self, text: str, t: float) -> None:
        if text == " ":
            self.last_dactyl_space_t = t
        if not self.inject:
            return
        if text == "\b":
            self.input.key("backspace")
        else:
            self.input.type_text(text)
