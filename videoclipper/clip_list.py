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
from .utils import format_time

_THUMB_W, _THUMB_H = 240, 135


class ClipItemWidget(QFrame):
    activated = pyqtSignal(int)
    renamed = pyqtSignal(int, str)
    delete_requested = pyqtSignal(int)

    def __init__(self, clip: Clip, parent=None):
        super().__init__(parent)
        self.clip_id = clip.id

        self.setObjectName("clipItem")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        self.thumb_label = QLabel("Generating thumbnail…")
        self.thumb_label.setFixedSize(_THUMB_W, _THUMB_H)
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

    # -- external updates -------------------------------------------------
    def set_thumbnail(self, pixmap: QPixmap):
        scaled = pixmap.scaled(
            _THUMB_W, _THUMB_H,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.thumb_label.setPixmap(scaled)

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

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Clips")
        title.setObjectName("panelHeader")
        self.count_label = QLabel("0")
        self.count_label.setObjectName("panelCount")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.count_label)
        root.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

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
        root.addWidget(self.empty_hint)
        self.scroll.setVisible(False)

    def add_clip(self, clip: Clip):
        item = ClipItemWidget(clip)
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
        self.scroll.setVisible(count > 0)
        self.empty_hint.setVisible(count == 0)
