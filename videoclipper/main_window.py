"""Top-level window: wires the viewport, timeline, clip panel and export flow."""
from __future__ import annotations

import os
from typing import List, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QColorDialog, QDialog, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QSlider, QSplitter,
    QToolButton, QVBoxLayout, QWidget,
)

from .clip_list import ClipListPanel
from .export_dialog import ExportProgressDialog, ExportSettingsDialog
from .media_utils import Exporter, ProbeWorker, ThumbnailWorker
from .models import Clip, SourceInfo
from .timeline_widget import TimelineWidget
from .utils import format_fps, format_time, random_pleasant_color
from .video_widget import VideoViewport

_VIDEO_FILTER = (
    "Video Files (*.mp4 *.mkv *.avi *.mov *.webm *.m4v *.wmv *.flv *.mpg *.mpeg *.ts);;"
    "All Files (*)"
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VideoClipper")
        self.resize(1400, 860)

        self.video_path: Optional[str] = None
        self.source_info: Optional[SourceInfo] = None
        self.clips: List[Clip] = []
        self.pending_start: Optional[float] = None
        self._clip_name_counter = 0
        self._dirty = False  # True when clips exist that haven't been exported yet
        self._active_clip_end: Optional[float] = None  # auto-pause point set by clicking a clip card
        # Lists, not a dict keyed by clip_id: a clip can be re-thumbnailed
        # (e.g. resized twice quickly) while an earlier request for the same
        # clip is still running in the background, so more than one worker
        # per clip can be in flight at once. Each removes itself on finish.
        self._thumb_workers: List[ThumbnailWorker] = []
        self._probe_workers: List[ProbeWorker] = []
        self._exporter: Optional[Exporter] = None
        self._progress_dialog: Optional[ExportProgressDialog] = None

        self._build_ui()
        self._wire_signals()
        self._install_shortcuts()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        top_bar = QWidget()
        top_bar.setObjectName("topBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(18, 12, 18, 12)
        title = QLabel("VideoClipper")
        title.setObjectName("appTitle")

        self.open_video_btn = QPushButton("Open Video")
        self.open_video_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self.export_btn = QPushButton("Export Clips")
        self.export_btn.setObjectName("primaryButton")
        self.export_btn.setEnabled(False)
        self.export_btn.setToolTip("Add at least one clip to export.")
        self.export_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        top_layout.addWidget(title)
        top_layout.addWidget(self.open_video_btn)
        top_layout.addStretch(1)
        top_layout.addWidget(self.export_btn)
        main_layout.addWidget(top_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_pane = QWidget()
        left_pane.setObjectName("leftPane")
        left_layout = QVBoxLayout(left_pane)
        left_layout.setContentsMargins(18, 16, 10, 16)
        left_layout.setSpacing(10)

        self.viewport = VideoViewport()
        left_layout.addWidget(self.viewport, 1)

        controls_row = QHBoxLayout()
        controls_row.setSpacing(10)
        self.play_btn = QToolButton()
        self.play_btn.setObjectName("playBtn")
        self.play_btn.setText("▶")  # ▶
        self.play_btn.setEnabled(False)
        self.play_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.play_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self.mute_btn = QToolButton()
        self.mute_btn.setObjectName("muteBtn")
        self.mute_btn.setText("🔊")
        self.mute_btn.setToolTip("Mute")
        self.mute_btn.setEnabled(False)
        self.mute_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(90)
        self.volume_slider.setToolTip("Volume")
        self.volume_slider.setEnabled(False)
        self.volume_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setObjectName("muted")

        self.start_btn = QPushButton("Set In  (I)")
        self.start_btn.setObjectName("markerStart")
        self.start_btn.setEnabled(False)
        self.start_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self.end_btn = QPushButton("Set Out  (O)")
        self.end_btn.setObjectName("markerEnd")
        self.end_btn.setEnabled(False)
        self.end_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.end_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        controls_row.addWidget(self.play_btn)
        controls_row.addWidget(self.mute_btn)
        controls_row.addWidget(self.volume_slider)
        controls_row.addWidget(self.time_label)
        controls_row.addStretch(1)
        controls_row.addWidget(self.start_btn)
        controls_row.addWidget(self.end_btn)
        left_layout.addLayout(controls_row)

        self.timeline = TimelineWidget()
        left_layout.addWidget(self.timeline)

        self.clip_panel = ClipListPanel()
        self.clip_panel.setObjectName("rightPane")
        self.clip_panel.setMinimumWidth(300)
        self.clip_panel.setMaximumWidth(420)

        splitter.addWidget(left_pane)
        splitter.addWidget(self.clip_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([1040, 340])

        main_layout.addWidget(splitter, 1)
        self.statusBar()

    def _wire_signals(self):
        self.open_video_btn.clicked.connect(self.open_video_dialog)
        self.viewport.open_requested.connect(self.open_video_dialog)
        self.viewport.position_changed.connect(self._on_position_changed)
        self.viewport.duration_changed.connect(self._on_duration_changed)
        self.viewport.playing_changed.connect(self._on_playing_changed)
        self.play_btn.clicked.connect(self.viewport.toggle_play)
        self.mute_btn.clicked.connect(self._on_mute_clicked)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        self.start_btn.clicked.connect(self.on_set_start)
        self.end_btn.clicked.connect(self.on_set_end)

        self.timeline.seek_requested.connect(self._on_seek_requested)
        self.timeline.clip_renamed.connect(self.rename_clip)
        self.timeline.clip_delete_requested.connect(self.delete_clip)
        self.timeline.clip_color_requested.connect(self.change_clip_color)
        self.timeline.clip_resizing.connect(self._on_clip_resizing)
        self.timeline.clip_resized.connect(self._on_clip_resized)

        self.clip_panel.item_activated.connect(self.on_clip_activated)
        self.clip_panel.item_renamed.connect(self.rename_clip)
        self.clip_panel.item_delete_requested.connect(self.delete_clip)

        self.export_btn.clicked.connect(self.open_export_dialog)

    def _install_shortcuts(self):
        def bind(seq, slot):
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(slot)
            return sc

        self._shortcuts = [
            bind("Space", self._shortcut_toggle_play),
            bind("I", self._shortcut_set_start),
            bind("O", self._shortcut_set_end),
            bind("Esc", self._shortcut_cancel_pending),
            bind("Left", lambda: self._seek_relative(-5)),
            bind("Right", lambda: self._seek_relative(5)),
            bind("Shift+Left", lambda: self._seek_relative(-1)),
            bind("Shift+Right", lambda: self._seek_relative(1)),
            bind("Home", lambda: self._safe_seek(0.0)),
            bind("End", lambda: self._safe_seek(self.viewport.duration())),
        ]

    # ------------------------------------------------------------------
    # Unsaved-work guard
    # ------------------------------------------------------------------
    def _has_unsaved_work(self) -> bool:
        return bool(self.clips) and self._dirty

    def _confirm_discard_if_needed(self, action_description: str) -> bool:
        """Returns True if it's OK to proceed (nothing to lose, or user confirmed)."""
        if not self._has_unsaved_work():
            return True
        answer = QMessageBox.warning(
            self, "Unexported clips",
            "Your current clips haven't been exported yet. "
            f"If you {action_description}, this work will be lost.\n\n"
            "Continue anyway?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    # ------------------------------------------------------------------
    # Opening a video
    # ------------------------------------------------------------------
    def open_video_dialog(self):
        if not self._confirm_discard_if_needed("open another video"):
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open video", "", _VIDEO_FILTER)
        if path:
            self._load_video(path)

    def _load_video(self, path: str):
        self._reset_clips()
        self.video_path = path
        self.source_info = None
        self.viewport.load(path)
        self.setWindowTitle(f"VideoClipper — {os.path.basename(path)}")
        self.statusBar().showMessage("Video loaded.", 3000)
        self._probe_source(path)

    def _reset_clips(self):
        self.clip_panel.clear()
        self.timeline.reset()
        self.clips = []
        self.pending_start = None
        self._clip_name_counter = 0
        self._dirty = False
        self._active_clip_end = None
        self.start_btn.setEnabled(True)
        self.end_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.export_btn.setToolTip("Add at least one clip to export.")

    def _probe_source(self, path: str):
        worker = ProbeWorker(path)
        self._probe_workers.append(worker)
        worker.ready.connect(self._on_source_probed)
        worker.finished.connect(lambda w=worker: w in self._probe_workers and self._probe_workers.remove(w))
        worker.start()

    def _on_source_probed(self, info: SourceInfo):
        self.source_info = info
        if info.width and info.height:
            extra = f" ({info.width}x{info.height}"
            if info.fps:
                extra += f", {format_fps(info.fps)} fps"
            extra += ")"
            self.statusBar().showMessage("Video loaded." + extra, 4000)

    def _on_duration_changed(self, seconds: float):
        self.timeline.set_duration(seconds)
        self._update_time_label()
        if self.video_path:
            self.play_btn.setEnabled(True)
            self.mute_btn.setEnabled(True)
            self.volume_slider.setEnabled(True)
            self.start_btn.setEnabled(self.pending_start is None)
            self.end_btn.setEnabled(self.pending_start is not None)

    def _on_position_changed(self, seconds: float):
        self.timeline.set_position(seconds)
        self._update_time_label()
        if self._active_clip_end is not None and seconds >= self._active_clip_end:
            self._active_clip_end = None
            self.viewport.pause()

    def _on_playing_changed(self, is_playing: bool):
        self.play_btn.setText("⏸" if is_playing else "▶")  # ⏸ / ▶

    def _on_seek_requested(self, seconds: float):
        self._active_clip_end = None  # a manual seek exits "play this clip" mode
        self.viewport.seek(seconds)

    def _on_mute_clicked(self):
        muted = not self.viewport.is_muted()
        self.viewport.set_muted(muted)
        self.mute_btn.setText("🔇" if muted else "🔊")

    def _on_volume_changed(self, value: int):
        self.viewport.set_volume(value / 100.0)
        muted = value == 0
        self.viewport.set_muted(muted)
        self.mute_btn.setText("🔇" if muted else "🔊")

    def _update_time_label(self):
        self.time_label.setText(
            f"{format_time(self.viewport.current_position())} / "
            f"{format_time(self.viewport.duration())}"
        )

    # ------------------------------------------------------------------
    # Marker placement (start -> end -> new clip)
    # ------------------------------------------------------------------
    def on_set_start(self):
        if not self.video_path:
            return
        t = self.viewport.current_position()
        for clip in self.clips:
            if clip.contains(t):
                self.statusBar().showMessage("Can't start a clip inside an existing clip.", 4000)
                return
        self.pending_start = t
        self.timeline.set_pending_start(t)
        self.start_btn.setEnabled(False)
        self.end_btn.setEnabled(True)
        self.statusBar().showMessage(
            f"In-point set at {format_time(t)}. Scrub ahead and set the out-point.", 4000)

    def on_set_end(self):
        if self.pending_start is None:
            return
        t = self.viewport.current_position()
        if t <= self.pending_start:
            self.statusBar().showMessage("Out-point must be after the in-point.", 4000)
            return
        for clip in self.clips:
            if clip.overlaps(self.pending_start, t):
                self.statusBar().showMessage("That range overlaps an existing clip.", 4000)
                return

        self._clip_name_counter += 1
        clip = Clip(start=self.pending_start, end=t,
                    name=f"Clip{self._clip_name_counter}",
                    color=random_pleasant_color())
        self.clips.append(clip)
        self.timeline.add_clip(clip)
        self.clip_panel.add_clip(clip)
        self._request_thumbnail(clip)
        self._dirty = True

        self.pending_start = None
        self.timeline.set_pending_start(None)
        self.start_btn.setEnabled(True)
        self.end_btn.setEnabled(False)
        self.export_btn.setEnabled(True)
        self.export_btn.setToolTip("")
        self.statusBar().showMessage(f"Clip '{clip.name}' created.", 3000)

    def _cancel_pending_marker(self):
        if self.pending_start is not None:
            self.pending_start = None
            self.timeline.set_pending_start(None)
            self.start_btn.setEnabled(True)
            self.end_btn.setEnabled(False)
            self.statusBar().showMessage("In-point cancelled.", 2000)

    # ------------------------------------------------------------------
    # Trimming (drag a clip's edge on the timeline)
    # ------------------------------------------------------------------
    def _on_clip_resizing(self, clip_id: int, start: float, end: float):
        item = self.clip_panel.get_item(clip_id)
        if item:
            item.set_duration_text(end - start)

    def _on_clip_resized(self, clip_id: int, start: float, end: float):
        clip = self._clip_by_id(clip_id)
        if not clip:
            return
        self._dirty = True
        self.clip_panel.update_range(clip_id, start, end)
        self._request_thumbnail(clip)  # the first frame may have moved

    # ------------------------------------------------------------------
    # Thumbnails
    # ------------------------------------------------------------------
    def _request_thumbnail(self, clip: Clip):
        if not self.video_path:
            return
        worker = ThumbnailWorker(clip.id, self.video_path, clip.start)
        self._thumb_workers.append(worker)
        worker.ready.connect(self._on_thumbnail_ready)
        worker.failed.connect(self._on_thumbnail_failed)
        worker.finished.connect(lambda w=worker: w in self._thumb_workers and self._thumb_workers.remove(w))
        worker.start()

    def _on_thumbnail_ready(self, clip_id: int, data: bytes):
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        clip = self._clip_by_id(clip_id)
        if clip:
            clip.thumbnail = pixmap
        self.clip_panel.update_thumbnail(clip_id, pixmap)

    def _on_thumbnail_failed(self, clip_id: int, message: str):
        self.statusBar().showMessage(f"Could not generate a thumbnail: {message}", 4000)

    # ------------------------------------------------------------------
    # Rename / delete / recolor
    # ------------------------------------------------------------------
    def rename_clip(self, clip_id: int, name: str):
        clip = self._clip_by_id(clip_id)
        if not clip:
            return
        clip.name = name
        self._dirty = True
        self.timeline.update_clip(clip)
        self.clip_panel.rename_clip(clip_id, name)

    def delete_clip(self, clip_id: int):
        clip = self._clip_by_id(clip_id)
        if not clip:
            return
        answer = QMessageBox.question(
            self, "Delete clip", f"Delete '{clip.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.clips = [c for c in self.clips if c.id != clip_id]
        self.timeline.remove_clip(clip_id)
        self.clip_panel.remove_clip(clip_id)
        self._dirty = True
        if not self.clips:
            self.export_btn.setEnabled(False)
            self.export_btn.setToolTip("Add at least one clip to export.")

    def change_clip_color(self, clip_id: int):
        clip = self._clip_by_id(clip_id)
        if not clip:
            return
        color = QColorDialog.getColor(QColor(*clip.color), self, "Choose clip color")
        if color.isValid():
            clip.color = (color.red(), color.green(), color.blue())
            self.timeline.update_clip(clip)

    def _clip_by_id(self, clip_id: int) -> Optional[Clip]:
        for clip in self.clips:
            if clip.id == clip_id:
                return clip
        return None

    # ------------------------------------------------------------------
    # Click-to-jump (right panel)
    # ------------------------------------------------------------------
    def on_clip_activated(self, clip_id: int):
        clip = self._clip_by_id(clip_id)
        if not clip:
            return
        self._active_clip_end = clip.end  # auto-pause once playback reaches the clip's end
        self.viewport.seek(clip.start)
        self.viewport.play()

    # ------------------------------------------------------------------
    # Shortcuts (guarded so typing in a rename box doesn't trigger them)
    # ------------------------------------------------------------------
    @staticmethod
    def _typing_in_text_field() -> bool:
        return isinstance(QApplication.focusWidget(), QLineEdit)

    def _shortcut_toggle_play(self):
        if self._typing_in_text_field() or not self.video_path:
            return
        self.viewport.toggle_play()

    def _shortcut_set_start(self):
        if self._typing_in_text_field():
            return
        if self.start_btn.isEnabled():
            self.on_set_start()

    def _shortcut_set_end(self):
        if self._typing_in_text_field():
            return
        if self.end_btn.isEnabled():
            self.on_set_end()

    def _shortcut_cancel_pending(self):
        if self._typing_in_text_field():
            return
        self._cancel_pending_marker()

    def _seek_relative(self, delta: float):
        if self._typing_in_text_field() or not self.video_path:
            return
        self._active_clip_end = None
        self.viewport.seek(self.viewport.current_position() + delta)

    def _safe_seek(self, t: float):
        if self._typing_in_text_field() or not self.video_path:
            return
        self._active_clip_end = None
        self.viewport.seek(t)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def open_export_dialog(self):
        if not self.clips or not self.video_path:
            return
        dialog = ExportSettingsDialog(
            self.clips, video_path=self.video_path, source_info=self.source_info, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._start_export(dialog.get_settings())

    def _start_export(self, settings: dict):
        clips_sorted = sorted(self.clips, key=lambda c: c.start)
        self._progress_dialog = ExportProgressDialog(len(clips_sorted), parent=self)

        self._exporter = Exporter(
            self.video_path, clips_sorted,
            settings["output_dir"], settings, settings["ext"],
            source_info=self.source_info,
        )
        self._exporter.clip_started.connect(self._progress_dialog.update_clip_started)
        self._exporter.clip_progress.connect(
            lambda _idx, pct: self._progress_dialog.update_clip_progress(pct))
        self._exporter.overall_progress.connect(self._progress_dialog.update_overall)
        self._exporter.finished_all.connect(self._on_export_finished)
        self._progress_dialog.cancel_requested.connect(self._exporter.request_cancel)

        self._exporter.start()
        self._progress_dialog.exec()

    def _on_export_finished(self, success: bool, message: str):
        if success:
            self._dirty = False
        if self._progress_dialog:
            self._progress_dialog.set_finished(success, message)
            if success:
                # Nothing more to review - close the progress dialog on its own.
                QTimer.singleShot(700, self._progress_dialog.accept)
        self.statusBar().showMessage(message, 6000)

    def closeEvent(self, event):
        if not self._confirm_discard_if_needed("quit VideoClipper"):
            event.ignore()
            return
        if self._exporter is not None and self._exporter.isRunning():
            self._exporter.request_cancel()
            self._exporter.wait(3000)
        super().closeEvent(event)
