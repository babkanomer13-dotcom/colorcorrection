"""Configurable, layout-independent shortcuts shared by all desktop pages."""

import json
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QKeySequenceEdit,
    QLineEdit,
    QPlainTextEdit,
    QSlider,
    QTextEdit,
    QWidget,
)


@dataclass(frozen=True)
class Action:
    id: str
    label: str
    scope: str
    key: str


ACTIONS = (
    Action("open", "Добавить фотографии / ZIP", "app", "Ctrl+O"),
    Action("photos", "Фотографии", "app", "Ctrl+Alt+1"),
    Action("compare", "До / после", "app", "Ctrl+Alt+2"),
    Action("settings", "Настройки", "app", "Ctrl+K"),
    Action("shortcuts", "Настроить горячие клавиши", "app", "Ctrl+Alt+Shift+K"),
    Action("updates", "Обновления", "app", "Ctrl+Alt+4"),
    Action("help", "Помощь", "app", "F1"),
    Action("escape", "Выйти из полного экрана / вернуться", "app", "Esc"),
    Action("next", "Следующая фотография", "image", "PgDown"),
    Action("previous", "Предыдущая фотография", "image", "PgUp"),
    Action("zoom_in", "Приблизить", "image", "Ctrl+="),
    Action("zoom_out", "Отдалить", "image", "Ctrl+-"),
    Action("fit", "Вписать фотографию в окно", "image", "Ctrl+0"),
    Action("fullscreen", "Полноэкранный просмотр", "image", "F11"),
    Action("mode", "Рядом / разделитель", "image", "Ctrl+Tab"),
    # Keep the 1.6.0 ID so existing custom Levels bindings survive the upgrade.
    Action("edit", "Уровни", "tool", "Ctrl+L"),
    Action("hsl", "Цветовой тон / насыщенность", "tool", "Ctrl+U"),
    Action("balance", "Цветовой баланс", "tool", "Ctrl+B"),
    Action("tone", "Яркость / контраст (без клавиш в Photoshop)", "tool", ""),
    Action("auto_tone", "Автотон", "tool", "Ctrl+Shift+L"),
    Action("auto_contrast", "Автоконтраст", "tool", "Ctrl+Alt+Shift+L"),
    Action("auto_color", "Автоцвет", "tool", "Ctrl+Shift+B"),
    Action("channel_rgb", "Уровни: общий канал RGB", "editor", "Alt+2"),
    Action("channel_red", "Уровни: красный канал", "editor", "Alt+3"),
    Action("channel_green", "Уровни: зелёный канал", "editor", "Alt+4"),
    Action("channel_blue", "Уровни: синий канал", "editor", "Alt+5"),
    Action("increase", "Увеличить выбранный параметр", "value", "Up"),
    Action("decrease", "Уменьшить выбранный параметр", "value", "Down"),
    Action("increase_fast", "Увеличить выбранный параметр ×10", "value", "Shift+Up"),
    Action("decrease_fast", "Уменьшить выбранный параметр ×10", "value", "Shift+Down"),
    Action("save", "Сохранить правки", "editor", "Ctrl+S"),
    Action("undo", "Отменить правку", "editor", "Ctrl+Z"),
    Action("step_back", "Шаг назад по истории правок", "editor", "Ctrl+Alt+Z"),
    Action("redo", "Повторить правку", "editor", "Ctrl+Shift+Z"),
    Action("preview", "Показать / скрыть ручные правки", "editor", "\\"),
    Action("reset", "Сбросить ручные правки", "editor", "Ctrl+Alt+R"),
    Action("remove", "Убрать выбранное из очереди", "queue", "Del"),
    Action("select_all", "Выделить очередь", "queue", "Ctrl+A"),
)
BY_ID = {action.id: action for action in ACTIONS}
GROUPS = {
    "app": "Приложение",
    "image": "Просмотр",
    "tool": "Инструменты",
    "value": "Параметры",
    "editor": "Коррекция",
    "queue": "Очередь",
}
KEY_FORMAT = QKeySequence.SequenceFormat.PortableText


def enum_value(value):
    return value.value if hasattr(value, "value") else int(value)


def sequence_code(sequence):
    value = sequence[0]
    return value.toCombined() if hasattr(value, "toCombined") else int(value)


def defaults():
    return {action.id: action.key for action in ACTIONS}


