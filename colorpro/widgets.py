"""Explicit popup palette avoids inheriting sidebar light-on-dark text."""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QComboBox, QListView, QStyledItemDelegate


def combo_box():
    combo = QComboBox()
    view = QListView()
    view.setItemDelegate(QStyledItemDelegate(view))
    palette = view.palette()
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        for role, color in (
            (QPalette.ColorRole.Base, "#ffffff"),
            (QPalette.ColorRole.Window, "#ffffff"),
            (QPalette.ColorRole.Text, "#242424"),
            (QPalette.ColorRole.WindowText, "#242424"),
            (QPalette.ColorRole.Highlight, "#d83387"),
            (QPalette.ColorRole.HighlightedText, "#ffffff"),
        ):
            palette.setColor(group, role, QColor(color))
    view.setPalette(palette)
    combo.setView(view)
    return combo
