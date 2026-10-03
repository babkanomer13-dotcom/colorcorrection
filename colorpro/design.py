"""ColorPro visual system: vector artwork, window chrome and queue presentation."""

import io
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, QThread, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

STYLE = """
QWidget { font-family: 'Segoe UI'; font-size: 13px; color: #20213e; }
QMainWindow, #shell { background: #24212d; }
#body, #page, #workspace, QStackedWidget { background: #f6f6fd; }
#sidebar { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #211e29,stop:1 #2c2735); }
#sidebar QLabel { color: #f9f7ff; background: transparent; }
#sidebar QLabel[muted='true'] { color: #bcb6c9; font-size: 12px; }
#brand { font-size: 25px; font-weight: 600; }
#brandTagline { color: #bcb6c9; font-size: 12px; }
#sidebar QFrame#separator { background: #494252; max-height: 1px; border: 0; }
#sidebar QPushButton#nav { text-align: left; padding: 12px 14px; border: 1px solid transparent;
 border-radius: 9px; background: transparent; color: #eee8f4; font-weight: 400; }
#sidebar QPushButton#nav:hover { background: #3a2e40; }
#sidebar QPushButton#nav:checked { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
 stop:0 #60304e,stop:1 #4b2c4c); border: 1px solid #bc3a89; color: #fff0fa; }
#sidebar QLabel#navStatus { color: #ef95c7; padding: 8px 4px; font-size: 12px; }
#chrome { background: #f6f6fd; }
QPushButton#windowControl { border: 0; border-radius: 5px; background: transparent;
 color: #82829c; padding: 0; min-height: 0; font-size: 15px; font-weight: 400; }
QPushButton#windowControl:hover { background: #e7e6f3; color: #26223c; }
QPushButton#closeControl { border: 0; border-radius: 5px; background: transparent;
 color: #82829c; padding: 0; min-height: 0; font-size: 18px; }
QPushButton#closeControl:hover { background: #df3f64; color: white; }
QLabel#pageTitle { font-size: 30px; font-weight: 700; color: #131331; }
QLabel#title { font-size: 26px; font-weight: 700; color: #171729; }
QLabel#section { font-size: 15px; font-weight: 700; color: #20203c; }
QLabel#muted { color: #7c7fa1; font-size: 12px; background: transparent; }
QLabel#eyebrow { color: #cf2990; font-size: 11px; font-weight: 700; letter-spacing: 1px; }
QFrame#card, QFrame#queueCard, QFrame#statCard { background: #fdfdff;
 border: 1px solid #e8e8f5; border-radius: 12px; }
QFrame#drop { background: #f0f1fa; border: 1px dashed #d7daed; border-radius: 10px; }
QFrame#notice { background: #edeef8; border: 1px solid #e4e5f3; border-radius: 10px; }
QLabel#statValue { color: #171737; font-size: 23px; font-weight: 700; }
QLabel#statTitle { color: #515374; font-size: 11px; }
QLabel#stepNumber { color: #8b35d8; background: #efe5ff; border-radius: 12px;
 font-size: 18px; font-weight: 600; padding: 12px; }
QPushButton { color: #303151; background: #fefeff; border: 1px solid #e0e2f3;
 border-radius: 9px; padding: 8px 15px; font-weight: 600; min-height: 20px; }
QPushButton:hover { background: #eeeef9; border-color: #d1c7e8; }
QPushButton:pressed { background: #e4e2f3; }
QPushButton:disabled { color: #a3a2b8; background: #f4f3fa; border-color: #e8e7f2; }
QPushButton#primary { background: qlineargradient(
 x1:0,y1:0,x2:0,y2:1,stop:0 #dd47ad,stop:1 #c60b82);
 color: white; border: 1px solid #d62999; padding: 10px 22px; }
QPushButton#primary:hover { background: #c51789; }
QPushButton#primary:pressed { background: #ab0e75; }
QPushButton#primary:disabled { background: #e4b3d4; color: #fff8fd; border-color: #e4b3d4; }
QPushButton#small { padding: 6px 12px; min-height: 18px; }
QPushButton#square { padding: 6px 0; min-height: 20px; font-size: 18px; }
QPushButton:focus, QComboBox:focus, QLineEdit:focus { border: 1px solid #c445a0; }
QLineEdit, QComboBox { background: #fefeff; border: 1px solid #dfe1f1; border-radius: 8px;
 selection-background-color: #c62490; padding: 7px 11px; min-height: 20px; }
QComboBox { padding-right: 34px; }
QComboBox::drop-down { width: 30px; border: 0; }
QComboBox::down-arrow { image: none; width: 0; height: 0; }
QComboBox:hover { border-color: #c9b7de; }
QComboBox:disabled, QLineEdit:disabled { color: #a3a2b8; }
QScrollArea { border: 0; background: #f6f6fd; }
QTableView { border: 0; background: #fdfdff; alternate-background-color: #fdfdff;
 selection-background-color: #f1ecfa; selection-color: #242442;
 gridline-color: #eeedf7; outline: 0; }
QHeaderView::section { background: #eeeff8; color: #595b80; padding: 9px 10px;
 border: 0; font-weight: 600; font-size: 12px; }
QProgressBar { background: #e6e5f1; border: 0; border-radius: 4px;
 min-height: 6px; max-height: 6px; }
QProgressBar::chunk { background: #d52995; border-radius: 4px; }
QToolTip { background: #302a3c; color: white; border: 0; padding: 8px; }
QCheckBox { spacing: 10px; background: transparent; }
QScrollBar:vertical { background: transparent; width: 9px; }
QScrollBar::handle:vertical { background: #c8c5d9; border-radius: 4px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


def brand_icon():
    """Use the approved artwork unchanged on every application surface."""
    asset = Path(__file__).with_name("assets") / "logo.png"
    result = QIcon(str(asset))
    if result.isNull():
        raise RuntimeError("Отсутствует логотип ColorPro")
    return result


class ChromeBar(QWidget):
    """Small custom title bar; native system move keeps Windows snap available."""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner, self.drag = owner, None
        self.setObjectName("chrome")
        self.setFixedHeight(30)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 10, 0)
        row.setSpacing(2)
        row.addStretch()
        for text, accessible, callback in (
            ("−", "Свернуть окно", owner.showMinimized),
            ("□", "Развернуть или восстановить окно", self.toggle_maximized),
            ("×", "Закрыть ColorPro", owner.close),
        ):
            control = QPushButton(text)
            control.setObjectName("closeControl" if text == "×" else "windowControl")
            control.setFixedSize(38, 26)
            control.setAccessibleName(accessible)
            control.setToolTip(accessible)
            control.clicked.connect(callback)
            row.addWidget(control)

    def toggle_maximized(self):
        self.owner.showNormal() if self.owner.isMaximized() else self.owner.showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.owner.windowHandle()
            if handle and handle.startSystemMove():
                return
            self.drag = event.globalPos() - self.owner.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self.drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.owner.move(event.globalPos() - self.drag)

    def mouseReleaseEvent(self, event):
        self.drag = None

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()


class ProfileButton(QPushButton):
    """Local profile entry with initials; no implied account or online connection."""

    def __init__(self, name):
        super().__init__()
        self.setFixedHeight(68)
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_name(name)

    def set_name(self, name):
        self.name = name or "Пользователь"
        self.setAccessibleName("Профиль пользователя: " + self.name)
        self.setToolTip(self.name + " · локальный профиль")
        self.update()

    def sizeHint(self):
        return QSize(194, 68)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        if self.isChecked() or self.underMouse() or self.hasFocus():
            p.setBrush(QColor("#403044"))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0, 2, 0, -2), 10, 10)
        p.setBrush(QColor("#8055a1"))
        p.drawEllipse(QRectF(10, (self.height() - 38) / 2, 38, 38))
        p.setPen(QColor("#fff0fb"))
        font = QFont(self.font())
        font.setPixelSize(15)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        initials = "".join(word[0] for word in self.name.split()[:2]).upper()
        p.drawText(QRectF(10, 0, 38, self.height()), Qt.AlignmentFlag.AlignCenter, initials)
        font.setPixelSize(13)
        p.setFont(font)
        name = p.fontMetrics().elidedText(self.name, Qt.TextElideMode.ElideRight, self.width() - 66)
        p.drawText(QRectF(60, self.height() / 2 - 18, self.width() - 66, 23), name)
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.Normal)
        p.setFont(font)
        p.setPen(QColor("#bcb6c9"))
        p.drawText(QRectF(60, self.height() / 2 + 5, self.width() - 66, 21), "Локальный профиль")
        p.end()


class ToggleSwitch(QCheckBox):
    def __init__(self, text):
        super().__init__(text)
        self.setMinimumHeight(32)

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 66, 36)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        y = (self.height() - 24) / 2
        p.setBrush(QColor("#cc2190" if self.isChecked() else "#c5c4d4"))
        p.drawRoundedRect(QRectF(0, y, 46, 24), 12, 12)
        p.setBrush(QColor("white"))
        p.drawEllipse(QRectF(25 if self.isChecked() else 3, y + 3, 18, 18))
        p.setPen(QColor("#35354f"))
        p.drawText(self.rect().adjusted(59, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, self.text())
        if self.hasFocus():
            p.setPen(QPen(QColor("#c445a0"), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 6, 6)
        p.end()


def icon_tile(kind, size=44):
    from colorpro.widgets import navigation_icon

    tile = QLabel()
    tile.setFixedSize(size, size)
    tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
    tile.setStyleSheet("background: #eee4ff; border-radius: 12px;")
    tile.setPixmap(navigation_icon(kind, "#8937e4").pixmap(size - 18, size - 18))
    return tile


def stat_card(title, color):
    card = QFrame()
    card.setObjectName("statCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(2)
    heading = QHBoxLayout()
    heading.setSpacing(7)
    dot = QLabel("●")
    dot.setStyleSheet("color: " + color + "; background: transparent; font-size: 16px;")
    heading.addWidget(dot)
    name = QLabel(title)
    name.setObjectName("statTitle")
    heading.addWidget(name)
    heading.addStretch()
    layout.addLayout(heading)
    value = QLabel("0")
    value.setObjectName("statValue")
    value.setContentsMargins(23, 0, 0, 0)
    layout.addWidget(value)
    return card, value


class QueueHeader(QHeaderView):
    def __init__(self, model):
        super().__init__(Qt.Orientation.Horizontal)
        self.queue = model
        self.setSectionsClickable(True)
        self.sectionClicked.connect(self.toggle_all)

    def toggle_all(self, section):
        if section == 0 and self.queue.items:
            self.queue.checked = (
                set()
                if len(self.queue.checked) == len(self.queue.items)
                else {item.key for item in self.queue.items}
            )
            self.queue.dataChanged.emit(
                self.queue.index(0, 0), self.queue.index(self.queue.rowCount() - 1, 0)
            )
            self.viewport().update()

    def paintSection(self, painter, rect, section):
        painter.save()
        super().paintSection(painter, rect, section)
        painter.restore()
        if section == 0:
            painter.save()
            checked = bool(self.queue.items) and len(self.queue.checked) == len(self.queue.items)
            painter.setPen(QPen(QColor("#a5a8c6"), 1.2))
            painter.setBrush(QColor("#ce2a91" if checked else "#fafaff"))
            box = QRectF(rect.center().x() - 6, rect.center().y() - 6, 12, 12)
            painter.drawRoundedRect(box, 3, 3)
            if checked:
                painter.setPen(QColor("white"))
                painter.drawText(box.adjusted(-2, -2, 2, 2), Qt.AlignmentFlag.AlignCenter, "✓")
            painter.restore()


class PhotoDelegate(QStyledItemDelegate):
    def paint(self, p, option, index):
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        p.fillRect(option.rect, QColor("#f3effa" if selected else "#fdfdff"))
        p.setPen(QColor("#eeeef7"))
        p.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        item = index.model().items[index.row()]
        pix, dimensions = index.model().thumbnails.get(item.key, (None, ""))
        thumb = QRectF(option.rect.left() + 10, option.rect.top() + 9, 36, 48)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#e9e9f4"))
        p.drawRoundedRect(thumb, 5, 5)
        if pix is not None:
            target = QRectF(thumb)
            size = pix.size().scaled(thumb.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio)
            target.setSize(size)
            target.moveCenter(thumb.center())
            p.drawPixmap(target, pix, QRectF(pix.rect()))
        text = option.rect.adjusted(59, 7, -12, -30)
        p.setPen(QColor("#26253e"))
        font = QFont(option.font)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.drawText(
            text,
            Qt.AlignmentFlag.AlignVCenter,
            option.fontMetrics.elidedText(item.name, Qt.TextElideMode.ElideRight, text.width()),
        )
        font.setWeight(QFont.Weight.Normal)
        font.setPointSizeF(max(8, font.pointSizeF() - 1))
        p.setFont(font)
        p.setPen(QColor("#898baa"))
        size = (item.member_size if item.member else item.size) / 1024**2
        meta = (dimensions + "  ·  " if dimensions else "") + f"{size:.1f} МБ"
        p.drawText(option.rect.adjusted(59, 30, -12, -7), Qt.AlignmentFlag.AlignVCenter, meta)
        p.restore()


class ThumbnailWorker(QThread):
    loaded = Signal(object, object, str)

    def __init__(self, items):
        super().__init__()
        self.items = items

    def run(self):
        from PIL import Image, ImageOps

        from colorpro.files import MAX_PIXELS, input_stream

        for item in self.items:
            if self.isInterruptionRequested():
                break
            try:
                with input_stream(item) as stream, Image.open(stream) as original:
                    if original.format == "MPO":
                        original.seek(0)
                    if original.width * original.height > MAX_PIXELS:
                        continue
                    width, height = original.size
                    if original.getexif().get(274, 1) in (5, 6, 7, 8):
                        width, height = height, width
                    # MPO can contain a different embedded preview; use its primary frame.
                    if original.format != "MPO":
                        original.draft("RGB", (96, 96))
                    with ImageOps.exif_transpose(original) as oriented:
                        oriented.thumbnail((72, 96))
                        with oriented.convert("RGB") as small:
                            output = io.BytesIO()
                            small.save(output, format="PNG")
                self.loaded.emit(item.key, output.getvalue(), f"{width} × {height}")
            except Exception:
                # Thumbnails are optional; processing reports actual decoding errors.
                self.loaded.emit(item.key, b"", "")
