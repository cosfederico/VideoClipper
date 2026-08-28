"""Top-level window: wires the viewport, timeline, clip panel and export flow."""
from __future__ import annotations

import os
from typing import List, Optional

from PyQt6.QtCore import QEvent, QSettings, Qt, QTimer
from PyQt6.QtGui import QAction, QColor, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QColorDialog, QDialog, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton, QScrollBar,
    QSlider, QSplitter, QToolButton, QVBoxLayout, QWidget,
)

from . import project as project_file
from .clip_list import ClipListPanel
from .export_dialog import ExportProgressDialog, ExportSettingsDialog
from .help_dialog import HelpDialog
from .media_utils import Exporter, ProbeWorker, ThumbnailWorker
from .models import Clip, SourceInfo
from .time_display import TimeDisplayWidget
from .timeline_widget import MAX_ZOOM, MIN_CLIP_LEN, MIN_ZOOM, TimelineWidget
from .utils import VIDEO_EXTENSIONS, format_fps, format_time, random_pleasant_color
from .video_widget import VideoViewport

_ORG, _APP = "VideoClipper", "VideoClipper"
_RECENT_PROJECTS_KEY = "recent_projects"
_MAX_RECENT_PROJECTS = 10

_SCROLLBAR_SCALE = 1000  # seconds -> integer units for the QScrollBar (millisecond resolution)

