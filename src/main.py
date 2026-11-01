"""MyGuard entry point: application lifecycle and event routing."""
from __future__ import annotations

import logging
import sys
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PyQt6.QtCore import QLockFile, QObject
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox

from .core.face_recognizer import TrustedFaceStore
from .core.vision_worker import VisionWorker
from .ui.dynamic_island import DynamicIsland
from .ui.face_enrollment import EnrollmentDialog
from .ui.frosted_glass import FrostedGlassShield
from .ui.settings_dialog import SettingsDialog
from .ui.tray_manager import TrayManager
from .utils.autostart import set_run_on_startup
from .utils.config_manager import ASSETS_DIR, DATA_DIR, ConfigManager
from .utils.sound_player import SoundPlayer

log = logging.getLogger("shoulderguard")


def _setup_logging() -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()] if sys.stderr else []
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(DATA_DIR / "shoulderguard.log", maxBytes=512_000, backupCount=2))
    except OSError:
        pass
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sys.excepthook = lambda t, v, tb: log.critical("Unhandled exception", exc_info=(t, v, tb))


class MyGuardApp(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self._app = app
        self.config = ConfigManager()
        self.config.load()
        self.store = TrustedFaceStore(DATA_DIR / "trusted_faces.json")
        self.store.load()

        self.island = DynamicIsland()
        self.shield = FrostedGlassShield(self.config)
        self.sound = SoundPlayer(self.config)
        self.worker = VisionWorker(self.config, self.store)
        self.tray = TrayManager(self.config.settings.protection_enabled)
        self._dialog = None

        w = self.worker
        w.threat_detected.connect(self._on_threat)
        w.threat_cleared.connect(self._on_cleared)
        w.trusted_verified.connect(self.island.show_safe)
        w.camera_state.connect(self._on_camera_state)
        w.error_occurred.connect(lambda msg: self.tray.notify("MyGuard", msg))
        self.tray.toggle_requested.connect(self._on_toggle)
        self.tray.enroll_requested.connect(self._open_enrollment)
        self.tray.settings_requested.connect(self._open_settings)
        self.tray.exit_requested.connect(self.quit)
        app.aboutToQuit.connect(self._shutdown)

    def start(self) -> None:
        s = self.config.settings
        self.island.set_enabled(s.show_island)
        if not s.protection_enabled:
            self.island.show_paused()
        self.worker.start()

    # ---- worker events ----
    def _on_threat(self, count: int) -> None:
        log.info("Threat detected (%d unauthorised viewer[s])", count)
        s = self.config.settings
        if s.show_island:
            self.island.show_alert(count)
        self.shield.show_shield()
        self.sound.play_alert()

    def _on_cleared(self) -> None:
        log.info("Threat cleared")
        self.island.clear_alert()
        self.shield.hide_shield()

    def _on_camera_state(self, ok: bool, message: str) -> None:
        if ok:
            self.island.show_paused() if not self.config.settings.protection_enabled else self.island.show_idle()
        else:
            self.island.show_error("Camera unavailable")
            self.tray.notify("MyGuard", message)

    # ---- user actions ----
    def _on_toggle(self, enabled: bool) -> None:
        self.config.update(protection_enabled=enabled)
        self.worker.set_protection(enabled)
        if enabled:
            self.island.show_idle()
        else:
            self.island.clear_alert()
            self.island.show_paused()
            self.shield.hide_shield()

    def _open_enrollment(self) -> None:
        if self._dialog is not None and self._dialog.isVisible():
            self._dialog.raise_()
            return
        self._dialog = EnrollmentDialog(self.worker, self.store)
        self._dialog.show()

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.config)
        if dlg.exec():
            values = dlg.values()
            previous = self.config.settings.run_on_startup
            self.config.update(**values)
            if values["run_on_startup"] != previous and not set_run_on_startup(values["run_on_startup"]):
                QMessageBox.warning(None, "MyGuard", "Could not change the startup setting.")
            self.island.set_enabled(values["show_island"])

    def quit(self) -> None:
        self._app.quit()

    def _shutdown(self) -> None:
        self.worker.stop()
        self.worker.wait(4000)
        self.shield.hide_shield(immediate=True)
        self.tray.hide()


def main() -> int:
    _setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("MyGuard")
    app.setQuitOnLastWindowClosed(False)
    icon = ASSETS_DIR / "icons" / "app.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    qss = ASSETS_DIR / "style.qss"
    if qss.exists():
        app.setStyleSheet(qss.read_text(encoding="utf-8"))

    lock = QLockFile(str(Path(tempfile.gettempdir()) / "shoulderguard.lock"))
    if not lock.tryLock(100):
        log.error("MyGuard is already running")
        return 1

    guard = MyGuardApp(app)
    guard.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
