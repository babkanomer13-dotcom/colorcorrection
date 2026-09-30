"""Non-blocking checks/downloads; only an explicit click starts installation."""

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QCheckBox, QDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout

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


class UpdateDialog(QDialog):
    available = Signal(str)
    idle = Signal()

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.worker = None
        self.release = self.folder = None
        self.install_started = False
        self.setWindowTitle("Обновления ColorPro")
        self.setMinimumWidth(510)
        self.setModal(True)
        layout = QVBoxLayout(self)
        self.status = QLabel("Установлена версия " + __version__)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.notes = QLabel(
            "Обработка локальная. В GitHub отправляется только запрос о выпуске, без фотографий."
        )
        self.notes.setTextFormat(Qt.TextFormat.PlainText)
        self.notes.setWordWrap(True)
        layout.addWidget(self.notes)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        layout.addWidget(self.bar)
        self.auto = QCheckBox("Проверять при запуске, не чаще раза в сутки")
        self.auto.setChecked(str(owner.settings.value("auto_updates", "true")).lower() == "true")
        self.auto.toggled.connect(lambda value: owner.settings.setValue("auto_updates", value))
        layout.addWidget(self.auto)
        self.check_button = QPushButton("Проверить обновления")
        self.check_button.clicked.connect(lambda: self.check())
        layout.addWidget(self.check_button)
        self.action = QPushButton("Скачать обновление")
        self.action.setEnabled(False)
        self.action.clicked.connect(self.download_or_install)
        layout.addWidget(self.action)
        self.cancel = QPushButton("Закрыть")
        self.cancel.clicked.connect(self.reject)
        layout.addWidget(self.cancel)

    def running(self):
        return self.worker is not None and self.worker.isRunning()

    def run_task(self, operation, receiver):
        if self.running():
            return
        self.check_button.setEnabled(False)
        self.action.setEnabled(False)
        self.worker = UpdateWorker(operation)
        self.worker.result.connect(receiver)
        self.worker.failed.connect(self.failure)
        self.worker.progress.connect(self.show_progress)
        self.worker.finished.connect(self.finished_task)
        self.worker.start()

    def finished_task(self):
        self.check_button.setEnabled(True)
        self.action.setEnabled(self.release is not None and not self.install_started)
        self.idle.emit()
        if self.install_started:
            self.hide()
            self.owner.close()

    def check(self):
        if self.running():
            return
        self.release = self.folder = None
        self.action.setText("Скачать обновление")
        self.status.setText("Проверяем GitHub Releases…")
        platform = load_config().get("platform", "win10")
        self.run_task(lambda worker: updates.latest_release(__version__, platform), self.checked)

    def checked(self, release):
        import time

        self.owner.settings.setValue("update_checked_at", str(int(time.time())))
        self.release = release
        if release is None:
            self.status.setText("Установлена актуальная версия " + __version__)
            return
        size = sum(row["size"] for row in release["files"]) / 1024**2
        self.status.setText("Доступна ColorPro {} · {:.0f} МБ".format(release["version"], size))
        self.notes.setText(
            release["notes"] or "Обновление приложения. Настройки и фотографии сохраняются."
        )
        self.available.emit(release["version"])
        if not getattr(sys, "frozen", False):
            self.notes.setText(
                "Это запуск из исходников. Установите новую сборку с GitHub Releases; "
                "исходный код автоматически не заменяется."
            )

    def failure(self, message):
        self.bar.setRange(0, 100)
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
        self.action.setText("Закрыть ColorPro и установить")

    def installing(self, pid):
        self.install_started = True

    def reject(self):
        if self.running():
            self.worker.requestInterruption()
            self.status.setText("Завершаем сетевой запрос…")
            return
        super().reject()

    def closeEvent(self, event):
        if self.running():
            self.worker.requestInterruption()
            event.ignore()
        else:
            event.accept()
