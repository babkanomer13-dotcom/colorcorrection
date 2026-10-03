"""Shared, accessible desktop controls with platform-independent rendering."""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QComboBox, QListView, QStyle, QStyledItemDelegate


class ChoiceDelegate(QStyledItemDelegate):
    def __init__(self, combo, view):
        super().__init__(view)
        self.combo = combo

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width() + 56, 44)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        rect = QRectF(option.rect).adjusted(5, 3, -5, -3)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#d83387" if selected else "#ffffff"))
        painter.drawRoundedRect(rect, 7, 7)
        painter.setPen(QColor("#ffffff" if selected else "#242424"))
        painter.setFont(option.font)
        text_rect = option.rect.adjusted(17, 0, -37, 0)
        text = option.fontMetrics.elidedText(
            str(index.data()), Qt.TextElideMode.ElideRight, text_rect.width()
        )
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, text)
        if index.row() == self.combo.currentIndex():
            x, y = option.rect.right() - 23, option.rect.center().y()
            painter.setPen(QPen(QColor("white" if selected else "#d83387"), 1.8))
            painter.drawPolyline(
                QPolygonF([QPointF(x - 4, y), QPointF(x - 1, y + 3), QPointF(x + 5, y - 4)])
            )
        painter.restore()


class ChoiceBox(QComboBox):
    def __init__(self):
        super().__init__()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(38)
        self.setMaxVisibleItems(8)
        view = QListView()
        view.setItemDelegate(ChoiceDelegate(self, view))
        view.setSpacing(0)
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
        view.setStyleSheet(
            "QListView { background: white; color: #242424; border: 1px solid #e0d9df; "
            "selection-background-color: #d83387; selection-color: white; "
            "padding: 4px; outline: 0; }"
        )
        self.setView(view)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#706570" if self.isEnabled() else "#b8b4b8"), 1.8))
        x, y = self.width() - 21, self.height() / 2
        painter.drawPolyline(
            QPolygonF([QPointF(x - 5, y - 2), QPointF(x, y + 3), QPointF(x + 5, y - 2)])
        )
        painter.end()

    def wheelEvent(self, event):
        # Scrolling a settings page must not silently change an unfocused choice.
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


def combo_box():
    return ChoiceBox()


def navigation_icon(kind, tint=None):
    result = QIcon()
    for state, color in ((QIcon.State.Off, "#d0c8d9"), (QIcon.State.On, "#ffe1f3")):
        color = tint or color
        pix = QPixmap(44, 44)
        pix.setDevicePixelRatio(2)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(color), 1.6))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if kind in {"previous", "next"}:
            painter.setPen(QPen(QColor(tint or "#8a8eb6"), 1.8))
            x0, x1 = (13, 8) if kind == "previous" else (8, 13)
            painter.drawPolyline(QPolygonF([QPointF(x0, 5), QPointF(x1, 11), QPointF(x0, 17)]))
        elif kind == "compare":
            painter.drawRoundedRect(QRectF(3, 3, 16, 16), 3, 3)
            painter.drawLine(QPointF(11, 3), QPointF(11, 19))
            painter.drawLine(QPointF(5, 16), QPointF(8, 12))
            painter.drawLine(QPointF(14, 12), QPointF(17, 16))
        elif kind == "photos":
            painter.drawRoundedRect(QRectF(3, 3, 16, 16), 3, 3)
            painter.drawEllipse(QPointF(8, 8), 1.3, 1.3)
            painter.drawPolyline(
                QPolygonF(
                    [
                        QPointF(4, 16),
                        QPointF(9, 11),
                        QPointF(12, 14),
                        QPointF(15, 11),
                        QPointF(19, 15),
                    ]
                )
            )
        elif kind == "settings":
            for x, y in ((5, 8), (11, 15), (17, 7)):
                painter.drawLine(QPointF(x, 3), QPointF(x, y - 2))
                painter.drawLine(QPointF(x, y + 2), QPointF(x, 19))
                painter.drawEllipse(QPointF(x, y), 2, 2)
        elif kind == "folder":
            painter.drawPolyline(
                QPolygonF(
                    [
                        QPointF(3, 18),
                        QPointF(3, 5),
                        QPointF(9, 5),
                        QPointF(11, 8),
                        QPointF(19, 8),
                        QPointF(19, 18),
                        QPointF(3, 18),
                    ]
                )
            )
        elif kind == "processor":
            painter.drawRoundedRect(QRectF(5, 5, 12, 12), 3, 3)
            painter.drawEllipse(QPointF(11, 11), 3, 3)
        elif kind == "refresh":
            painter.drawArc(QRectF(3, 3, 16, 16), 25 * 16, 135 * 16)
            painter.drawArc(QRectF(3, 3, 16, 16), 205 * 16, 135 * 16)
            painter.drawPolyline(QPolygonF([QPointF(15, 6), QPointF(19, 7), QPointF(19, 3)]))
            painter.drawPolyline(QPolygonF([QPointF(7, 16), QPointF(3, 15), QPointF(3, 19)]))
        elif kind == "play":
            painter.drawPolygon(QPolygonF([QPointF(7, 4), QPointF(17, 11), QPointF(7, 18)]))
        elif kind == "plus":
            painter.drawLine(QPointF(11, 4), QPointF(11, 18))
            painter.drawLine(QPointF(4, 11), QPointF(18, 11))
        elif kind == "open":
            painter.drawPolyline(
                QPolygonF(
                    [
                        QPointF(10, 4),
                        QPointF(4, 4),
                        QPointF(4, 18),
                        QPointF(18, 18),
                        QPointF(18, 12),
                    ]
                )
            )
            painter.drawPolyline(QPolygonF([QPointF(13, 3), QPointF(19, 3), QPointF(19, 9)]))
            painter.drawLine(QPointF(10, 12), QPointF(19, 3))
        elif kind == "fullscreen":
            for x, y, dx, dy in ((3, 3, 5, 5), (19, 3, -5, 5), (3, 19, 5, -5), (19, 19, -5, -5)):
                painter.drawPolyline(
                    QPolygonF([QPointF(x + dx, y), QPointF(x, y), QPointF(x, y + dy)])
                )
        elif kind == "upload":
            painter.drawLine(QPointF(11, 3), QPointF(11, 15))
            painter.drawPolyline(QPolygonF([QPointF(5, 9), QPointF(11, 3), QPointF(17, 9)]))
            painter.drawPolyline(
                QPolygonF([QPointF(3, 13), QPointF(3, 20), QPointF(19, 20), QPointF(19, 13)])
            )
        elif kind == "updates":
            painter.drawLine(QPointF(11, 3), QPointF(11, 14))
            painter.drawPolyline(QPolygonF([QPointF(6, 10), QPointF(11, 15), QPointF(16, 10)]))
            painter.drawPolyline(
                QPolygonF([QPointF(4, 15), QPointF(4, 19), QPointF(18, 19), QPointF(18, 15)])
            )
        else:
            painter.drawEllipse(QPointF(11, 11), 8, 8)
            painter.setFont(QFont("Segoe UI", 11))
            painter.drawText(
                QRectF(3, 2, 16, 18), Qt.AlignmentFlag.AlignCenter, "?" if kind == "help" else "i"
            )
        painter.end()
        result.addPixmap(pix, QIcon.Mode.Normal, state)
    return result
