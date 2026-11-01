"""System-tray icon and menu."""
from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from ..utils.config_manager import ASSETS_DIR

log = logging.getLogger(__name__)


def make_shield_icon(color: QColor) -> QIcon:
    custom = ASSETS_DIR / "icons" / ("app.png" if color.name().lower() == "#30d158" else "app_off.png")
    if custom.exists():
        return QIcon(str(custom))
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.moveTo(32, 4)
    path.lineTo(56, 13)
    path.lineTo(56, 32)
    path.cubicTo(56, 46, 46, 56, 32, 61)
    path.cubicTo(18, 56, 8, 46, 8, 32)
    path.lineTo(8, 13)
    path.closeSubpath()
    p.fillPath(path, color)
    pen = QPen(QColor("white"), 5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawPolyline(QPolygonF([QPointF(22, 33), QPointF(29, 41), QPointF(43, 24)]))
    p.end()
    return QIcon(pm)


class TrayManager(QObject):
    toggle_requested = pyqtSignal(bool)
    enroll_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    exit_requested = pyqtSignal()

    def __init__(self, protection_enabled: bool) -> None:
        super().__init__()
        self._on_icon = make_shield_icon(QColor("#30D158"))
        self._off_icon = make_shield_icon(QColor("#8E8E93"))
        self.available = QSystemTrayIcon.isSystemTrayAvailable()
        if not self.available:
            log.warning("No system tray available; use the process manager to exit")
        self._tray = QSystemTrayIcon(self._on_icon if protection_enabled else self._off_icon)
        self._tray.setToolTip("MyGuard")

        menu = QMenu()
        self._toggle = QAction("Protection enabled", menu, checkable=True)
        self._toggle.setChecked(protection_enabled)
        self._toggle.toggled.connect(self._on_toggled)
        register = QAction("Register / Manage Faces…", menu)
        register.triggered.connect(self.enroll_requested)
        settings = QAction("Settings…", menu)
        settings.triggered.connect(self.settings_requested)
        quit_action = QAction("Exit", menu)
        quit_action.triggered.connect(self.exit_requested)
        for item in (self._toggle, register, settings):
            menu.addAction(item)
        menu.addSeparator()
        menu.addAction(quit_action)
        self._menu = menu
        self._tray.setContextMenu(menu)
        self._tray.show()

    def _on_toggled(self, checked: bool) -> None:
        self._tray.setIcon(self._on_icon if checked else self._off_icon)
        self.toggle_requested.emit(checked)

    def set_protection_checked(self, checked: bool) -> None:
        self._toggle.blockSignals(True)
        self._toggle.setChecked(checked)
        self._toggle.blockSignals(False)
        self._tray.setIcon(self._on_icon if checked else self._off_icon)

    def notify(self, title: str, message: str) -> None:
        if self.available:
            self._tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Warning, 5000)

    def hide(self) -> None:
        self._tray.hide()
