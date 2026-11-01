"""Tier 1: ultra-fast face detection (MediaPipe short-range model)."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class FaceDetection:
    x: int
    y: int
    w: int
    h: int
    score: float
    # (6, 2) pixel coords: right eye, left eye, nose tip, mouth centre, right ear, left ear
    keypoints: np.ndarray

    @property
    def area(self) -> int:
        return self.w * self.h

    def yaw_ratio(self) -> float:
        """Cheap head-yaw proxy: nose offset from eye midpoint / inter-eye distance (0 = frontal)."""
        r_eye, l_eye, nose = self.keypoints[0], self.keypoints[1], self.keypoints[2]
        eye_dist = abs(float(l_eye[0] - r_eye[0]))
        if eye_dist < 1.0:
            return 9.0
        mid = float(r_eye[0] + l_eye[0]) / 2.0
        return abs(float(nose[0]) - mid) / eye_dist

    def is_facing(self, max_yaw: float) -> bool:
        return self.yaw_ratio() <= max_yaw


class FaceDetector:
    def __init__(self, min_confidence: float = 0.6) -> None:
        try:
            import mediapipe as mp
        except ImportError as exc:  # pragma: no cover
            raise ImportError("mediapipe is required: pip install -r requirements.txt") from exc
        self._mp_fd = mp.solutions.face_detection
        self._confidence = min_confidence
        self._det = self._make(min_confidence)

    def _make(self, confidence: float):
        return self._mp_fd.FaceDetection(model_selection=0, min_detection_confidence=confidence)

    def set_confidence(self, confidence: float) -> None:
        if abs(confidence - self._confidence) > 1e-6:
            self._det.close()
            self._confidence = confidence
            self._det = self._make(confidence)

    def detect(self, frame_bgr: np.ndarray) -> list[FaceDetection]:
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        result = self._det.process(rgb)
        faces: list[FaceDetection] = []
        for det in result.detections or []:
            loc = det.location_data
            kps = np.array([[k.x * w, k.y * h] for k in loc.relative_keypoints], dtype=np.float32)
            if kps.shape[0] < 4:
                continue
            bb = loc.relative_bounding_box
            x0, y0 = max(0, int(bb.xmin * w)), max(0, int(bb.ymin * h))
            x1, y1 = min(w, int((bb.xmin + bb.width) * w)), min(h, int((bb.ymin + bb.height) * h))
            if x1 <= x0 or y1 <= y0:
                continue
            faces.append(FaceDetection(x0, y0, x1 - x0, y1 - y0, float(det.score[0]), kps))
        return faces

    def close(self) -> None:
        self._det.close()
