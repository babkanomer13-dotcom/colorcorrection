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
    window.update_page.check()
    pump(app, lambda: not window.update_page.running() and window.update_page.release is not None)
    assert window.updates.text() == "Обновления  •"
    assert window.update_page.action.isEnabled()
    assert not window.update_page.isWindow()
    assert window.pages.currentIndex() == 2
    window.update_page.auto.setChecked(False)
    assert not window.settings.value("auto_updates", type=bool)
    window.close()


def test_network_failure_does_not_block_photo_ui(app, tmp_path, monkeypatch):
    window = Window(settings=QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat))

    def offline(*args):
        raise ValueError("Offline")

    monkeypatch.setattr(updates, "latest_release", offline)
    window.show_updates()
    window.update_page.check()
    pump(
        app,
        lambda: not window.update_page.running() and window.update_page.status.text() == "Offline",
    )
    assert not window.busy()
    assert window.update_page.check_button.isEnabled()
    window.close()


def test_busy_window_cannot_start_install(app, tmp_path, monkeypatch):
    window = Window(settings=QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat))
    d = window.update_page
    d.release, d.folder = dict(version="1.2.0"), tmp_path
    monkeypatch.setattr(updates.sys, "frozen", True, raising=False)
    monkeypatch.setattr(window, "busy", lambda: True)
    d.download_or_install()
    assert "Дождитесь" in d.status.text()
    assert not d.running()
    monkeypatch.setattr(window, "busy", lambda: False)
    window.close()


def test_install_verification_blocks_new_processing(app, tmp_path, monkeypatch):
    import threading

    from PIL import Image

    from colorpro.files import collect_inputs

    window = Window(settings=QSettings(str(tmp_path / "install.ini"), QSettings.IniFormat))
    d = window.update_page
    d.release, d.folder = dict(version="9.0.0"), tmp_path
    monkeypatch.setattr(updates.sys, "frozen", True, raising=False)
    gate = threading.Event()

    def fail_install(*args):
        gate.wait(5)
        raise ValueError("Verification failed")

    monkeypatch.setattr(updates, "launch_installer", fail_install)
    photo = tmp_path / "test.png"
    Image.new("RGB", (20, 20)).save(photo)
    window.queue.add(collect_inputs([photo])[0])
    d.download_or_install()
    try:
        assert window.busy() and window.install_pending
        window.start_batch()
        window.import_files([str(photo)])
        assert window.worker is None and window.importer is None
        assert not window.start.isEnabled()
    finally:
        gate.set()
        pump(app, lambda: not d.running() and not window.install_pending)
    assert "Verification failed" in d.status.text()
    assert window.start.isEnabled()
    window.close()
