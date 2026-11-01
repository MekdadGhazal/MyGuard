"""Asynchronous alert tone. The WAV is synthesised on first use (no binary assets)."""
from __future__ import annotations

import logging
import math
import struct
import time
import wave
from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QApplication

from .config_manager import ASSETS_DIR, DATA_DIR, ConfigManager

log = logging.getLogger(__name__)
_RATE = 22050


def _synthesise(path: Path) -> None:
    frames = bytearray()
    for freq, dur in ((880.0, 0.12), (660.0, 0.2)):
        n = int(_RATE * dur)
        for i in range(n):
            env = min(1.0, i / 300, (n - i) / 600)
            sample = int(32767 * 0.5 * env * math.sin(2 * math.pi * freq * i / _RATE))
            frames += struct.pack("<h", sample)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(_RATE)
        wav.writeframes(bytes(frames))


def _ensure_wav() -> Path | None:
    for base in (ASSETS_DIR / "sounds", DATA_DIR):
        path = base / "alert.wav"
        if path.exists():
            return path
        try:
            _synthesise(path)
            return path
        except OSError:
            continue
    return None


class SoundPlayer:
    COOLDOWN_S = 8.0

    def __init__(self, config: ConfigManager) -> None:
        self._config = config
        self._last = 0.0
        self._effect = None
        self._init_done = False

    def _init_effect(self) -> None:
        """Create the QSoundEffect lazily, and only if an audio output device exists."""
        self._init_done = True
        try:
            from PyQt6.QtMultimedia import QMediaDevices, QSoundEffect

            wav = _ensure_wav()
            if wav is None or not QMediaDevices.audioOutputs():
                log.info("No audio output available; using system beep")
                return
            self._effect = QSoundEffect()
            self._effect.setSource(QUrl.fromLocalFile(str(wav)))
            self._effect.setVolume(0.6)
        except ImportError:
            log.info("QtMultimedia unavailable; using system beep")

    def play_alert(self) -> None:
        if not self._config.settings.play_sound:
            return
        now = time.monotonic()
        if now - self._last < self.COOLDOWN_S:
            return
        self._last = now
        if not self._init_done:
            self._init_effect()
        if self._effect is not None:
            self._effect.play()
        else:
            QApplication.beep()
