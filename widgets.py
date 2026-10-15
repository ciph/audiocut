"""Waveform interaction and a compact save form."""

import math
import re
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QActionGroup, QColor, QFont, QIcon, QPainter, QPainterPath, QPainterPathStroker, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QMenu, QPushButton, QVBoxLayout, QWidget,
)

from core import CURVES, FORMATS, gain_at, normalize_format
from theme import COLORS, icon


def time_text(seconds, precise=False):
    milliseconds = max(0, round(float(seconds) * 1000))
    minutes, remainder = divmod(milliseconds, 60_000)
    whole_seconds, fraction = divmod(remainder, 1000)
    result = f"{minutes:02d}:{whole_seconds:02d}"
    return f"{result}.{fraction:03d}" if precise else result


def fade_path(rect, curve, side="in"):
    """Flatten the actual gain function to a subpixel screen-space tolerance."""
    def point(t):
        gain = gain_at(t, curve)
        if side == "out":
            gain = 1 - gain
        return QPointF(rect.left() + rect.width() * t, rect.bottom() - rect.height() * gain)

    path = QPainterPath(point(0))

    def segment(t0, p0, t1, p1, depth=0):
        dx, dy = p1.x() - p0.x(), p1.y() - p0.y()
        length = max(math.hypot(dx, dy), 1e-12)
        samples = [(t0 + (t1 - t0) * f, point(t0 + (t1 - t0) * f)) for f in (0.25, 0.5, 0.75)]
        error = max(abs(dx * (p.y() - p0.y()) - dy * (p.x() - p0.x())) / length for _, p in samples)
        if error > 0.12 and depth < 18:
            tm, pm = samples[1]
            segment(t0, p0, tm, pm, depth + 1)
            segment(tm, pm, t1, p1, depth + 1)
        else:
            path.lineTo(p1)

    segment(0, point(0), 1, point(1))
    return path