_VIDEO_FILTER = (
    "Video Files (" + " ".join(f"*{ext}" for ext in VIDEO_EXTENSIONS) + ");;"
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
        self._dirty = False  # True when clips exist that haven't been exported/saved yet
        self.project_path: Optional[str] = None
        self.last_export_settings: Optional[dict] = None
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
    def _build_menu(self):
        file_menu = self.menuBar().addMenu("&File")

        self.open_video_action = QAction("Open Video...", self)
        file_menu.addAction(self.open_video_action)

        file_menu.addSeparator()

        self.save_project_action = QAction("Save Project JSON...", self)
        self.save_project_action.setShortcut(QKeySequence("Ctrl+S"))
        file_menu.addAction(self.save_project_action)

        self.open_project_action = QAction("Open Project JSON...", self)
        file_menu.addAction(self.open_project_action)

        self.recent_menu = QMenu("Open Recent", self)
        file_menu.addMenu(self.recent_menu)

        self.clear_recent_action = QAction("Clear Recent Projects", self)
        file_menu.addAction(self.clear_recent_action)

        file_menu.addSeparator()

        self.exit_action = QAction("Exit", self)
        file_menu.addAction(self.exit_action)

        self.help_action = QAction("&Help", self)
        self.menuBar().addAction(self.help_action)

    def _build_ui(self):
        self._build_menu()
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

        self.time_display = TimeDisplayWidget()
        self.time_display.setEnabled(False)

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
        controls_row.addWidget(self.time_display, 1)  # stretch factor centers it in the row
        controls_row.addWidget(self.start_btn)
        controls_row.addWidget(self.end_btn)
        left_layout.addLayout(controls_row)

        self.timeline = TimelineWidget()
        left_layout.addWidget(self.timeline)

        # Shown only once zoomed in; keyboard-focusable so panning doesn't need a mouse.
        self.pan_scrollbar = QScrollBar(Qt.Orientation.Horizontal)
        self.pan_scrollbar.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.pan_scrollbar.setCursor(Qt.CursorShape.ArrowCursor)
        self.pan_scrollbar.setInvertedControls(False)
        self.pan_scrollbar.setVisible(False)
        left_layout.addWidget(self.pan_scrollbar)

        zoom_row = QHBoxLayout()
        zoom_row.setSpacing(6)
        zoom_row.addStretch(1)

        self.zoom_out_btn = QToolButton()
        self.zoom_out_btn.setText("−")
        self.zoom_out_btn.setToolTip("Zoom out")
        self.zoom_out_btn.setEnabled(False)
        self.zoom_out_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.zoom_out_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("muted")
        self.zoom_label.setFixedWidth(44)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.zoom_in_btn = QToolButton()
        self.zoom_in_btn.setText("+")
        self.zoom_in_btn.setToolTip("Zoom in")
        self.zoom_in_btn.setEnabled(False)
        self.zoom_in_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.zoom_in_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self.zoom_fit_btn = QToolButton()
        self.zoom_fit_btn.setText("Fit")
        self.zoom_fit_btn.setToolTip("Reset zoom to fit the whole video")
        self.zoom_fit_btn.setEnabled(False)
        self.zoom_fit_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.zoom_fit_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        zoom_row.addWidget(self.zoom_out_btn)
        zoom_row.addWidget(self.zoom_label)
        zoom_row.addWidget(self.zoom_in_btn)
        zoom_row.addWidget(self.zoom_fit_btn)
        left_layout.addLayout(zoom_row)

        self.clip_panel = ClipListPanel()
        self.clip_panel.setObjectName("rightPane")
        self.clip_panel.setMinimumWidth(190)
        self.clip_panel.setMaximumWidth(420)

        splitter.addWidget(left_pane)
        splitter.addWidget(self.clip_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([1040, 340])

        main_layout.addWidget(splitter, 1)
        self.statusBar()

    def _wire_signals(self):
        self.open_video_action.triggered.connect(self.open_video_dialog)
        self.save_project_action.triggered.connect(self.save_project)
        self.open_project_action.triggered.connect(self.open_project_dialog)
        self.recent_menu.aboutToShow.connect(self._rebuild_recent_menu)
        self.clear_recent_action.triggered.connect(self._clear_recent_projects)
        self.exit_action.triggered.connect(self.close)
        self.help_action.triggered.connect(self.show_help)

        self.open_video_btn.clicked.connect(self.open_video_dialog)
        self.viewport.open_requested.connect(self.open_video_dialog)
        self.viewport.video_dropped.connect(self._try_load_video)
        self.viewport.position_changed.connect(self._on_position_changed)
        self.viewport.duration_changed.connect(self._on_duration_changed)
        self.viewport.playing_changed.connect(self._on_playing_changed)
        self.play_btn.clicked.connect(self.viewport.toggle_play)
        self.mute_btn.clicked.connect(self._on_mute_clicked)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        self.start_btn.clicked.connect(self.on_set_start)
        self.end_btn.clicked.connect(self.on_set_end)
        self.time_display.time_edit_requested.connect(self._on_seek_requested)

        self.timeline.seek_requested.connect(self._on_seek_requested)
        self.timeline.clip_renamed.connect(self.rename_clip)
        self.timeline.clip_delete_requested.connect(self.delete_clip)
        self.timeline.clip_color_requested.connect(self.change_clip_color)
        self.timeline.clip_resizing.connect(self._on_clip_resizing)
        self.timeline.clip_resized.connect(self._on_clip_resized)
        self.timeline.view_changed.connect(self._on_view_changed)
        self.timeline.selection_changed.connect(self._update_marker_buttons)

        self.zoom_out_btn.clicked.connect(self.timeline.zoom_out)
        self.zoom_in_btn.clicked.connect(self.timeline.zoom_in)
        self.zoom_fit_btn.clicked.connect(self.timeline.reset_zoom)
        self.pan_scrollbar.valueChanged.connect(self._on_scrollbar_moved)

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
            bind("Up", lambda: self._step_frame(1)),
            bind("Down", lambda: self._step_frame(-1)),
            bind("Home", lambda: self._safe_seek(0.0)),
            bind("End", lambda: self._safe_seek(self.viewport.duration())),
            bind("Del", self._shortcut_delete_selected_clip),
        ]

        # Disables shortcuts while a text field/scrollbar has focus (see CLAUDE.md).
        QApplication.instance().focusChanged.connect(self._on_focus_changed)
        # Clears the timeline selection on any click outside the timeline.
        QApplication.instance().installEventFilter(self)

    def _on_focus_changed(self, _old, _new):
        self._set_shortcuts_enabled(not self._input_widget_has_focus())

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress and self.timeline.selected_clip_id is not None:
            target = obj if isinstance(obj, QWidget) else None
            if target is not None and target is not self.timeline and not self.timeline.isAncestorOf(target):
                self.timeline.clear_selection()
        return super().eventFilter(obj, event)

    def _set_shortcuts_enabled(self, enabled: bool):
        for shortcut in self._shortcuts:
            shortcut.setEnabled(enabled)

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
        path, _ = QFileDialog.getOpenFileName(self, "Open video", "", _VIDEO_FILTER)
        if path:
            self._try_load_video(path)

    def _try_load_video(self, path: str):
        if not self._confirm_discard_if_needed("open another video"):
            return
        self._load_video(path)

    def _load_video(self, path: str):
        self._reset_clips()
        self.video_path = path
        self.source_info = None
        self.viewport.load(path)
        self._update_window_title()
        self.statusBar().showMessage("Video loaded.", 3000)
        self._probe_source(path)

    def _update_window_title(self):
        name = None
        if self.project_path:
            name = os.path.basename(self.project_path)
        elif self.video_path:
            name = os.path.basename(self.video_path)
        self.setWindowTitle(f"VideoClipper — {name}" if name else "VideoClipper")

    def _reset_clips(self):
        self.clip_panel.clear()
        self.clip_panel.set_aspect_ratio(None)  # back to the 16:9 default until the new video is probed
        self.timeline.reset()
        self.clips = []
        self.pending_start = None
        self.project_path = None
        self._clip_name_counter = 0
        self._dirty = False
        self._active_clip_end = None
        self._update_marker_buttons()
        self.export_btn.setEnabled(False)
        self.export_btn.setToolTip("Add at least one clip to export.")
        self.zoom_out_btn.setEnabled(False)
        self.zoom_in_btn.setEnabled(False)
        self.zoom_fit_btn.setEnabled(False)
        self.pan_scrollbar.setVisible(False)

    # ------------------------------------------------------------------
    # Project save/load
    # ------------------------------------------------------------------
    def save_project(self):
        if self.project_path:
            self._save_project_to(self.project_path)
        else:
            self._save_project_as()

    def _save_project_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project", self.project_path or "", "VideoClipper Project (*.json)")
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        self._save_project_to(path)

    def _save_project_to(self, path: str):
        try:
            project_file.save_project(
                path, self.video_path, self.clips, self._clip_name_counter,
                self.last_export_settings)
        except Exception as exc:
            QMessageBox.warning(self, "Save failed", f"Could not save the project:\n{exc}")
            return
        self.project_path = path
        self._dirty = False
        self._add_recent_project(path)
        self._update_window_title()
        self.statusBar().showMessage(f"Project saved to {path}", 4000)

    def open_project_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", "", "VideoClipper Project (*.json);;All Files (*)")
        if path:
            self._open_project_from_path(path)

    def _open_project_from_path(self, path: str):
        if not self._confirm_discard_if_needed("open a different project"):
            return
        try:
            data = project_file.load_project(path)
        except Exception as exc:
            QMessageBox.warning(self, "Open project failed", f"Could not open '{path}':\n{exc}")
            self._remove_recent_project(path)
            return

        self._reset_clips()
        self.project_path = path
        self._clip_name_counter = data["clip_name_counter"]
        self.last_export_settings = data["export_settings"]

        saved_video_path = data["video_path"]
        if saved_video_path and os.path.exists(saved_video_path):
            self.video_path = saved_video_path
            self.source_info = None
            self.viewport.load(self.video_path)
            self._probe_source(self.video_path)
        else:
            self.video_path = None
            if saved_video_path:
                QMessageBox.warning(
                    self, "Video not found",
                    f"The project's video could not be found:\n{saved_video_path}\n\n"
                    "The saved clips are still loaded - use Open Video to relink it.")
            if data["clips"]:
                self.timeline.set_duration(max(c.end for c in data["clips"]) * 1.05)

        for clip in data["clips"]:
            self.clips.append(clip)
            self.timeline.add_clip(clip)
            self.clip_panel.add_clip(clip)
            if self.video_path:
                self._request_thumbnail(clip)

        if self.clips:
            self.export_btn.setEnabled(True)
            self.export_btn.setToolTip("")
        self._dirty = False
        self._add_recent_project(path)
        self._update_window_title()
        self.statusBar().showMessage(f"Project loaded from {path}", 4000)

    # -- recent projects -------------------------------------------------
    def _rebuild_recent_menu(self):
        self.recent_menu.clear()
        recents = self._get_recent_projects()
        if not recents:
            empty_action = QAction("(No recent projects)", self.recent_menu)
            empty_action.setEnabled(False)
            self.recent_menu.addAction(empty_action)
            return
        for path in recents:
            action = QAction(path, self.recent_menu)
            action.triggered.connect(lambda checked=False, p=path: self._open_project_from_path(p))
            self.recent_menu.addAction(action)

    @staticmethod
    def _get_recent_projects() -> List[str]:
        raw = QSettings(_ORG, _APP).value(_RECENT_PROJECTS_KEY, [])
        if isinstance(raw, str):
            raw = [raw] if raw else []
        return list(raw or [])

    def _add_recent_project(self, path: str):
        recents = [p for p in self._get_recent_projects() if p != path]
        recents.insert(0, path)
        QSettings(_ORG, _APP).setValue(_RECENT_PROJECTS_KEY, recents[:_MAX_RECENT_PROJECTS])

    def _remove_recent_project(self, path: str):
        recents = [p for p in self._get_recent_projects() if p != path]
        QSettings(_ORG, _APP).setValue(_RECENT_PROJECTS_KEY, recents)

    def _clear_recent_projects(self):
        QSettings(_ORG, _APP).setValue(_RECENT_PROJECTS_KEY, [])

    def show_help(self):
        HelpDialog(self).exec()

    def _probe_source(self, path: str):
        worker = ProbeWorker(path)
        self._probe_workers.append(worker)
        worker.ready.connect(self._on_source_probed)
        worker.finished.connect(lambda w=worker: w in self._probe_workers and self._probe_workers.remove(w))
        worker.start()

    def _on_source_probed(self, info: SourceInfo):
        self.source_info = info
        self.time_display.set_fps(info.fps)
        if info.width and info.height:
            self.clip_panel.set_aspect_ratio(info.width / info.height)
            extra = f" ({info.width}x{info.height}"
            if info.fps:
                extra += f", {format_fps(info.fps)} fps"
            extra += ")"
            self.statusBar().showMessage("Video loaded." + extra, 4000)

    def _on_duration_changed(self, seconds: float):
        self.timeline.set_duration(seconds)
        self.time_display.set_duration(seconds)
        if self.video_path:
            self.play_btn.setEnabled(True)
            self.mute_btn.setEnabled(True)
            self.volume_slider.setEnabled(True)
            self.time_display.setEnabled(True)
            self._update_marker_buttons()
            self.zoom_in_btn.setEnabled(True)
            self._on_view_changed(self.timeline.zoom, self.timeline.view_start, self.timeline.duration)

    def _on_view_changed(self, zoom: float, view_start: float, duration: float):
        self.zoom_label.setText(f"{round(zoom * 100)}%")
        zoomed_in = self.video_path is not None and zoom > MIN_ZOOM + 1e-6
        self.zoom_out_btn.setEnabled(zoomed_in)
        self.zoom_fit_btn.setEnabled(zoomed_in)
        self.zoom_in_btn.setEnabled(self.video_path is not None and zoom < MAX_ZOOM - 1e-6)

        self.pan_scrollbar.setVisible(zoomed_in)
        if zoomed_in and duration > 0:
            visible = duration / zoom
            max_start = max(0.0, duration - visible)
            self.pan_scrollbar.blockSignals(True)
            self.pan_scrollbar.setRange(0, round(max_start * _SCROLLBAR_SCALE))
            self.pan_scrollbar.setPageStep(max(1, round(visible * _SCROLLBAR_SCALE)))
            self.pan_scrollbar.setSingleStep(max(1, round(visible * 0.1 * _SCROLLBAR_SCALE)))
            self.pan_scrollbar.setValue(round(view_start * _SCROLLBAR_SCALE))
            self.pan_scrollbar.blockSignals(False)

    def _on_scrollbar_moved(self, value: int):
        self.timeline.pan_to(value / _SCROLLBAR_SCALE)

    def _on_position_changed(self, seconds: float):
        self.timeline.set_position(seconds)
        self.time_display.set_current(seconds)
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

    # ------------------------------------------------------------------
    # Marker placement (start -> end -> new clip)
    # ------------------------------------------------------------------
    def _update_marker_buttons(self):
        has_pending = self.pending_start is not None
        has_selection = self.timeline.selected_clip_id is not None
        self.start_btn.setEnabled(not has_pending)
        self.end_btn.setEnabled(has_pending or has_selection)

    def on_set_start(self):
        if not self.video_path:
            return
        t = self.viewport.current_position()
        if self.pending_start is None and self.timeline.selected_clip_id is not None:
            clip = self._clip_by_id(self.timeline.selected_clip_id)
            if clip:
                lower, _upper = self.timeline.neighbor_bounds(clip)
                clip.start = max(lower, min(t, clip.end - MIN_CLIP_LEN))
                self.timeline.update_clip(clip)
                self._on_clip_resized(clip.id, clip.start, clip.end)
                self.statusBar().showMessage(
                    f"'{clip.name}' in-point moved to {format_time(clip.start)}.", 3000)
            return
        for clip in self.clips:
            if clip.contains(t):
                self.statusBar().showMessage("Can't start a clip inside an existing clip.", 4000)
                return
        self.pending_start = t
        self.timeline.set_pending_start(t)
        self._update_marker_buttons()
        self.statusBar().showMessage(
            f"In-point set at {format_time(t)}. Scrub ahead and set the out-point.", 4000)

    def on_set_end(self):
        if self.pending_start is None:
            clip = self._clip_by_id(self.timeline.selected_clip_id) \
                if self.timeline.selected_clip_id is not None else None
            if not clip:
                return
            t = self.viewport.current_position()
            _lower, upper = self.timeline.neighbor_bounds(clip)
            clip.end = min(upper, max(t, clip.start + MIN_CLIP_LEN))
            self.timeline.update_clip(clip)
            self._on_clip_resized(clip.id, clip.start, clip.end)
            self.statusBar().showMessage(
                f"'{clip.name}' out-point moved to {format_time(clip.end)}.", 3000)
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
        self._update_marker_buttons()
        self.export_btn.setEnabled(True)
        self.export_btn.setToolTip("")
        self.statusBar().showMessage(f"Clip '{clip.name}' created.", 3000)

    def _cancel_pending_marker(self):
        if self.pending_start is not None:
            self.pending_start = None
            self.timeline.set_pending_start(None)
            self._update_marker_buttons()
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
    # Shortcuts
    # ------------------------------------------------------------------
    @staticmethod
    def _input_widget_has_focus() -> bool:
        return isinstance(QApplication.focusWidget(), (QLineEdit, QScrollBar))

    def _shortcut_toggle_play(self):
        if self._input_widget_has_focus() or not self.video_path:
            return
        self.viewport.toggle_play()

    def _shortcut_set_start(self):
        if self._input_widget_has_focus():
            return
        if self.start_btn.isEnabled():
            self.on_set_start()

    def _shortcut_set_end(self):
        if self._input_widget_has_focus():
            return
        if self.end_btn.isEnabled():
            self.on_set_end()

    def _shortcut_cancel_pending(self):
        if self._input_widget_has_focus():
            return
        self._cancel_pending_marker()

    def _seek_relative(self, delta: float):
        if self._input_widget_has_focus() or not self.video_path:
            return
        self._active_clip_end = None
        self.viewport.seek(self.viewport.current_position() + delta)

    def _safe_seek(self, t: float):
        if self._input_widget_has_focus() or not self.video_path:
            return
        self._active_clip_end = None
        self.viewport.seek(t)

    def _step_frame(self, delta_frames: int):
        if self._input_widget_has_focus() or not self.video_path:
            return
        self._active_clip_end = None
        self.viewport.pause()  # frame-stepping only makes sense paused
        fps = self.source_info.fps if self.source_info and self.source_info.fps else 30.0
        self.viewport.seek(self.viewport.current_position() + delta_frames / fps)

    def _shortcut_delete_selected_clip(self):
        if self._input_widget_has_focus():
            return
        clip_id = self.timeline.selected_clip_id
        if clip_id is not None:
            self.delete_clip(clip_id)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def open_export_dialog(self):
        if not self.clips or not self.video_path:
            return
        dialog = ExportSettingsDialog(
            self.clips, video_path=self.video_path, source_info=self.source_info,
            initial_settings=self.last_export_settings, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._start_export(dialog.get_settings())

    def _start_export(self, settings: dict):
        self.last_export_settings = settings
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
