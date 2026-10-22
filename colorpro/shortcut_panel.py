"""Inline settings for keyboard shortcuts; no modal configuration windows."""

from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from colorpro.shortcuts import ACTIONS, GROUPS, KEY_FORMAT, defaults, physical_key


class KeyRecorder(QKeySequenceEdit):
    def __init__(self):
        super().__init__()
        self.findChild(QLineEdit).textChanged.connect(self.clear_if_empty)

    def clear_if_empty(self, text):
        if not text and not self.keySequence().isEmpty():
            self.clear()

    def keyPressEvent(self, event):
        translated = QKeyEvent(
            event.type(),
            physical_key(event),
            event.modifiers(),
            event.text(),
            event.isAutoRepeat(),
            event.count(),
        )
        super().keyPressEvent(translated)


class ShortcutPanel(QFrame):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        title = QLabel("Горячие клавиши")
        title.setObjectName("section")
        layout.addWidget(title)
        hint = QLabel(
            "Нажмите сочетание в нужной строке. Очистите поле, чтобы отключить команду. "
            "В текстовых полях клавиши работают как обычно."
        )
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        layout.addWidget(hint)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Найти команду…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter)
        layout.addWidget(self.search)
        self.table = QTableWidget(len(ACTIONS), 3)
        self.table.setHorizontalHeaderLabels(["Раздел", "Команда", "Сочетание"])
        self.table.verticalHeader().hide()
        self.table.setMinimumHeight(230)
        self.table.setMaximumHeight(330)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.editors = {}
        for row, action in enumerate(ACTIONS):
            from PySide6.QtCore import Qt

            for column, text in enumerate((GROUPS[action.scope], action.label)):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)
            edit = KeyRecorder()
            edit.setAccessibleName(action.label)
            line = edit.findChild(QLineEdit)
            line.setClearButtonEnabled(True)
            line.setPlaceholderText("Не назначено")
            self.table.setCellWidget(row, 2, edit)
            self.table.setRowHeight(row, 44)
            self.editors[action.id] = edit
        layout.addWidget(self.table)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        buttons = QHBoxLayout()
        self.reset = QPushButton("По умолчанию")
        self.reset.clicked.connect(lambda: self.populate(defaults()))
        buttons.addWidget(self.reset)
        buttons.addStretch()
        self.save = QPushButton("Сохранить клавиши")
        self.save.setObjectName("primary")
        self.save.clicked.connect(self.apply)
        buttons.addWidget(self.save)
        layout.addLayout(buttons)
        self.populate(manager.bindings)
        if manager.load_error:
            self.message.setText(
                "Восстановлены стандартные клавиши: " + manager.load_error
            )

    def populate(self, bindings):
        for action, edit in self.editors.items():
            edit.setKeySequence(QKeySequence(bindings[action], KEY_FORMAT))
        self.message.clear()
        self.filter()

    def filter(self):
        query = self.search.text().strip().casefold()
        for row, action in enumerate(ACTIONS):
            text = (
                GROUPS[action.scope]
                + " "
                + action.label
                + " "
                + self.editors[action.id].keySequence().toString()
            )
            self.table.setRowHidden(row, query not in text.casefold())

    def apply(self):
        try:
            self.manager.apply(
                {
                    action: edit.keySequence().toString(KEY_FORMAT)
                    for action, edit in self.editors.items()
                }
            )
            self.message.setText("Сочетания сохранены.")
            return True
        except ValueError as error:
            self.message.setText(str(error))
            return False
