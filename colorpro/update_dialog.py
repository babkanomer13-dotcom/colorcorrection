"""Non-blocking checks/downloads; only an explicit click starts installation."""

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from colorpro import __version__, updates
from colorpro.config import load_config


class UpdateWorker(QThread):
    result = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, operation):
        super().__init__()
        self.operation = operation

    def run(self):
        try:
            self.result.emit(self.operation(self))
        except updates.Cancelled:
            self.failed.emit("Загрузка отменена. Уже скачанные части сохранены.")
        except Exception as error:
            self.failed.emit(str(error))


class UpdatePage(QWidget):
    available = Signal(str)
    idle = Signal()

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.worker = None
        self.release = self.folder = None
        self.install_started = False
        self.setObjectName("page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 30, 36, 30)
        layout.setSpacing(20)
        title = QLabel("Обновления")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        subtitle = QLabel("Новые возможности — в привычном приложении.")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        card = QFrame()
        card.setObjectName("card")
        content = QVBoxLayout(card)
        content.setContentsMargins(26, 26, 26, 26)
        content.setSpacing(18)
        current = QLabel("УСТАНОВЛЕННАЯ ВЕРСИЯ")
        current.setObjectName("eyebrow")
        content.addWidget(current)
        version = QLabel("ColorPro " + __version__)
        version.setObjectName("title")
        content.addWidget(version)
        self.status = QLabel("Проверьте, доступна ли новая версия.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        content.addWidget(self.status)
        self.notes = QLabel("")
        self.notes.setTextFormat(Qt.TextFormat.PlainText)
        self.notes.setWordWrap(True)
        self.notes.setObjectName("muted")
        self.notes.hide()
        content.addWidget(self.notes)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.hide()
        content.addWidget(self.bar)
        buttons = QHBoxLayout()
        self.check_button = QPushButton("Проверить обновления")
        self.check_button.clicked.connect(lambda: self.check())
        buttons.addWidget(self.check_button)
        self.action = QPushButton("Скачать и подготовить")
        self.action.setObjectName("primary")
        self.action.setEnabled(False)
        self.action.hide()
        self.action.clicked.connect(self.download_or_install)
        buttons.addWidget(self.action)
        self.cancel = QPushButton("Отменить")
        self.cancel.clicked.connect(self.cancel_task)
        self.cancel.hide()
        buttons.addWidget(self.cancel)
        buttons.addStretch()
        content.addLayout(buttons)
        layout.addWidget(card)
        self.auto = QCheckBox("Проверять обновления автоматически")
        self.auto.setChecked(str(owner.settings.value("auto_updates", "true")).lower() == "true")
        self.auto.toggled.connect(lambda value: owner.settings.setValue("auto_updates", value))
        layout.addWidget(self.auto)
        privacy = QLabel(
            "Установка начнётся только с вашего разрешения. Фотографии и настройки сохранятся."
        )
        privacy.setWordWrap(True)
        privacy.setObjectName("muted")
        layout.addWidget(privacy)
        layout.addStretch()
        for control in (self.check_button, self.action, self.cancel, self.auto):
            control.setCursor(Qt.CursorShape.PointingHandCursor)

    def running(self):
        return self.worker is not None and self.worker.isRunning()

    def run_task(self, operation, receiver):
        if self.running():
            return
        self.check_button.setEnabled(False)
        self.action.setEnabled(False)
        self.cancel.setVisible(not self.owner.install_pending)
        self.cancel.setEnabled(True)
        self.worker = UpdateWorker(operation)
        self.worker.result.connect(receiver)
        self.worker.failed.connect(self.failure)
        self.worker.progress.connect(self.show_progress)
        self.worker.finished.connect(self.finished_task)
        self.worker.start()

    def finished_task(self):
        self.cancel.hide()
        self.check_button.setEnabled(True)
        self.action.setEnabled(self.release is not None and not self.install_started)
        if self.install_started:
            self.owner.install_pending = False
            self.owner.close()
        else:
            self.idle.emit()

    def check(self):
        if self.running():
            return
        self.release = self.folder = None
        self.action.setText("Скачать и подготовить")
        self.action.hide()
        self.notes.hide()
        self.bar.setRange(0, 0)
        self.bar.show()
        self.status.setText("Проверяем обновления…")
        platform = load_config().get("platform", "win10")
        self.run_task(lambda worker: updates.latest_release(__version__, platform), self.checked)

    def checked(self, release):
        import time

        self.owner.settings.setValue("update_checked_at", str(int(time.time())))
        self.bar.hide()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.release = release
        if release is None:
            self.status.setText("Установлена актуальная версия " + __version__)
            return
        size = sum(row["size"] for row in release["files"]) / 1024**2
        self.status.setText("Доступна ColorPro {} · {:.1f} МБ".format(release["version"], size))
        self.notes.setText(
            release["notes"] or "Обновление приложения. Настройки и фотографии сохраняются."
        )
        self.notes.show()
        if release.get("kind") == "compact":
            self.notes.setText(
                "Обновятся только изменённые файлы приложения. "
                "Библиотеки и модель заново не скачиваются.\n\n" + self.notes.text()
            )
        self.action.show()
        self.available.emit(release["version"])
        if not getattr(sys, "frozen", False):
            self.notes.setText(
                "Это запуск из исходников. Установите новую сборку с GitHub Releases; "
                "исходный код автоматически не заменяется."
            )

    def failure(self, message):
        if self.owner.install_pending and not self.install_started:
            self.owner.install_pending = False
            self.owner.set_busy(False)
        self.bar.setRange(0, 100)
        self.bar.hide()
        self.status.setText(message)

    def show_progress(self, done, total):
        # Signal values are MiB to remain within Qt's signed 32-bit int.
        self.bar.setValue(int(100 * done / max(total, 1)))
        self.status.setText(f"Загружено {done} из {total} МБ")

    def download_or_install(self):
        if self.running() or not self.release:
            return
        if not getattr(sys, "frozen", False):
            self.failure("Автоустановка доступна только в установленном ColorPro, не в исходниках.")
            return
        if self.folder is None:
            self.bar.setRange(0, 100)
            self.bar.setValue(0)
            self.bar.show()
            cache = Path(load_config()["state_root"]) / "updates"
            self.run_task(
                lambda worker: updates.download_update(
                    self.release,
                    cache,
                    lambda a, b: worker.progress.emit(a // 1024**2, max(1, b // 1024**2)),
                    worker.isInterruptionRequested,
                ),
                self.downloaded,
            )
        else:
            if self.owner.busy() or (
                self.owner.preview_loader and self.owner.preview_loader.isRunning()
            ):
                self.failure("Дождитесь завершения обработки и загрузки превью перед установкой.")
                return
            self.status.setText("Повторная проверка файлов перед установкой…")
            self.owner.install_pending = True
            self.owner.set_busy(True)
            self.run_task(
                lambda worker: updates.launch_installer(self.release, self.folder).pid,
                self.installing,
            )

    def downloaded(self, folder):
        self.folder = folder
        self.bar.setValue(100)
        self.status.setText(
            "Загрузка проверена. Установка закроет ColorPro. "
            "После установки запустите его с ярлыка."
        )
        self.action.setText("Установить и закрыть")

    def installing(self, pid):
        self.install_started = True
        self.owner.close_requested = True

    def cancel_task(self):
        if self.running():
            self.worker.requestInterruption()
            self.cancel.setEnabled(False)
            self.status.setText("Завершаем сетевой запрос…")
