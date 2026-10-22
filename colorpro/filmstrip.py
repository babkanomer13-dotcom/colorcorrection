"""Virtual vertical photo rail; decoding shares the queue's bounded cache."""

from PySide6.QtCore import QAbstractListModel, QPoint, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QListView,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)


class PhotoList(QAbstractListModel):
    def __init__(self, queue):
        super().__init__()
        self.queue = queue
        queue.modelReset.connect(self.reset)
        queue.rowsInserted.connect(self.reset)
        queue.dataChanged.connect(self.changed)

    def reset(self, *args):
        self.beginResetModel()
        self.endResetModel()

    def changed(self, first, last, *args):
        self.dataChanged.emit(self.index(first.row()), self.index(last.row()))

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.queue.items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.queue.items):
            return None
        item = self.queue.items[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return item.name
        if role == Qt.ItemDataRole.ToolTipRole:
            return item.label
        if role == Qt.ItemDataRole.SizeHintRole:
            return QSize(142, 132)


class PhotoTile(QStyledItemDelegate):
    def paint(self, painter, option, index):
        queue = index.model().queue
        item = queue.items[index.row()]
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(option.rect).adjusted(4, 3, -4, -3)
        painter.setPen(
            QPen(QColor("#d52c95" if selected else "#e5e5ee"), 2 if selected else 1)
        )
        painter.setBrush(QColor("#fff3fa" if selected else "#ffffff"))
        painter.drawRoundedRect(rect, 9, 9)
        box = rect.adjusted(8, 7, -8, -32)
        cached = queue.thumbnails.get(item.key)
        pixmap = cached[0] if cached else None
        if pixmap is not None and not pixmap.isNull():
            size = pixmap.size().scaled(
                box.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio
            )
            dest = QRectF(0, 0, size.width(), size.height())
            dest.moveCenter(box.center())
            painter.drawPixmap(dest, pixmap, QRectF(pixmap.rect()))
        else:
            painter.setPen(QColor("#9895a4"))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, str(index.row() + 1))
        status = queue.results.get(index.row(), {}).get("status", "queued")
        color = {
            "corrected": "#3ca978",
            "error": "#d64a5d",
            "running": "#df9a32",
            "needs_attention": "#df9a32",
            "partial": "#df9a32",
        }.get(status, "#a8a6b5")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(rect.right() - 12, rect.top() + 7, 5, 5)
        painter.setPen(QColor("#42384d"))
        label = option.fontMetrics.elidedText(
            item.name, Qt.TextElideMode.ElideMiddle, int(rect.width() - 12)
        )
        painter.drawText(
            rect.adjusted(6, rect.height() - 30, -6, -4),
            Qt.AlignmentFlag.AlignCenter,
            label,
        )
        painter.restore()


class Filmstrip(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setFixedWidth(154)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.heading = QLabel("Все фотографии")
        self.heading.setObjectName("section")
        layout.addWidget(self.heading)
        self.view = QListView()
        self.view.setAccessibleName("Лента всех добавленных фотографий")
        self.model = PhotoList(owner.queue)
        self.view.setModel(self.model)
        self.view.setItemDelegate(PhotoTile(self.view))
        self.view.setUniformItemSizes(True)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setStyleSheet("QListView { background: white; border:0; outline:0; }")
        self.syncing = False
        self.view.selectionModel().currentChanged.connect(self.activated)
        layout.addWidget(self.view, 1)
        self.timer = QTimer(self)
        self.timer.setInterval(160)
        self.timer.timeout.connect(self.load_visible)
        self.timer.start()

    def select(self, row):
        self.heading.setText(f"Фотографии · {len(self.owner.queue.items)}")
        if self.view.currentIndex().row() != row:
            index = self.model.index(row)
            self.syncing = True
            self.view.setCurrentIndex(index)
            self.syncing = False
            if index.isValid():
                self.view.scrollTo(index)

    def activated(self, index, previous):
        if index.isValid() and not self.syncing:
            self.owner.select_photo(index.row())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self.reveal_current)

    def reveal_current(self):
        index = self.view.currentIndex()
        if self.isVisible() and index.isValid():
            self.view.scrollTo(index)

    def load_visible(self):
        owner = self.owner
        if not self.isVisible() or owner.close_requested:
            return
        first = self.view.indexAt(QPoint(20, 8)).row()
        if first < 0:
            first = max(0, self.view.verticalScrollBar().value() // 132)
        owner.start_thumbnails(
            owner.queue.items[first : first + max(6, self.view.height() // 132 + 2)]
        )
