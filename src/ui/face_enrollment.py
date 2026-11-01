"""Dialog to capture, label and manage trusted faces."""
from __future__ import annotations

import logging

import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QVBoxLayout)

from ..core.face_recognizer import TrustedFaceStore
from ..core.vision_worker import VisionWorker

log = logging.getLogger(__name__)
SAMPLES_NEEDED = 5
MAX_ATTEMPTS = 20


class EnrollmentDialog(QDialog):
    def __init__(self, worker: VisionWorker, store: TrustedFaceStore, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("MyGuard - Trusted Faces")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._worker, self._store = worker, store
        self._samples: list[np.ndarray] = []
        self._attempts = 0

        self._preview = QLabel("Starting camera…")
        self._preview.setFixedSize(320, 240)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setStyleSheet("background:#000;border-radius:8px;")
        self._name = QLineEdit()
        self._name.setPlaceholderText("Name (e.g. Alex)")
        self._role = QComboBox()
        self._role.addItems(["Owner", "Colleague", "Friend", "Family"])
        self._status = QLabel("Only the person being registered should be in view.")
        self._status.setWordWrap(True)
        self._progress = QProgressBar()
        self._progress.setRange(0, SAMPLES_NEEDED)
        self._progress.setTextVisible(False)
        self._capture = QPushButton("Capture face")
        self._capture.clicked.connect(self._start_capture)
        self._list = QListWidget()
        remove = QPushButton("Remove selected")
        remove.clicked.connect(self._remove_selected)

        row = QHBoxLayout()
        row.addWidget(self._name, 2)
        row.addWidget(self._role, 1)
        layout = QVBoxLayout(self)
        layout.addWidget(self._preview, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addLayout(row)
        layout.addWidget(self._progress)
        layout.addWidget(self._status)
        layout.addWidget(self._capture)
        layout.addWidget(QLabel("Trusted faces"))
        layout.addWidget(self._list)
        layout.addWidget(remove)

        self._timer = QTimer(self)
        self._timer.setInterval(700)
        self._timer.timeout.connect(self._worker.request_sample)
        worker.preview_frame.connect(self._on_preview)
        worker.enrollment_sample.connect(self._on_sample)
        worker.enrollment_failed.connect(self._on_failed)
        self.finished.connect(self._cleanup)
        self._refresh()
        worker.set_enrollment_mode(True)

    def _cleanup(self) -> None:
        self._timer.stop()
        for sig, slot in ((self._worker.preview_frame, self._on_preview),
                          (self._worker.enrollment_sample, self._on_sample),
                          (self._worker.enrollment_failed, self._on_failed)):
            try:
                sig.disconnect(slot)
            except TypeError:
                pass
        self._worker.set_enrollment_mode(False)

    def _refresh(self) -> None:
        self._list.clear()
        for face in self._store.list_faces():
            item = QListWidgetItem(f"{face.name}  ({face.role}, {face.samples} samples)")
            item.setData(Qt.ItemDataRole.UserRole, face.face_id)
            self._list.addItem(item)

    def _on_preview(self, image: QImage) -> None:
        self._preview.setPixmap(QPixmap.fromImage(image).scaled(
            self._preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def _start_capture(self) -> None:
        if not self._name.text().strip():
            self._status.setText("Enter a name first.")
            return
        self._samples, self._attempts = [], 0
        self._progress.setValue(0)
        self._capture.setEnabled(False)
        self._status.setText("Hold still and look at the camera…")
        self._timer.start()

    def _finish(self) -> None:
        self._timer.stop()
        self._capture.setEnabled(True)

    def _on_sample(self, emb: object) -> None:
        if not self._timer.isActive():
            return
        self._samples.append(emb)
        self._progress.setValue(len(self._samples))
        if len(self._samples) >= SAMPLES_NEEDED:
            self._finish()
            try:
                face = self._store.add(self._name.text(), self._role.currentText(), self._samples)
            except OSError as exc:
                QMessageBox.critical(self, "MyGuard", f"Could not save the face: {exc}")
                return
            self._status.setText(f"Saved {face.name}.")
            self._name.clear()
            self._refresh()

    def _on_failed(self, message: str) -> None:
        if not self._timer.isActive():
            return
        self._status.setText(message)
        self._attempts += 1
        if self._attempts >= MAX_ATTEMPTS:
            self._finish()
            self._status.setText(f"{message} Capture stopped; try again.")

    def _remove_selected(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        try:
            self._store.remove(item.data(Qt.ItemDataRole.UserRole))
        except OSError as exc:
            QMessageBox.critical(self, "MyGuard", f"Could not update the database: {exc}")
        self._refresh()
