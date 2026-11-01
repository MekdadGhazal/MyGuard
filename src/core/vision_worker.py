"""Background QThread: capture -> Tier 1 detect -> Tier 2 recognise -> threat state machine."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage

from ..utils.config_manager import ConfigManager, Settings
from .camera_stream import CameraError, CameraStream
from .face_detector import FaceDetection, FaceDetector
from .face_recognizer import FaceRecognizer, TrustedFaceStore

log = logging.getLogger(__name__)


@dataclass
class _Track:
    threat: bool = False
    streak: int = 0
    last_stranger: float = 0.0
    verified: frozenset = frozenset()
    verified_at: float = 0.0


def _to_qimage(frame_bgr: np.ndarray, faces: list[FaceDetection]) -> QImage:
    view = frame_bgr.copy()
    for f in faces:
        cv2.rectangle(view, (f.x, f.y), (f.x + f.w, f.y + f.h), (80, 210, 48), 2)
    rgb = cv2.cvtColor(cv2.flip(view, 1), cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


class VisionWorker(QThread):
    threat_detected = pyqtSignal(int)        # number of unauthorised viewers
    threat_cleared = pyqtSignal()
    trusted_verified = pyqtSignal(str)       # names of recognised trusted viewers
    camera_state = pyqtSignal(bool, str)     # ok, message
    error_occurred = pyqtSignal(str)
    preview_frame = pyqtSignal(QImage)       # enrollment preview only
    enrollment_sample = pyqtSignal(object)   # np.ndarray embedding
    enrollment_failed = pyqtSignal(str)

    def __init__(self, config: ConfigManager, store: TrustedFaceStore, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._store = store
        self._stop_evt = threading.Event()
        self._protect = threading.Event()
        if config.settings.protection_enabled:
            self._protect.set()
        self._enroll = threading.Event()
        self._sample_req = threading.Event()
        self._recognizer: Optional[FaceRecognizer] = None
        self._recognizer_retry_at = 0.0
        self._camera_ok: Optional[bool] = None
        self._track = _Track()

    # ---- thread-safe controls (called from the GUI thread) ----
    def set_protection(self, enabled: bool) -> None:
        (self._protect.set if enabled else self._protect.clear)()

    def set_enrollment_mode(self, enabled: bool) -> None:
        (self._enroll.set if enabled else self._enroll.clear)()
        self._sample_req.clear()

    def request_sample(self) -> None:
        self._sample_req.set()

    def stop(self) -> None:
        self._stop_evt.set()

    # ---- thread body ----
    def run(self) -> None:
        cv2.setNumThreads(1)  # keep CPU use low and predictable
        try:
            detector = FaceDetector(self._config.settings.detection_confidence)
        except Exception as exc:  # noqa: BLE001
            log.exception("Face detector initialisation failed")
            self.error_occurred.emit(f"Face detector unavailable: {exc}")
            return
        camera: Optional[CameraStream] = None
        try:
            while not self._stop_evt.is_set():
                s = self._config.settings
                enrolling = self._enroll.is_set()
                if not (self._protect.is_set() or enrolling):
                    camera = self._close(camera)
                    self._end_threat()
                    self._camera_ok = None
                    self._stop_evt.wait(0.25)
                    continue
                if camera is None:
                    camera = self._open(s)
                    if camera is None:
                        self._stop_evt.wait(3.0)
                        continue
                started = time.monotonic()
                try:
                    frame = camera.read()
                except CameraError as exc:
                    log.warning("Camera lost: %s", exc)
                    camera = self._close(camera)
                    self._end_threat()
                    self._set_camera_state(False, str(exc))
                    self._stop_evt.wait(2.0)
                    continue
                try:
                    detector.set_confidence(s.detection_confidence)
                    self._process(frame, detector, s, enrolling)
                except Exception:  # noqa: BLE001
                    log.exception("Frame processing failed")
                fps = 10.0 if enrolling else s.detection_fps
                self._stop_evt.wait(max(0.0, 1.0 / fps - (time.monotonic() - started)))
        finally:
            self._close(camera)
            detector.close()

    # ---- helpers ----
    def _open(self, s: Settings) -> Optional[CameraStream]:
        cam = CameraStream(s.camera_index)
        try:
            cam.open()
        except CameraError as exc:
            self._set_camera_state(False, str(exc))
            return None
        self._set_camera_state(True, "")
        return cam

    @staticmethod
    def _close(camera: Optional[CameraStream]) -> None:
        if camera is not None:
            camera.release()
        return None

    def _set_camera_state(self, ok: bool, msg: str) -> None:
        if self._camera_ok != ok:
            self._camera_ok = ok
            self.camera_state.emit(ok, msg)

    def _end_threat(self) -> None:
        if self._track.threat:
            self.threat_cleared.emit()
        self._track = _Track()

    def _get_recognizer(self) -> Optional[FaceRecognizer]:
        if self._recognizer is not None:
            return self._recognizer
        now = time.monotonic()
        if now < self._recognizer_retry_at:
            return None
        try:
            self._recognizer = FaceRecognizer()
        except Exception as exc:  # noqa: BLE001
            self._recognizer_retry_at = now + 30.0
            log.error("Recognizer unavailable: %s", exc)
            self.error_occurred.emit(f"Recognition model unavailable: {exc}")
        return self._recognizer

    def _process(self, frame: np.ndarray, detector: FaceDetector, s: Settings, enrolling: bool) -> None:
        min_w = s.min_face_ratio * frame.shape[1]
        faces = [f for f in detector.detect(frame) if f.w >= min_w]
        faces.sort(key=lambda f: f.area, reverse=True)
        if enrolling:
            self._enrollment_step(frame, faces)
        else:
            self._evaluate(frame, faces, s)

    def _enrollment_step(self, frame: np.ndarray, faces: list[FaceDetection]) -> None:
        self.preview_frame.emit(_to_qimage(frame, faces))
        if not self._sample_req.is_set():
            return
        self._sample_req.clear()
        if not faces:
            self.enrollment_failed.emit("No face detected. Look at the camera.")
        elif len(faces) > 1:
            self.enrollment_failed.emit("More than one face in view.")
        else:
            rec = self._get_recognizer()
            emb = rec.embed(frame, faces[0]) if rec else None
            if rec is None:
                self.enrollment_failed.emit("Recognition model unavailable (see log).")
            elif emb is None:
                self.enrollment_failed.emit("Could not align the face. Face the camera directly.")
            else:
                self.enrollment_sample.emit(emb)

    def _evaluate(self, frame: np.ndarray, faces: list[FaceDetection], s: Settings) -> None:
        st = self._track
        now = time.monotonic()
        has_whitelist = not self._store.is_empty()
        # Tier 2 only runs when there is someone besides the primary user (largest face).
        candidates = faces if (s.verify_primary and has_whitelist) else faces[1:]
        strangers, verified = 0, []
        recognizer = self._get_recognizer() if (candidates and has_whitelist) else None
        for face in candidates:
            if not face.is_facing(s.max_yaw):
                continue  # looking away: not a threat
            match = None
            if recognizer is not None:
                emb = recognizer.embed(frame, face)
                match = self._store.match(emb, s.match_threshold) if emb is not None else None
            if match is not None:
                verified.append(match.name)
            else:
                strangers += 1  # unknown, or recogniser unavailable (fail-safe)

        if strangers:
            st.streak += 1
            st.last_stranger = now
            if not st.threat and st.streak >= s.confirm_frames:
                st.threat = True
                self.threat_detected.emit(strangers)
        else:
            st.streak = 0
            if st.threat and (now - st.last_stranger) * 1000.0 >= s.clear_delay_ms:
                st.threat = False
                self.threat_cleared.emit()

        current = frozenset(verified)
        if current and not st.threat and current != st.verified:
            self.trusted_verified.emit(", ".join(sorted(current)))
        if current or now - st.verified_at > 3.0:
            st.verified = current
        if current:
            st.verified_at = now
