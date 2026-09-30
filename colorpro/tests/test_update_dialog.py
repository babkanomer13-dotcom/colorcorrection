import time

from PySide6.QtCore import QSettings

from colorpro.ui import Window
from colorpro.update_dialog import updates


def pump(app, predicate):
    end = time.monotonic() + 5
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("Update UI did not finish")


def test_check_is_background_and_does_not_install(app, tmp_path, monkeypatch):
    window = Window(settings=QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat))
    release = dict(version="1.2.0", files=[dict(size=1024)], notes="Test release")
    monkeypatch.setattr(updates, "latest_release", lambda *args: release)
    monkeypatch.setattr(
        updates,
        "launch_installer",
        lambda *args: (_ for _ in ()).throw(AssertionError("unexpected install")),
    )
    window.show_updates()
    pump(
        app, lambda: not window.update_dialog.running() and window.update_dialog.release is not None
    )
    assert window.updates.text() == "Обновить до 1.2.0"
    assert window.update_dialog.action.isEnabled()
    window.update_dialog.auto.setChecked(False)
    assert not window.settings.value("auto_updates", type=bool)
    window.update_dialog.reject()
    window.close()


def test_network_failure_does_not_block_photo_ui(app, tmp_path, monkeypatch):
    window = Window(settings=QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat))

    def offline(*args):
        raise ValueError("Offline")

    monkeypatch.setattr(updates, "latest_release", offline)
    window.show_updates()
    pump(
        app,
        lambda: (
            not window.update_dialog.running() and window.update_dialog.status.text() == "Offline"
        ),
    )
    assert not window.busy()
    assert window.update_dialog.check_button.isEnabled()
    window.update_dialog.reject()
    window.close()


def test_busy_window_cannot_start_install(app, tmp_path, monkeypatch):
    window = Window(settings=QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat))
    d = window.update_dialog
    d.release, d.folder = dict(version="1.2.0"), tmp_path
    monkeypatch.setattr(updates.sys, "frozen", True, raising=False)
    monkeypatch.setattr(window, "busy", lambda: True)
    d.download_or_install()
    assert "Дождитесь" in d.status.text()
    assert not d.running()
    monkeypatch.setattr(window, "busy", lambda: False)
    window.close()
