"""Threaded camera capture that always hands out the newest frame (no backlog lag)."""
from __future__ import annotations

import logging
import sys
import threading
import time
from typing import Optional

import cv2
import numpy as np

log = logging.getLogger(__name__)


def list_cameras(max_index: int = 6) -> list[int]:
    found = []
    for i in range(max_index):
        cap = _open(i)
        if cap is not None and cap.isOpened():
            found.append(i)
            cap.release()
    return found


def _disable_exposure_fps_drop(index: int) -> None:
    """Linux/UVC: with 'exposure_auto_priority' on, the camera lengthens the exposure in
    dim light and silently drops to 5-10 fps. Turning it off keeps the full frame rate
    (brightness is unchanged: auto exposure still works, just capped by the frame time)."""
    try:
        import fcntl
        import struct
        V4L2_CID_EXPOSURE_AUTO_PRIORITY, VIDIOC_S_CTRL = 0x009A0903, 0xC008561C
        with open(f"/dev/video{index}", "rb", buffering=0) as dev:
            fcntl.ioctl(dev, VIDIOC_S_CTRL, struct.pack("Ii", V4L2_CID_EXPOSURE_AUTO_PRIORITY, 0))
    except Exception as e:   # not a UVC camera / no permission: nothing to do
        log.debug("exposure_auto_priority not changed: %s", e)


def _open(index: int):
    if sys.platform == "win32":
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)   # opens much faster than MSMF
    elif sys.platform.startswith("linux"):
        cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
    else:
        cap = cv2.VideoCapture(index)
    return cap


class Camera:
    def __init__(self, index: int = 0, width: int = 640, height: int = 480, fps: int = 30, source: str = ""):
        self.index, self.width, self.height, self.fps = index, width, height, fps
        self.source = source            # optional video file (for demos/tests)
        self._cap = None
        self._lock = threading.Lock()
        self._frame: Optional[np.ndarray] = None
        self._frame_t = 0.0
        self._frame_id = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.error: str = ""

    def start(self) -> bool:
        if self.source:
            self._cap = cv2.VideoCapture(self.source)
        else:
            linux = sys.platform.startswith("linux")
            # Linux: raw YUYV avoids the 'Corrupt JPEG' frames cheap UVC cams produce in MJPG
            # and the decode cost; fall back to MJPG if it cannot hold the frame rate.
            first, second = ("YUYV", "MJPG") if linux else ("MJPG", "YUYV")
            self._cap = self._configure(first)
            if (self._cap is not None and self._cap.isOpened() and linux and not self._healthy()):
                log.warning("%s stream is unstable, falling back to %s", first, second)
                self._cap.release()
                self._cap = self._configure(second)
        if self._cap is None or not self._cap.isOpened():
            self.error = f"Не удалось открыть камеру #{self.index}"
            return False
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="camera", daemon=True)
        self._thread.start()
        return True

    def _configure(self, fourcc: str):
        cap = _open(self.index)
        if cap is not None and cap.isOpened():
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            cap.set(cv2.CAP_PROP_FPS, self.fps)
            if sys.platform.startswith("linux"):
                # A single V4L2 buffer halves the frame rate (camera idles while we hold
                # it); the reader thread below drains frames, so no backlog builds up.
                _disable_exposure_fps_drop(self.index)
            else:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _healthy(self, warmup: int = 15, frames: int = 20, budget_s: float = 5.0) -> bool:
        """Unhealthy if reads fail or the steady-state rate is far below target.

        Auto exposure needs a moment after opening, so the first frames are ignored."""
        bad, good, t0, t_mark = 0, 0, time.perf_counter(), 0.0
        while good < warmup + frames and time.perf_counter() - t0 < budget_s:
            ok, _ = self._cap.read()
            if ok:
                good += 1
                if good == warmup:
                    t_mark = time.perf_counter()
            else:
                bad += 1
        if good < warmup + frames:
            return False
        rate = frames / max(time.perf_counter() - t_mark, 1e-3)
        return bad <= 2 and rate >= 0.7 * self.fps

    def _loop(self) -> None:
        period = 1.0 / (self._cap.get(cv2.CAP_PROP_FPS) or 30) if self.source else 0
        while self._running:
            ok, frame = self._cap.read()
            if not ok:
                if self.source:          # loop demo videos
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                self.error = "Камера перестала отдавать кадры"
                time.sleep(0.05)
                continue
            with self._lock:
                self._frame = frame
                self._frame_t = time.perf_counter()
                self._frame_id += 1
            if period:
                time.sleep(period)

    def read(self, last_id: int = -1, timeout: float = 0.5):
        """Waits for a frame newer than `last_id`; returns (frame_id, t, frame) or None."""
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline and self._running:
            with self._lock:
                if self._frame is not None and self._frame_id != last_id:
                    return self._frame_id, self._frame_t, self._frame
            time.sleep(0.002)
        return None

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if self._cap is not None:
            self._cap.release()
            self._cap = None