def validate_bindings(data):
    if not isinstance(data, dict) or set(data) - BY_ID.keys():
        raise ValueError("Неизвестная команда в настройках клавиш.")
    result = defaults()
    result.update(data)
    occupied = {}
    for action in ACTIONS:
        key = result[action.id]
        if not isinstance(key, str) or len(key) > 80:
            raise ValueError("Некорректное сочетание клавиш.")
        if not key:
            continue
        sequence = QKeySequence.fromString(key, KEY_FORMAT)
        portable = sequence.toString(KEY_FORMAT)
        if (
            sequence.count() != 1
            or not portable
            or (sequence_code(sequence) & 0x01FFFFFF)
            in {
                enum_value(Qt.Key.Key_unknown),
                enum_value(Qt.Key.Key_Control),
                enum_value(Qt.Key.Key_Alt),
                enum_value(Qt.Key.Key_Shift),
                enum_value(Qt.Key.Key_Meta),
                enum_value(Qt.Key.Key_AltGr),
                0,
            }
        ):
            raise ValueError("Задайте одно сочетание, например Ctrl+L.")
        code = sequence_code(sequence)
        if code & enum_value(Qt.KeyboardModifier.MetaModifier) or portable in {
            "Alt+F4",
            "Alt+Tab",
            "Ctrl+Alt+Del",
            "Alt+Space",
        }:
            raise ValueError(f"«{portable}» занято Windows.")
        if code in occupied:
            raise ValueError(f"«{portable}» уже назначено: {occupied[code]}.")
        occupied[code] = action.label
        result[action.id] = portable
    return result


def physical_key(event):
    native = event.nativeVirtualKey()
    if 0x41 <= native <= 0x5A or 0x30 <= native <= 0x39:
        return native
    return {
        0xDC: enum_value(Qt.Key.Key_Backslash),
        0xBB: enum_value(Qt.Key.Key_Equal),
        0xBD: enum_value(Qt.Key.Key_Minus),
    }.get(native, event.key())


def load_bindings(data):
    """New default keys must never override previously saved custom keys."""
    if not isinstance(data, dict) or set(data) - BY_ID.keys():
        raise ValueError("Неизвестная команда в настройках клавиш.")
    # Validate saved choices in isolation before introducing newly added actions.
    saved = validate_bindings({**dict.fromkeys(BY_ID, ""), **data})
    occupied = {
        sequence_code(QKeySequence(key, KEY_FORMAT)) for key in saved.values() if key
    }
    disabled = []
    for action in ACTIONS:
        if action.id in data or not action.key:
            continue
        code = sequence_code(QKeySequence(action.key, KEY_FORMAT))
        if code in occupied:
            disabled.append(action.label)
        else:
            saved[action.id] = action.key
            occupied.add(code)
    return validate_bindings(saved), disabled


