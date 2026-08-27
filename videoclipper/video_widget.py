"""The main viewport: shows an 'Open Video' prompt, then the video surface."""
from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtCore import QMimeData, QTimer, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from .utils import VIDEO_EXTENSIONS


def _dropped_video_path(mime_data: QMimeData) -> Optional[str]:
    """The local file path to load from a drop, or None if it has no files.
    A dropped file is used regardless of its extension if it's the only
    one; among multiple, one with a recognized video extension is preferred."""
    if not mime_data.hasUrls():
        return None
    local_paths = [url.toLocalFile() for url in mime_data.urls() if url.isLocalFile()]
    if not local_paths:
        return None
    for path in local_paths:
        if os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS:
            return path
    return local_paths[0]


class VideoViewport(QWidget):
    """Wraps QMediaPlayer/QVideoWidget with an empty-state 'Open Video' page."""

    open_requested = pyqtSignal()
    video_dropped = pyqtSignal(str)        # local file path
    position_changed = pyqtSignal(float)   # seconds
    duration_changed = pyqtSignal(float)   # seconds
    playing_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(1.0)
        self.player.setAudioOutput(self.audio_output)

        self.video_widget = QVideoWidget(self)
        self.video_widget.setStyleSheet("background: black;")
        self.player.setVideoOutput(self.video_widget)

        self.stack = QStackedWidget(self)

        self.empty_page = QWidget()
        self.empty_page.setStyleSheet("background: #101116;")
        empty_layout = QVBoxLayout(self.empty_page)
        empty_layout.setContentsMargins(24, 24, 24, 24)

        self.drop_zone = QWidget()
        self.drop_zone.setObjectName("dropZone")
        drop_layout = QVBoxLayout(self.drop_zone)
        drop_layout.setSpacing(10)
        drop_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.open_btn = QPushButton("Open Video")
        self.open_btn.setObjectName("openVideoBtn")
        self.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.open_btn.clicked.connect(self.open_requested.emit)

        drag_hint = QLabel("or drag and drop a video here")
        drag_hint.setObjectName("dropZoneHint")
        drag_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        hint = QLabel("MP4, MKV, AVI, MOV, WebM and more")
        hint.setObjectName("openVideoHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        drop_layout.addWidget(self.open_btn, 0, Qt.AlignmentFlag.AlignCenter)
        drop_layout.addWidget(drag_hint, 0, Qt.AlignmentFlag.AlignCenter)
        drop_layout.addWidget(hint, 0, Qt.AlignmentFlag.AlignCenter)

        empty_layout.addWidget(self.drop_zone)

        self.stack.addWidget(self.empty_page)
        self.stack.addWidget(self.video_widget)
        self.stack.setCurrentWidget(self.empty_page)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

        self._duration = 0.0
        self._primed = False
        self._muted_before_priming = False

        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.playbackStateChanged.connect(self._on_playback_state)
        self.player.mediaStatusChanged.connect(self._on_media_status)

    # -- public API ---------------------------------------------------
    def load(self, path: str):
        self._primed = False
        # Priming (below) briefly plays the file to force the first frame to
        # render; mute for that instant so it doesn't cause an audible blip,
        # then restore whatever mute state the user actually had.
        self._muted_before_priming = self.audio_output.isMuted()
        self.audio_output.setMuted(True)
        self.player.setSource(QUrl.fromLocalFile(path))
        self.stack.setCurrentWidget(self.video_widget)

    def toggle_play(self):
        if self.is_playing():
            self.player.pause()
        else:
            self.player.play()

    def play(self):
        self.player.play()

    def pause(self):
        self.player.pause()

    def seek(self, seconds: float):
        seconds = max(0.0, min(seconds, self._duration if self._duration else seconds))
        self.player.setPosition(int(seconds * 1000))

    def current_position(self) -> float:
        return self.player.position() / 1000.0

    def duration(self) -> float:
        return self._duration

    def is_playing(self) -> bool:
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def has_video(self) -> bool:
        return self.stack.currentWidget() is self.video_widget

    def set_volume(self, value: float):
        """value in [0.0, 1.0]."""
        self.audio_output.setVolume(max(0.0, min(1.0, value)))

    def volume(self) -> float:
        return self.audio_output.volume()

    def set_muted(self, muted: bool):
        self.audio_output.setMuted(muted)

    def is_muted(self) -> bool:
        return self.audio_output.isMuted()

    # -- drag and drop ---------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent):
        if _dropped_video_path(event.mimeData()) is not None:
            event.acceptProposedAction()
            self._set_drop_active(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._set_drop_active(False)

    def dropEvent(self, event: QDropEvent):
        self._set_drop_active(False)
        path = _dropped_video_path(event.mimeData())
        if path is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self.video_dropped.emit(path)

    def _set_drop_active(self, active: bool):
        self.drop_zone.setProperty("dragActive", active)
        self.drop_zone.style().unpolish(self.drop_zone)
        self.drop_zone.style().polish(self.drop_zone)

    # -- internal signal handlers -------------------------------------
    def _on_media_status(self, status):
        if status == QMediaPlayer.MediaStatus.LoadedMedia and not self._primed:
            # Prime the first frame: play then immediately pause so the
            # viewport shows frame 0 instead of a black surface.
            self._primed = True
            self.player.play()
            QTimer.singleShot(60, self._finish_priming)

    def _finish_priming(self):
        self.player.pause()
        self.player.setPosition(0)
        self.audio_output.setMuted(self._muted_before_priming)

    def _on_position(self, ms: int):
        self.position_changed.emit(ms / 1000.0)

    def _on_duration(self, ms: int):
        self._duration = ms / 1000.0
        self.duration_changed.emit(self._duration)

    def _on_playback_state(self, state):
        self.playing_changed.emit(state == QMediaPlayer.PlaybackState.PlayingState)
