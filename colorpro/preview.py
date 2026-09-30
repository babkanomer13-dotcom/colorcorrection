"""Matched face crops and synchronized, large before/after comparison."""

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QThread, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from colorpro.files import collect_inputs, preview_bytes, read_image
from colorpro.widgets import combo_box


def face_region(shape, bbox):
    """One square crop in source coordinates, including hair and chin, for both sides."""
    height, width = shape[:2]
    x0, y0, x1, y1 = bbox
    side = min(width, height, round(max((x1 - x0) * 1.85, (y1 - y0) * 1.7)))
    if side <= 0:
        raise ValueError("Некорректная область лица")
    left = max(0, min(width - side, round((x0 + x1) / 2 - side / 2)))
    top = max(0, min(height - side, round(y0 + (y1 - y0) * 0.52 - side / 2)))
    return left, top, left + side, top + side


class PreviewWorker(QThread):
    loaded = Signal(object, object, object, str)

    def __init__(self, key, item, output, bbox=None):
        super().__init__()
        self.key, self.item, self.output, self.bbox = key, item, output, bbox

    def run(self):
        before = after = None
        error = ""
        try:
            pixels, _, _ = read_image(self.item)
            shape = pixels.shape
            region = face_region(shape, self.bbox) if self.bbox else None
            if region:
                x0, y0, x1, y1 = region
                before = preview_bytes(pixels[y0:y1, x0:x1])
            else:
                before = preview_bytes(pixels)
            del pixels
            if self.output and not self.isInterruptionRequested():
                items, errors = collect_inputs([Path(self.output)])
                if errors:
                    raise ValueError(errors[0])
                pixels, _, _ = read_image(items[0])
                if pixels.shape != shape:
                    raise ValueError("Размер результата отличается от исходника")
                after = preview_bytes(pixels[y0:y1, x0:x1] if region else pixels)
        except Exception as exc:
            error = str(exc)
        if not self.isInterruptionRequested():
            self.loaded.emit(self.key, before, after, error)


