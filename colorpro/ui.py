"""Native desktop UI; all decoding and model work stays outside the GUI thread."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSettings,
    QSize,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QFontDatabase,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from colorpro import __version__
from colorpro.batch import Control, run_batch
from colorpro.files import EXTENSIONS, collect_inputs
from colorpro.preview import ComparePage, PreviewWorker
from colorpro.widgets import combo_box, navigation_icon

STATUS = {
    "queued": "В очереди",
    "running": "Обрабатывается…",
    "corrected": "Готово",
    "partial": "Частично · проверьте",
    "needs_attention": "Требует проверки",
    "error": "Ошибка",
    "cancelled": "Не обработано",
}

REASONS = {
    "face_not_found": "Лицо не найдено. Проверьте снимок вручную.",
    "some_faces_failed": "Часть лиц не обработана. Проверьте результат.",
    "all_faces_failed": "Лица найдены, но обработать их не удалось.",
    "no_pixel_changes": "Изменений нет: сохранён исходный вид фотографии.",
}

STYLE = """
QWidget { font-family: 'Segoe UI'; font-size: 13px; color: #303030; }
QMainWindow, #body, #page, QStackedWidget { background: #ffffff; }
#sidebar { background: #251d29; border: 0; }
#sidebar QLabel { color: #fff5fb; background: transparent; }
#sidebar QLabel[muted='true'] { color: #c9b5c7; }
#brand { font-size: 26px; font-weight: 700; letter-spacing: -1px; }
#sidebar QPushButton#nav { text-align: left; padding: 13px 14px; border: 0;
    border-radius: 10px; background: transparent; color: #cfc3ce; font-size: 14px; }
#sidebar QPushButton#nav:hover { background: #352938; color: white; }
#sidebar QPushButton#nav:checked { background: #513048; color: #ffc5e1; }
#sidebar QPushButton#nav:focus { border: 1px solid #e48bb8; }
#sidebar QLabel#navStatus { color: #eaa4c7; padding: 8px 4px; font-size: 12px; }
QComboBox::drop-down { border: 0; width: 34px; }
QComboBox::down-arrow { image: none; width: 0; height: 0; }
QComboBox { background: #ffffff; border: 1px solid #dcd6dc; border-radius: 9px;
    padding: 5px 39px 5px 12px; min-height: 22px; }
QComboBox:hover { border-color: #b998ac; background: #fdfbfd; }
QComboBox:on, QComboBox:focus { border-color: #d83387; }
QComboBox:disabled { color: #aaa4aa; border-color: #ece9ec; }
QLineEdit { background: white; border: 1px solid #dcd6dc; border-radius: 9px;
    padding: 11px 12px; selection-background-color: #d83387; }
QPushButton:focus, QComboBox:focus, QLineEdit:focus { border: 2px solid #ed73ae; }
QScrollArea { border: 0; background: white; }
QSplitter::handle { background: transparent; height: 9px; }
QPushButton { background: white; border: 1px solid #dedede; border-radius: 8px;
    padding: 9px 14px; font-weight: 600; min-height: 19px; }
QPushButton:hover { background: #f6f6f6; border-color: #bdbdbd; }
QPushButton:pressed { background: #ededed; }
QPushButton:disabled { color: #a4a4a4; background: white; border-color: #e4e4e4; }
QPushButton#primary { background: #d83387; color: white; border: 0;
    font-size: 14px; padding: 12px 25px; }
QPushButton#primary:hover { background: #b9216e; }
QPushButton#primary:disabled { background: #e7bad0; color: #fff4f9; }
QPushButton#small { padding: 5px 10px; min-height: 15px; }
QLabel#title { font-size: 25px; font-weight: 700; }
QLabel#pageTitle { font-size: 30px; font-weight: 700; color: #28232b; }
QLabel#eyebrow { font-size: 11px; font-weight: 600; color: #a68195; letter-spacing: 2px; }
QLabel#section { font-size: 16px; font-weight: 600; }
QLabel#muted { color: #737373; }
QLabel#stepNumber { color: #c42b78; background: #fcecf4; border-radius: 12px;
    font-size: 16px; font-weight: 600; padding: 10px; }
QCheckBox { spacing: 10px; padding: 8px 0; }
QCheckBox::indicator { width: 18px; height: 18px; }
QLabel#badge { color: #187044; background: white; padding: 6px 10px; border-radius: 6px; }
QFrame#card { background: white; border: 1px solid #e4e4e4; border-radius: 12px; }
QFrame#drop { background: white; border: 2px dashed #d5d5d5; border-radius: 12px; }
QLabel#preview { background: white; color: #737373; border-radius: 8px; }
QTableView { border: 0; background: white; alternate-background-color: white;
    selection-background-color: #ededed; selection-color: #303030; gridline-color: #eeeeee; }
QHeaderView::section { background: white; color: #737373; padding: 10px 12px;
    border: 0; border-bottom: 1px solid #e4e4e4; font-weight: 600; }
QProgressBar { background: #ededed; border: 0; border-radius: 4px;
    min-height: 8px; max-height: 8px; }
QProgressBar::chunk { background: #d83387; border-radius: 4px; }
QToolTip { background: #322133; color: white; border: 0; padding: 8px; }
QScrollBar:vertical { background: white; width: 10px; }
QScrollBar::handle:vertical { background: #bdbdbd; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


def icon():
    pix = QPixmap(128, 128)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#d83387"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(0, 0, 128, 128, 28, 28)
    painter.setPen(QColor("white"))
    painter.setFont(QFont("Segoe UI", 62, QFont.Weight.Bold))
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "C")
    painter.end()
    return QIcon(pix)


def label(text, name=None, wrap=False):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def button(text, slot=None, name=None):
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if slot:
        widget.clicked.connect(slot)
    if name:
        widget.setObjectName(name)
    return widget


def duration(seconds):
    seconds = max(0, int(seconds))
    return (
        f"{seconds // 3600}:{seconds // 60 % 60:02}:{seconds % 60:02}"
        if seconds >= 3600
        else f"{seconds // 60}:{seconds % 60:02}"
    )


class QueueModel(QAbstractTableModel):
    headers = ["", "Фотография", "Источник", "Статус", "Лица", "Время"]

    def __init__(self):
        super().__init__()
        self.items = []
        self.results = {}

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.items)

    def columnCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.headers)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self.items[index.row()]
        record = self.results.get(index.row(), {})
        state = record.get("status", "queued")
        if role == Qt.ItemDataRole.DisplayRole:
            return [
                str(index.row() + 1),
                item.name,
                f"ZIP · {Path(item.path).name}" if item.member else "Файл",
                STATUS.get(state, state),
                str(record.get("corrected_faces", "—")),
                f"{record['seconds']:.1f} с" if "seconds" in record else "—",
            ][index.column()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return "\n".join(
                filter(None, [item.label, item.path, record.get("reason"), record.get("output")])
            )
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 3:
            return QColor(
                {
                    "corrected": "#17834e",
                    "error": "#b52836",
                    "partial": "#ac711b",
                    "needs_attention": "#ac711b",
                    "running": "#d83387",
                }.get(state, "#907a89")
            )
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in {0, 4, 5}:
            return int(Qt.AlignmentFlag.AlignCenter)

    def add(self, items):
        if items:
            first = len(self.items)
            self.beginInsertRows(QModelIndex(), first, first + len(items) - 1)
            self.items.extend(items)
            self.endInsertRows()

    def reset(self, items=None):
        self.beginResetModel()
        if items is not None:
            self.items = list(items)
        self.results.clear()
        self.endResetModel()

    def update(self, index, record):
        self.results[index] = record
        self.dataChanged.emit(self.index(index, 0), self.index(index, 5))

    def remove_rows(self, selected):
        retained = [i for i in range(len(self.items)) if i not in selected]
        items = [self.items[i] for i in retained]
        results = {
            new: dict(self.results[old], index=new)
            for new, old in enumerate(retained)
            if old in self.results
        }
        self.beginResetModel()
        self.items, self.results = items, results
        self.endResetModel()


class ImportWorker(QThread):
    result = Signal(object, object)
    failed = Signal(str)

    def __init__(self, paths, existing):
        super().__init__()
        self.paths, self.existing = paths, existing

    def run(self):
        try:
            items, errors = collect_inputs(self.paths, self.existing, self.isInterruptionRequested)
            self.result.emit(items, errors)
        except Exception as error:
            self.failed.emit(str(error))


class BatchWorker(QThread):
    event = Signal(object)
    failed = Signal(str)

    def __init__(self, items, output, model, device, fmt, engine_factory=None):
        super().__init__()
        self.args = (list(items), output, model, device, fmt)
        self.control = Control()
        self.engine_factory = engine_factory

    def run(self):
        try:
            run_batch(*self.args, self.control, self.event.emit, engine_factory=self.engine_factory)
        except Exception as error:
            self.failed.emit(str(error))


class Window(QMainWindow):
    PHOTOS, COMPARE, SETTINGS, UPDATES, HELP = range(5)

    def __init__(self, engine_factory=None, settings=None):
        super().__init__()
        self.setWindowTitle(f"ColorPro · {__version__}")
        self.setWindowIcon(icon())
        self.resize(1220, 820)
        self.setMinimumSize(980, 640)
        self.setAcceptDrops(True)
        self.engine_factory = engine_factory
        self.settings = settings if settings is not None else QSettings("ColorPro", "Desktop")
        self.worker = self.importer = None
        self.output_folder = None
        self.close_requested = False
        self.install_pending = False
        self.last_report = None
        self.queue = QueueModel()
        self.previews = {}  # Last eight previews only; large queues cannot exhaust RAM.
        self.preview_loader = None
        self.preview_pending = None
        self.preview_key = None
        self.face_record_key = None
        self.review = None
        self.review_was_maximized = False
        self.batch_preview = None
        shell = QWidget()
        outer = QHBoxLayout(shell)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.pages = QStackedWidget()
        sidebar = QFrame()
        self.navigation = sidebar
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(224)
        left = QVBoxLayout(sidebar)
        left.setContentsMargins(16, 30, 16, 22)
        left.setSpacing(8)
        left.addWidget(label("ColorPro", "brand"))
        left.addSpacing(32)
        self.nav_buttons = []
        for index, (text, kind) in enumerate(
            (
                ("Фотографии", "photos"),
                ("До / после", "compare"),
                ("Настройки", "settings"),
                ("Обновления", "updates"),
                ("Помощь", "help"),
            )
        ):
            if index == self.HELP:
                left.addStretch()
                self.nav_status = label("", "navStatus", True)
                left.addWidget(self.nav_status)
            nav = button(text, lambda checked=False, i=index: self.show_page(i), "nav")
            nav.setCheckable(True)
            nav.setAutoExclusive(True)
            nav.setIcon(navigation_icon(kind))
            nav.setIconSize(QSize(22, 22))
            left.addWidget(nav)
            self.nav_buttons.append(nav)
        self.nav_buttons[0].setChecked(True)
        self.updates = self.nav_buttons[self.UPDATES]
        foot = label(f"ColorPro {__version__}")
        foot.setProperty("muted", True)
        foot.setContentsMargins(14, 12, 0, 0)
        left.addWidget(foot)
        outer.addWidget(sidebar)

        body = QWidget()
        body.setObjectName("body")
        main = QVBoxLayout(body)
        main.setContentsMargins(24, 22, 24, 18)
        main.setSpacing(12)
        headline = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(5)
        titles.addWidget(label("Фотографии", "pageTitle"))
        headline.addLayout(titles)
        headline.addStretch()
        main.addLayout(headline)

        toolbar = QHBoxLayout()
        self.queue_title = label("Очередь пуста", "muted")
        toolbar.addWidget(self.queue_title)
        toolbar.addStretch()
        self.remove = button("Убрать", self.remove_selected, "small")
        self.remove.setToolTip("Убрать выбранные из очереди · Delete. Файлы останутся на диске.")
        self.clear = button("Очистить", self.clear_queue, "small")
        self.add = button("+ Добавить", self.pick_files)
        self.add.setToolTip("Добавить фотографии или ZIP · Ctrl+O")
        toolbar.addWidget(self.remove)
        toolbar.addWidget(self.clear)
        toolbar.addWidget(self.add)
        main.addLayout(toolbar)

        self.drop = QFrame()
        self.drop.setObjectName("drop")
        drop_layout = QVBoxLayout(self.drop)
        drop_layout.setContentsMargins(20, 12, 20, 12)
        drop_layout.setSpacing(8)
        drop_layout.addStretch()
        for text, name in [
            ("Здесь начинается новая серия", "section"),
            ("Перетащите фотографии или ZIP в это окно", "muted"),
        ]:
            item = label(text, name, True)
            item.setAlignment(Qt.AlignmentFlag.AlignCenter)
            drop_layout.addWidget(item)
        self.empty_add = button("Выбрать фотографии", self.pick_files, "primary")
        drop_layout.addWidget(self.empty_add, 0, Qt.AlignmentFlag.AlignCenter)
        drop_layout.addStretch()
        self.table = QTableView()
        self.table.setModel(self.queue)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.hideColumn(2)
        self.table.hideColumn(4)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col, width in [(0, 32), (2, 80), (3, 160), (4, 62), (5, 72)]:
            self.table.setColumnWidth(col, width)
        self.table.setMinimumHeight(100)
        self.table.selectionModel().selectionChanged.connect(self.selection_changed)
        self.table.doubleClicked.connect(self.open_comparison)
        self.table.hide()
        self.stack = QFrame()
        self.stack.setObjectName("queueCard")
        stack_layout = QVBoxLayout(self.stack)
        stack_layout.setContentsMargins(1, 1, 1, 1)
        stack_layout.addWidget(self.drop)
        stack_layout.addWidget(self.table)

        main.addWidget(self.stack, 1)
        review_row = QHBoxLayout()
        self.summary = label("", "muted")
        review_row.addWidget(self.summary)
        review_row.addStretch()
        self.expand = button("Посмотреть до / после", self.open_comparison)
        self.expand.setEnabled(False)
        review_row.addWidget(self.expand)
        self.next_attention = button("Следующий на проверку", self.select_attention, "small")
        self.next_attention.setEnabled(False)
        self.next_attention.hide()
        review_row.addWidget(self.next_attention)
        main.addLayout(review_row)

        self.stage = label("", "muted", True)
        self.stage.hide()
        main.addWidget(self.stage)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.hide()
        main.addWidget(self.progress)
        controls = QHBoxLayout()
        self.counter = label("", "muted")
        controls.addWidget(self.counter)
        controls.addStretch()
        self.open_folder = button("Результаты", self.open_results)
        self.open_folder.setEnabled(False)
        self.pause = button("Пауза", self.toggle_pause)
        self.cancel = button("Остановить", self.cancel_batch)
        self.pause.hide()
        self.cancel.hide()
        self.start = button("Обработать серию", self.start_batch, "primary")
        self.start.setEnabled(False)
        for widget in (self.open_folder, self.pause, self.cancel, self.start):
            controls.addWidget(widget)
        main.addLayout(controls)
        self.pages.addWidget(body)
        self.review = ComparePage(self)
        self.compare = self.review.view
        self.face_choice = self.review.faces
        self.preview_mode = self.review.mode
        self.preview_detail = self.review.detail
        self.open_photo = self.review.open_file
        self.pages.addWidget(self.review)
        self.pages.addWidget(self.settings_page())
        from colorpro.update_dialog import UpdatePage

        self.update_page = UpdatePage(self)
        self.pages.addWidget(self.wrap_page(self.update_page))
        self.pages.addWidget(self.help_page())
        outer.addWidget(self.pages, 1)
        self.setCentralWidget(shell)
        self.sync_review()
        QShortcut(QKeySequence("F11"), self).activated.connect(self.toggle_review_fullscreen)
        QShortcut(QKeySequence("Escape"), self).activated.connect(self.escape_page)
        for index in range(self.pages.count()):
            QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self).activated.connect(
                lambda i=index: self.show_page(i)
            )
        for sequence, callback in (("Ctrl+O", self.pick_files), ("Delete", self.remove_selected)):
            shortcut = QShortcut(
                QKeySequence(sequence), self.table if sequence == "Delete" else self
            )
            if sequence == "Delete":
                shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(callback)
        for name, widget in (
            ("device_mode", self.device),
            ("format", self.format),
        ):
            saved = widget.findData(self.settings.value(name, widget.currentData()))
            if saved >= 0:
                widget.setCurrentIndex(saved)
            widget.currentIndexChanged.connect(
                lambda index, key=name, control=widget: self.settings.setValue(
                    key, control.currentData()
                )
            )
        self.output.editingFinished.connect(
            lambda: self.settings.setValue("output", self.output.text())
        )
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        screen = self.screen().availableGeometry()
        self.resize(min(self.width(), screen.width()), min(self.height(), screen.height()))
        self.remove.setEnabled(False)
        self.clear.setEnabled(False)
        self.update_page.available.connect(lambda version: self.updates.setText("Обновления  •"))
        self.update_page.idle.connect(self.update_idle)
        QTimer.singleShot(8000, self.auto_check_updates)

    def wrap_page(self, content):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def page_layout(self, title, subtitle):
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(36, 30, 36, 30)
        layout.setSpacing(20)
        layout.addWidget(label(title, "pageTitle"))
        layout.addWidget(label(subtitle, "muted", True))
        return page, layout

    def settings_page(self):
        page, layout = self.page_layout(
            "Настройки", "Всё готово к работе. При необходимости измените параметры ниже."
        )
        processing = QFrame()
        processing.setObjectName("card")
        form = QVBoxLayout(processing)
        form.setContentsMargins(24, 22, 24, 24)
        form.setSpacing(12)
        form.addWidget(label("Обработка", "section"))
        form.addWidget(label("Устройство", "muted"))
        self.device = combo_box()
        self.device.setAccessibleName("Устройство обработки")
        self.device.addItem("Автоматически", "auto")
        self.device.addItem("Видеокарта NVIDIA", "cuda")
        self.device.addItem("Процессор", "cpu")
        self.device.setToolTip("Автовыбор NVIDIA или процессора. AMD и Intel — через процессор.")
        form.addWidget(self.device)
        form.addWidget(
            label(
                "В автоматическом режиме ColorPro сам выберет доступное устройство.", "muted", True
            )
        )
        layout.addWidget(processing)
        saving = QFrame()
        saving.setObjectName("card")
        save = QVBoxLayout(saving)
        save.setContentsMargins(24, 22, 24, 24)
        save.setSpacing(12)
        save.addWidget(label("Сохранение", "section"))
        save.addWidget(label("Формат результата", "muted"))
        self.format = combo_box()
        self.format.setAccessibleName("Формат результата")
        self.format.addItem("PNG · без потерь", "PNG")
        self.format.addItem("JPEG · качество 100%", "JPEG")
        self.format.setToolTip(
            "JPEG: качество 100%, цвет 4:4:4. Для сохранения без потерь выберите PNG."
        )
        save.addWidget(self.format)
        save.addSpacing(4)
        save.addWidget(label("Папка результатов", "muted"))
        row = QHBoxLayout()
        self.output = QLineEdit(
            str(self.settings.value("output", str(Path.home() / "Pictures" / "ColorPro")))
        )
        self.output.setAccessibleName("Папка результатов")
        row.addWidget(self.output, 1)
        self.choose_output = button("Выбрать…", self.pick_output)
        row.addWidget(self.choose_output)
        save.addLayout(row)
        save.addWidget(
            label("Каждая серия — в отдельной папке. Исходники не изменяются.", "muted", True)
        )
        layout.addWidget(saving)
        self.settings_notice = label("Параметры сохраняются автоматически.", "muted", True)
        layout.addWidget(self.settings_notice)
        layout.addStretch()
        return self.wrap_page(page)

    def help_page(self):
        page, layout = self.page_layout("Помощь", "От исходника до готовой серии — три шага.")
        for number, title, text in (
            (
                "01",
                "Добавьте фотографии",
                "Выберите файлы или перетащите их в окно. Можно добавить сразу ZIP-архив.",
            ),
            (
                "02",
                "Обработайте серию",
                "Нажмите «Обработать серию». Во время работы доступны пауза и остановка.",
            ),
            (
                "03",
                "Сравните и сохраните",
                "Откройте вкладку «До / после», чтобы сравнить фотографии. "
                "Кнопка «Результаты» откроет папку с готовыми фотографиями.",
            ),
        ):
            card = QFrame()
            card.setObjectName("card")
            row = QHBoxLayout(card)
            row.setContentsMargins(22, 22, 22, 22)
            row.setSpacing(20)
            row.addWidget(label(number, "stepNumber"), 0, Qt.AlignmentFlag.AlignTop)
            text_layout = QVBoxLayout()
            text_layout.addWidget(label(title, "section"))
            text_layout.addWidget(label(text, "muted", True))
            row.addLayout(text_layout, 1)
            layout.addWidget(card)
        layout.addWidget(
            label(
                "Поддерживаются JPEG, PNG, TIFF, WebP и BMP: "
                "8-битные изображения без прозрачности. RAW и 16-битные файлы пока недоступны.",
                "muted",
                True,
            )
        )
        layout.addWidget(
            label(
                "Фотографии обрабатываются на вашем компьютере и не отправляются в сеть.",
                "muted",
                True,
            )
        )
        layout.addStretch()
        return self.wrap_page(page)

    def show_page(self, index):
        if self.isFullScreen() and index != self.COMPARE:
            self.leave_review_fullscreen()
        self.pages.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)
        self.nav_buttons[index].setFocus(Qt.FocusReason.OtherFocusReason)
        if index == self.COMPARE:
            if self.queue.items and not self.table.selectionModel().selectedRows():
                self.table.selectRow(0)
            self.sync_review()

    def update_idle(self):
        if self.close_requested:
            self.close()

    def show_updates(self):
        self.show_page(self.UPDATES)

    def auto_check_updates(self):
        import sys
        import time

        if not getattr(sys, "frozen", False) or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            return
        if self.busy() or self.close_requested or not self.update_page.auto.isChecked():
            return
        try:
            checked = int(self.settings.value("update_checked_at", "0"))
        except (ValueError, TypeError):
            checked = 0
        if time.time() - checked >= 86400:
            self.update_page.check()

    def busy(self):
        return bool(
            self.install_pending
            or (self.worker and self.worker.isRunning())
            or (self.importer and self.importer.isRunning())
        )

    def pick_files(self):
        if self.busy():
            return
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Выберите фотографии или ZIP",
            str(self.settings.value("input", "")),
            "Фото и ZIP ("
            + " ".join("*" + e for e in sorted(EXTENSIONS | {".zip"}))
            + ");;Все файлы (*)",
        )
        if files:
            self.settings.setValue("input", str(Path(files[0]).parent))
            self.import_files(files)

    def pick_output(self):
        path = QFileDialog.getExistingDirectory(
            self, "Куда сохранять результаты", self.output.text()
        )
        if path:
            self.output.setText(path)
            self.settings.setValue("output", path)

    def import_files(self, paths):
        if self.busy():
            return
        self.show_page(0)
        self.stage.show()
        self.progress.show()
        self.stage.setText("Проверка файлов и содержимого ZIP…")
        self.progress.setRange(0, 0)
        self.set_busy(True)
        self.importer = ImportWorker(paths, list(self.queue.items))
        self.importer.result.connect(self.imported)
        self.importer.failed.connect(self.error)
        self.importer.finished.connect(self.import_finished)
        self.importer.start()

    def imported(self, items, errors):
        self.queue.add(items)
        self.update_queue()
        self.stage.setText(f"Добавлено: {len(items)}. Всего в очереди: {len(self.queue.items)}.")
        if self.queue.items and not self.table.selectionModel().selectedRows():
            self.table.selectRow(0)
        if errors:
            box = QMessageBox(self)
            box.setWindowTitle("Некоторые файлы не добавлены")
            box.setText(f"Пропущено: {len(errors)}. Остальные фотографии добавлены в очередь.")
            box.setDetailedText("\n".join(errors[:100]))
            box.exec()

    def import_finished(self):
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.set_busy(False)
        if self.close_requested:
            self.close()

    def update_queue(self):
        count = len(self.queue.items)
        self.queue_title.setText(f"В очереди: {count}" if count else "Очередь пуста")
        self.counter.setText(f"{count} фотографий" if count else "")
        self.drop.setVisible(not count)
        self.table.setVisible(bool(count))
        self.start.setEnabled(bool(count) and not self.busy())
        self.clear.setEnabled(bool(count) and not self.busy())
        self.update_summary()

    def update_summary(self):
        states = [record.get("status") for record in self.queue.results.values()]
        attention = sum(s in {"needs_attention", "partial"} for s in states)
        errors = states.count("error")
        self.summary.setText(
            f"Готово: {states.count('corrected')}  ·  Проверить: {attention}  ·  Ошибки: {errors}"
            if self.queue.items
            else ""
        )
        self.next_attention.setEnabled(bool(attention or errors))
        self.next_attention.setVisible(bool(attention or errors))
        self.sync_review()

    def select_attention(self):
        rows = self.table.selectionModel().selectedRows()
        current = rows[0].row() if rows else -1
        candidates = [
            i
            for i, record in sorted(self.queue.results.items())
            if record.get("status") in {"partial", "needs_attention", "error"}
        ]
        if candidates:
            self.table.selectRow(next((i for i in candidates if i > current), candidates[0]))
            self.show_page(self.COMPARE)

    def remove_selected(self):
        if self.busy():
            return
        selected = {i.row() for i in self.table.selectionModel().selectedRows()}
        if not selected:
            return
        self.queue.remove_rows(selected)
        self.previews.clear()
        self.reset_preview()
        self.update_queue()
        if self.queue.items:
            self.table.selectRow(min(min(selected), len(self.queue.items) - 1))

    def clear_queue(self):
        if not self.busy():
            self.queue.reset([])
            self.previews.clear()
            self.reset_preview()
            self.update_queue()
            self.stage.setText("Добавьте фотографии для новой серии.")
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.hide()
            self.stage.hide()

    def set_busy(self, active):
        for widget in (
            self.add,
            self.empty_add,
            self.remove,
            self.clear,
            self.device,
            self.format,
            self.output,
            self.choose_output,
        ):
            widget.setEnabled(not active)
        self.start.setEnabled(not active and bool(self.queue.items))
        self.clear.setEnabled(not active and bool(self.queue.items))
        self.remove.setEnabled(not active and bool(self.table.selectionModel().selectedRows()))
        self.settings_notice.setText(
            "Параметры доступны после завершения обработки."
            if active
            else "Параметры сохраняются автоматически."
        )
        self.nav_status.setText("Обработка…" if active else "")

    def start_batch(self):
        if self.busy() or not self.queue.items:
            return
        if not self.output.text().strip():
            self.error("Выберите папку для результатов")
            return
        self.settings.setValue("output", self.output.text())
        for name, widget in (
            ("device_mode", self.device),
            ("format", self.format),
        ):
            self.settings.setValue(name, widget.currentData())
        self.queue.reset()
        self.previews.clear()
        self.reset_preview()
        self.update_summary()
        self.last_report = None
        self.output_folder = None
        self.open_folder.setEnabled(False)
        self.set_busy(True)
        self.progress.setRange(0, 0)
        self.progress.show()
        self.stage.show()
        self.counter.setText(f"0 / {len(self.queue.items)}")
        self.stage.setText("Подготовка к обработке…")
        self.pause.setText("Пауза")
        self.pause.setEnabled(True)
        self.cancel.setEnabled(True)
        self.pause.show()
        self.cancel.show()
        self.start.hide()
        self.worker = BatchWorker(
            self.queue.items,
            self.output.text().strip(),
            "v39",
            self.device.currentData(),
            self.format.currentData(),
            self.engine_factory,
        )
        self.worker.event.connect(self.batch_event)
        self.worker.failed.connect(self.error)
        self.worker.finished.connect(self.worker_finished)
        self.worker.start()

    def batch_event(self, event):
        kind = event["type"]
        if kind == "folder":
            self.output_folder = event["path"]
            self.open_folder.setEnabled(True)
        elif kind == "stage":
            self.stage.setText(event["text"])
        elif kind == "ready":
            self.progress.setRange(0, len(self.queue.items))
            self.progress.setValue(0)
            self.stage.setText("Обработка фотографий…")
        elif kind == "paused":
            self.stage.setText(
                "На паузе. Нажмите «Продолжить», чтобы обработать оставшиеся снимки."
            )
        elif kind == "resumed":
            self.stage.setText("Продолжаем обработку…")
        elif kind == "start":
            self.queue.update(event["index"], {"status": "running"})
            self.stage.setText(f"{event['index'] + 1} / {len(self.queue.items)} · {event['text']}")
            self.table.scrollTo(self.queue.index(event["index"], 0))
            if not self.table.selectionModel().selectedRows():
                self.table.selectRow(event["index"])
        elif kind == "preview":
            self.batch_preview = (event["index"], event["before"], event["after"])
        elif kind == "result":
            self.queue.update(event["record"]["index"], event["record"])
            record = event["record"]
            if self.batch_preview and self.batch_preview[0] == record["index"]:
                key = (self.queue.items[record["index"]].key, record.get("output"), None)
                self.cache_preview(key, self.batch_preview[1:])
            self.batch_preview = None
            self.progress.setValue(event["done"])
            remaining = event["elapsed"] / event["done"] * (event["total"] - event["done"])
            self.counter.setText(
                f"{event['done']} / {event['total']}  ·  {event['done'] / event['total']:.0%}"
                f"  ·  ≈ {duration(remaining)} осталось"
            )
            self.nav_status.setText(f"Готово {event['done']} из {event['total']}")
            self.update_summary()
            selected = self.table.selectionModel().selectedRows()
            if selected and selected[0].row() == event["record"]["index"]:
                self.selection_changed()
            if self.worker and self.worker.control.stop.is_set():
                self.stage.setText("Остановка… Сохраняем готовые результаты и отчёт.")
            elif self.worker and not self.worker.control.resume.is_set():
                self.stage.setText("Переход на паузу… Готовые результаты сохранены.")
        elif kind == "finished":
            report = event["report"]
            self.last_report = report
            for index in range(len(self.queue.items)):
                if self.queue.results.get(index, {}).get("status", "queued") in {
                    "queued",
                    "running",
                }:
                    self.queue.update(index, {"status": "cancelled"})
            self.progress.setRange(0, len(self.queue.items))
            self.progress.setValue(report["processed"])
            title = {
                "completed": "Пачка завершена",
                "cancelled": "Остановлено",
                "failed": "Обработка остановлена с ошибкой",
            }[report["state"]]
            self.stage.setText(
                f"{title}. Готово: {report['corrected']}; проверить: {report['attention']};"
                f" ошибок: {report['errors']}; не обработано: {report['remaining']}."
            )
            self.counter.setText(
                f"{report['processed']} / {report['total']} · {duration(report['elapsed_seconds'])}"
            )
            self.update_summary()
            if report.get("error"):
                self.preview_detail.setText(report["error"])

    def worker_finished(self):
        self.pause.hide()
        self.cancel.hide()
        self.start.show()
        self.set_busy(False)
        self.selection_changed()
        if self.close_requested:
            self.close()

    def toggle_pause(self):
        if not self.worker or not self.worker.isRunning():
            return
        if self.worker.control.resume.is_set():
            self.worker.control.resume.clear()
            self.pause.setText("Продолжить")
            self.stage.setText("Пауза после текущей фотографии. Уже готовые результаты сохранены.")
        else:
            self.worker.control.resume.set()
            self.pause.setText("Пауза")
            self.stage.setText("Продолжаем обработку…")

    def cancel_batch(self):
        if self.worker and self.worker.isRunning():
            self.worker.control.cancel()
            self.cancel.setEnabled(False)
            self.pause.setEnabled(False)
            self.stage.setText(
                "Останавливаемся после текущей фотографии… Готовые результаты сохранятся."
            )

    def selection_changed(self, *args):
        selected = self.table.selectionModel().selectedRows()
        index = selected[0].row() if selected else -1
        record = self.queue.results.get(index, {})
        self.open_photo.setEnabled(bool(record.get("output")))
        self.remove.setEnabled(bool(selected) and not self.busy())
        if index < 0:
            self.reset_preview()
            return
        item = self.queue.items[index]
        self.sync_review()
        faces = [
            tuple(face["native_bbox"]) for face in record.get("faces", []) if "native_bbox" in face
        ]
        face_record_key = (item.key, record.get("output"), tuple(faces))
        if face_record_key != self.face_record_key:
            self.face_record_key = face_record_key
            self.face_choice.blockSignals(True)
            self.face_choice.clear()
            self.face_choice.addItem("Весь кадр", None)
            for number, bbox in enumerate(faces, 1):
                self.face_choice.addItem(f"Лицо {number}", bbox)
            self.face_choice.setCurrentIndex(0)
            self.face_choice.setEnabled(bool(faces))
            self.face_choice.blockSignals(False)
        bbox = self.face_choice.currentData()
        bbox = tuple(bbox) if bbox is not None else None
        reason = record.get("reason")
        detail = REASONS.get(reason, reason) or STATUS.get(record.get("status", "queued"), "")
        self.preview_detail.setText(f"{item.name} · {detail}")
        self.preview_detail.setToolTip(item.label + "\n" + str(detail))
        key = (item.key, record.get("output"), bbox)
        if key == self.preview_key and self.compare.before is not None:
            return
        self.preview_key = key
        if key in self.previews:
            before, after = self.previews[key]
            self.show_preview(before, after)
        else:
            self.compare.clear("Загрузка исходника…")
            self.expand.setEnabled(False)
            self.sync_review()
            self.preview_pending = (key, item, record.get("output"), bbox)
            self.load_preview()

    def reset_preview(self):
        self.preview_key = self.preview_pending = None
        self.face_record_key = None
        self.face_choice.blockSignals(True)
        self.face_choice.clear()
        self.face_choice.addItem("Весь кадр", None)
        self.face_choice.setEnabled(False)
        self.face_choice.blockSignals(False)
        self.expand.setEnabled(False)
        if self.preview_loader and self.preview_loader.isRunning():
            self.preview_loader.requestInterruption()
        self.compare.clear()
        self.preview_detail.setText("")
        self.open_photo.setEnabled(False)
        self.sync_review()

    def load_preview(self):
        if self.preview_loader and self.preview_loader.isRunning():
            return
        if self.preview_pending is None or self.close_requested:
            return
        self.preview_loader = PreviewWorker(*self.preview_pending)
        self.preview_pending = None
        self.preview_loader.loaded.connect(self.preview_loaded)
        self.preview_loader.finished.connect(self.preview_finished)
        self.preview_loader.start()

    def preview_finished(self):
        if self.close_requested:
            self.close()
        else:
            self.load_preview()

    def preview_loaded(self, key, before, after, error):
        if key != self.preview_key:
            return
        if before:
            self.show_preview(before, after)
            if not error:
                self.cache_preview(key, (before, after))
        else:
            self.compare.clear("Не удалось открыть снимок")
        if error:
            self.preview_detail.setText(f"Предпросмотр: {error}")
        self.sync_review()

    def cache_preview(self, key, pair):
        self.previews[key] = pair
        while len(self.previews) > 8:
            self.previews.pop(next(iter(self.previews)))

    def show_preview(self, before, after):
        self.compare.show_pair(before, after)
        self.expand.setEnabled(True)
        self.sync_review()

    def sync_review(self):
        if self.review is not None:
            self.review.sync_controls()

    def select_photo(self, index):
        if 0 <= index < len(self.queue.items):
            selected = self.table.selectionModel().selectedRows()
            if not selected or selected[0].row() != index:
                self.table.selectRow(index)

    def select_relative(self, delta):
        selected = self.table.selectionModel().selectedRows()
        self.select_photo((selected[0].row() if selected else -1) + delta)

    def open_comparison(self, *args):
        self.show_page(self.COMPARE)

    def toggle_review_fullscreen(self):
        self.open_comparison()
        if self.isFullScreen():
            self.leave_review_fullscreen()
        else:
            self.review_was_maximized = self.isMaximized()
            self.navigation.hide()
            self.review.fullscreen.setText("Вернуться · Esc")
            self.showFullScreen()

    def leave_review_fullscreen(self):
        self.navigation.show()
        self.review.fullscreen.setText("На весь экран · F11")
        self.showMaximized() if self.review_was_maximized else self.showNormal()

    def escape_page(self):
        if self.isFullScreen():
            self.leave_review_fullscreen()
        elif self.pages.currentIndex() != self.PHOTOS:
            self.show_page(self.PHOTOS)

    def open_selected(self, *args):
        selected = self.table.selectionModel().selectedRows()
        if selected:
            path = self.queue.results.get(selected[0].row(), {}).get("output")
            if path and Path(path).is_file():
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def open_results(self):
        if self.output_folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.output_folder))

    def error(self, message):
        QMessageBox.warning(self, "ColorPro", message)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self.busy():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths and not self.busy():
            self.import_files(paths)
            event.acceptProposedAction()

    def closeEvent(self, event):
        if self.update_page.running():
            self.close_requested = True
            self.update_page.worker.requestInterruption()
            event.ignore()
            return
        if self.busy():
            if not self.close_requested:
                answer = QMessageBox.question(
                    self,
                    "Остановить обработку?",
                    "Дождаться текущей фотографии, сохранить результаты и закрыть программу?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    event.ignore()
                    return
                self.close_requested = True
                self.cancel_batch()
                if self.importer and self.importer.isRunning():
                    self.importer.requestInterruption()
            event.ignore()
        else:
            if self.preview_loader and self.preview_loader.isRunning():
                self.close_requested = True
                self.preview_pending = None
                self.preview_loader.requestInterruption()
                event.ignore()
                return
            if self.isFullScreen():
                self.leave_review_fullscreen()
            self.settings.setValue("geometry", self.saveGeometry())
            event.accept()


def launch(screenshot=None):
    app = QApplication.instance() or QApplication([])
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        for name in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
            QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / name))
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setWindowIcon(icon())
    window = Window()
    if screenshot:
        window.resize(1220, 820)
    window.show()
    if screenshot:

        def capture():
            window.grab().save(str(screenshot))
            app.quit()

        QTimer.singleShot(800, capture)
    return app.exec()
