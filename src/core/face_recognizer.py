"""Tier 2: local face embeddings (OpenCV SFace, 128-D) and the trusted-face database."""
from __future__ import annotations

import logging
import os
import shutil
import threading
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from ..utils.config_manager import ASSETS_DIR, MODELS_DIR, atomic_write_json
from .face_detector import FaceDetection

log = logging.getLogger(__name__)

MODEL_NAME = "face_recognition_sface_2021dec.onnx"
MODEL_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_recognition_sface/" + MODEL_NAME
)
_MIN_MODEL_BYTES = 1_000_000
EMBEDDING_DIM = 128

# ArcFace/SFace 112x112 template: right eye, left eye, nose tip, mouth centre
_TEMPLATE = np.array(
    [[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366], [56.1396, 92.2848]],
    dtype=np.float32,
)


class RecognizerError(RuntimeError):
    pass


def ensure_model(directory: Path = MODELS_DIR) -> Path:
    """Return the SFace model path, downloading it once (~37 MB) if missing."""
    bundled = ASSETS_DIR / "models" / MODEL_NAME  # shipped inside the installer
    if bundled.exists() and bundled.stat().st_size > _MIN_MODEL_BYTES:
        return bundled
    path = directory / MODEL_NAME
    if path.exists() and path.stat().st_size > _MIN_MODEL_BYTES:
        return path
    directory.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    try:
        log.info("Downloading face model from %s", MODEL_URL)
        with urllib.request.urlopen(MODEL_URL, timeout=30) as resp, open(tmp, "wb") as out:
            shutil.copyfileobj(resp, out)
        if tmp.stat().st_size < _MIN_MODEL_BYTES:
            raise RecognizerError("Downloaded model file is invalid")
        os.replace(tmp, path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise RecognizerError(
            f"Could not download the face model. Place {MODEL_NAME} in {directory} manually. ({exc})"
        ) from exc
    return path


class FaceRecognizer:
    def __init__(self, model_path: Optional[Path] = None) -> None:
        path = model_path or ensure_model()
        try:
            self._rec = cv2.FaceRecognizerSF.create(str(path), "")
        except (cv2.error, AttributeError) as exc:
            raise RecognizerError(f"Cannot load face model: {exc}") from exc

    @staticmethod
    def _align(frame: np.ndarray, keypoints: np.ndarray) -> Optional[np.ndarray]:
        matrix, _ = cv2.estimateAffinePartial2D(
            keypoints[:4].astype(np.float32), _TEMPLATE, method=cv2.LMEDS
        )
        if matrix is None:
            return None
        return cv2.warpAffine(frame, matrix, (112, 112), flags=cv2.INTER_LINEAR)

    def embed(self, frame_bgr: np.ndarray, face: FaceDetection) -> Optional[np.ndarray]:
        aligned = self._align(frame_bgr, face.keypoints)
        if aligned is None:
            return None
        vec = self._rec.feature(aligned).reshape(-1).astype(np.float32)
        norm = float(np.linalg.norm(vec))
        return vec / norm if norm > 0 else None


@dataclass(frozen=True)
class MatchResult:
    face_id: str
    name: str
    role: str
    score: float


@dataclass(frozen=True)
class TrustedFace:
    face_id: str
    name: str
    role: str
    samples: int
    created: str


class TrustedFaceStore:
    """Thread-safe whitelist persisted as JSON (embeddings only, no images)."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._faces: list[dict] = []
        self._matrix = np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        self._owner: list[int] = []

    def load(self) -> None:
        with self._lock:
            self._faces = []
            if self._path.exists():
                try:
                    import json

                    raw = json.loads(self._path.read_text(encoding="utf-8"))
                    for f in raw["faces"]:
                        embs = [e for e in f["embeddings"] if len(e) == EMBEDDING_DIM]
                        if embs:
                            self._faces.append({
                                "id": str(f["id"]), "name": str(f["name"]),
                                "role": str(f.get("role", "Friend")),
                                "created": str(f.get("created", "")), "embeddings": embs,
                            })
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    backup = self._path.with_suffix(".corrupt")
                    log.error("Trusted-face file unreadable (%s); moved to %s", exc, backup)
                    try:
                        os.replace(self._path, backup)
                    except OSError:
                        pass
                    self._faces = []
            self._rebuild()

    def _save(self) -> None:
        atomic_write_json(self._path, {"version": 1, "faces": self._faces})

    def _rebuild(self) -> None:
        vectors, owners = [], []
        for i, face in enumerate(self._faces):
            for emb in face["embeddings"]:
                v = np.asarray(emb, dtype=np.float32)
                n = float(np.linalg.norm(v))
                if n > 0:
                    vectors.append(v / n)
                    owners.append(i)
        self._matrix = np.stack(vectors) if vectors else np.zeros((0, EMBEDDING_DIM), np.float32)
        self._owner = owners

    def add(self, name: str, role: str, embeddings: list[np.ndarray]) -> TrustedFace:
        record = {
            "id": uuid.uuid4().hex[:12], "name": name.strip() or "Unnamed", "role": role,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "embeddings": [[round(float(x), 6) for x in e] for e in embeddings],
        }
        with self._lock:
            self._faces.append(record)
            try:
                self._save()
            except OSError:
                self._faces.pop()
                raise
            self._rebuild()
        return TrustedFace(record["id"], record["name"], role, len(embeddings), record["created"])

    def remove(self, face_id: str) -> bool:
        with self._lock:
            before = list(self._faces)
            self._faces = [f for f in self._faces if f["id"] != face_id]
            if len(self._faces) == len(before):
                return False
            try:
                self._save()
            except OSError:
                self._faces = before
                raise
            self._rebuild()
            return True

    def list_faces(self) -> list[TrustedFace]:
        with self._lock:
            return [TrustedFace(f["id"], f["name"], f["role"], len(f["embeddings"]), f["created"])
                    for f in self._faces]

    def is_empty(self) -> bool:
        with self._lock:
            return len(self._owner) == 0

    def match(self, embedding: np.ndarray, threshold: float) -> Optional[MatchResult]:
        with self._lock:
            if not self._owner:
                return None
            sims = self._matrix @ embedding
            idx = int(np.argmax(sims))
            best = float(sims[idx])
            if best < threshold:
                return None
            face = self._faces[self._owner[idx]]
            return MatchResult(face["id"], face["name"], face["role"], best)
