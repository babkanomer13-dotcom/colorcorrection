"""Inline Levels editor. Full-resolution decode/save run outside the UI thread."""

import copy
from dataclasses import asdict

import numpy as np
from PySide6.QtCore import QPointF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from colorpro.files import preview_bytes
from colorpro.levels import LevelsSession, defaults, levels_lut, picked_levels
from colorpro.widgets import combo_box


class LevelsTask(QThread):
    completed = Signal(object, str)

    def __init__(self, operation):
        super().__init__()
        self.operation = operation

    def run(self):
        try:
            self.completed.emit(self.operation(), "")
        except Exception as error:
            self.completed.emit(None, str(error))


class Histogram(QWidget):
    def __init__(self):
        super().__init__()
        self.values = np.zeros(256)
        self.color = "#56526d"
        self.setMinimumHeight(64)
        self.setMaximumHeight(78)
        self.setAccessibleName("Гистограмма выбранного канала")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        maximum = (
            max(1, np.percentile(self.values[self.values > 0], 98)) if self.values.any() else 1
        )
        path = QPainterPath(QPointF(0, self.height()))
        for x, value in enumerate(self.values):
            path.lineTo(x * self.width() / 255, self.height() * (1 - min(1, value / maximum)))
        path.lineTo(self.width(), self.height())
        painter.fillPath(path, QColor(self.color))


