"""Matched face crops and synchronized, large before/after comparison."""

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from colorpro.editor_render import rgb_image
from colorpro.files import collect_inputs, preview_bytes, read_image
from colorpro.levels_panel import LevelsPanel
from colorpro.widgets import combo_box, navigation_icon


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

    def __init__(
        self,
        key,
        item,
        output,
        bbox=None,
        workspace=None,
        full=False,
        source_only=False,
    ):
        super().__init__()
        self.key, self.item, self.output, self.bbox = key, item, output, bbox
        self.workspace = workspace
        self.native_size = None
        self.full = full
        self.source_only = source_only

    def run(self):
        before = after = None
        error = ""
        try:
            encode = rgb_image if self.full else preview_bytes
            pixels, _, _ = read_image(self.item)
            shape = pixels.shape
            region = face_region(shape, self.bbox) if self.bbox else None
            self.native_size = (
                (region[2] - region[0], region[3] - region[1])
                if region
                else (shape[1], shape[0])
            )
            if region:
                x0, y0, x1, y1 = region
                before = encode(pixels[y0:y1, x0:x1])
            else:
                before = encode(pixels)
            del pixels
            if (
                self.output
                and not self.source_only
                and not self.isInterruptionRequested()
            ):
                items, errors = collect_inputs([Path(self.output)])
                if errors:
                    raise ValueError(errors[0])
                pixels, _, base_sha = read_image(items[0])
                if pixels.shape != shape:
                    raise ValueError("Размер результата отличается от исходника")
                if region:
                    pixels = pixels[y0:y1, x0:x1]
                if not self.full:
                    # These are pointwise tools: a bounded display proxy avoids
                    # rendering the entire export merely to open a thumbnail.
                    import numpy as np
                    from PIL import Image

                    image = Image.fromarray(pixels)
                    image.thumbnail((1500, 1500))
                    pixels = np.array(image)
                    image.close()
                if self.workspace is not None:
                    saved = self.workspace.load_edit(self.item, self.output, base_sha)
                    if saved:
                        from colorcorrection.levels_operator import apply_rgb_lut

                        from colorpro.manual_hsl import apply_hsl
                        from colorpro.manual_tone import combined_lut

                        levels, tone, hsl, balance = saved["current"]
                        pixels = apply_hsl(
                            apply_rgb_lut(pixels, combined_lut(levels, tone, balance)),
                            hsl,
                        )
                after = encode(pixels)
        except Exception as exc:  # noqa: BLE001 -- worker reports failures to the UI
            error = str(exc)
        if not self.isInterruptionRequested():
            self.loaded.emit(self.key, before, after, error)


