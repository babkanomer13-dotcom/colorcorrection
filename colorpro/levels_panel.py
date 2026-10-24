"""Inline Levels editor. Full-resolution decode/save run outside the UI thread."""

import copy

import numpy as np
from PySide6.QtCore import QPointF, QSize, Qt, QThread, QTimer, Signal
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
from colorpro.levels import LevelsSession, defaults, picked_levels
from colorpro.manual_balance import balance_defaults
from colorpro.manual_hsl import apply_hsl, hsl_available, hsl_defaults
from colorpro.manual_tone import combined_lut, tone_available, tone_defaults
from colorpro.widgets import combo_box, navigation_icon


class LevelsTask(QThread):
    completed = Signal(object, str)

    def __init__(self, operation):
        super().__init__()
        self.operation = operation

    def run(self):
        try:
            self.completed.emit(self.operation(), "")
        except Exception as error:  # noqa: BLE001 -- report errors across the Qt thread boundary
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
            max(1, np.percentile(self.values[self.values > 0], 98))
            if self.values.any()
            else 1
        )
        path = QPainterPath(QPointF(0, self.height()))
        for x, value in enumerate(self.values):
            path.lineTo(
                x * self.width() / 255, self.height() * (1 - min(1, value / maximum))
            )
        path.lineTo(self.width(), self.height())
        painter.fillPath(path, QColor(self.color))


class ToolSection(QWidget):
    """Compact tool group; collapsed groups keep the image workspace readable."""

    def __init__(self, caption, expanded=False):
        super().__init__()
        self.caption = caption
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.toggle = QPushButton()
        self.toggle.setObjectName("adjustmentToggle")
        self.toggle.setCheckable(True)
        self.toggle.setChecked(expanded)
        self.body = QWidget()
        self.shortcut = QLabel()
        self.shortcut.setObjectName("muted")
        self.shortcut.setStyleSheet("font-size: 10px; padding-right: 4px;")
        self.content = QVBoxLayout(self.body)
        self.content.setContentsMargins(0, 0, 0, 6)
        self.content.setSpacing(6)
        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(4)
        heading.addWidget(self.toggle, 1)
        heading.addWidget(self.shortcut)
        layout.addLayout(heading)
        layout.addWidget(self.body)
        self.toggle.toggled.connect(self.expand)
        self.expand(expanded)

    def expand(self, expanded):
        self.toggle.setText(self.caption)
        self.toggle.setIcon(
            navigation_icon(
                "down" if expanded else "next", "#a71971" if expanded else "#6d6377"
            )
        )
        self.toggle.setIconSize(QSize(14, 14))
        self.body.setVisible(expanded)
        if expanded:
            QTimer.singleShot(0, self.reveal)

    def reveal(self):
        if not self.isVisible() or not self.toggle.isChecked():
            return
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                parent.ensureWidgetVisible(self.toggle, 0, 8)
                return
            parent = parent.parentWidget()


