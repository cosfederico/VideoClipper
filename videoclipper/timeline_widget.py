"""Custom-painted timeline: scrub bar, pending marker, clip blocks, ruler."""
from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor, QFontMetrics, QMouseEvent, QPainter, QPen, QPolygonF, QResizeEvent,
    QWheelEvent,
)
from PyQt6.QtWidgets import QLineEdit, QMenu, QWidget

from .models import Clip
from .utils import format_time, nice_time_step

_MARGIN = 10
_TRACK_Y = 18
_TRACK_H = 42
_RULER_Y = _TRACK_Y + _TRACK_H + 4
_EDGE_GRAB_PX = 6
MIN_CLIP_LEN = 0.05

MIN_ZOOM = 1.0
MAX_ZOOM = 60.0
_WHEEL_ZOOM_FACTOR = 1.15   # per wheel notch (angleDelta of 120)
_BUTTON_ZOOM_FACTOR = 1.6   # per click of the +/- buttons
_WHEEL_PAN_FRACTION = 0.08  # of the visible window, per wheel notch


class _InlineEditor(QLineEdit):
    """A QLineEdit that reports Escape instead of silently eating it."""

    cancelled = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)


class TimelineWidget(QWidget):
    seek_requested = pyqtSignal(float)
    clip_renamed = pyqtSignal(int, str)
    clip_delete_requested = pyqtSignal(int)
    clip_color_requested = pyqtSignal(int)
    clip_resizing = pyqtSignal(int, float, float)   # live, while dragging an edge
    clip_resized = pyqtSignal(int, float, float)    # once, on release
    view_changed = pyqtSignal(float, float, float)  # zoom, view_start, duration
    selection_changed = pyqtSignal(object)          # clip id (int), or None when cleared

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(_RULER_Y + 18)
        self.setMaximumHeight(_RULER_Y + 18)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

        self.duration = 0.0
        self.position = 0.0
        self.pending_start: Optional[float] = None
        self.clips: List[Clip] = []
        self.selected_clip_id: Optional[int] = None

        # maps [view_start, view_start + visible_duration()] to the widget's width
        self.zoom = MIN_ZOOM
        self.view_start = 0.0

        self._dragging = False
        self._active_editor: Optional[_InlineEditor] = None

        self._resizing_clip: Optional[Clip] = None
        self._resizing_edge: Optional[str] = None
        self._resize_lower = 0.0
        self._resize_upper = 0.0

    # -- state setters --------------------------------------------------
    def set_duration(self, seconds: float):
        self.duration = max(0.0, seconds)
        self.update()

    def set_position(self, seconds: float):
        self.position = max(0.0, seconds)
        # keep the playhead in view when zoomed in
        if self.zoom > MIN_ZOOM + 1e-9:
            visible = self.visible_duration()
            if not (self.view_start <= self.position <= self.view_start + visible):
                old_view_start = self.view_start
                self._set_view_start(self.position - visible / 2.0)
                if abs(self.view_start - old_view_start) > 1e-9:
                    self.view_changed.emit(self.zoom, self.view_start, self.duration)
        self.update()

    def set_pending_start(self, seconds: Optional[float]):
        self.pending_start = seconds
        self.update()

    def add_clip(self, clip: Clip):
        self.clips.append(clip)
        self.update()

    def remove_clip(self, clip_id: int):
        self.clips = [c for c in self.clips if c.id != clip_id]
        if self.selected_clip_id == clip_id:
            self._set_selection(None)
        self.update()

    def update_clip(self, clip: Clip):
        self.update()

    # -- selection ----------------------------------------------------
    def _set_selection(self, clip_id: Optional[int]):
        if clip_id == self.selected_clip_id:
            return
        self.selected_clip_id = clip_id
        self.update()
        self.selection_changed.emit(clip_id)

    def clear_selection(self):
        self._set_selection(None)

    def reset(self):
        self.clips = []
        self.pending_start = None
        self.duration = 0.0
        self.position = 0.0
        self.zoom = MIN_ZOOM
        self.view_start = 0.0
        self._set_selection(None)
        self._resizing_clip = None
        self._resizing_edge = None
        self.update()
        self.view_changed.emit(self.zoom, self.view_start, self.duration)

    # -- coordinate mapping ----------------------------------------------
    def _usable_width(self) -> float:
        return max(1.0, self.width() - 2 * _MARGIN)

    def visible_duration(self) -> float:
        return max(0.001, self.duration / self.zoom) if self.duration > 0 else 0.001

    def _x_for(self, t: float) -> float:
        visible = self.visible_duration()
        return _MARGIN + ((t - self.view_start) / visible) * self._usable_width()

    def _t_for(self, x: float) -> float:
        visible = self.visible_duration()
        frac = (x - _MARGIN) / self._usable_width()
        return max(0.0, min(self.duration, self.view_start + frac * visible))

    # -- zoom / pan --------------------------------------------------------
    def _set_view_start(self, view_start: float):
        visible = self.visible_duration()
        max_start = max(0.0, self.duration - visible)
        self.view_start = max(0.0, min(max_start, view_start))

    def set_zoom(self, zoom: float, anchor_time: Optional[float] = None):
        """Zoom to `zoom` (clamped to [MIN_ZOOM, MAX_ZOOM]), keeping
        `anchor_time` at the same pixel position it was at before the
        change (defaults to the middle of the current view)."""
        if self.duration <= 0:
            return
        old_visible = self.visible_duration()
        if anchor_time is None:
            anchor_time = self.view_start + old_visible / 2.0
        frac = (anchor_time - self.view_start) / old_visible

        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        if abs(new_zoom - self.zoom) < 1e-9:
            return
        self.zoom = new_zoom
        new_visible = self.visible_duration()
        self._set_view_start(anchor_time - frac * new_visible)
        self.update()
        self.view_changed.emit(self.zoom, self.view_start, self.duration)

    def zoom_in(self):
        self.set_zoom(self.zoom * _BUTTON_ZOOM_FACTOR, anchor_time=self.position)

    def zoom_out(self):
        self.set_zoom(self.zoom / _BUTTON_ZOOM_FACTOR, anchor_time=self.position)

    def reset_zoom(self):
        self.set_zoom(MIN_ZOOM)

    def _pan(self, delta_seconds: float):
        if self.zoom <= MIN_ZOOM + 1e-9:
            return
        self.pan_to(self.view_start + delta_seconds)

    def pan_to(self, view_start: float):
        """Move the visible window to start at `view_start` (clamped), without changing zoom."""
        old = self.view_start
        self._set_view_start(view_start)
        if abs(self.view_start - old) > 1e-9:
            self.update()
            self.view_changed.emit(self.zoom, self.view_start, self.duration)

    def wheelEvent(self, event: QWheelEvent):
        if self.duration <= 0:
            event.ignore()
            return
        angle = event.angleDelta()
        shift_pan = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier) and angle.y() != 0
        if angle.x() != 0 or shift_pan:
            notches = (angle.x() if angle.x() != 0 else -angle.y()) / 120.0
            self._pan(notches * _WHEEL_PAN_FRACTION * self.visible_duration())
            event.accept()
            return
        if angle.y() != 0:
            anchor_t = self._t_for(event.position().x())
            notches = angle.y() / 120.0
            self.set_zoom(self.zoom * (_WHEEL_ZOOM_FACTOR ** notches), anchor_time=anchor_t)
            event.accept()
            return
        event.ignore()

    def _clip_rect(self, clip: Clip) -> QRect:
        x0 = self._x_for(clip.start)
        x1 = self._x_for(clip.end)
        return QRect(int(x0), _TRACK_Y, max(3, int(x1 - x0)), _TRACK_H)

    def _clip_at(self, pos: QPoint) -> Optional[Clip]:
        if not (_TRACK_Y <= pos.y() <= _TRACK_Y + _TRACK_H):
            return None
        for clip in self.clips:
            if self._clip_rect(clip).contains(pos):
                return clip
        return None

    def _edge_at(self, pos: QPoint):
        """Return (clip, 'start'|'end') if pos is near a clip's trim handle."""
        if not (_TRACK_Y - 4 <= pos.y() <= _TRACK_Y + _TRACK_H + 4):
            return None, None
        for clip in self.clips:
            x0 = self._x_for(clip.start)
            x1 = self._x_for(clip.end)
            if abs(pos.x() - x0) <= _EDGE_GRAB_PX:
                return clip, "start"
            if abs(pos.x() - x1) <= _EDGE_GRAB_PX:
                return clip, "end"
        return None, None

    def neighbor_bounds(self, clip: Clip):
        """The [lower, upper] time range this clip's edges may move within,
        bounded by the nearest adjacent clips (clips never overlap)."""
        lower = 0.0
        upper = self.duration
        for other in self.clips:
            if other.id == clip.id:
                continue
            if other.end <= clip.start:
                lower = max(lower, other.end)
            if other.start >= clip.end:
                upper = min(upper, other.start)
        return lower, upper

    # -- painting ----------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        track_rect = QRectF(_MARGIN, _TRACK_Y, w - 2 * _MARGIN, _TRACK_H)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#22242c"))
        painter.drawRoundedRect(track_rect, 6, 6)

        for clip in self.clips:
            self._draw_clip(painter, clip)

        if self.pending_start is not None:
            self._draw_pending_marker(painter)

        self._draw_ruler(painter, w)
        self._draw_playhead(painter)

    def _draw_clip(self, painter: QPainter, clip: Clip):
        rect = QRectF(self._clip_rect(clip))
        is_selected = clip.id == self.selected_clip_id
        color = QColor(*clip.color)
        painter.setBrush(color)
        painter.setPen(QPen(QColor("#ffffff") if is_selected else color.lighter(135),
                             2.6 if is_selected else 1.4))
        painter.drawRoundedRect(rect, 5, 5)

        if is_selected:
            # a soft outer halo so selection reads clearly even for pale clip colors
            painter.setPen(QPen(QColor(255, 255, 255, 90), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), 7, 7)

        text_color = QColor("#101116") if color.lightnessF() > 0.62 else QColor("#f5f6f8")
        painter.setPen(text_color)
        fm = QFontMetrics(painter.font())
        text = fm.elidedText(clip.name, Qt.TextElideMode.ElideRight, max(0, int(rect.width()) - 10))
        painter.drawText(rect.adjusted(6, 0, -6, 0),
                          int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)

    def _draw_pending_marker(self, painter: QPainter):
        x = self._x_for(self.pending_start)
        pen = QPen(QColor("#ffcc66"))
        pen.setWidth(2)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(QPoint(int(x), 2), QPoint(int(x), _TRACK_Y + _TRACK_H))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ffcc66"))
        painter.drawEllipse(QPoint(int(x), 8), 4, 4)

    def _draw_ruler(self, painter: QPainter, w: int):
        painter.setPen(QColor("#565b68"))
        visible = self.visible_duration()
        step = nice_time_step(visible, self._usable_width())
        t = (self.view_start // step) * step if step > 0 else 0.0
        end_t = min(self.duration, self.view_start + visible)
        # small epsilon so float error doesn't drop the last tick
        while t <= end_t + 1e-6:
            if t >= -1e-6:
                x = self._x_for(t)
                painter.drawLine(QPoint(int(x), _TRACK_Y + _TRACK_H + 1), QPoint(int(x), _TRACK_Y + _TRACK_H + 6))
                label_rect = QRect(int(x) - 26, _RULER_Y, 52, 14)
                painter.drawText(label_rect, int(Qt.AlignmentFlag.AlignHCenter), format_time(t))
            t += step

    def _draw_playhead(self, painter: QPainter):
        x = self._x_for(self.position)
        pen = QPen(QColor("#ff5c5c"))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawLine(QPoint(int(x), 0), QPoint(int(x), _TRACK_Y + _TRACK_H))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ff5c5c"))
        triangle = QPolygonF([QPointF(x - 5, 0), QPointF(x + 5, 0), QPointF(x, 9)])
        painter.drawPolygon(triangle)

    # -- mouse interaction ---------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.RightButton:
            clip = self._clip_at(event.position().toPoint())
            if clip:
                self._set_selection(clip.id)
                self._show_context_menu(clip, event.globalPosition().toPoint())
            return
        if event.button() == Qt.MouseButton.LeftButton:
            clip, edge = self._edge_at(event.position().toPoint())
            if clip is not None:
                self._set_selection(clip.id)
                self._resizing_clip = clip
                self._resizing_edge = edge
                self._resize_lower, self._resize_upper = self.neighbor_bounds(clip)
                return
            clicked_clip = self._clip_at(event.position().toPoint())
            self._set_selection(clicked_clip.id if clicked_clip else None)
            self._dragging = True
            self.seek_requested.emit(self._t_for(event.position().x()))

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.position()
        if self._resizing_clip is not None:
            t = self._t_for(pos.x())
            clip = self._resizing_clip
            if self._resizing_edge == "start":
                new_start = max(self._resize_lower, min(t, clip.end - MIN_CLIP_LEN))
                clip.start = new_start
                self.seek_requested.emit(new_start)
            else:
                new_end = min(self._resize_upper, max(t, clip.start + MIN_CLIP_LEN))
                clip.end = new_end
                self.seek_requested.emit(new_end)
            self.clip_resizing.emit(clip.id, clip.start, clip.end)
            self.update()
            return
        if self._dragging:
            self.seek_requested.emit(self._t_for(pos.x()))
            return
        clip, _edge = self._edge_at(pos.toPoint())
        self.setCursor(Qt.CursorShape.SizeHorCursor if clip is not None
                        else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._resizing_clip is not None:
                clip = self._resizing_clip
                self._resizing_clip = None
                self._resizing_edge = None
                self.clip_resized.emit(clip.id, clip.start, clip.end)
            self._dragging = False

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        clip = self._clip_at(event.position().toPoint())
        if clip:
            self._start_rename(clip)

    def resizeEvent(self, event: QResizeEvent):
        if self._active_editor is not None:
            self._active_editor.deleteLater()
            self._active_editor = None
        super().resizeEvent(event)

    # -- rename / context menu -------------------------------------------------
    def _start_rename(self, clip: Clip):
        if self._active_editor is not None:
            self._active_editor.deleteLater()
            self._active_editor = None

        rect = self._clip_rect(clip)
        rect.setWidth(max(80, rect.width()))
        editor = _InlineEditor(self)
        editor.setText(clip.name)
        editor.setGeometry(rect)
        editor.show()
        editor.selectAll()
        editor.setFocus(Qt.FocusReason.MouseFocusReason)

        def commit():
            if self._active_editor is not editor:
                return
            self._active_editor = None
            text = editor.text().strip() or clip.name
            editor.deleteLater()
            if text != clip.name:
                self.clip_renamed.emit(clip.id, text)

        def cancel():
            if self._active_editor is not editor:
                return
            self._active_editor = None
            editor.deleteLater()

        editor.editingFinished.connect(commit)
        editor.cancelled.connect(cancel)
        self._active_editor = editor

    def _show_context_menu(self, clip: Clip, global_pos: QPoint):
        menu = QMenu(self)
        rename_action = menu.addAction("Rename clip")
        color_action = menu.addAction("Change color")
        menu.addSeparator()
        delete_action = menu.addAction("Delete clip")
        chosen = menu.exec(global_pos)
        if chosen is rename_action:
            self._start_rename(clip)
        elif chosen is color_action:
            self.clip_color_requested.emit(clip.id)
        elif chosen is delete_action:
            self.clip_delete_requested.emit(clip.id)