class CompareView(QWidget):
    """A shared scale and center prevent the two views from drifting apart."""

    zoom_changed = Signal(float)
    expand_requested = Signal()
    pixel_picked = Signal(float, float)
    native_requested = Signal()
    viewport_changed = Signal()

    def __init__(self):
        super().__init__()
        self.before = self.after = None
        self.after_detail = None
        self.mode = 0
        self.position = 0.5
        self.zoom = 1.0
        self.center = QPointF(0.5, 0.5)
        self.drag_start = None
        self.picking = False
        self.original_visible = False
        self.native_size = None
        self.high_detail = False
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
            if isinstance(data, QPixmap):
                pixmaps.append(data)
                continue
            pixmap = QPixmap()
            if data:
                pixmap.loadFromData(data, "PNG")
            pixmaps.append(pixmap if not pixmap.isNull() else None)
        self.set_pixmaps(*pixmaps)

    def set_pixmaps(self, before, after):
        self.before, self.after = before, after
        self.after_detail = None
        self.high_detail = False
        self.reset_zoom()

    def clear(self, message="Выберите фотографию в очереди"):
        self.before = self.after = None
        self.after_detail = None
        self.native_size = None
        self.high_detail = False
        self.message = message
        self.reset_zoom()

    def set_mode(self, mode):
        self.mode = mode
        self.clamp_center()
        self.update()
        self.setCursor(
            Qt.CursorShape.SplitHCursor if mode == 1 else Qt.CursorShape.OpenHandCursor
        )
        self.viewport_changed.emit()

    def reset_zoom(self):
        self.zoom = 1.0
        self.center = QPointF(0.5, 0.5)
        self.zoom_changed.emit(self.zoom)
        self.update()
        self.viewport_changed.emit()

    def set_zoom(self, value):
        self.zoom = max(0.1, min(32.0, float(value)))
        self.clamp_center()
        self.zoom_changed.emit(self.zoom)
        self.update()
        self.viewport_changed.emit()
        if (
            not self.high_detail
            and self.before is not None
            and self.native_size
            and self.drawn_size()[0] > self.before.width() * 1.05
        ):
            self.native_requested.emit()

    def panes(self):
        if self.mode:
            return [QRectF(0, 34, self.width(), max(1, self.height() - 34))]
        half = (self.width() - 20) / 2
        return [
            QRectF(0, 34, half, max(1, self.height() - 34)),
            QRectF(half + 20, 34, half, max(1, self.height() - 34)),
        ]

    def toggle_original(self):
        self.set_original(not self.original_visible)

    def set_original(self, visible):
        self.original_visible = bool(visible)
        self.update()

    def visible_region(self, shape):
        """Native pixel rectangle under either synchronized pane."""
        import math

        height, width = shape[:2]
        pane = self.panes()[0]
        target = self.target_rect(pane)
        x0 = max(0, math.floor((pane.left() - target.left()) / target.width() * width))
        y0 = max(0, math.floor((pane.top() - target.top()) / target.height() * height))
        x1 = min(
            width, math.ceil((pane.right() - target.left()) / target.width() * width)
        )
        y1 = min(
            height, math.ceil((pane.bottom() - target.top()) / target.height() * height)
        )
        return min(x0, width - 1), min(y0, height - 1), max(1, x1), max(1, y1)

    def draw_detail(self, painter, pane):
        if self.after_detail is None or self.original_visible or not self.native_size:
            return
        (x0, y0, x1, y1), pixmap = self.after_detail
        width, height = self.native_size
        target = self.target_rect(pane)
        detail = QRectF(
            target.x() + x0 / width * target.width(),
            target.y() + y0 / height * target.height(),
            (x1 - x0) / width * target.width(),
            (y1 - y0) / height * target.height(),
        )
        painter.drawPixmap(detail, pixmap, QRectF(pixmap.rect()))

    def actual_size(self):
        if self.before is None:
            return
        pane = self.panes()[0]
        width, height = self.native_size or (self.before.width(), self.before.height())
        fit = min(pane.width() / width, pane.height() / height)
        self.set_zoom(1 / max(fit, 0.001))
        if not self.high_detail:
            self.native_requested.emit()

    def drawn_size(self):
        pane = self.panes()[0]
        if self.before is None:
            return 1.0, 1.0
        scale = min(
            pane.width() / self.before.width(), pane.height() / self.before.height()
        )
        return (
            self.before.width() * scale * self.zoom,
            self.before.height() * scale * self.zoom,
        )

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
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        panes = self.panes()
        captions = (
            ["Исходное", "Исходное · отпустите Enter"]
            if self.original_visible
            else ["Исходное", "Результат · удерживайте Enter: исходное"]
        )
        for index in range(1 if self.mode == 2 else 2):
            header = QRectF(
                index * self.width() / 2,
                0,
                self.width() if self.mode == 2 else self.width() / 2,
                34,
            )
            painter.setPen(QColor("#575975"))
            painter.drawText(
                header,
                Qt.AlignmentFlag.AlignCenter,
                captions[1] if self.mode == 2 else captions[index],
            )
        if self.before is None:
            painter.setPen(QColor("#737373"))
            painter.drawText(
                self.rect().adjusted(20, 40, -20, -10),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                self.message,
            )
            return
        for index, pane in enumerate(panes):
            pixmap = self.before if not index or self.original_visible else self.after
            if self.mode == 2:
                pixmap = (
                    self.before if self.original_visible else self.after or self.before
                )
            painter.save()
            clip = QPainterPath()
            clip.addRoundedRect(pane, 10, 10)
            painter.setClipPath(clip)
            painter.fillRect(pane, QColor("#292929"))
            if pixmap is not None:
                painter.drawPixmap(
                    self.target_rect(pane), pixmap, QRectF(pixmap.rect())
                )
                if self.mode == 2 or (self.mode == 0 and index == 1):
                    self.draw_detail(painter, pane)
            else:
                painter.setPen(QColor("#c8c8c8"))
                painter.drawText(
                    pane.adjusted(20, 0, -20, 0),
                    Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                    "Результат появится\nпосле обработки",
                )
            painter.restore()
        if self.mode == 1 and self.after is not None and not self.original_visible:
            pane = panes[0]
            divider = int(self.width() * self.position)
            painter.save()
            clip = QPainterPath()
            clip.addRoundedRect(pane, 10, 10)
            painter.setClipPath(clip)
            painter.setClipRect(
                QRectF(divider, pane.top(), self.width() - divider, pane.height()),
                Qt.ClipOperation.IntersectClip,
            )
            painter.drawPixmap(
                self.target_rect(pane), self.after, QRectF(self.after.rect())
            )
            self.draw_detail(painter, pane)
            painter.restore()
            painter.setPen(QPen(QColor("#737373"), 2))
            painter.drawLine(divider, 34, divider, self.height())

    def mousePressEvent(self, event):
        if self.picking:
            if self.after is not None and event.button() == Qt.MouseButton.LeftButton:
                pane = self.panes()[-1]
                target = self.target_rect(pane)
                point = event.position()
                if (
                    pane.contains(point)
                    and target.contains(point)
                    and not self.original_visible
                    and (self.mode != 1 or point.x() >= self.width() * self.position)
                ):
                    self.pixel_picked.emit(
                        (point.x() - target.left()) / target.width(),
                        (point.y() - target.top()) / target.height(),
                    )
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self.drag_start = event.position()
            if self.mode == 1:
                self.position = max(0, min(1, event.position().x() / self.width()))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.update()

    def mouseMoveEvent(self, event):
        if self.drag_start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if self.mode == 1:
                self.position = max(0, min(1, event.position().x() / self.width()))
            else:
                delta = event.position() - self.drag_start
                width, height = self.drawn_size()
                self.center -= QPointF(delta.x() / width, delta.y() / height)
                self.clamp_center()
            self.drag_start = event.position()
            self.update()
            self.viewport_changed.emit()

    def mouseReleaseEvent(self, event):
        self.drag_start = None
        self.setCursor(
            Qt.CursorShape.OpenHandCursor
            if not self.mode
            else Qt.CursorShape.SplitHCursor
        )

    def mouseDoubleClickEvent(self, event):
        self.expand_requested.emit()

    def wheelEvent(self, event):
        if self.before is not None:
            # Qt5 wheel events have position()/posF(), but no localPos().
            position = getattr(event, "position", None)
            point = position() if position else event.posF()
            pane = next((p for p in self.panes() if p.contains(point)), self.panes()[0])
            width, height = self.drawn_size()
            anchor = self.center + QPointF(
                (point.x() - pane.center().x()) / width,
                (point.y() - pane.center().y()) / height,
            )
            self.set_zoom(self.zoom * (1.2 if event.angleDelta().y() > 0 else 1 / 1.2))
            width, height = self.drawn_size()
            self.center = anchor - QPointF(
                (point.x() - pane.center().x()) / width,
                (point.y() - pane.center().y()) / height,
            )
            self.clamp_center()
            self.update()
            self.viewport_changed.emit()
            event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.viewport_changed.emit()

    def keyPressEvent(self, event):
        return super().keyPressEvent(event)


