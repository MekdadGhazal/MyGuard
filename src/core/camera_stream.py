"""Safe webcam access: bounded resolution, deterministic release, no leaked handles."""
from __future__ import annotations

import logging
import sys
from typing import Optional

import cv2
import numpy as np

log = logging.getLogger(__name__)


class CameraError(RuntimeError):
    """Raised when the camera cannot be opened or read."""


class CameraStream:
    def __init__(self, index: int = 0, width: int = 640, height: int = 480,
                 max_width: int = 640, fps: int = 15) -> None:
        self._index = index
        self._size = (width, height)
        self._max_width = max_width
        self._fps = fps
        self._cap: Optional[cv2.VideoCapture] = None

    @property
    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    def open(self) -> None:
        self.release()
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        cap = cv2.VideoCapture(self._index, backend)
        if not cap.isOpened():
            cap.release()
            raise CameraError(
                f"Camera {self._index} unavailable (in use, disconnected, or permission denied)"
            )
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._size[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._size[1])
        cap.set(cv2.CAP_PROP_FPS, self._fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._cap = cap
        log.info("Camera %d opened", self._index)

    def read(self) -> np.ndarray:
        """Return a BGR frame, downscaled to `max_width` if larger."""
        if self._cap is None:
            raise CameraError("Camera is not open")
        ok, frame = self._cap.read()
        if not ok or frame is None or frame.size == 0:
            raise CameraError("Camera stopped delivering frames")
        h, w = frame.shape[:2]
        if w > self._max_width:
            scale = self._max_width / w
            frame = cv2.resize(frame, (self._max_width, int(h * scale)), interpolation=cv2.INTER_AREA)
        return frame

    def release(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            finally:
                self._cap = None
                log.info("Camera released")

    def __enter__(self) -> "CameraStream":
        self.open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()

    def __del__(self) -> None:
        try:
            self.release()
        except Exception:  # noqa: BLE001
            pass