class LevelsPanel(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.active = False
        self.session = self.task = None
        self.pick_kind = None
        self.settings = defaults()
        self.index = -1
        self.setFixedWidth(292)
        self.hide()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll, 1)
        content = QWidget()
        content.setObjectName("levelsPanel")
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        title = QLabel("Уровни")
        title.setObjectName("section")
        heading = QHBoxLayout()
        heading.addWidget(title, 1)
        self.auto = QPushButton("Автоцвет")
        self.auto.setObjectName("small")
        self.auto.setToolTip("Наш проверенный автоцвет для текущего результата; можно отменить")
        self.auto.clicked.connect(self.auto_levels)
        heading.addWidget(self.auto)
        layout.addLayout(heading)
        self.channel = combo_box()
        self.channel.addItems(["RGB · все каналы", "Красный", "Зелёный", "Синий"])
        self.channel.currentIndexChanged.connect(self.refresh_controls)
        layout.addWidget(self.channel)
        self.histogram = Histogram()
        layout.addWidget(self.histogram)
        layout.addWidget(QLabel("Входные значения"))
        input_row = QHBoxLayout()
        output_row = QHBoxLayout()
        layout.addLayout(input_row)
        self.controls = {}
        for name, title, maximum in (
            ("input_black", "Чёрный", 253),
            ("gamma", "Гамма", 999),
            ("input_white", "Белый", 255),
            ("output_black", "Чёрный", 253),
            ("output_white", "Белый", 255),
        ):
            if name == "output_black":
                layout.addWidget(QLabel("Выходные значения"))
                layout.addLayout(output_row)
            row = QVBoxLayout()
            label = QLabel(title)
            label.setObjectName("muted")
            row.addWidget(label)
            spin = QDoubleSpinBox() if name == "gamma" else QSpinBox()
            spin.setRange(
                0.10 if name == "gamma" else 0, maximum / 100 if name == "gamma" else maximum
            )
            if name == "gamma":
                spin.setDecimals(2)
                spin.setSingleStep(0.01)
            spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            spin.setMinimumWidth(60)
            spin.setKeyboardTracking(False)
            spin.setAccessibleName(title)
            row.addWidget(spin)
            (output_row if name.startswith("output") else input_row).addLayout(row, 1)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(10 if name == "gamma" else 0, maximum)
            slider.setAccessibleName(title)
            slider.valueChanged.connect(lambda value, key=name: self.change(key, value))
            spin.valueChanged.connect(
                lambda value, key=name: self.change(
                    key, round(value * 100) if key == "gamma" else value
                )
            )
            self.controls[name] = (spin, slider)
            row.addWidget(slider)
        row = QHBoxLayout()
        self.reset = QPushButton("Сбросить всё")
        self.reset.clicked.connect(self.reset_all)
        row.addWidget(self.reset)
        self.preview = QCheckBox("Просмотр")
        self.preview.setChecked(True)
        self.preview.toggled.connect(self.render_preview)
        row.addWidget(self.preview)
        layout.addLayout(row)
        self.pickers = []
        pickers = QHBoxLayout()
        for title, kind in (("Чёрная", "black"), ("Серая", "gray"), ("Белая", "white")):
            picker = QPushButton(title)
            picker.setObjectName("small")
            picker.setCheckable(True)
            picker.setToolTip("Пипетка: выберите точку на результате; общий RGB будет сброшен")
            picker.clicked.connect(lambda checked, k=kind: self.pick(k if checked else None))
            pickers.addWidget(picker)
            self.pickers.append(picker)
        layout.addLayout(pickers)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self.save = QPushButton("Сохранить результат")
        self.save.setObjectName("primary")
        self.save.clicked.connect(self.save_result)
        outer.addWidget(self.save)
        self.cancel = QPushButton("Отмена")
        self.cancel.clicked.connect(self.cancel_edit)
        outer.addWidget(self.cancel)
        layout.addStretch()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(45)
        self.timer.timeout.connect(self.render_preview)
        self.refresh_controls()

    def running(self):
        return bool(self.task and self.task.isRunning())

    def begin(self):
        owner = self.owner
        if owner.busy() or (owner.preview_loader and owner.preview_loader.isRunning()):
            return
        selected = owner.table.selectionModel().selectedRows()
        if not selected:
            return
        self.index = selected[0].row()
        record = owner.queue.results.get(self.index, {})
        if not record.get("output"):
            return
        owner.face_choice.setCurrentIndex(0)
        self.active = True
        self.settings = defaults()
        self.session = None
        self.show()
        owner.set_busy(True)
        owner.nav_status.setText("Ручные уровни")
        owner.table.setEnabled(False)
        for button in owner.nav_buttons:
            button.setEnabled(False)
        owner.sync_review()
        self.status.setText("Загрузка полного размера…")
        self.set_controls_enabled(False)
        self.task = LevelsTask(
            lambda: LevelsSession(record["output"], owner.queue.items[self.index].path)
        )
        self.task.completed.connect(self.loaded)
        self.task.finished.connect(owner.sync_review)
        self.task.start()

    def loaded(self, session, error):
        if error:
            self.status.setText(error)
            self.cancel.setEnabled(True)
            return
        self.session = session
        self.status.setText("Сохраняется только результат. Исходник не изменяется.")
        self.set_controls_enabled(True)
        self.refresh_controls()
        self.render_preview()

    def set_controls_enabled(self, enabled):
        for widget in (
            self.channel,
            self.preview,
            self.reset,
            self.save,
            self.cancel,
            self.auto,
            *self.pickers,
        ):
            widget.setEnabled(enabled)
        for pair in self.controls.values():
            for widget in pair:
                widget.setEnabled(enabled)

    def refresh_controls(self, *args):
        index = self.channel.currentIndex()
        row = self.settings[index]
        for name, (spin, slider) in self.controls.items():
            spin.blockSignals(True)
            slider.blockSignals(True)
            low, high = (10, 999) if name == "gamma" else (0, 255)
            if name.endswith("black"):
                high = row[name.replace("black", "white")] - 2
            elif name.endswith("white"):
                low = row[name.replace("white", "black")] + 2
            spin.setRange(
                low / 100 if name == "gamma" else low, high / 100 if name == "gamma" else high
            )
            spin.setValue(row[name])
            slider.setRange(low, high)
            slider.setValue(round(row[name] * 100) if name == "gamma" else row[name])
            spin.blockSignals(False)
            slider.blockSignals(False)
        if self.session is not None:
            self.histogram.values = (
                self.session.histogram.sum(axis=0)
                if index == 0
                else self.session.histogram[index - 1]
            )
            self.histogram.color = ("#56526d", "#d96676", "#46a584", "#6986db")[index]
            self.histogram.update()

    def change(self, key, value):
        self.settings[self.channel.currentIndex()][key] = (
            value / 100 if key == "gamma" else int(value)
        )
        self.refresh_controls()
        self.timer.start()

    def reset_all(self):
        self.pick(None)
        self.settings = defaults()
        self.refresh_controls()
        self.render_preview()

    def auto_levels(self):
        if self.running() or self.session is None:
            return
        from colorcorrection.auto_color import auto_color_parameters

        self.pick(None)
        self.set_controls_enabled(False)
        self.status.setText("Подбор автоцвета…")
        self.task = LevelsTask(lambda: auto_color_parameters(self.session.pixels))
        self.task.completed.connect(self.auto_loaded)
        self.task.start()

    def auto_loaded(self, result, error):
        self.set_controls_enabled(True)
        if error:
            self.status.setText(error)
            return
        self.settings = [defaults()[0]] + [asdict(row) for row in result.channels]
        self.status.setText("Автоцвет применён к предпросмотру. Изменения ещё не сохранены.")
        self.refresh_controls()
        self.render_preview()

    def pick(self, kind):
        self.pick_kind = kind
        for index, button in enumerate(self.pickers):
            value = ("black", "gray", "white")[index]
            button.setChecked(kind == value)
        self.owner.compare.picking = kind is not None
        self.owner.compare.setCursor(
            Qt.CursorShape.CrossCursor if kind else Qt.CursorShape.OpenHandCursor
        )
        if kind:
            self.status.setText("Щёлкните по нужной точке на результате справа.")

    def picked(self, x, y):
        if self.session is None or self.pick_kind is None:
            return
        pixels = self.session.pixels
        value = pixels[
            min(pixels.shape[0] - 1, int(y * pixels.shape[0])),
            min(pixels.shape[1] - 1, int(x * pixels.shape[1])),
        ]
        self.settings = picked_levels(self.settings, value, self.pick_kind)
        self.pick(None)
        self.status.setText("Точка выбрана. Изменения ещё не сохранены.")
        self.refresh_controls()
        self.render_preview()

    def render_preview(self, *args):
        if self.session is None or not self.active:
            return
        from colorcorrection.levels_operator import apply_rgb_lut

        pixels = self.session.preview
        if self.preview.isChecked():
            pixels = apply_rgb_lut(pixels, levels_lut(self.settings))
        pixmap = QPixmap()
        pixmap.loadFromData(preview_bytes(pixels), "PNG")
        self.owner.compare.after = pixmap
        self.owner.compare.update()

    def save_result(self):
        if self.running() or self.session is None:
            return
        self.timer.stop()
        self.pick(None)
        settings = copy.deepcopy(self.settings)
        self.set_controls_enabled(False)
        self.status.setText("Сохранение полного размера…")
        self.task = LevelsTask(lambda: self.session.save(settings))
        self.task.completed.connect(self.saved)
        self.task.finished.connect(self.finish_save)
        self.task.start()

    def saved(self, data, error):
        self.save_success = not error
        if error:
            self.status.setText(error)
            self.set_controls_enabled(True)
        else:
            self.owner.manual_result_saved(self.index, data)

    def finish_save(self):
        if self.save_success:
            self.end()

    def cancel_edit(self):
        if not self.running():
            self.end()

    def end(self):
        self.pick(None)
        self.timer.stop()
        self.active = False
        self.session = None
        self.hide()
        owner = self.owner
        owner.table.setEnabled(True)
        for button in owner.nav_buttons:
            button.setEnabled(True)
        owner.set_busy(False)
        owner.previews.clear()
        owner.preview_key = owner.face_record_key = None
        owner.selection_changed()
