"""Persistent user settings and shared filesystem locations."""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import threading
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)

APP_NAME = "MyGuard"
FROZEN = getattr(sys, "frozen", False)  # True inside the PyInstaller build


def _user_data_dir() -> Path:
    """Per-user writable data folder (Windows: %APPDATA%\\MyGuard)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / APP_NAME


if FROZEN:
    PROJECT_ROOT = Path(sys.executable).resolve().parent            # install folder
    ASSETS_DIR = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT)) / "assets"  # bundled, read-only
    DATA_DIR = _user_data_dir()
else:
    PROJECT_ROOT = Path(__file__).resolve().parents[2]
    ASSETS_DIR = PROJECT_ROOT / "assets"
    # Windows: %APPDATA%\MyGuard ; during development on other systems keep ./data
    DATA_DIR = _user_data_dir() if sys.platform == "win32" else PROJECT_ROOT / "data"
MODELS_DIR = DATA_DIR / "models"
SETTINGS_FILE = DATA_DIR / "settings.json"


def atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON atomically (temp file + rename); the file is owner-only (0600)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@dataclass(frozen=True)
class Settings:
    camera_index: int = 0
    detection_fps: float = 5.0          # inference rate (frames per second)
    detection_confidence: float = 0.6   # MediaPipe min confidence (lower = more sensitive)
    min_face_ratio: float = 0.05        # ignore faces narrower than this fraction of frame width
    max_yaw: float = 0.55               # facing tolerance; larger = counts more head angles as "looking"
    match_threshold: float = 0.363      # SFace cosine similarity threshold
    confirm_frames: int = 2             # consecutive frames before raising an alert
    clear_delay_ms: int = 1500          # grace period before clearing an alert
    verify_primary: bool = False        # also verify the largest face against the whitelist
    show_island: bool = True            # action: Dynamic Island notification
    blur_screen: bool = True            # action: frosted-glass screen shield
    play_sound: bool = False            # action: alert tone
    blur_strength: int = 14             # 1..40
    shield_opacity: float = 0.45        # white tint strength over the blur, 0..0.9
    native_blur: bool = True            # use OS acrylic blur where available (Windows)
    run_on_startup: bool = False
    protection_enabled: bool = True


_RANGES = {
    "camera_index": (0, 16),
    "detection_fps": (1.0, 10.0),
    "detection_confidence": (0.3, 0.95),
    "min_face_ratio": (0.02, 0.5),
    "max_yaw": (0.2, 1.0),
    "match_threshold": (0.2, 0.8),
    "confirm_frames": (1, 10),
    "clear_delay_ms": (200, 10000),
    "blur_strength": (1, 40),
    "shield_opacity": (0.0, 0.9),
}


def _sanitize(raw: dict[str, Any]) -> Settings:
    defaults = Settings()
    values: dict[str, Any] = {}
    for f in fields(Settings):
        default = getattr(defaults, f.name)
        value = raw.get(f.name, default)
        try:
            value = bool(value) if isinstance(default, bool) else type(default)(value)
        except (TypeError, ValueError):
            value = default
        if f.name in _RANGES:
            lo, hi = _RANGES[f.name]
            value = type(default)(min(max(value, lo), hi))
        values[f.name] = value
    return Settings(**values)


class ConfigManager(QObject):
    """Thread-safe settings holder. `settings` is an immutable snapshot."""

    changed = pyqtSignal()

    def __init__(self, path: Path = SETTINGS_FILE) -> None:
        super().__init__()
        self._path = path
        self._lock = threading.Lock()
        self._settings = Settings()

    @property
    def settings(self) -> Settings:
        return self._settings

    def load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("settings root must be an object")
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            log.warning("Ignoring unreadable settings file: %s", exc)
            return
        with self._lock:
            self._settings = _sanitize(raw)

    def update(self, **changes: Any) -> None:
        with self._lock:
            self._settings = _sanitize({**asdict(self._settings), **changes})
            snapshot = asdict(self._settings)
        try:
            atomic_write_json(self._path, snapshot)
        except OSError as exc:
            log.error("Could not save settings: %s", exc)
        self.changed.emit()
