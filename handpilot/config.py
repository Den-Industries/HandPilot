"""User settings persisted as JSON in the per-user config directory."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields, is_dataclass

APP_NAME = "HandPilot"
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(PACKAGE_DIR, "assets")
MODELS_DIR = os.path.join(ASSETS_DIR, "models")


def config_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


@dataclass
class CameraSettings:
    index: int = 0
    width: int = 640
    height: int = 480
    fps: int = 30
    mirror: bool = True          # selfie view: moving the hand right moves the cursor right


@dataclass
class TrackingSettings:
    min_detection_confidence: float = 0.8
    min_presence_confidence: float = 0.65
    min_tracking_confidence: float = 0.6
    preferred_hand: str = "any"  # "any" | "Right" | "Left"
    landmark_smoothing: float = 1.0   # One Euro min cutoff for landmarks (Hz)


@dataclass
class CursorSettings:
    mode: str = "relative"       # "relative" (touchpad-like) | "absolute" (pointing)
    speed: float = 1.0           # base gain
    acceleration: float = 1.0    # 0 = linear; higher = faster for quick moves
    smoothing: float = 0.8       # One Euro min cutoff (Hz) – lower is smoother
    responsiveness: float = 0.6  # One Euro beta – higher reduces lag on fast moves
    active_area: float = 0.6     # absolute mode: fraction of the frame mapped to the screen
    scroll_speed: float = 1.0
    natural_scroll: bool = True  # content follows the hand, like a touchscreen


@dataclass
class GestureSettings:
    pinch_on: float = 0.36       # thumb–finger distance in palm sizes to start a pinch
    pinch_off: float = 0.50      # ...and to release it (hysteresis)
    drag_threshold: float = 0.02   # hand travel (frame heights) that turns a held pinch into a drag
    click_freeze_ms: int = 220   # cursor freezes this long after pinch onset
    menu_hold_ms: int = 1100     # thumbs-up hold to open the mode menu
    scroll_enabled: bool = True
    right_click_enabled: bool = True
    shortcuts_enabled: bool = True   # swipes (Alt+Tab...), media keys and the volume "knob"
    swipe_distance: float = 2.0      # hand travel in palm sizes that counts as a swipe
    knob_step_deg: float = 12.0      # hand tilt per volume step


@dataclass
class KeyboardSettings:
    layout: str = "ru"           # "ru" | "en"
    dwell_ms: int = 0            # 0 = pinch to press; >0 = also press by hovering
    height_fraction: float = 0.38
    opacity: float = 0.94
    suggestions: bool = True
    sound: bool = True


@dataclass
class DactylSettings:
    min_confidence: float = 0.45
    stable_ms: int = 120         # letter must be steady this long to be typed (tuned on recordings)


@dataclass
class UiSettings:
    show_preview: bool = True
    show_hud: bool = True
    first_run: bool = True
    hotkeys: bool = True
    autostart: bool = False


@dataclass
class Settings:
    camera: CameraSettings = field(default_factory=CameraSettings)
    tracking: TrackingSettings = field(default_factory=TrackingSettings)
    cursor: CursorSettings = field(default_factory=CursorSettings)
    gestures: GestureSettings = field(default_factory=GestureSettings)
    keyboard: KeyboardSettings = field(default_factory=KeyboardSettings)
    dactyl: DactylSettings = field(default_factory=DactylSettings)
    ui: UiSettings = field(default_factory=UiSettings)

    @property
    def path(self) -> str:
        return os.path.join(config_dir(), "settings.json")

    def save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        try:
            with open(s.path, encoding="utf-8") as f:
                _merge(s, json.load(f))
        except (OSError, ValueError):
            pass
        return s


def _merge(obj, data: dict) -> None:
    """Copy known keys from `data` into the dataclass tree, ignoring unknown/invalid ones."""
    for fl in fields(obj):
        if fl.name not in data:
            continue
        cur = getattr(obj, fl.name)
        val = data[fl.name]
        if is_dataclass(cur) and isinstance(val, dict):
            _merge(cur, val)
        elif isinstance(cur, bool):
            setattr(obj, fl.name, bool(val))
        elif isinstance(cur, (int, float, str)) and isinstance(val, (int, float, str)):
            try:
                setattr(obj, fl.name, type(cur)(val))
            except ValueError:
                pass
