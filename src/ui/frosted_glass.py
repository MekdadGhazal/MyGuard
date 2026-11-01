"""Full-screen frosted-glass privacy shield (one click-through overlay per monitor)."""
from __future__ import annotations

import logging
import sys
from typing import Optional

from PyQt6.QtCore import QEasingCurve, QObject, QPropertyAnimation, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap, QScreen
from PyQt6.QtWidgets import QWidget

from ..utils.config_manager import ConfigManager, Settings

log = logging.getLogger(__name__)


def _enable_acrylic(hwnd: int, tint_rgb: tuple[int, int, int], alpha: int) -> bool:
    """Windows 10/11 live acrylic blur-behind via SetWindowCompositionAttribute."""
    import ctypes

    class AccentPolicy(ctypes.Structure):
        _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                    ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]

    class WinCompAttrData(ctypes.Structure):
        _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p), ("SizeOfData", ctypes.c_size_t)]

    r, g, b = tint_rgb
    accent = AccentPolicy(4, 2, (alpha << 24) | (b << 16) | (g << 8) | r, 0)  # ACRYLICBLURBEHIND
    data = WinCompAttrData(19, ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p), ctypes.sizeof(accent))
    return bool(ctypes.windll.user32.SetWindowCompositionAttribute(int(hwnd), ctypes.byref(data)))


def _blur(pixmap: QPixmap, strength: int) -> QPixmap:
    """Cheap, GPU-free blur: repeated smooth down/up-scaling."""
    img = pixmap.toImage()
    w, h = img.width(), img.height()
    k = 2 + strength
    steps = [max(1, w // k), max(1, w // max(2, k // 2)), max(1, w // max(2, k // 4)), w]
    ratio = h / w
    cur = img
    for width in steps:
        cur = cur.scaled(width, max(1, int(width * ratio)), Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    out = QPixmap.fromImage(cur.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation))
    out.setDevicePixelRatio(pixmap.devicePixelRatio())
    return out


class _ShieldWindow(QWidget):
    def __init__(self, screen: QScreen, s: Settings) -> None:
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput
                 | Qt.WindowType.WindowDoesNotAcceptFocus)
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._tint = QColor(255, 255, 255, int(255 * s.shield_opacity))
        self._pix: Optional[QPixmap] = None
        self._native = False

        # Snapshot BEFORE showing, so the overlay never captures itself.
        if not (sys.platform == "win32" and s.native_blur):
            shot = screen.grabWindow(0)
            if not shot.isNull():
                self._pix = _blur(shot, s.blur_strength)
        self.setGeometry(screen.geometry())
        self.setWindowOpacity(0.0)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.show()
        if sys.platform == "win32" and s.native_blur:
            try:
                self._native = _enable_acrylic(self.winId(), (240, 240, 245), int(255 * s.shield_opacity))
            except Exception:  # noqa: BLE001
                log.exception("Native acrylic failed; using plain tint")
            if not self._native:
                self._tint = QColor(30, 30, 34, 200)

    def fade_to(self, value: float, ms: int = 220) -> None:
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(value)
        self._fade.setDuration(ms)
        self._fade.start()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        if self._pix is not None:
            p.drawPixmap(self.rect(), self._pix)
        p.fillRect(self.rect(), QColor(0, 0, 0, 1) if self._native else self._tint)


class FrostedGlassShield(QObject):
    def __init__(self, config: ConfigManager) -> None:
        super().__init__()
        self._config = config
        self._windows: list[_ShieldWindow] = []
        self._active = False

    def show_shield(self) -> None:
        s = self._config.settings
        if not s.blur_screen:
            return
        self._active = True
        if self._windows:  # still fading out: just fade back in
            for w in self._windows:
                w.fade_to(1.0)
            return
        for screen in QGuiApplication.screens():
            w = _ShieldWindow(screen, s)
            w._fade.finished.connect(self._cleanup_if_hidden)
            self._windows.append(w)
            w.fade_to(1.0)

    def hide_shield(self, immediate: bool = False) -> None:
        self._active = False
        for w in self._windows:
            w.fade_to(0.0, 1 if immediate else 260)
        if immediate:
            self._cleanup_if_hidden()

    def _cleanup_if_hidden(self) -> None:
        if self._active or not self._windows:
            return
        if all(w.windowOpacity() < 0.02 for w in self._windows):
            for w in self._windows:
                w.close()
                w.deleteLater()
            self._windows = []