class ComparePage(QWidget):
    """One persistent review surface, synchronized with the processing queue."""

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setObjectName("page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 4, 28, 20)
        layout.setSpacing(12)
        heading = QHBoxLayout()
        title = QLabel("До / после")
        title.setObjectName("pageTitle")
        titles = QVBoxLayout()
        titles.setSpacing(5)
        titles.addWidget(title)
        subtitle = QLabel("Сравните исходное фото и результат обработки.")
        subtitle.setObjectName("muted")
        titles.addWidget(subtitle)
        heading.addLayout(titles)
        heading.addStretch()
        self.attention = QPushButton("Следующий на проверку")
        self.attention.clicked.connect(owner.select_attention)
        heading.addWidget(self.attention)
        self.levels_button = QPushButton("Коррекция")
        self.levels_button.setEnabled(False)
        self.levels_button.clicked.connect(lambda: self.editor.begin())
        heading.addWidget(self.levels_button)
        self.open_file = QPushButton("Открыть результат")
        self.open_file.setIcon(navigation_icon("open", "#585b84"))
        self.open_file.setEnabled(False)
        self.open_file.clicked.connect(owner.open_selected)
        heading.addWidget(self.open_file)
        layout.addLayout(heading)
        selection = QHBoxLayout()
        self.previous = QPushButton()
        self.previous.setIcon(navigation_icon("previous"))
        self.previous.setIconSize(QSize(18, 18))
        self.previous.setFixedWidth(34)
        self.previous.setAccessibleName("Предыдущая фотография")
        self.previous.setToolTip("Предыдущая фотография")
        self.previous.clicked.connect(lambda: owner.select_relative(-1))
        selection.addWidget(self.previous)
        self.photos = combo_box()
        self.photos.setAccessibleName("Фотография для сравнения")
        self.photos.setMinimumContentsLength(10)
        self.photos.setSizeAdjustPolicy(
            self.photos.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.photos.setModel(owner.queue)
        self.photos.setModelColumn(1)
        self.photos.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.photos.activated.connect(owner.select_photo)
        selection.addWidget(self.photos, 1)
        self.next = QPushButton()
        self.next.setIcon(navigation_icon("next"))
        self.next.setIconSize(QSize(18, 18))
        self.next.setFixedWidth(34)
        self.next.setAccessibleName("Следующая фотография")
        self.next.setToolTip("Следующая фотография")
        self.next.clicked.connect(lambda: owner.select_relative(1))
        selection.addWidget(self.next)
        self.count = QLabel("0 / 0")
        self.count.setObjectName("muted")
        self.count.setMinimumWidth(60)
        selection.addWidget(self.count)
        self.faces = combo_box()
        self.faces.setAccessibleName("Лицо для сравнения")
        self.faces.addItem("Весь кадр", None)
        self.faces.setEnabled(False)
        self.faces.currentIndexChanged.connect(owner.selection_changed)
        selection.addWidget(self.faces)
        self.mode = combo_box()
        self.mode.addItems(["2 фото", "Разделитель", "1 фото"])
        self.mode.setAccessibleName("Режим сравнения")
        selection.addWidget(self.mode)
        layout.addLayout(selection)
        self.tools = QHBoxLayout()
        self.tools.setSpacing(6)
        self.tool_buttons = {}
        for action, caption, glyph in (
            ("edit", "Уровни", "levels"),
            ("tone", "Яркость / контраст", "tone"),
            ("hsl", "Тон / насыщенность", "hsl"),
            ("balance", "Цветовой баланс", "balance"),
            ("auto_color", "Автоцвет", "hsl"),
            ("auto_tone", "Автотон", "tone"),
            ("auto_contrast", "Автоконтраст", "levels"),
        ):
            control = QPushButton("А" if action.startswith("auto_") else "")
            control.setIcon(navigation_icon(glyph, "#766581"))
            control.setIconSize(QSize(22, 22))
            control.setFixedSize(42 if action.startswith("auto_") else 36, 36)
            control.setObjectName("editorTool")
            control.setCheckable(not action.startswith("auto_"))
            control.setAccessibleName(caption)
            control.setProperty("caption", caption)
            control.clicked.connect(
                lambda checked=False, a=action: owner.shortcuts.dispatch(a)
            )
            self.tools.addWidget(control)
            self.tool_buttons[action] = control
        self.tools.addStretch()
        self.compare_toggle = QPushButton("До / после")
        self.compare_toggle.setCheckable(True)
        self.compare_toggle.clicked.connect(lambda: self.view.toggle_original())
        self.tools.addWidget(self.compare_toggle)
        layout.addLayout(self.tools)
        self.view = CompareView()
        self.view.native_requested.connect(owner.request_native_detail)
        mode = str(owner.settings.value("comparison_mode", "2"))
        mode = int(mode) if mode in {"0", "1", "2"} else 2
        self.mode.setCurrentIndex(mode)
        self.view.set_mode(mode)
        owner.settings.setValue("comparison_mode", mode)
        self.mode.currentIndexChanged.connect(self.view.set_mode)
        self.mode.currentIndexChanged.connect(
            lambda value: owner.settings.setValue("comparison_mode", value)
        )
        self.view.setAccessibleName("До и после, одинаковый масштаб")
        self.view.expand_requested.connect(owner.toggle_review_fullscreen)
        self.zoom_label = QLabel("1.0×")
        self.view.zoom_changed.connect(
            lambda value: self.zoom_label.setText(f"{value:.1f}×")
        )
        workspace = QHBoxLayout()
        workspace.addWidget(self.view, 1)
        self.editor = LevelsPanel(owner)
        self.view.viewport_changed.connect(self.editor.viewport_changed)
        self.view.pixel_picked.connect(self.editor.picked)
        workspace.addWidget(self.editor)
        from colorpro.filmstrip import Filmstrip

        self.filmstrip = Filmstrip(owner)
        workspace.insertWidget(0, self.filmstrip)
        for button in (self.editor.undo_button, self.editor.redo_button):
            self.tools.insertWidget(7, button)
        self.editor.auto.hide()
        self.editor.auto_mode.hide()
        self.editor.cancel.hide()
        self.levels_button.hide()  # Toolbar is the single visible tool entry point.
        layout.addLayout(workspace, 1)
        self.detail = QLabel("")
        self.detail.setObjectName("muted")
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.detail.setWordWrap(True)
        self.detail.setMaximumHeight(40)
        self.detail.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.detail.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        toolbar = QHBoxLayout()
        toolbar.addWidget(self.detail, 1)
        toolbar.addWidget(self.zoom_label)
        self.rail_toggle = QPushButton("Лента")
        self.panel_toggle = QPushButton("Параметры")
        for widget, key, callback in (
            (self.rail_toggle, "filmstrip_visible", self.toggle_filmstrip),
            (self.panel_toggle, "parameters_visible", self.toggle_parameters),
        ):
            widget.setCheckable(True)
            widget.setChecked(str(owner.settings.value(key, "true")).lower() == "true")
            widget.clicked.connect(callback)
            toolbar.addWidget(widget)
        self.filmstrip.setVisible(self.rail_toggle.isChecked())
        self.zoom_controls = []
        for title, callback in (
            ("−", lambda: self.view.set_zoom(self.view.zoom / 1.2)),
            ("+", lambda: self.view.set_zoom(self.view.zoom * 1.2)),
            ("По размеру", self.view.reset_zoom),
            ("100%", self.view.actual_size),
        ):
            control = QPushButton(title)
            if title in ("−", "+"):
                control.setObjectName("square")
                control.setFixedWidth(34)
            control.clicked.connect(callback)
            toolbar.addWidget(control)
            self.zoom_controls.append(control)
        self.fullscreen = QPushButton("На весь экран")
        self.fullscreen.setIcon(navigation_icon("fullscreen", "#585b84"))
        self.fullscreen.clicked.connect(owner.toggle_review_fullscreen)
        toolbar.addWidget(self.fullscreen)
        layout.addLayout(toolbar)
        for control in self.findChildren(QPushButton):
            control.setCursor(Qt.CursorShape.PointingHandCursor)

    def toggle_filmstrip(self):
        self.filmstrip.setVisible(self.rail_toggle.isChecked())
        self.owner.settings.setValue("filmstrip_visible", self.rail_toggle.isChecked())

    def toggle_parameters(self):
        self.owner.settings.setValue(
            "parameters_visible", self.panel_toggle.isChecked()
        )
        if self.panel_toggle.isChecked() and not self.editor.active:
            self.editor.begin()
        self.editor.setVisible(self.panel_toggle.isChecked() and self.editor.active)

    def highlight_tool(self, name):
        for action, button in self.tool_buttons.items():
            if button.isCheckable():
                button.setChecked(action == ("edit" if name == "levels" else name))

    def sync_controls(self):
        owner = self.owner
        selected = owner.table.selectionModel().selectedRows()
        index = selected[0].row() if selected else -1
        total = len(owner.queue.items)
        self.photos.blockSignals(True)
        self.photos.setCurrentIndex(index)
        self.photos.blockSignals(False)
        self.photos.setEnabled(bool(total))
        self.photos.setToolTip(owner.queue.items[index].label if index >= 0 else "")
        self.previous.setEnabled(index > 0)
        self.next.setEnabled(0 <= index < total - 1)
        self.count.setText(f"{index + 1} / {total}")
        self.filmstrip.select(index)
        self.attention.setVisible(owner.next_attention.isEnabled())
        self.attention.setEnabled(owner.next_attention.isEnabled())
        for control in self.zoom_controls:
            control.setEnabled(self.view.before is not None)
        editing = self.editor.active
        self.filmstrip.view.setEnabled(True)
        loading = bool(owner.preview_loader and owner.preview_loader.isRunning())
        output = owner.queue.results.get(index, {}).get("output")
        self.levels_button.setEnabled(bool(output) and not owner.busy() and not loading)
        for control in self.tool_buttons.values():
            control.setEnabled(
                (
                    editing
                    and self.editor.session is not None
                    and not self.editor.running()
                )
                or self.levels_button.isEnabled()
            )
        if editing:
            for control in (
                self.faces,
                self.open_file,
            ):
                control.setEnabled(False)