class CompareView(QWidget):
    """A shared scale and center prevent the two views from drifting apart."""

    zoom_changed = Signal(float)
    expand_requested = Signal()

    def __init__(self):
        super().__init__()
        self.before = self.after = None
        self.mode = 0
        self.position = 0.5
        self.zoom = 1.0
        self.center = QPointF(0.5, 0.5)
        self.drag_start = None
        self.message = "Выберите фотографию в очереди"
        self.setMinimumSize(200, 145)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setAccessibleName("До и после, одинаковый масштаб")
        self.setToolTip(
            "Колесо — приблизить · потяните снимок — переместить оба вида · двойной щелчок — крупно"
        )

    def show_pair(self, before, after):
        pixmaps = []
        for data in (before, after):
            pixmap = QPixmap()
            if data:
                pixmap.loadFromData(data, "PNG")
            pixmaps.append(pixmap if not pixmap.isNull() else None)
        self.set_pixmaps(*pixmaps)

    def set_pixmaps(self, before, after):
        self.before, self.after = before, after
        self.reset_zoom()

    def clear(self, message="Выберите фотографию в очереди"):
        self.before = self.after = None
        self.message = message
        self.reset_zoom()

    def set_mode(self, mode):
        self.mode = mode
        self.reset_zoom()
        self.setCursor(Qt.CursorShape.OpenHandCursor if not mode else Qt.CursorShape.SplitHCursor)

    def reset_zoom(self):
        self.zoom = 1.0
        self.center = QPointF(0.5, 0.5)
        self.zoom_changed.emit(self.zoom)
        self.update()

    def set_zoom(self, value):
        self.zoom = max(1.0, min(8.0, value))
        self.clamp_center()
        self.zoom_changed.emit(self.zoom)
        self.update()

    def panes(self):
        if self.mode:
            return [QRectF(0, 34, self.width(), max(1, self.height() - 34))]
        half = (self.width() - 2) / 2
        return [
            QRectF(0, 34, half, max(1, self.height() - 34)),
            QRectF(half + 2, 34, half, max(1, self.height() - 34)),
        ]

    def drawn_size(self):
        pane = self.panes()[0]
        if self.before is None:
            return 1.0, 1.0
        scale = min(pane.width() / self.before.width(), pane.height() / self.before.height())
        return self.before.width() * scale * self.zoom, self.before.height() * scale * self.zoom

    def clamp_center(self):
        pane = self.panes()[0]
        width, height = self.drawn_size()

        def clamp(value, visible, drawn):
            margin = min(0.5, visible / (2 * drawn))
            return max(margin, min(1 - margin, value))

        self.center = QPointF(
            clamp(self.center.x(), pane.width(), width),
            clamp(self.center.y(), pane.height(), height),
        )

    def target_rect(self, pane):
        width, height = self.drawn_size()
        return QRectF(
            pane.center().x() - self.center.x() * width,
            pane.center().y() - self.center.y() * height,
            width,
            height,
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        panes = self.panes()
        captions = ["Исходник", "Результат"]
        for index in range(2):
            header = QRectF(index * self.width() / 2, 0, self.width() / 2, 34)
            painter.fillRect(header, QColor("#ffffff"))
            painter.setPen(QColor("#444444"))
            painter.drawText(header, Qt.AlignmentFlag.AlignCenter, captions[index])
        if self.before is None:
            painter.setPen(QColor("#737373"))
            painter.drawText(
                self.rect().adjusted(20, 40, -20, -10),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                self.message,
            )
            return
        for index, pane in enumerate(panes):
            pixmap = self.before if not index else self.after
            painter.save()
            painter.setClipRect(pane)
            if pixmap is not None:
                painter.drawPixmap(self.target_rect(pane), pixmap, QRectF(pixmap.rect()))
            else:
                painter.setPen(QColor("#737373"))
                painter.drawText(
                    pane.adjusted(20, 0, -20, 0),
                    Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                    "Результат появится\nпосле обработки",
                )
            painter.restore()
        if self.mode and self.after is not None:
            pane = panes[0]
            divider = int(self.width() * self.position)
            painter.save()
            painter.setClipRect(QRectF(divider, pane.top(), self.width() - divider, pane.height()))
            painter.drawPixmap(self.target_rect(pane), self.after, QRectF(self.after.rect()))
            painter.restore()
            painter.setPen(QPen(QColor("#737373"), 2))
            painter.drawLine(divider, 34, divider, self.height())
        elif not self.mode:
            painter.fillRect(QRectF(panes[0].right(), 0, 2, self.height()), QColor("#e4e4e4"))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self.drag_start = event.position()
            if self.mode:
                self.position = max(0, min(1, event.position().x() / self.width()))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.update()

    def mouseMoveEvent(self, event):
        if self.drag_start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if self.mode:
                self.position = max(0, min(1, event.position().x() / self.width()))
            else:
                delta = event.position() - self.drag_start
                width, height = self.drawn_size()
                self.center -= QPointF(delta.x() / width, delta.y() / height)
                self.clamp_center()
            self.drag_start = event.position()
            self.update()

    def mouseReleaseEvent(self, event):
        self.drag_start = None
        self.setCursor(
            Qt.CursorShape.OpenHandCursor if not self.mode else Qt.CursorShape.SplitHCursor
        )

    def mouseDoubleClickEvent(self, event):
        self.expand_requested.emit()

    def wheelEvent(self, event):
        if self.before is not None:
            self.set_zoom(self.zoom * (1.2 if event.angleDelta().y() > 0 else 1 / 1.2))
            event.accept()

    def keyPressEvent(self, event):
        if event.key() in {Qt.Key.Key_Plus, Qt.Key.Key_Equal}:
            self.set_zoom(self.zoom * 1.2)
        elif event.key() == Qt.Key.Key_Minus:
            self.set_zoom(self.zoom / 1.2)
        elif event.key() in {Qt.Key.Key_0, Qt.Key.Key_Home}:
            self.reset_zoom()
        else:
            return super().keyPressEvent(event)


class CompareDialog(QDialog):
    """The photograph fills the window, with a single set of controls for both sides."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("ColorPro · До и после")
        self.setMinimumSize(760, 520)
        self.setStyleSheet(
            "QDialog { background: white; } QLabel { color: #444444; }"
            "QPushButton, QComboBox { background: white; color: #303030; "
            "border: 1px solid #dedede; padding: 8px 12px; border-radius: 6px; }"
            "QComboBox { padding-right: 39px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 12)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Сравнение до / после"))
        toolbar.addStretch()
        faces = combo_box()
        for index in range(parent.face_choice.count()):
            faces.addItem(parent.face_choice.itemText(index))
        faces.setCurrentIndex(parent.face_choice.currentIndex())
        faces.setEnabled(parent.face_choice.count() > 1)
        faces.currentIndexChanged.connect(parent.face_choice.setCurrentIndex)
        toolbar.addWidget(faces)
        self.view = CompareView()
        self.view.set_pixmaps(parent.compare.before, parent.compare.after)
        self.zoom_label = QLabel("1×")
        self.view.zoom_changed.connect(lambda value: self.zoom_label.setText(f"{value:.1f}×"))
        for title, callback in (
            ("−", lambda: self.view.set_zoom(self.view.zoom / 1.2)),
            ("+", lambda: self.view.set_zoom(self.view.zoom * 1.2)),
            ("По размеру", self.view.reset_zoom),
            ("Закрыть · Esc", self.reject),
        ):
            control = QPushButton(title)
            control.clicked.connect(callback)
            toolbar.addWidget(control)
        toolbar.insertWidget(3, self.zoom_label)
        layout.addLayout(toolbar)
        layout.addWidget(self.view, 1)
        self.detail = QLabel(parent.preview_detail.text())
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        layout.addWidget(
            QLabel(
                "Колесо — приблизить · потяните любое изображение — оба вида переместятся вместе"
            )
        )
