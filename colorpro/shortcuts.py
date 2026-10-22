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
    Action("edit", "Открыть ручную коррекцию", "image", "Ctrl+L"),
    Action("save", "Сохранить правки", "editor", "Ctrl+S"),
    Action("undo", "Отменить правку", "editor", "Ctrl+Z"),
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


class ShortcutManager(QObject):
    changed = Signal()

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.load_error = ""
        try:
            raw = owner.settings.value("shortcuts_v1", "{}")
            if not isinstance(raw, str) or len(raw) > 20000:
                raise ValueError("Повреждённые настройки клавиш")
            self.bindings = validate_bindings(json.loads(raw))
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
        self.changed.emit()

    def hint(self, action):
        return self.bindings[action] or "не назначено"

    def allowed(self, action, watched):
        owner = self.owner
        editor = owner.review.editor
        scope = BY_ID[action].scope
        if scope == "editor":
            return editor.active and editor.session is not None and not editor.running()
        if scope == "image":
            return owner.pages.currentIndex() == owner.COMPARE and not editor.running()
        if scope == "queue":
            return watched in (owner.table, owner.table.viewport()) and not owner.busy()
        return True

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
        if action == "save":
            candidate = self.owner.focusWidget()
            while candidate is not None and candidate is not self.owner:
                if isinstance(candidate, QAbstractSpinBox):
                    commit_spin = candidate
                    break
                candidate = candidate.parentWidget()
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
        if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
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
        elif action == "edit":
            owner.review.levels_button.click()
        elif action == "remove":
            owner.remove_selected()
        elif action == "select_all":
            owner.table.selectAll()
        elif action == "save":
            editor.save_result()
        elif action == "undo":
            editor.undo_edit()
        elif action == "redo":
            editor.redo_edit()
        elif action == "preview":
            editor.preview.toggle()
        elif action == "reset":
            editor.reset_all()
