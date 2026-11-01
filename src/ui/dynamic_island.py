"""Animated top-centre capsule ("Dynamic Island")."""
from __future__ import annotations

import math
from enum import Enum, auto

from PyQt6.QtCore import (QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer,
                          QVariantAnimation, pyqtProperty)
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget


class IslandState(Enum):
    IDLE = auto()
    PAUSED = auto()
    SAFE = auto()
    ALERT = auto()
    ERROR = auto()


_GREEN, _RED, _GREY, _AMBER = QColor("#30D158"), QColor("#FF453A"), QColor("#8E8E93"), QColor("#FFD60A")
_SPECS = {
    IslandState.IDLE: (QSize(150, 34), _GREEN, "Protected"),
    IslandState.PAUSED: (QSize(130, 34), _GREY, "Paused"),
    IslandState.SAFE: (QSize(260, 44), _GREEN, "Trusted viewer"),
    IslandState.ALERT: (QSize(370, 58), _RED, "Unauthorized Viewer Detected"),
    IslandState.ERROR: (QSize(260, 40), _AMBER, "Camera unavailable"),
}


class DynamicIsland(QWidget):
    _WIN_W, _WIN_H, _TOP = 430, 90, 6

    def __init__(self) -> None:
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus
                 | Qt.WindowType.WindowTransparentForInput)
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.resize(self._WIN_W, self._WIN_H)

        self._enabled = True
        self._state = IslandState.IDLE
        self._rest = (IslandState.IDLE, None)
        self._text = _SPECS[IslandState.IDLE][2]
        self._capsule = QSize(_SPECS[IslandState.IDLE][0])
        self._pulse = 0.0

        self._size_anim = QPropertyAnimation(self, b"capsuleSize", self)
        self._pulse_anim = QVariantAnimation(self)
        self._pulse_anim.setStartValue(0.0)
        self._pulse_anim.setEndValue(1.0)
        self._pulse_anim.setDuration(1000)
        self._pulse_anim.setLoopCount(-1)
        self._pulse_anim.valueChanged.connect(self._on_pulse)
        self._safe_timer = QTimer(self)
        self._safe_timer.setSingleShot(True)
        self._safe_timer.timeout.connect(self._restore_rest)

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            screen.geometryChanged.connect(lambda *_: self.reposition())
        QGuiApplication.instance().primaryScreenChanged.connect(lambda *_: self.reposition())

    # ---- animated property ----
    def _get_capsule(self) -> QSize:
        return self._capsule

    def _set_capsule(self, size: QSize) -> None:
        self._capsule = size
        self.update()

    capsuleSize = pyqtProperty(QSize, _get_capsule, _set_capsule)

    # ---- public API ----
    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.show() if enabled else self.hide()

    def show_idle(self) -> None:
        self._set_rest(IslandState.IDLE)

    def show_paused(self) -> None:
        self._set_rest(IslandState.PAUSED)

    def show_error(self, message: str) -> None:
        self._set_rest(IslandState.ERROR, message)

    def show_safe(self, names: str) -> None:
        if self._state is not IslandState.ALERT:
            self._apply(IslandState.SAFE, f"Trusted: {names}")
            self._safe_timer.start(2500)

    def show_alert(self, count: int = 1) -> None:
        self._safe_timer.stop()
        text = "Unauthorized Viewer Detected" if count <= 1 else f"{count} Unauthorized Viewers Detected"
        self._apply(IslandState.ALERT, text)

    def clear_alert(self) -> None:
        if self._state is IslandState.ALERT:
            self._restore_rest()

    def reposition(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            g = screen.geometry()
            self.move(g.x() + (g.width() - self.width()) // 2, g.y())

    # ---- internals ----
    def _set_rest(self, state: IslandState, text: str | None = None) -> None:
        self._rest = (state, text)
        if self._state is not IslandState.ALERT and not self._safe_timer.isActive():
            self._restore_rest()

    def _restore_rest(self) -> None:
        self._apply(*self._rest)

    def _apply(self, state: IslandState, text: str | None = None) -> None:
        target, _color, default_text = _SPECS[state]
        expanding = target.width() >= self._capsule.width()
        self._state, self._text = state, text or default_text
        self._size_anim.stop()
        self._size_anim.setStartValue(self._capsule)
        self._size_anim.setEndValue(target)
        self._size_anim.setDuration(520 if expanding else 380)
        self._size_anim.setEasingCurve(QEasingCurve.Type.OutBack if expanding else QEasingCurve.Type.InOutCubic)
        self._size_anim.start()
        if state is IslandState.ALERT:
            self._pulse_anim.start()
        else:
            self._pulse_anim.stop()
            self._pulse = 0.0
        self.update()

    def _on_pulse(self, value) -> None:
        self._pulse = float(value)
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802
        self.reposition()
        super().showEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        cw, ch = max(24, self._capsule.width()), max(24, self._capsule.height())
        rect = QRectF((self.width() - cw) / 2, self._TOP, cw, ch)
        glow = 0.5 - 0.5 * math.cos(2 * math.pi * self._pulse)
        alert = self._state is IslandState.ALERT

        path = QPainterPath()
        path.addRoundedRect(rect, ch / 2, ch / 2)
        p.fillPath(path, QColor(int(24 + 70 * glow), 8, 10, 245) if alert else QColor(10, 10, 12, 242))
        if alert:
            p.setPen(QPen(QColor(255, 69, 58, int(90 + 165 * glow)), 2.0))
            p.drawPath(path)
        p.setClipPath(path)

        cx, cy = rect.left() + ch / 2 + 2, rect.center().y()
        color = _SPECS[self._state][1]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        if alert:
            s = ch * 0.2
            p.drawPolygon(QPolygonF([QPointF(cx, cy - s * 1.15), QPointF(cx + s * 1.25, cy + s * 0.95),
                                     QPointF(cx - s * 1.25, cy + s * 0.95)]))
            bang = QFont()
            bang.setPixelSize(int(s * 1.5))
            bang.setBold(True)
            p.setFont(bang)
            p.setPen(QColor("white"))
            p.drawText(QRectF(cx - s, cy - s * 0.75, 2 * s, 2 * s), Qt.AlignmentFlag.AlignCenter, "!")
        else:
            p.drawEllipse(QPointF(cx, cy), 5.0, 5.0)

        font = QFont()
        font.setPixelSize(15 if alert else 13)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(QColor(245, 245, 247))
        left = cx + (24 if alert else 14)
        p.drawText(QRectF(left, rect.top(), rect.right() - left - ch / 3, ch),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._text)
