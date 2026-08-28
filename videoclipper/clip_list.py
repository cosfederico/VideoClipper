"""Right-hand panel: a vertical list of clip cards (thumbnail + name).

Cards are static - just a thumbnail and a name, no per-card video playback.
Click a card to jump the main viewport to that clip and play it there.
"""
from __future__ import annotations

from typing import Dict, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QSizePolicy,
    QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from .models import Clip
from .style import MUTED
from .utils import format_time

_CARD_MARGIN = 8      # matches ClipItemWidget's outer QVBoxLayout margins
_DEFAULT_ASPECT = 16 / 9
_MIN_ASPECT, _MAX_ASPECT = 0.3, 4.0  # clamp: extreme-portrait to extreme-ultrawide
_BASE_CARD_W = 240     # card width at which text sizes below equal the app default
_BASE_NAME_PX, _BASE_DURATION_PX = 13, 11
_MIN_TEXT_SCALE, _MAX_TEXT_SCALE = 0.8, 1.6


class ClipItemWidget(QFrame):
    activated = pyqtSignal(int)
    renamed = pyqtSignal(int, str)
    delete_requested = pyqtSignal(int)

    def __init__(self, clip: Clip, aspect_ratio: float = _DEFAULT_ASPECT, parent=None):
        super().__init__(parent)
        self.clip_id = clip.id
        ratio = aspect_ratio if aspect_ratio and aspect_ratio > 0 else _DEFAULT_ASPECT
        self._aspect_ratio = max(_MIN_ASPECT, min(_MAX_ASPECT, ratio))
        self._raw_pixmap: Optional[QPixmap] = None

        self.setObjectName("clipItem")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(_CARD_MARGIN, _CARD_MARGIN, _CARD_MARGIN, _CARD_MARGIN)
        outer.setSpacing(6)

        self.thumb_label = QLabel("Generating thumbnail…")
        # Ignored horizontal: width comes from the layout, not the pixmap (see CLAUDE.md).
        self.thumb_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setStyleSheet(
            "background:#101116; color:#8d93a3; border-radius:6px;"
        )
        outer.addWidget(self.thumb_label)

        name_row = QHBoxLayout()
        name_row.setSpacing(6)

        self.name_stack = QStackedWidget()
        self.name_label = QLabel(clip.name)
        self.name_label.setObjectName("clipName")
        self.name_label.setCursor(Qt.CursorShape.IBeamCursor)
        self.name_edit = QLineEdit(clip.name)
        self.name_stack.addWidget(self.name_label)
        self.name_stack.addWidget(self.name_edit)

        self.duration_label = QLabel(format_time(clip.duration()))
        self.duration_label.setObjectName("clipDuration")

        self.delete_btn = QToolButton()
        self.delete_btn.setObjectName("deleteClipBtn")
        self.delete_btn.setText("✕")
        self.delete_btn.setToolTip("Delete clip")
        self.delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.clip_id))

        name_row.addWidget(self.name_stack, 1)
        name_row.addWidget(self.duration_label, 0)
        name_row.addWidget(self.delete_btn, 0)
        outer.addLayout(name_row)

        self.name_edit.editingFinished.connect(self._commit_rename)

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._update_thumb_size()

    # -- responsive sizing --------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_thumb_size()

    def _update_thumb_size(self):
        avail_w = max(1, self.width() - 2 * _CARD_MARGIN)
        thumb_h = max(2, round(avail_w / self._aspect_ratio))
        if thumb_h != self.thumb_label.height():
            self.thumb_label.setFixedHeight(thumb_h)
        self._rescale_thumbnail()

        scale = max(_MIN_TEXT_SCALE, min(_MAX_TEXT_SCALE, avail_w / _BASE_CARD_W))
        name_px = max(10, round(_BASE_NAME_PX * scale))
        duration_px = max(9, round(_BASE_DURATION_PX * scale))
        # per-instance stylesheet so each card scales independently
        self.name_label.setStyleSheet(f"font-weight:600; font-size:{name_px}px;")
        self.duration_label.setStyleSheet(f"color:{MUTED}; font-size:{duration_px}px;")

    def _rescale_thumbnail(self):
        if self._raw_pixmap is None or self._raw_pixmap.isNull():
            return
        w, h = self.thumb_label.width(), self.thumb_label.height()
        if w <= 0 or h <= 0:
            return
        scaled = self._raw_pixmap.scaled(
            w, h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.thumb_label.setPixmap(scaled)

    def set_aspect_ratio(self, ratio: float):
        ratio = ratio if ratio and ratio > 0 else _DEFAULT_ASPECT
        self._aspect_ratio = max(_MIN_ASPECT, min(_MAX_ASPECT, ratio))
        self._update_thumb_size()

    # -- external updates -------------------------------------------------
    def set_thumbnail(self, pixmap: QPixmap):
        self._raw_pixmap = pixmap
        self._rescale_thumbnail()

    def set_name(self, name: str):
        self.name_label.setText(name)
        if not self.name_edit.hasFocus():
            self.name_edit.setText(name)

    def set_duration_text(self, seconds: float):
        self.duration_label.setText(format_time(seconds))

    # -- rename ------------------------------------------------------------
    def _begin_rename(self):
        self.name_edit.setText(self.name_label.text())
        self.name_stack.setCurrentWidget(self.name_edit)
        self.name_edit.selectAll()
        self.name_edit.setFocus(Qt.FocusReason.MouseFocusReason)

    def _commit_rename(self):
        if self.name_stack.currentWidget() is not self.name_edit:
            return
        text = self.name_edit.text().strip() or self.name_label.text()
        self.name_stack.setCurrentWidget(self.name_label)
        if text != self.name_label.text():
            self.name_label.setText(text)
            self.renamed.emit(self.clip_id, text)

    # -- mouse events ---------------------------------------------
    def mousePressEvent(self, event):
        if self.name_stack.currentWidget() is self.name_edit:
            return super().mousePressEvent(event)
        self.activated.emit(self.clip_id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.thumb_label.underMouse():
            return super().mouseDoubleClickEvent(event)
        self._begin_rename()


class ClipListPanel(QWidget):
    item_activated = pyqtSignal(int)
    item_renamed = pyqtSignal(int, str)
    item_delete_requested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: Dict[int, ClipItemWidget] = {}
        self._clip_starts: Dict[int, float] = {}
        self._aspect_ratio = _DEFAULT_ASPECT

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("Clips")
        title.setObjectName("panelHeader")
        self.count_label = QLabel("0")
        self.count_label.setObjectName("panelCount")
        self.count_label.setVisible(False)  # hidden until there's at least one clip
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.count_label)
        root.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Always-on, not AsNeeded - avoids a width/height feedback loop (see CLAUDE.md).
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(10)
        self._list_layout.addStretch(1)
        self.scroll.setWidget(self._list_container)
        root.addWidget(self.scroll, 1)

        self.empty_hint = QLabel(
            "No clips yet.\nScrub the timeline and set an In / Out marker to create one."
        )
        self.empty_hint.setObjectName("emptyHint")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setWordWrap(True)
        root.addWidget(self.empty_hint, 1)  # stretch matches scroll's, so extra space goes here
        self.scroll.setVisible(False)

    def set_aspect_ratio(self, ratio: float):
        """Called once the source video's dimensions are known (or reset to
        the default when a new video is loading) so thumbnails match its
        actual shape instead of an assumed 16:9."""
        self._aspect_ratio = ratio if ratio and ratio > 0 else _DEFAULT_ASPECT
        for item in self._items.values():
            item.set_aspect_ratio(self._aspect_ratio)

    def add_clip(self, clip: Clip):
        item = ClipItemWidget(clip, aspect_ratio=self._aspect_ratio)
        item.activated.connect(self.item_activated.emit)
        item.renamed.connect(self.item_renamed.emit)
        item.delete_requested.connect(self.item_delete_requested.emit)
        self._items[clip.id] = item

        insert_at = self._list_layout.count() - 1  # keep trailing stretch last
        for i in range(self._list_layout.count() - 1):
            widget = self._list_layout.itemAt(i).widget()
            if isinstance(widget, ClipItemWidget) and widget.clip_id in self._clip_starts \
                    and self._clip_starts[widget.clip_id] > clip.start:
                insert_at = i
                break
        self._list_layout.insertWidget(insert_at, item)
        self._clip_starts[clip.id] = clip.start
        self._refresh_visibility()

    def remove_clip(self, clip_id: int):
        item = self._items.pop(clip_id, None)
        if item:
            item.setParent(None)
            item.deleteLater()
        self._clip_starts.pop(clip_id, None)
        self._refresh_visibility()

    def clear(self):
        for clip_id in list(self._items.keys()):
            self.remove_clip(clip_id)

    def update_thumbnail(self, clip_id: int, pixmap: QPixmap):
        item = self._items.get(clip_id)
        if item:
            item.set_thumbnail(pixmap)

    def rename_clip(self, clip_id: int, name: str):
        item = self._items.get(clip_id)
        if item:
            item.set_name(name)

    def update_range(self, clip_id: int, start: float, end: float):
        item = self._items.get(clip_id)
        if item:
            item.set_duration_text(end - start)

    def get_item(self, clip_id: int) -> Optional[ClipItemWidget]:
        return self._items.get(clip_id)

    def _refresh_visibility(self):
        count = len(self._items)
        self.count_label.setText(str(count))
        self.count_label.setVisible(count > 0)
        self.scroll.setVisible(count > 0)
        self.empty_hint.setVisible(count == 0)
