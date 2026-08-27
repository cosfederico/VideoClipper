"""Frame-precise 'current / total' time readout - the current-time half is
click-to-edit (type a time, Enter to jump to it)."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QStackedWidget, QWidget

from .utils import format_time_frames, parse_time_frames


class _ClickableLabel(QLabel):
    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _TimeEditor(QLineEdit):
    """A QLineEdit that reports Escape instead of silently eating it."""

    cancelled = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)


class TimeDisplayWidget(QWidget):
    """'2:10.15 / 3:24.02' - click the current-time half to type a new
    frame-accurate time and jump to it; Escape or an unparsable value
    reverts without seeking."""

    time_edit_requested = pyqtSignal(float)  # seconds

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_seconds = 0.0
        self._duration_seconds = 0.0
        self._fps: Optional[float] = None
        self._editing = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch(1)

        self._stack = QStackedWidget()
        self._current_label = _ClickableLabel()
        self._current_label.setObjectName("timeCurrent")
        self._current_label.setCursor(Qt.CursorShape.IBeamCursor)
        self._current_label.setToolTip("Click to type a time to jump to (frame-accurate)")
        self._current_label.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        self._current_edit = _TimeEditor()
        self._current_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._stack.addWidget(self._current_label)
        self._stack.addWidget(self._current_edit)
        self._stack.setCurrentWidget(self._current_label)

        self._duration_label = QLabel()
        self._duration_label.setObjectName("muted")

        layout.addWidget(self._stack)
        layout.addWidget(self._duration_label)
        layout.addStretch(1)

        self._current_label.clicked.connect(self._begin_edit)
        self._current_edit.editingFinished.connect(self._commit_edit)
        self._current_edit.cancelled.connect(self._cancel_edit)

        self._refresh_current()
        self._refresh_duration()

    # -- external updates -------------------------------------------------
    def set_fps(self, fps: Optional[float]):
        self._fps = fps
        self._refresh_current()
        self._refresh_duration()

    def set_current(self, seconds: float):
        self._current_seconds = max(0.0, seconds)
        # Don't clobber whatever the user is typing mid-edit.
        if not self._editing:
            self._refresh_current()

    def set_duration(self, seconds: float):
        self._duration_seconds = max(0.0, seconds)
        self._refresh_duration()

    def _refresh_current(self):
        self._current_label.setText(format_time_frames(self._current_seconds, self._fps))

    def _refresh_duration(self):
        self._duration_label.setText(" / " + format_time_frames(self._duration_seconds, self._fps))

    # -- editing -------------------------------------------------------
    def _begin_edit(self):
        if not self.isEnabled():
            return
        self._editing = True
        self._current_edit.setText(format_time_frames(self._current_seconds, self._fps))
        self._stack.setCurrentWidget(self._current_edit)
        self._current_edit.selectAll()
        self._current_edit.setFocus(Qt.FocusReason.MouseFocusReason)

    def _commit_edit(self):
        if not self._editing:
            return
        self._editing = False
        text = self._current_edit.text()
        self._stack.setCurrentWidget(self._current_label)
        seconds = parse_time_frames(text, self._fps)
        if seconds is not None:
            self.time_edit_requested.emit(seconds)
        else:
            self._refresh_current()  # invalid input - revert

    def _cancel_edit(self):
        if not self._editing:
            return
        self._editing = False
        self._stack.setCurrentWidget(self._current_label)
        self._refresh_current()
