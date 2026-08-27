"""Export settings dialog + the export progress dialog."""
from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import QSettings, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton, QSlider,
    QVBoxLayout, QWidget,
)

from .ffmpeg_utils import FPS_CHOICES, SCALE_CHOICES, build_output_basename
from .models import Clip, SourceInfo
from .utils import format_fps, format_time

_CONTAINERS = {
    "MP4 (.mp4)": (".mp4", ("libx264", "libx265", "copy")),
    "MKV (.mkv)": (".mkv", ("libx264", "libx265", "libvpx-vp9", "copy")),
    "MOV (.mov)": (".mov", ("libx264", "libx265", "copy")),
    "WebM (.webm)": (".webm", ("libvpx-vp9",)),
}

_CODEC_LABELS = {
    "libx264": "H.264 (libx264) — recommended",
    "libx265": "H.265 / HEVC (libx265) — smaller files, slower",
    "libvpx-vp9": "VP9 (libvpx-vp9)",
    "copy": "Copy — no re-encode, fastest, cuts snap to keyframes",
}

_PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast",
            "medium", "slow", "slower", "veryslow"]


class ExportSettingsDialog(QDialog):
    def __init__(self, clips: List[Clip], video_path: str = "",
                 source_info: Optional[SourceInfo] = None,
                 default_dir: str = "", parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.source_info = source_info
        self.setWindowTitle("Export Clips")
        self.setMinimumWidth(480)
        self._settings_store = QSettings("VideoClipper", "VideoClipper")

        total = sum(c.duration() for c in clips)
        first_clip_name = clips[0].name if clips else "Clip1"
        root = QVBoxLayout(self)

        summary = QLabel(f"Exporting {len(clips)} clip(s) — {format_time(total)} total")
        summary.setObjectName("sectionLabel")
        root.addWidget(summary)

        # -- output folder --------------------------------------------------
        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit(default_dir or self._settings_store.value("last_dir", ""))
        self.folder_edit.setPlaceholderText("Choose an output folder…")
        self.folder_edit.setReadOnly(True)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._choose_folder)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(browse_btn)

        form = QFormLayout()
        form.setSpacing(10)
        form.addRow("Save to", folder_row)

        # -- container / codec ------------------------------------------------
        self.container_combo = QComboBox()
        self.container_combo.addItems(_CONTAINERS.keys())
        last_container = self._settings_store.value("container", "MP4 (.mp4)")
        if last_container in _CONTAINERS:
            self.container_combo.setCurrentText(last_container)
        self.container_combo.currentTextChanged.connect(self._on_container_changed)
        form.addRow("Format", self.container_combo)

        self.codec_combo = QComboBox()
        self.codec_combo.currentTextChanged.connect(self._on_codec_changed)
        form.addRow("Video codec", self.codec_combo)

        # -- quality -----------------------------------------------------------
        crf_row = QHBoxLayout()
        self.crf_slider = QSlider(Qt.Orientation.Horizontal)
        self.crf_slider.setRange(0, 51)
        self.crf_slider.setValue(int(self._settings_store.value("crf", 20)))
        self.crf_value_label = QLabel(str(self.crf_slider.value()))
        self.crf_slider.valueChanged.connect(lambda v: self.crf_value_label.setText(str(v)))
        crf_row.addWidget(self.crf_slider, 1)
        crf_row.addWidget(self.crf_value_label)
        form.addRow("Quality (CRF)", crf_row)

        crf_hint = QLabel("Lower = better quality & larger file. 18–28 is a typical range.")
        crf_hint.setObjectName("muted")
        form.addRow("", crf_hint)

        self.preset_combo = QComboBox()
        self.preset_combo.addItems(_PRESETS)
        self.preset_combo.setCurrentText(str(self._settings_store.value("preset", "medium")))
        form.addRow("Encode speed", self.preset_combo)

        self.scale_combo = QComboBox()
        for label, _value in SCALE_CHOICES:
            self.scale_combo.addItem(label, _value)
        form.addRow("Resolution", self.scale_combo)

        self.fps_combo = QComboBox()
        source_fps = source_info.fps if source_info else None
        maintain_label = "Maintain original"
        if source_fps:
            maintain_label += f" ({format_fps(source_fps)} fps)"
        self.fps_combo.addItem(maintain_label, None)
        for label, _value, arg in FPS_CHOICES:
            self.fps_combo.addItem(f"{label} fps", arg)
        form.addRow("Frame rate", self.fps_combo)

        # -- audio -----------------------------------------------------------
        self.audio_check = QCheckBox("Include audio")
        self.audio_check.setChecked(True)
        self.audio_check.toggled.connect(self._on_audio_toggled)
        form.addRow("", self.audio_check)

        self.audio_codec_combo = QComboBox()
        self.audio_codec_combo.addItems(["AAC", "Copy"])
        form.addRow("Audio codec", self.audio_codec_combo)

        self.audio_bitrate_combo = QComboBox()
        self.audio_bitrate_combo.addItems(["128k", "192k", "256k", "320k"])
        self.audio_bitrate_combo.setCurrentText("192k")
        form.addRow("Audio bitrate", self.audio_bitrate_combo)
        self.audio_codec_combo.currentTextChanged.connect(self._on_audio_codec_changed)

        # -- filenames / metadata ---------------------------------------------
        self.include_video_name_check = QCheckBox("Include original video name in exported files")
        self.include_video_name_check.setChecked(
            bool(self._settings_store.value("include_video_name", True, type=bool))
        )
        self.include_video_name_check.toggled.connect(self._update_filename_preview)
        form.addRow("", self.include_video_name_check)

        self.filename_preview = QLabel("")
        self.filename_preview.setObjectName("muted")
        form.addRow("", self.filename_preview)

        self.save_metadata_check = QCheckBox("Save clip metadata (JSON: source info, export settings, clip times)")
        self.save_metadata_check.setChecked(
            bool(self._settings_store.value("save_metadata", True, type=bool))
        )
        form.addRow("", self.save_metadata_check)

        root.addLayout(form)

        self.warning_label = QLabel("")
        self.warning_label.setObjectName("warningLabel")
        self.warning_label.setWordWrap(True)
        self.warning_label.setVisible(False)
        root.addWidget(self.warning_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.export_btn = QPushButton("Export")
        self.export_btn.setObjectName("primaryButton")
        self.export_btn.setDefault(True)
        buttons.addButton(self.export_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self._on_accept)
        root.addWidget(buttons)

        self._first_clip_name = first_clip_name
        self._on_container_changed(self.container_combo.currentText())
        last_codec = self._settings_store.value("video_codec", "")
        codec_values = [self.codec_combo.itemData(i) for i in range(self.codec_combo.count())]
        if last_codec and last_codec in codec_values:
            self.codec_combo.setCurrentIndex(codec_values.index(last_codec))
        self._on_codec_changed(self.codec_combo.currentText())
        self._update_filename_preview()

    # -- reactive UI -----------------------------------------------------
    def _on_container_changed(self, label: str):
        _, codecs = _CONTAINERS[label]
        self.codec_combo.blockSignals(True)
        self.codec_combo.clear()
        for codec in codecs:
            self.codec_combo.addItem(_CODEC_LABELS[codec], codec)
        self.codec_combo.blockSignals(False)
        self._on_codec_changed(self.codec_combo.currentText())

    def _on_codec_changed(self, _label: str):
        codec = self.codec_combo.currentData()
        is_copy = codec == "copy"
        can_crf = codec in ("libx264", "libx265", "libvpx-vp9")
        can_preset = codec in ("libx264", "libx265")
        self.crf_slider.setEnabled(can_crf)
        self.crf_value_label.setEnabled(can_crf)
        self.preset_combo.setEnabled(can_preset)
        self.scale_combo.setEnabled(not is_copy)
        self.fps_combo.setEnabled(not is_copy)
        if is_copy:
            self.fps_combo.setCurrentIndex(0)  # "maintain original" - can't change fps without re-encoding
            self.warning_label.setText(
                "Copy mode skips re-encoding: exports are fast but cut points snap "
                "to the nearest keyframe, and resolution/frame rate can't be changed."
            )
            self.warning_label.setVisible(True)
        else:
            self.warning_label.setVisible(False)

    def _on_audio_toggled(self, checked: bool):
        self.audio_codec_combo.setEnabled(checked)
        self.audio_bitrate_combo.setEnabled(checked and self.audio_codec_combo.currentText() == "AAC")

    def _on_audio_codec_changed(self, text: str):
        self.audio_bitrate_combo.setEnabled(self.audio_check.isChecked() and text == "AAC")

    def _update_filename_preview(self):
        ext, _ = _CONTAINERS[self.container_combo.currentText()] if self.container_combo.count() else (".mp4", None)
        name = build_output_basename(
            self.video_path or "video", self._first_clip_name,
            self.include_video_name_check.isChecked(),
        )
        self.filename_preview.setText(f"Example filename: {name}{ext}")

    def _choose_folder(self):
        start_dir = self.folder_edit.text() or str(self._settings_store.value("last_dir", ""))
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder", start_dir)
        if folder:
            self.folder_edit.setText(folder)

    def _on_accept(self):
        if not self.folder_edit.text().strip():
            self.warning_label.setText("Please choose an output folder before exporting.")
            self.warning_label.setVisible(True)
            return
        self._settings_store.setValue("last_dir", self.folder_edit.text())
        self._settings_store.setValue("container", self.container_combo.currentText())
        self._settings_store.setValue("video_codec", self.codec_combo.currentData())
        self._settings_store.setValue("crf", self.crf_slider.value())
        self._settings_store.setValue("preset", self.preset_combo.currentText())
        self._settings_store.setValue("include_video_name", self.include_video_name_check.isChecked())
        self._settings_store.setValue("save_metadata", self.save_metadata_check.isChecked())
        self.accept()

    def get_settings(self) -> dict:
        ext, _ = _CONTAINERS[self.container_combo.currentText()]
        return {
            "output_dir": self.folder_edit.text().strip(),
            "ext": ext,
            "video_codec": self.codec_combo.currentData(),
            "crf": self.crf_slider.value(),
            "preset": self.preset_combo.currentText(),
            "scale": self.scale_combo.currentData(),
            "fps_arg": self.fps_combo.currentData(),
            "fps_label": self.fps_combo.currentText(),
            "include_audio": self.audio_check.isChecked(),
            "audio_codec": "aac" if self.audio_codec_combo.currentText() == "AAC" else "copy",
            "audio_bitrate": self.audio_bitrate_combo.currentText(),
            "include_video_name": self.include_video_name_check.isChecked(),
            "save_metadata": self.save_metadata_check.isChecked(),
        }


class ExportProgressDialog(QDialog):
    cancel_requested = pyqtSignal()

    def __init__(self, total_clips: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Exporting…")
        self.setMinimumWidth(420)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self._finished = False
        self._total_clips = total_clips

        root = QVBoxLayout(self)

        self.title_label = QLabel("Exporting clips…")
        self.title_label.setObjectName("panelHeader")
        root.addWidget(self.title_label)

        self.clip_label = QLabel(f"Preparing 1 of {total_clips}…")
        self.clip_label.setObjectName("muted")
        root.addWidget(self.clip_label)

        root.addWidget(QLabel("Current clip"))
        self.clip_progress = QProgressBar()
        self.clip_progress.setRange(0, 100)
        root.addWidget(self.clip_progress)

        root.addWidget(QLabel("Overall"))
        self.overall_progress = QProgressBar()
        self.overall_progress.setRange(0, 100)
        root.addWidget(self.overall_progress)

        self.eta_label = QLabel("Estimating time remaining…")
        self.eta_label.setObjectName("muted")
        root.addWidget(self.eta_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.action_btn = QPushButton("Cancel")
        self.action_btn.clicked.connect(self._on_action)
        btn_row.addWidget(self.action_btn)
        root.addLayout(btn_row)

    def _on_action(self):
        if self._finished:
            self.accept()
        else:
            self.cancel_requested.emit()
            self.action_btn.setEnabled(False)
            self.action_btn.setText("Cancelling…")

    # -- progress updates --------------------------------------------------
    def update_clip_started(self, index: int, total: int, name: str):
        self.clip_label.setText(f"Clip {index + 1} of {total} — {name}")
        self.clip_progress.setValue(0)

    def update_clip_progress(self, pct: float):
        self.clip_progress.setValue(int(max(0, min(100, pct))))

    def update_overall(self, pct: float, eta_seconds: Optional[float]):
        self.overall_progress.setValue(int(max(0, min(100, pct))))
        if eta_seconds is None:
            self.eta_label.setText("Estimating time remaining…")
        else:
            self.eta_label.setText(f"About {format_time(eta_seconds)} remaining")

    def set_finished(self, success: bool, message: str):
        self._finished = True
        self.overall_progress.setValue(100 if success else self.overall_progress.value())
        self.title_label.setText("Export complete" if success else "Export failed")
        self.clip_label.setText(message)
        self.eta_label.setText("")
        self.action_btn.setEnabled(True)
        self.action_btn.setText("Close")
