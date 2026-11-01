"""Settings dialog."""
from __future__ import annotations

from PyQt6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                             QSpinBox)

from ..utils.config_manager import ConfigManager


def _dspin(lo: float, hi: float, step: float, value: float, decimals: int = 2) -> QDoubleSpinBox:
    w = QDoubleSpinBox()
    w.setRange(lo, hi)
    w.setSingleStep(step)
    w.setDecimals(decimals)
    w.setValue(value)
    return w


def _spin(lo: int, hi: int, value: int, suffix: str = "") -> QSpinBox:
    w = QSpinBox()
    w.setRange(lo, hi)
    w.setValue(value)
    w.setSuffix(suffix)
    return w


class SettingsDialog(QDialog):
    def __init__(self, config: ConfigManager, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("MyGuard - Settings")
        self._config = config
        s = config.settings
        self._w = {
            "camera_index": _spin(0, 16, s.camera_index),
            "detection_fps": _dspin(1, 10, 1, s.detection_fps, 1),
            "detection_confidence": _dspin(0.3, 0.95, 0.05, s.detection_confidence),
            "match_threshold": _dspin(0.2, 0.8, 0.01, s.match_threshold, 3),
            "confirm_frames": _spin(1, 10, s.confirm_frames),
            "clear_delay_ms": _spin(200, 10000, s.clear_delay_ms, " ms"),
            "blur_strength": _spin(1, 40, s.blur_strength),
            "shield_opacity": _dspin(0.0, 0.9, 0.05, s.shield_opacity),
            "show_island": QCheckBox("Dynamic Island notification"),
            "blur_screen": QCheckBox("Frosted-glass screen shield"),
            "play_sound": QCheckBox("Alert sound"),
            "verify_primary": QCheckBox("Also verify the main user against trusted faces"),
            "run_on_startup": QCheckBox("Start with the system"),
        }
        for key in ("show_island", "blur_screen", "play_sound", "verify_primary", "run_on_startup"):
            self._w[key].setChecked(getattr(s, key))
        form = QFormLayout(self)
        labels = [
            ("camera_index", "Camera index"), ("detection_fps", "Detection rate (FPS)"),
            ("detection_confidence", "Detection confidence (lower = more sensitive)"),
            ("match_threshold", "Face match threshold (higher = stricter)"),
            ("confirm_frames", "Frames to confirm a threat"), ("clear_delay_ms", "Clear delay"),
            ("blur_strength", "Blur strength"), ("shield_opacity", "Shield tint opacity"),
        ]
        for key, text in labels:
            form.addRow(text, self._w[key])
        for key in ("show_island", "blur_screen", "play_sound", "verify_primary", "run_on_startup"):
            form.addRow(self._w[key])
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict:
        out = {}
        for key, w in self._w.items():
            out[key] = w.isChecked() if isinstance(w, QCheckBox) else w.value()
        return out