class LevelsPanel(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.active = False
        self.session = self.task = None
        self.pending_tool = None
        self.departure = None
        self.dirty = False
        self.item = None
        self.saved_snapshot = None
        self.preview_task = None
        self.preview_inflight = False
        self.preview_revision = 0
        self.preview_job_revision = 0
        self.preview_pending = False
        self.pick_kind = None
        self.settings = defaults()
        self.tone = tone_defaults()
        self.hsl = hsl_defaults()
        self.balance = balance_defaults()
        self.history = []
        self.future = []
        self.group_change = self.group_recorded = False
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
        title = QLabel("Коррекция")
        title.setObjectName("section")
        title.hide()
        heading = QHBoxLayout()
        heading.addWidget(title, 1)
        self.auto = QPushButton("Применить")
        self.auto.setObjectName("small")
        self.auto.setToolTip(
            "Применить выбранный автоинструмент к результату, заменив настройки уровней. Можно отменить."
        )
        self.auto.clicked.connect(self.auto_levels)
        heading.addWidget(self.auto)
        layout.addLayout(heading)
        self.auto_mode = combo_box()
        self.auto_mode.addItems(["Автоцвет", "Автотон", "Автоконтраст"])
        self.auto_mode.setAccessibleName("Автоматический инструмент для ручной правки")
        layout.addWidget(self.auto_mode)
        self.tone_controls = {}
        self.tone_section = None
        if tone_available():
            self.tone_section = ToolSection("Яркость и контраст")
            layout.addWidget(self.tone_section)
            tone_layout = self.tone_section.content
            for name, caption, low, high in (
                ("brightness", "Яркость", -150, 150),
                ("contrast", "Контраст", -50, 100),
            ):
                title_row = QHBoxLayout()
                title_row.addWidget(QLabel(caption), 1)
                spin = QSpinBox()
                spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
                spin.setRange(low, high)
                spin.setKeyboardTracking(False)
                spin.setAccessibleName(caption)
                spin.setFixedWidth(70)
                title_row.addWidget(spin)
                tone_layout.addLayout(title_row)
                slider = QSlider(Qt.Orientation.Horizontal)
                slider.setRange(low, high)
                slider.setAccessibleName(caption)
                slider.valueChanged.connect(
                    lambda value, key=name: self.change_tone(key, value)
                )
                spin.valueChanged.connect(
                    lambda value, key=name: self.change_tone(key, value)
                )
                tone_layout.addWidget(slider)
                self.tone_controls[name] = (spin, slider)
        self.levels_section = ToolSection("Уровни", expanded=True)
        layout.addWidget(self.levels_section)
        levels_layout = self.levels_section.content
        if self.tone_section is not None:
            layout.removeWidget(self.tone_section)
            layout.addWidget(self.tone_section)
        self.channel = combo_box()
        self.channel.addItems(["RGB · все каналы", "Красный", "Зелёный", "Синий"])
        self.channel.currentIndexChanged.connect(self.refresh_controls)
        levels_layout.addWidget(self.channel)
        self.histogram = Histogram()
        levels_layout.addWidget(self.histogram)
        levels_layout.addWidget(QLabel("Входные значения"))
        input_row = QHBoxLayout()
        output_row = QHBoxLayout()
        levels_layout.addLayout(input_row)
        self.controls = {}
        for name, title, maximum in (
            ("input_black", "Чёрный", 253),
            ("gamma", "Гамма", 999),
            ("input_white", "Белый", 255),
            ("output_black", "Чёрный", 253),
            ("output_white", "Белый", 255),
        ):
            if name == "output_black":
                levels_layout.addWidget(QLabel("Выходные значения"))
                levels_layout.addLayout(output_row)
            row = QVBoxLayout()
            label = QLabel(title)
            label.setObjectName("muted")
            row.addWidget(label)
            spin = QDoubleSpinBox() if name == "gamma" else QSpinBox()
            spin.setRange(
                0.10 if name == "gamma" else 0,
                maximum / 100 if name == "gamma" else maximum,
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
        self.balance_section = ToolSection("Цветовой баланс")
        layout.addWidget(self.balance_section)
        balance_layout = self.balance_section.content
        self.balance_band = combo_box()
        self.balance_band.addItems(["Тени", "Средние тона", "Света"])
        self.balance_band.setCurrentIndex(1)
        self.balance_band.currentIndexChanged.connect(self.refresh_controls)
        balance_layout.addWidget(self.balance_band)
        self.balance_controls = {}
        for channel, caption, left, right in (
            (0, "Голубой / Красный", "#1bbcc5", "#e66475"),
            (1, "Пурпурный / Зелёный", "#c852ba", "#48a275"),
            (2, "Жёлтый / Синий", "#d8b240", "#6187d4"),
        ):
            title_row = QHBoxLayout()
            title_row.addWidget(QLabel(caption), 1)
            spin = QSpinBox()
            spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            spin.setRange(-100, 100)
            spin.setKeyboardTracking(False)
            spin.setAccessibleName(caption)
            spin.setFixedWidth(70)
            title_row.addWidget(spin)
            balance_layout.addLayout(title_row)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(-100, 100)
            slider.setAccessibleName(caption)
            slider.setStyleSheet(
                "QSlider::groove:horizontal { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 "
                + left
                + ",stop:0.5 #dedce7,stop:1 "
                + right
                + "); } QSlider::sub-page:horizontal { background: transparent; }"
            )
            slider.valueChanged.connect(
                lambda value, c=channel: self.change_balance(c, value)
            )
            spin.valueChanged.connect(
                lambda value, c=channel: self.change_balance(c, value)
            )
            balance_layout.addWidget(slider)
            self.balance_controls[channel] = (spin, slider)
        self.preserve_luminosity = QCheckBox("Сохранять яркость")
        self.preserve_luminosity.setChecked(True)
        self.preserve_luminosity.toggled.connect(self.change_preserve_luminosity)
        balance_layout.addWidget(self.preserve_luminosity)
        self.hsl_controls = {}
        self.hsl_section = None
        if hsl_available():
            self.hsl_section = ToolSection("Тон / насыщенность")
            layout.addWidget(self.hsl_section)
            hsl_layout = self.hsl_section.content
            for name, caption, limit in (
                ("hue", "Цветовой тон", 180),
                ("saturation", "Насыщенность", 100),
                ("lightness", "Светлота", 100),
            ):
                title_row = QHBoxLayout()
                title_row.addWidget(QLabel(caption), 1)
                spin = QSpinBox()
                spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
                spin.setRange(-limit, limit)
                spin.setKeyboardTracking(False)
                spin.setAccessibleName(caption)
                spin.setFixedWidth(70)
                title_row.addWidget(spin)
                hsl_layout.addLayout(title_row)
                slider = QSlider(Qt.Orientation.Horizontal)
                slider.setRange(-limit, limit)
                slider.setAccessibleName(caption)
                slider.valueChanged.connect(
                    lambda value, key=name: self.change_hsl(key, value)
                )
                spin.valueChanged.connect(
                    lambda value, key=name: self.change_hsl(key, value)
                )
                hsl_layout.addWidget(slider)
                self.hsl_controls[name] = (spin, slider)
        row = QHBoxLayout()
        self.reset = QPushButton("Сбросить")
        self.reset.clicked.connect(self.reset_all)
        row.addWidget(self.reset)
        self.preview = QCheckBox("Просмотр")
        self.preview.setChecked(True)
        self.preview.toggled.connect(self.render_preview)
        row.addWidget(self.preview)
        outer.addLayout(row)
        self.undo_button = QPushButton()
        self.redo_button = QPushButton()
        self.undo_button.setIcon(navigation_icon("undo", "#6c627b"))
        self.redo_button.setIcon(navigation_icon("redo", "#6c627b"))
        for control, caption in (
            (self.undo_button, "Отменить правку"),
            (self.redo_button, "Повторить правку"),
        ):
            control.setObjectName("historyButton")
            control.setFixedSize(32, 32)
            control.setIconSize(QSize(18, 18))
            control.setAccessibleName(caption)
        self.undo_button.clicked.connect(self.undo_edit)
        self.redo_button.clicked.connect(self.redo_edit)
        row.insertWidget(1, self.undo_button)
        row.insertWidget(2, self.redo_button)
        self.pickers = []
        pickers = QHBoxLayout()
        for title, kind in (("Чёрная", "black"), ("Серая", "gray"), ("Белая", "white")):
            picker = QPushButton(title)
            picker.setObjectName("small")
            picker.setCheckable(True)
            picker.setToolTip(
                "Пипетка: выберите точку на результате; общий RGB будет сброшен"
            )
            picker.clicked.connect(
                lambda checked, k=kind: self.pick(k if checked else None)
            )
            pickers.addWidget(picker)
            self.pickers.append(picker)
        levels_layout.addLayout(pickers)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self.save = QPushButton("Экспортировать фото")
        self.save.setObjectName("primary")
        self.save.clicked.connect(self.save_result)
        outer.addWidget(self.save)
        self.cancel = QPushButton("Закрыть инструменты")
        self.cancel.clicked.connect(self.cancel_edit)
        outer.addWidget(self.cancel)
        layout.addStretch()
        self.key_help = QLabel()
        self.key_help.setObjectName("muted")
        self.key_help.setWordWrap(True)
        layout.addWidget(self.key_help)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(45)
        self.timer.timeout.connect(self.render_preview)
        self.autosave = QTimer(self)
        self.autosave.setSingleShot(True)
        self.autosave.setInterval(350)
        self.autosave.timeout.connect(self.flush_state)
        for name, section in (
            ("levels", self.levels_section),
            ("tone", self.tone_section),
            ("balance", self.balance_section),
            ("hsl", self.hsl_section),
        ):
            if section is not None:
                saved = owner.settings.value("tool_expanded_" + name)
                if saved is not None:
                    section.toggle.setChecked(str(saved).lower() == "true")
                section.toggle.toggled.connect(
                    lambda value, key=name: owner.settings.setValue(
                        "tool_expanded_" + key, value
                    )
                )
        for _, slider in self.control_pairs():
            # Tab moves between numeric fields; clicking still focuses sliders.
            slider.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
            slider.sliderPressed.connect(self.begin_gesture)
            slider.sliderReleased.connect(self.end_gesture)
        self.refresh_controls()

    def control_pairs(self):
        return (
            list(self.controls.values())
            + list(self.tone_controls.values())
            + list(self.hsl_controls.values())
            + list(self.balance_controls.values())
        )

    def snapshot(self):
        return (
            copy.deepcopy(self.settings),
            dict(self.tone),
            dict(self.hsl),
            copy.deepcopy(self.balance),
        )

    def flush_state(self):
        if not self.active or self.session is None:
            return True
        self.autosave.stop()
        # Finish a number still being typed before committing a frame transition.
        for spin, _ in self.control_pairs():
            spin.interpretText()
        current = self.snapshot()
        try:
            self.owner.workspace.save_edit(
                self.item,
                self.session.path,
                current,
                self.history,
                self.future,
                {
                    "zoom": self.owner.compare.zoom,
                    "center": [
                        self.owner.compare.center.x(),
                        self.owner.compare.center.y(),
                    ],
                },
                base_sha=self.session.sha,
            )
        except (OSError, ValueError, TypeError) as error:
            self.status.setText("Не удалось сохранить правки: " + str(error))
            self.owner.error(self.status.text())
            return False
        self.saved_snapshot = copy.deepcopy(current)
        self.dirty = False
        self.status.setText("Правки сохранены · экспорт — отдельной кнопкой")
        return True

    def leave(self, callback):
        self.departure = callback
        self.timer.stop()
        self.preview_pending = False
        self.preview_revision += 1
        if self.running() or self.preview_running():
            self.status.setText("Завершение текущей операции…")
            return
        self.finish_departure()

    def finish_departure(self):
        if self.departure is None or self.running() or self.preview_running():
            return
        callback, self.departure = self.departure, None
        if not self.flush_state():
            self.owner.requested_photo = None
            self.owner.table.blockSignals(True)
            self.owner.table.selectionModel().blockSignals(True)
            self.owner.table.selectRow(self.index)
            self.owner.table.selectionModel().blockSignals(False)
            self.owner.table.blockSignals(False)
            self.owner.sync_review()
            return
        self.end(refresh=False, persist=False)
        callback()

    def running(self):
        return bool(self.task and self.task.isRunning())

    def activate_tool(self, name):
        """Open a tool without resetting an existing, unsaved editing session."""
        if not self.active:
            self.begin(tool=name)
            return
        if self.running() or self.session is None:
            return
        if name == "resume":
            self.setVisible(self.owner.review.panel_toggle.isChecked())
            self.owner.review.highlight_tool(
                str(self.owner.settings.value("last_tool", "levels"))
            )
            return
        auto_modes = {"auto_color": 0, "auto_tone": 1, "auto_contrast": 2}
        tool = "levels" if name in auto_modes else name
        sections = {
            "levels": (self.levels_section, self.controls["input_black"][0]),
            "tone": (
                self.tone_section,
                self.tone_controls.get("brightness", (None,))[0],
            ),
            "balance": (self.balance_section, self.balance_controls[0][0]),
            "hsl": (self.hsl_section, self.hsl_controls.get("hue", (None,))[0]),
        }
        section, field = sections.get(tool, (None, None))
        if section is None:
            return
        self.pick(None)
        self.show()
        self.owner.review.panel_toggle.setChecked(True)
        self.owner.settings.setValue("parameters_visible", True)
        self.owner.review.highlight_tool(tool)
        self.owner.settings.setValue("last_tool", tool)
        for candidate, _ in sections.values():
            if candidate is not None:
                candidate.toggle.setChecked(candidate is section)
        section.reveal()
        field.setFocus(Qt.FocusReason.ShortcutFocusReason)
        field.selectAll()
        if name in auto_modes:
            self.auto_mode.setCurrentIndex(auto_modes[name])
            self.auto_levels()

    def refresh_shortcut_hints(self, manager):
        for section, action in (
            (self.levels_section, "edit"),
            (self.tone_section, "tone"),
            (self.balance_section, "balance"),
            (self.hsl_section, "hsl"),
        ):
            if section is not None:
                key = manager.bindings[action]
                section.shortcut.setText(key)
                section.shortcut.setVisible(bool(key))
                section.toggle.setToolTip(
                    section.caption + " · " + manager.hint(action)
                )
        for index, (caption, action) in enumerate(
            (
                ("Автоцвет", "auto_color"),
                ("Автотон", "auto_tone"),
                ("Автоконтраст", "auto_contrast"),
            )
        ):
            key = manager.bindings[action]
            self.auto_mode.setItemText(index, caption + (" · " + key if key else ""))
        for index, (caption, action) in enumerate(
            (
                ("RGB · все каналы", "channel_rgb"),
                ("Красный", "channel_red"),
                ("Зелёный", "channel_green"),
                ("Синий", "channel_blue"),
            )
        ):
            key = manager.bindings[action]
            self.channel.setItemText(index, caption + (" · " + key if key else ""))
        self.key_help.setText(
            manager.hint("increase")
            + " / "
            + manager.hint("decrease")
            + " — шаг; "
            + manager.hint("increase_fast")
            + " / "
            + manager.hint("decrease_fast")
            + " — ×10. Tab — следующее поле."
        )

    def begin(self, tool="resume"):
        owner = self.owner
        if self.active or owner.busy():
            return
        if owner.preview_loader and owner.preview_loader.isRunning():
            self.pending_tool = tool
            return
        selected = owner.table.selectionModel().selectedRows()
        if not selected:
            return
        self.index = selected[0].row()
        self.item = owner.queue.items[self.index]
        record = owner.queue.results.get(self.index, {})
        if not record.get("output"):
            return
        owner.face_choice.setCurrentIndex(0)
        self.active = True
        owner.edit_on_selection = True
        self.pending_tool = tool
        self.settings = defaults()
        self.tone = tone_defaults()
        self.hsl = hsl_defaults()
        self.balance = balance_defaults()
        self.history.clear()
        self.future.clear()
        self.session = None
        self.setVisible(tool != "resume" or owner.review.panel_toggle.isChecked())
        owner.set_busy(True)
        owner.nav_status.setText("Ручная коррекция")
        owner.sync_review()
        self.status.setText("Загрузка полного размера…")
        self.set_controls_enabled(False)
        item = self.item
        base = record.get("base_output") or record["output"]

        def load():
            session = LevelsSession(base, item.path)
            saved = owner.workspace.load_edit(item, base, session.sha)
            return session, saved

        self.task = LevelsTask(load)
        self.task.completed.connect(self.loaded)
        self.task.finished.connect(self.finish_load)
        self.task.start()

    def finish_load(self):
        self.owner.sync_review()
        if self.departure is not None:
            self.pending_tool = None
            self.finish_departure()
            return
        pending, self.pending_tool = self.pending_tool, None
        # QThread.finished, not completed: an auto action starts a second worker.
        if self.active and self.session is not None and pending:
            self.activate_tool(pending)
        self.finish_departure()

    def loaded(self, result, error):
        if error:
            self.status.setText(error)
            self.cancel.setEnabled(True)
            return
        self.session, saved = result
        self.owner.compare.native_size = (
            self.session.pixels.shape[1],
            self.session.pixels.shape[0],
        )
        if saved:
            self.settings, self.tone, self.hsl, self.balance = copy.deepcopy(
                saved["current"]
            )
            self.history = saved["history"]
            self.future = saved["future"]
            view = saved.get("view", {})
            center = view.get("center", [0.5, 0.5])
            if isinstance(center, list) and len(center) == 2:
                self.owner.compare.center = QPointF(*center)
            self.owner.compare.set_zoom(view.get("zoom", 1))
        self.saved_snapshot = self.snapshot()
        self.dirty = False
        self.status.setText("Правки сохраняются автоматически. Оригинал не изменяется.")
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
            self.auto_mode,
            self.balance_band,
            self.preserve_luminosity,
            self.undo_button,
            self.redo_button,
            *self.pickers,
        ):
            widget.setEnabled(enabled)
        for pair in self.control_pairs():
            for widget in pair:
                widget.setEnabled(enabled)

    def refresh_controls(self, *args):
        band = ("shadows", "midtones", "highlights")[self.balance_band.currentIndex()]
        for channel, pair in self.balance_controls.items():
            for widget in pair:
                widget.blockSignals(True)
                widget.setValue(self.balance[band][channel])
                widget.blockSignals(False)
        self.preserve_luminosity.blockSignals(True)
        self.preserve_luminosity.setChecked(self.balance["preserve_luminosity"])
        self.preserve_luminosity.blockSignals(False)
        for name, pair in self.hsl_controls.items():
            for widget in pair:
                widget.blockSignals(True)
                widget.setValue(self.hsl[name])
                widget.blockSignals(False)
        for name, pair in self.tone_controls.items():
            for widget in pair:
                widget.blockSignals(True)
                widget.setValue(self.tone[name])
                widget.blockSignals(False)
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
                low / 100 if name == "gamma" else low,
                high / 100 if name == "gamma" else high,
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
        self.undo_button.setEnabled(bool(self.history) and self.session is not None)
        self.redo_button.setEnabled(bool(self.future) and self.session is not None)

    def remember(self):
        if self.group_change and self.group_recorded:
            return
        self.history.append(self.snapshot())
        self.history = self.history[-100:]
        self.future.clear()
        self.group_recorded = self.group_change

    def begin_gesture(self):
        self.group_change, self.group_recorded = True, False

    def end_gesture(self):
        self.group_change = self.group_recorded = False

    def undo_edit(self):
        if self.running() or not self.history:
            return
        self.future.append(self.snapshot())
        self.settings, self.tone, self.hsl, self.balance = self.history.pop()
        self.refresh_controls()
        self.render_preview()

    def redo_edit(self):
        if self.running() or not self.future:
            return
        self.history.append(self.snapshot())
        self.settings, self.tone, self.hsl, self.balance = self.future.pop()
        self.refresh_controls()
        self.render_preview()

    def change(self, key, value):
        self.remember()
        self.settings[self.channel.currentIndex()][key] = (
            value / 100 if key == "gamma" else int(value)
        )
        self.refresh_controls()
        self.timer.start()

    def change_tone(self, key, value):
        self.remember()
        self.tone[key] = int(value)
        self.refresh_controls()
        self.timer.start()

    def change_hsl(self, key, value):
        self.remember()
        self.hsl[key] = int(value)
        self.refresh_controls()
        self.timer.start()

    def change_balance(self, channel, value):
        self.remember()
        band = ("shadows", "midtones", "highlights")[self.balance_band.currentIndex()]
        self.balance[band][channel] = int(value)
        self.refresh_controls()
        self.timer.start()

    def change_preserve_luminosity(self, checked):
        self.remember()
        self.balance["preserve_luminosity"] = bool(checked)
        self.refresh_controls()
        self.timer.start()

    def reset_all(self):
        self.remember()
        self.pick(None)
        self.settings = defaults()
        self.tone = tone_defaults()
        self.hsl = hsl_defaults()
        self.balance = balance_defaults()
        self.refresh_controls()
        self.render_preview()

    def auto_levels(self):
        if self.running() or self.session is None:
            return
        from colorpro.manual_auto import auto_settings

        self.pick(None)
        self.set_controls_enabled(False)
        self.status.setText("Подбор параметров…")
        mode = self.auto_mode.currentIndex()
        self.task = LevelsTask(lambda: auto_settings(self.session.pixels, mode))
        self.task.completed.connect(self.auto_loaded)
        self.task.finished.connect(self.finish_departure)
        self.task.start()

    def auto_loaded(self, result, error):
        self.set_controls_enabled(True)
        if error:
            self.status.setText(error)
            return
        self.remember()
        self.settings = result
        self.status.setText(
            "Коррекция применена к предпросмотру. Изменения ещё не сохранены."
        )
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
        self.remember()
        self.settings = picked_levels(self.settings, value, self.pick_kind)
        self.pick(None)
        self.status.setText("Точка выбрана. Изменения ещё не сохранены.")
        self.refresh_controls()
        self.render_preview()

    def render_preview(self, *args):
        self.timer.stop()
        if self.session is None or not self.active:
            return
        if self.snapshot() != self.saved_snapshot:
            self.dirty = True
            self.autosave.start()
        self.preview_revision += 1
        self.preview_pending = True
        self.start_preview()

    def preview_running(self):
        # A finished thread may still have queued result/finished signals.
        return self.preview_inflight

    def preview_idle(self):
        return (
            not self.preview_running()
            and not self.preview_pending
            and not self.timer.isActive()
        )

    def start_preview(self):
        if (
            not self.active
            or self.session is None
            or not self.preview_pending
            or self.preview_running()
        ):
            return
        from colorcorrection.levels_operator import apply_rgb_lut

        pixels = self.session.preview
        high_detail = self.owner.compare.high_detail
        if high_detail:
            pixels = self.session.pixels
        settings, tone, hsl, balance = self.snapshot()
        enabled = self.preview.isChecked()
        revision = self.preview_revision
        self.preview_job_revision = revision
        self.preview_pending = False

        def render():
            result = pixels
            if enabled:
                result = apply_rgb_lut(result, combined_lut(settings, tone, balance))
                result = apply_hsl(result, hsl)
            data = (
                preview_bytes(result, max_size=None)
                if high_detail
                else preview_bytes(result)
            )
            return revision, data

        self.preview_task = LevelsTask(render)
        self.preview_task.completed.connect(self.preview_loaded)
        self.preview_task.finished.connect(self.preview_finished)
        self.preview_inflight = True
        self.preview_task.start()

    def preview_loaded(self, result, error):
        if not self.active:
            return
        if error:
            if self.preview_job_revision == self.preview_revision:
                self.status.setText(error)
            return
        revision, data = result
        if revision != self.preview_revision:
            return
        pixmap = QPixmap()
        pixmap.loadFromData(data, "PNG")
        self.owner.compare.after = pixmap
        self.owner.compare.update()

    def preview_finished(self):
        self.preview_inflight = False
        if self.departure is not None:
            self.finish_departure()
        else:
            self.start_preview()
        if self.owner.close_requested and not self.active:
            QTimer.singleShot(0, self.owner.close)

    def save_result(self):
        if self.running() or self.session is None:
            return
        if not self.flush_state():
            return
        self.timer.stop()
        self.pick(None)
        snapshot = self.snapshot()
        item, session, index = self.item, self.session, self.index
        policy = self.owner.export_policy()
        previous = dict(self.owner.queue.results.get(index, {}))
        self.set_controls_enabled(False)
        self.status.setText("Сохранение полного размера…")

        def export():
            from colorpro.exporting import export_photo

            pixels = session.render(snapshot)
            data = export_photo(
                item,
                pixels,
                session.metadata,
                policy["format"],
                policy["mode"],
                policy["custom"],
                policy["protected"],
                previous,
                registry=self.owner.workspace,
            )
            data.update(
                base_output=str(session.path),
                manual_levels=snapshot[0],
                manual_brightness_contrast=snapshot[1],
                manual_hsl=snapshot[2],
                manual_color_balance=snapshot[3],
            )
            return data

        self.task = LevelsTask(export)
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
            self.status.setText("Фото экспортировано. Правки и история сохранены.")
        self.set_controls_enabled(True)
        self.finish_departure()

    def cancel_edit(self):
        self.owner.edit_on_selection = False
        self.leave(self.owner.selection_changed)

    def end(self, refresh=True, persist=True):
        if (
            persist
            and self.active
            and self.session is not None
            and not self.flush_state()
        ):
            return
        self.pick(None)
        self.timer.stop()
        self.autosave.stop()
        self.active = False
        self.departure = None
        self.pending_tool = None
        self.preview_revision += 1
        self.preview_pending = False
        self.session = None
        self.hide()
        owner = self.owner
        owner.table.setEnabled(True)
        owner.navigation.setVisible(not owner.isFullScreen())
        for button in owner.nav_buttons:
            button.setEnabled(True)
        owner.set_busy(False)
        if (
            self.item is not None
            and owner.compare.before
            and owner.compare.after
            and not owner.compare.high_detail
        ):
            record = owner.queue.results.get(self.index, {})
            key = (self.item.key, record.get("output"), None)
            owner.cache_preview(key, (owner.compare.before, owner.compare.after))
        owner.preview_key = owner.face_record_key = None
        if refresh:
            owner.edit_on_selection = False
            owner.selection_changed()
