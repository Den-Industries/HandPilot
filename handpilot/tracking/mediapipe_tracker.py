"""MediaPipe Tasks HandLandmarker backend.

Uses the Tasks API (not the deprecated `mp.solutions`) in VIDEO mode, which
tracks hands between frames and only re-runs palm detection when tracking is
lost. The model file is downloaded once into assets/models.
"""
from __future__ import annotations

import logging
import os
import urllib.request

import numpy as np

from ..config import MODELS_DIR, TrackingSettings
from .base import HandObservation

log = logging.getLogger(__name__)

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/latest/hand_landmarker.task")
MODEL_PATH = os.path.join(MODELS_DIR, "hand_landmarker.task")


def ensure_model() -> str:
    if not os.path.exists(MODEL_PATH):
        os.makedirs(MODELS_DIR, exist_ok=True)
        log.info("Downloading hand landmark model…")
        tmp = MODEL_PATH + ".part"
        urllib.request.urlretrieve(MODEL_URL, tmp)
        os.replace(tmp, MODEL_PATH)
    return MODEL_PATH


class MediaPipeTracker:
    name = "mediapipe"

    def __init__(self, cfg: TrackingSettings, num_hands: int = 2):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        self._mp = mp
        # Read the model into memory: MediaPipe cannot open paths with
        # non-ASCII characters on Windows (e.g. a Cyrillic user name).
        with open(ensure_model(), "rb") as f:
            model_bytes = f.read()
        options = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_buffer=model_bytes),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=num_hands,
            min_hand_detection_confidence=cfg.min_detection_confidence,
            min_hand_presence_confidence=cfg.min_presence_confidence,
            min_tracking_confidence=cfg.min_tracking_confidence,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)
        self._last_ts = -1

    def process(self, rgb: np.ndarray, timestamp_ms: int) -> list[HandObservation]:
        ts = max(int(timestamp_ms), self._last_ts + 1)   # must be strictly increasing
        self._last_ts = ts
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        res = self._landmarker.detect_for_video(image, ts)
        out = []
        for i, lms in enumerate(res.hand_landmarks):
            norm = np.array([[p.x, p.y, p.z] for p in lms], dtype=np.float32)
            world = None
            if res.hand_world_landmarks and i < len(res.hand_world_landmarks):
                world = np.array([[p.x, p.y, p.z] for p in res.hand_world_landmarks[i]], dtype=np.float32)
            cat = res.handedness[i][0] if res.handedness and i < len(res.handedness) else None
            out.append(HandObservation(norm=norm, world=world,
                                       handedness=cat.category_name if cat else "Right",
                                       score=float(cat.score) if cat else 1.0))
        return out

    def close(self) -> None:
        self._landmarker.close()