class ShortcutManager(QObject):
    changed = Signal()

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.load_error = ""
        self.load_notice = ""
        try:
            raw = owner.settings.value("shortcuts_v1", "{}")
            if not isinstance(raw, str) or len(raw) > 20000:
                raise ValueError("Повреждённые настройки клавиш")
            self.bindings, disabled = load_bindings(json.loads(raw))
            if disabled:
                self.load_notice = (
                    "Ваши сочетания сохранены. Новые команды без клавиш из-за конфликта: "
                    + ", ".join(disabled)
                    + ". Их можно назначить ниже."
                )
        except (ValueError, TypeError) as error:
            self.bindings = defaults()
            self.load_error = str(error)
        self.rebuild()

    def install(self):
        QApplication.instance().installEventFilter(self)

    def rebuild(self):
        self.codes = {
            sequence_code(QKeySequence(key, KEY_FORMAT)): action
            for action, key in self.bindings.items()
            if key
        }

    def apply(self, bindings):
        validated = validate_bindings(bindings)
        self.bindings = validated
        self.rebuild()
        self.owner.settings.setValue("shortcuts_v1", json.dumps(validated))
        self.owner.settings.sync()
        self.load_error = ""
        self.load_notice = ""
        self.changed.emit()

    def hint(self, action):
        return self.bindings[action] or "не назначено"

    def allowed(self, action, watched):
        owner = self.owner
        editor = owner.review.editor
        scope = BY_ID[action].scope
        if scope == "tool":
            return owner.pages.currentIndex() == owner.COMPARE and (
                (editor.active and editor.session is not None and not editor.running())
                or (not editor.active and owner.review.levels_button.isEnabled())
            )
        if scope == "value":
            return (
                editor.active
                and editor.session is not None
                and not editor.running()
                and self.focused_parameter() is not None
            )
        if scope == "editor":
            return editor.active and editor.session is not None and not editor.running()
        if scope == "image":
            return owner.pages.currentIndex() == owner.COMPARE and not editor.running()
        if scope == "queue":
            return watched in (owner.table, owner.table.viewport()) and not owner.busy()
        return True

    def focused_parameter(self):
        editor = self.owner.review.editor
        widget = self.owner.focusWidget()
        controls = {control for pair in editor.control_pairs() for control in pair}
        while widget is not None and widget is not self.owner:
            if widget in controls:
                return widget
            widget = widget.parentWidget()
        return None

    def eventFilter(self, watched, event):
        if event.type() not in {QEvent.Type.KeyPress, QEvent.Type.ShortcutOverride}:
            return False
        if not isinstance(watched, QWidget) or watched.window() is not self.owner:
            return False
        code = enum_value(physical_key(event)) | enum_value(event.modifiers())
        code &= ~enum_value(Qt.KeyboardModifier.KeypadModifier)
        action = self.codes.get(code)
        if action is None or not self.allowed(action, watched):
            return False
        # Saving from a numeric editor must include the value just typed, even
        # though keyboardTracking is off. Other editing keys stay local.
        commit_spin = None
        parameter = self.focused_parameter()
        numeric_command = (
            BY_ID[action].scope in {"tool", "value"}
            or action.startswith("channel_")
            or action in {"save", "step_back", "redo"}
        )
        # Plain letters/digits assigned by the user must still be typeable.
        modified = bool(
            event.modifiers()
            & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
        )
        text_command = (
            physical_key(event)
            in {Qt.Key.Key_A, Qt.Key.Key_C, Qt.Key.Key_V, Qt.Key.Key_X, Qt.Key.Key_Z}
            and event.modifiers() == Qt.KeyboardModifier.ControlModifier
        )
        if (
            isinstance(parameter, QAbstractSpinBox)
            and numeric_command
            and (
                (
                    BY_ID[action].scope == "value"
                    and physical_key(event)
                    in {
                        Qt.Key.Key_Up,
                        Qt.Key.Key_Down,
                        Qt.Key.Key_PageUp,
                        Qt.Key.Key_PageDown,
                    }
                )
                or (modified and not text_command)
                or Qt.Key.Key_F1 <= physical_key(event) <= Qt.Key.Key_F35
            )
        ):
            commit_spin = parameter
        # Check focus as well: ignored events can bubble out of a text field.
        for candidate in (watched, self.owner.focusWidget()):
            while candidate is not None and candidate is not self.owner:
                if isinstance(
                    candidate,
                    (
                        QLineEdit,
                        QTextEdit,
                        QPlainTextEdit,
                        QAbstractSpinBox,
                        QKeySequenceEdit,
                    ),
                ) and (commit_spin is None or isinstance(candidate, QKeySequenceEdit)):
                    return False
                candidate = candidate.parentWidget()
        event.accept()
        if event.type() == QEvent.Type.KeyPress and (
            not event.isAutoRepeat() or BY_ID[action].scope == "value"
        ):
            if commit_spin is not None:
                commit_spin.interpretText()
            self.dispatch(action)
        return True

    def dispatch(self, action):
        owner = self.owner
        editor = owner.review.editor
        pages = {
            "photos": owner.PHOTOS,
            "compare": owner.COMPARE,
            "settings": owner.SETTINGS,
            "updates": owner.UPDATES,
            "help": owner.HELP,
        }
        if action in pages:
            owner.show_page(pages[action])
        elif action == "shortcuts":
            owner.show_shortcut_settings()
        elif BY_ID[action].scope == "tool":
            editor.activate_tool("levels" if action == "edit" else action)
        elif action.startswith("channel_"):
            editor.activate_tool("levels")
            editor.channel.setCurrentIndex(
                ("channel_rgb", "channel_red", "channel_green", "channel_blue").index(
                    action
                )
            )
        elif BY_ID[action].scope == "value":
            parameter = self.focused_parameter()
            if parameter is not None:
                step = 10 if action.endswith("_fast") else 1
                step *= 1 if action.startswith("increase") else -1
                parameter.setValue(parameter.value() + parameter.singleStep() * step)
                if not isinstance(parameter, QSlider):
                    parameter.selectAll()
        elif action == "open":
            owner.pick_files()
        elif action == "escape":
            owner.escape_page()
        elif action == "fullscreen":
            owner.toggle_review_fullscreen()
        elif action == "next":
            owner.select_relative(1)
        elif action == "previous":
            owner.select_relative(-1)
        elif action == "zoom_in":
            owner.compare.set_zoom(owner.compare.zoom * 1.2)
        elif action == "zoom_out":
            owner.compare.set_zoom(owner.compare.zoom / 1.2)
        elif action == "fit":
            owner.compare.reset_zoom()
        elif action == "mode":
            owner.review.mode.setCurrentIndex(1 - owner.review.mode.currentIndex())
        elif action == "remove":
            owner.remove_selected()
        elif action == "select_all":
            owner.table.selectAll()
        elif action == "save":
            editor.save_result()
        elif action in {"undo", "step_back"}:
            editor.undo_edit()
        elif action == "redo":
            editor.redo_edit()
        elif action == "preview":
            editor.preview.toggle()
        elif action == "reset":
            editor.reset_all()
