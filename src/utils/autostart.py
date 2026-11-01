"""Run-on-login registration for Windows, macOS and Linux."""
from __future__ import annotations

import logging
import plistlib
import sys
from pathlib import Path

from .config_manager import PROJECT_ROOT

log = logging.getLogger(__name__)
APP_NAME = "MyGuard"


def _command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    exe = Path(sys.executable)
    if sys.platform == "win32" and exe.with_name("pythonw.exe").exists():
        exe = exe.with_name("pythonw.exe")
    return [str(exe), str(PROJECT_ROOT / "run.py")]


def set_run_on_startup(enabled: bool) -> bool:
    """Enable/disable autostart. Returns True on success."""
    try:
        if sys.platform == "win32":
            return _windows(enabled)
        if sys.platform == "darwin":
            return _macos(enabled)
        return _linux(enabled)
    except Exception as exc:  # noqa: BLE001
        log.error("Autostart change failed: %s", exc)
        return False


def _windows(enabled: bool) -> bool:
    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            cmd = " ".join(f'"{part}"' for part in _command())
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
    return True


def _macos(enabled: bool) -> bool:
    plist = Path.home() / "Library/LaunchAgents/com.shoulderguard.app.plist"
    if enabled:
        plist.parent.mkdir(parents=True, exist_ok=True)
        with plist.open("wb") as fh:
            plistlib.dump(
                {"Label": "com.shoulderguard.app", "ProgramArguments": _command(), "RunAtLoad": True},
                fh,
            )
    else:
        plist.unlink(missing_ok=True)
    return True


def _linux(enabled: bool) -> bool:
    entry = Path.home() / ".config/autostart/shoulderguard.desktop"
    if enabled:
        entry.parent.mkdir(parents=True, exist_ok=True)
        exec_line = " ".join(f'"{part}"' for part in _command())
        entry.write_text(
            "[Desktop Entry]\nType=Application\nName=MyGuard\n"
            f"Exec={exec_line}\nX-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )
    else:
        entry.unlink(missing_ok=True)
    return True