def curve_icon(curve, side="in"):
    pixmap = QPixmap(64, 44)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(COLORS["border"]), 1))
    painter.drawRect(3, 3, 58, 38)
    path = fade_path(QRectF(5, 5, 54, 34), curve, side)
    painter.setPen(QPen(QColor(COLORS["fade"]), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.drawPath(path)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


class Waveform(QWidget):
    seekRequested = Signal(float)
    selectionChanged = Signal(float, float)
    fadeChanged = Signal(str, float)
    curveChanged = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.info = None
        self.peaks = []
        self.edit = None
        self.editing = False
        self.position = 0.0
        self._drag = None
        self._drag_selection = None
        self._drag_origin = None
        self._curve_menu = None
        self.setObjectName("waveform")
        self.setMinimumHeight(220)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("音频波形")
        self.setToolTip("底部方块拖动裁剪；顶部三角拖出淡化；右键曲线选择形状")

    def set_audio(self, info, peaks):
        self.info = info
        self.peaks = list(peaks)
        self.position = 0.0
        self._drag = None
        self._drag_selection = None
        self._drag_origin = None
        self.update()

    def set_edit(self, edit, editing):
        self.edit = edit
        self.editing = bool(editing)
        if not self.editing:
            self._drag_selection = None
            self._drag = None
            self._drag_origin = None
        self.update()

    def set_position(self, seconds):
        self.position = max(0.0, min(float(seconds), self._duration()))
        self.update()

    def _duration(self):
        return max(0.0, float(self.info.duration)) if self.info else 0.0

    def _plot(self):
        return QRectF(28, 44, max(1, self.width() - 56), max(80, self.height() - 90))

    def _x(self, seconds):
        plot = self._plot()
        return plot.left() + plot.width() * seconds / max(self._duration(), 0.001)

    def _time(self, x):
        plot = self._plot()
        return max(0.0, min(1.0, (x - plot.left()) / plot.width())) * self._duration()

    def _selection(self):
        if self._drag_selection is not None:
            return self._drag_selection
        if self.edit is not None:
            return self.edit.start, self.edit.end
        return 0.0, self._duration()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(COLORS["border"]), 1))
        painter.setBrush(QColor(COLORS["surface"]))
        painter.drawRoundedRect(bounds, 14, 14)
        if not self.info:
            self._paint_empty(painter)
            return

        plot = self._plot()
        center = plot.center().y()
        height = plot.height() / 2 - 10
        start, end = self._selection()
        painter.setPen(QColor(COLORS["muted"]))
        painter.setFont(QFont("Microsoft YaHei UI", 9))
        caption = "底部裁剪 · 顶部淡化 · 右键选曲线" if self.editing else "完整音频"
        painter.drawText(QRectF(28, 13, plot.width(), 22), Qt.AlignmentFlag.AlignLeft, caption)
        if self.editing:
            painter.drawText(QRectF(28, 13, plot.width(), 22), Qt.AlignmentFlag.AlignRight,
                             "已选 " + time_text(end - start, True))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(COLORS["accent_soft"]))
            painter.drawRect(QRectF(self._x(start), plot.top(), self._x(end) - self._x(start), plot.height()))

        painter.setPen(QPen(QColor("#EEF0F5"), 1))
        painter.drawLine(QPointF(plot.left(), center), QPointF(plot.right(), center))
        count = max(1, int(plot.width() / 3))
        for column in range(count):
            left = column * len(self.peaks) // count
            right = max(left + 1, (column + 1) * len(self.peaks) // count)
            value = max(self.peaks[left:right], default=0.0)
            value = min(1.0, max(0.0, abs(float(value))))
            x = plot.left() + (column + 0.5) * plot.width() / count
            seconds = (column + 0.5) * self._duration() / count
            outside = self.editing and not start <= seconds <= end
            color = "#CDD3DF" if outside else COLORS["accent"]
            painter.setPen(QPen(QColor(color), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            amplitude = max(1.0, value * height)
            painter.drawLine(QPointF(x, center - amplitude), QPointF(x, center + amplitude))

        if self.editing and self.edit is not None:
            self._paint_fades(painter)
            for seconds in (start, end):
                x = self._x(seconds)
                painter.setPen(QPen(QColor(COLORS["accent"]), 2))
                painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))

        self._paint_ticks(painter, plot)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLORS["text"]))
        for rect in self._playhead_rects():
            painter.drawRect(rect)
        # Draw controls last so the playhead cannot hide an endpoint handle.
        for handle, path in self._handles():
            color = COLORS["fade"] if handle.startswith("fade_") else COLORS["accent"]
            painter.setPen(QPen(QColor(color), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(QColor(color) if handle == self._drag else QColor(COLORS["surface"]))
            painter.drawPath(path)

    def _playhead_rects(self):
        plot = self._plot()
        start, end = self._selection() if self.editing else (0, self._duration())
        left, right = self._x(start), self._x(end)
        width = max(0, right - left)
        stroke, cap = min(1.5, width), min(7, width)
        x = max(left, min(self._x(self.position) - stroke / 2, right - stroke))
        cap_x = max(left, min(self._x(self.position) - cap / 2, right - cap))
        return (QRectF(x, plot.top(), stroke, plot.height()),
                QRectF(cap_x, plot.top(), cap, 2), QRectF(cap_x, plot.bottom() - 2, cap, 2))

    def _paint_empty(self, painter):
        center = self.rect().center()
        disc = QRectF(center.x() - 25, center.y() - 63, 50, 50)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLORS["accent_soft"]))
        painter.drawRoundedRect(disc, 15, 15)
        icon("music", COLORS["accent"], 25).paint(painter, int(disc.x() + 12), int(disc.y() + 12), 26, 26)
        painter.setFont(QFont("Microsoft YaHei UI", 13, QFont.Weight.Medium))
        painter.setPen(QColor(COLORS["text"]))
        painter.drawText(QRectF(0, center.y() + 1, self.width(), 28), Qt.AlignmentFlag.AlignCenter, "打开音频，开始聆听")
        painter.setFont(QFont("Microsoft YaHei UI", 9))
        painter.setPen(QColor(COLORS["muted"]))
        painter.drawText(QRectF(0, center.y() + 38, self.width(), 24), Qt.AlignmentFlag.AlignCenter,
                         "NCM · WAV · MP3 · FLAC · M4A · AAC · OGG · OPUS · AIFF")

    def _fade_paths(self):
        if not self.editing or self.edit is None:
            return []
        start, end = self._selection()
        plot = self._plot()
        selected_length = max(0.001, end - start)
        paths = []
        for side, seconds, curve in (
            ("in", self.edit.fade_in, self.edit.curve_in),
            ("out", self.edit.fade_out, self.edit.curve_out),
        ):
            duration = min(max(0.0, seconds), selected_length)
            if duration <= 0:
                continue
            first = start if side == "in" else end - duration
            rect = QRectF(self._x(first), plot.top(), self._x(first + duration) - self._x(first), plot.height())
            path = fade_path(rect, curve, side)
            paths.append((side, path))
        return paths

    def _paint_fades(self, painter):
        painter.setPen(QPen(QColor(COLORS["fade"]), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for side, path in self._fade_paths():
            painter.drawPath(path)

    def _curve_at(self, point):
        # A screen-space tolerance also makes very short, steep fades selectable.
        for width in (4, 10, 18):
            stroker = QPainterPathStroker()
            stroker.setWidth(width)
            for side, path in self._fade_paths():
                if stroker.createStroke(path).contains(point):
                    return side
        return None

    def show_curve_menu(self, side, global_position):
        if not self.isEnabled() or not self.editing or self.edit is None:
            return None
        if self._curve_menu is not None:
            self._curve_menu.close()
            self._curve_menu.deleteLater()
        menu = QMenu(self)
        menu.setObjectName("curveMenu")
        heading = menu.addAction("淡入曲线" if side == "in" else "淡出曲线")
        heading.setEnabled(False)
        menu.addSeparator()
        group = QActionGroup(menu)
        group.setExclusive(True)
        current = self.edit.curve_in if side == "in" else self.edit.curve_out
        for label, key in CURVES.items():
            action = menu.addAction(curve_icon(key, side), label + ("  ✓" if key == current else ""))
            action.setData(key)
            action.setCheckable(True)
            action.setChecked(key == current)
            group.addAction(action)
            action.triggered.connect(lambda checked=False, key=key: self.curveChanged.emit(side, key))
        self._curve_menu = menu
        menu.popup(global_position)
        return menu

    def contextMenuEvent(self, event):
        side = self._curve_at(QPointF(event.pos()))
        if side is None and event.reason() == event.Reason.Keyboard:
            paths = self._fade_paths()
            side = paths[0][0] if paths else None
        if side is None:
            event.ignore()
            return
        self.show_curve_menu(side, event.globalPos())
        event.accept()

    def _paint_ticks(self, painter, plot):
        painter.setPen(QColor(COLORS["muted"]))
        painter.setFont(QFont("Segoe UI", 9))
        steps = max(2, min(8, int(plot.width() / 115)))
        for step in range(steps + 1):
            x = plot.left() + plot.width() * step / steps
            painter.drawLine(QPointF(x, plot.bottom() + 8), QPointF(x, plot.bottom() + 11))
            label = time_text(self._duration() * step / steps, self._duration() < 10)
            alignment = Qt.AlignmentFlag.AlignCenter
            rect = QRectF(x - 42, plot.bottom() + 15, 84, 20)
            if step == 0:
                rect.moveLeft(plot.left())
                alignment = Qt.AlignmentFlag.AlignLeft
            elif step == steps:
                rect.moveRight(plot.right())
                alignment = Qt.AlignmentFlag.AlignRight
            painter.drawText(rect, alignment, label)

    def _handles(self):
        if not self.editing or self.edit is None:
            return []
        plot = self._plot()
        start, end = self._selection()
        handles = []
        for handle, seconds, direction in (("start", start, 1), ("end", end, -1)):
            x = self._x(seconds)
            path = QPainterPath()
            path.addRect(QRectF(x - 12 if direction < 0 else x, plot.bottom() - 12, 12, 12))
            handles.append((handle, path))
        for handle, seconds, direction in (
            ("fade_in", start + min(self.edit.fade_in, end - start), 1),
            ("fade_out", end - min(self.edit.fade_out, end - start), -1),
        ):
            x, y = self._x(seconds), plot.top()
            path = QPainterPath()
            path.moveTo(x, y)
            path.lineTo(x + direction * 12, y)
            path.lineTo(x, y + 12)
            path.closeSubpath()
            handles.append((handle, path))
        return handles

    def _handle_at(self, point):
        handles = self._handles()
        for handle, path in handles:
            if path.contains(point):
                return handle
        # Prefer the closest shape in the extra hit area, even for tiny selections.
        stroker = QPainterPathStroker()
        stroker.setWidth(8)
        candidates = [(abs(point.x() - path.boundingRect().center().x()), handle)
                      for handle, path in handles if stroker.createStroke(path).contains(point)]
        return min(candidates)[1] if candidates else None

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self._duration() <= 0:
            return super().mousePressEvent(event)
        self.setFocus()
        self._drag = self._handle_at(event.position()) or "seek"
        if self._drag == "seek":
            self.seekRequested.emit(self._time(event.position().x()))
        else:
            self._drag_selection = self._selection()
            self._drag_origin = (event.position().x(), self.edit)
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            self.update()
        event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_origin is not None:
            self._move_handle(event.position())
        elif self._drag == "seek":
            self.seekRequested.emit(self._time(event.position().x()))
        else:
            handle = self._handle_at(event.position())
            cursor = Qt.CursorShape.SizeHorCursor if handle else Qt.CursorShape.PointingHandCursor
            self.setCursor(cursor if self.info else Qt.CursorShape.ArrowCursor)
            tips = {"start": "左键拖动：调整保留起点", "end": "左键拖动：调整保留终点",
                    "fade_in": "左键向右拖出淡入，向左缩短至零", "fade_out": "左键向左拖出淡出，向右缩短至零"}
            side = self._curve_at(event.position())
            self.setToolTip(tips.get(handle) or
                            (("右键更换淡入曲线" if side == "in" else "右键更换淡出曲线") if side else
                             "点击定位播放；底部方块裁剪；顶部三角淡化"))
        event.accept()

    def _move_handle(self, point):
        origin_x, original = self._drag_origin
        delta = (point.x() - origin_x) / self._plot().width() * self._duration()
        if self._drag in ("start", "end"):
            start, end = original.start, original.end
            gap = min(0.001, self._duration())
            if self._drag == "start":
                start = max(0.0, min(start + delta, end - gap))
            else:
                end = min(self._duration(), max(end + delta, start + gap))
            self._drag_selection = start, end
            self.selectionChanged.emit(start, end)
        else:
            seconds = original.fade_in + delta if self._drag == "fade_in" else original.fade_out - delta
            self.fadeChanged.emit("in" if self._drag == "fade_in" else "out",
                                  max(0.0, min(original.duration, seconds)))
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._drag_origin is not None:
                self._move_handle(event.position())
            self._drag = None
            self._drag_selection = None
            self._drag_origin = None
            self.unsetCursor()
            self.update()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if not self.info:
            return super().keyPressEvent(event)
        target = {
            Qt.Key.Key_Left: max(0.0, self.position - 1),
            Qt.Key.Key_Right: min(self._duration(), self.position + 1),
            Qt.Key.Key_Home: 0.0,
            Qt.Key.Key_End: self._duration(),
        }.get(event.key())
        if target is None:
            return super().keyPressEvent(event)
        self.seekRequested.emit(target)
        event.accept()


class SaveDialog(QDialog):
    def __init__(self, info, parent=None):
        super().__init__(parent)
        self.info = info
        self.setObjectName("saveDialog")
        self.setWindowTitle("保存音频")
        self.setMinimumWidth(510)
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 25, 28, 24)
        layout.setSpacing(12)
        title = QLabel("保存音频")
        title.setObjectName("title")
        layout.addWidget(title)
        subtitle = QLabel("为剪辑后的声音选择名称和格式。")
        subtitle.setObjectName("subtitle")
        layout.addWidget(subtitle)
        layout.addSpacing(12)

        self.name_edit = QLineEdit(info.original_path.stem + "_edit")
        self.name_edit.setObjectName("fileNameEdit")
        self.name_edit.setPlaceholderText("文件名，不含扩展名")
        self.name_edit.setMaxLength(240)
        self._add_field(layout, "文件名", self.name_edit)

        self.format_combo = QComboBox()
        self.format_combo.setObjectName("formatCombo")
        source = normalize_format(Path(info.path).suffix)
        if source in FORMATS:
            extension = Path(info.path).suffix.lower()
            label = "与源音频一致" if info.source_path else "与源一致"
            self.format_combo.addItem(f"{label} ({extension})", source)
            self.format_combo.setItemData(0, extension, Qt.ItemDataRole.UserRole + 1)
        for key, label in FORMATS.items():
            if key != source:
                self.format_combo.addItem(f"{label} (.{key})", key)
        if source not in FORMATS:
            self.format_combo.setCurrentIndex(max(0, self.format_combo.findData("wav")))
        self._add_field(layout, "文件格式", self.format_combo)

        self.directory_edit = QLineEdit(str(info.original_path.parent))
        self.directory_edit.setObjectName("directoryEdit")
        directory_row = QHBoxLayout()
        directory_row.setSpacing(8)
        directory_row.addWidget(self.directory_edit, 1)
        self.browse_button = QPushButton("浏览…")
        self.browse_button.setObjectName("browseButton")
        self.browse_button.clicked.connect(self._browse)
        directory_row.addWidget(self.browse_button)
        directory_label = QLabel("保存到")
        directory_label.setBuddy(self.directory_edit)
        layout.addWidget(directory_label)
        layout.addLayout(directory_row)

        layout.addSpacing(6)
        self.metadata_check = QCheckBox("保留 metadata（元数据）")
        self.metadata_check.setObjectName("keepMetadataCheck")
        self.metadata_check.setChecked(True)
        layout.addWidget(self.metadata_check)
        self.metadata_help = QLabel("保留目标格式支持的标签与封面。")
        self.metadata_help.setObjectName("subtitle")
        self.metadata_help.setWordWrap(True)
        layout.addWidget(self.metadata_help)
        layout.addSpacing(6)

        self.target_label = QLabel()
        self.target_label.setObjectName("targetPathLabel")
        self.target_label.setWordWrap(True)
        self.target_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.target_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.target_label)
        self.error_label = QLabel()
        self.error_label.setObjectName("validationLabel")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        buttons = QHBoxLayout()
        buttons.setSpacing(9)
        buttons.addStretch()
        cancel = QPushButton("取消")
        cancel.setObjectName("cancelButton")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.save_button = QPushButton("保存音频")
        self.save_button.setObjectName("saveButton")
        self.save_button.setIcon(icon("save", "#FFFFFF", 17))
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.accept)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)

        self.name_edit.textChanged.connect(self._refresh)
        self.directory_edit.textChanged.connect(self._refresh)
        self.format_combo.currentIndexChanged.connect(self._format_changed)
        self._format_changed()
        self.name_edit.selectAll()
        self.name_edit.setFocus()

    @staticmethod
    def _add_field(layout, text, widget):
        label = QLabel(text)
        label.setBuddy(widget)
        layout.addWidget(label)
        layout.addWidget(widget)

    def _browse(self):
        directory = QFileDialog.getExistingDirectory(self, "选择保存文件夹", self.directory_edit.text())
        if directory:
            self.directory_edit.setText(directory)

    def _format_changed(self):
        self.metadata_help.setText(
            {"aac": "AAC 标签兼容性取决于播放器；需要通用标签支持可选 M4A。",
             "wav": "保留目标格式支持的文字标签；WAV 不保存封面。",
             "ogg": "保留文字标签；当前版本导出 OGG 不保存封面。",
             "opus": "保留文字标签；当前版本导出 Opus 不保存封面。"}
            .get(self.format_combo.currentData(), "保留目标格式支持的标签与封面。")
        )
        self._refresh()

    def _extension(self):
        return self.format_combo.currentData(Qt.ItemDataRole.UserRole + 1) or "." + self.format_combo.currentData()

    def _validation_error(self):
        name = self.name_edit.text()
        if not name or not name.strip():
            return "请输入文件名。"
        if re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or name.endswith((".", " ")) or name in (".", ".."):
            return "文件名不能包含路径或特殊符号，也不能以空格或句点结尾。"
        if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", name):
            return "这个名称为系统保留名称，请更换文件名。"
        if not self.directory_edit.text().strip():
            return "请选择保存文件夹。"
        try:
            if not Path(self.directory_edit.text()).expanduser().is_dir():
                return "保存文件夹不存在，请选择已有文件夹。"
        except (OSError, ValueError):
            return "保存文件夹路径无效。"
        return ""

    def _refresh(self):
        name = self.name_edit.text()
        directory = self.directory_edit.text()
        self.target_label.setText("目标文件：" + str(Path(directory) / (name + self._extension())))
        error = self._validation_error()
        self.error_label.setText(error)
        self.error_label.setVisible(bool(error))
        self.save_button.setEnabled(not error)

    def result_options(self):
        destination = Path(self.directory_edit.text()).expanduser().resolve() / (self.name_edit.text() + self._extension())
        return destination, self.format_combo.currentData(), self.metadata_check.isChecked()

    def accept(self):
        if self._validation_error():
            self._refresh()
            return
        super().accept()
