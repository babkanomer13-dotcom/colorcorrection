import time

import pytest
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
    window = Window(
        settings=QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat)
    )
    release = dict(version="1.2.0", files=[dict(size=1024)], notes="Test release")
    monkeypatch.setattr(updates, "latest_release", lambda *args: release)
    monkeypatch.setattr(
        updates,
        "launch_installer",
        lambda *args: (_ for _ in ()).throw(AssertionError("unexpected install")),
    )
    window.show_updates()
    window.update_page.check()
    pump(
        app,
        lambda: (
            not window.update_page.running() and window.update_page.release is not None
        ),
    )
    assert window.updates.text() == "Обновления  •"
    assert window.update_page.action.isEnabled()
    assert not window.update_page.isWindow()
    assert window.pages.currentIndex() == window.UPDATES
    window.update_page.auto.setChecked(False)
    assert not window.settings.value("auto_updates", type=bool)
    window.close()


def test_network_failure_does_not_block_photo_ui(app, tmp_path, monkeypatch):
    window = Window(
        settings=QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat)
    )

    def offline(*args):
        raise ValueError("Offline")

    monkeypatch.setattr(updates, "latest_release", offline)
    window.show_updates()
    window.update_page.check()
    pump(
        app,
        lambda: (
            not window.update_page.running()
            and window.update_page.status.text() == "Offline"
        ),
    )
    assert not window.busy()
    assert window.update_page.check_button.isEnabled()
    window.close()


def test_busy_window_cannot_start_install(app, tmp_path, monkeypatch):
    window = Window(
        settings=QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat)
    )
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

    window = Window(
        settings=QSettings(str(tmp_path / "install.ini"), QSettings.IniFormat)
    )
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


def startup_check(window, monkeypatch):
    # QApplication is already using its offscreen plugin. Only bypass the
    # production guard around automatic network requests for this explicit call.
    with monkeypatch.context() as context:
        context.setattr(updates.sys, "frozen", True, raising=False)
        context.delenv("QT_QPA_PLATFORM")
        context.setattr(
            "colorpro.update_dialog.load_config", lambda: {"platform": "win10"}
        )
        window.auto_check_updates()


def test_startup_offer_background_later_and_next_launch(app, tmp_path, monkeypatch):
    import threading

    prefs = QSettings(str(tmp_path / "offer.ini"), QSettings.IniFormat)
    prefs.setValue("update_checked_at", str(int(time.time())))
    release = dict(version="9.0.0", files=[dict(size=1024)], notes="New release")
    gate = threading.Event()
    calls = []

    def fetch(*args):
        calls.append(args)
        gate.wait(5)
        return release

    monkeypatch.setattr(updates, "latest_release", fetch)
    monkeypatch.setattr(
        updates, "download_update", lambda *args: pytest.fail("Unrequested download")
    )
    monkeypatch.setattr(
        updates, "launch_installer", lambda *args: pytest.fail("Unrequested install")
    )
    window = Window(settings=prefs)
    window.show()
    original_page = window.pages.currentIndex()
    try:
        startup_check(window, monkeypatch)
        assert window.update_page.running() and not window.busy()
        assert window.update_offer.isHidden()
    finally:
        gate.set()
    pump(
        app,
        lambda: not window.update_page.running() and not window.update_offer.isHidden(),
    )
    assert "9.0.0" in window.update_offer.title.text()
    assert window.pages.currentIndex() == original_page
    window.update_offer.later.click()
    assert window.update_offer.isHidden()
    window.show_update_offer("9.0.0")
    startup_check(window, monkeypatch)
    assert window.update_offer.isHidden() and len(calls) == 1
    window.close()
    reopened = Window(settings=prefs)
    reopened.show()
    startup_check(reopened, monkeypatch)
    pump(
        app,
        lambda: (
            not reopened.update_page.running() and not reopened.update_offer.isHidden()
        ),
    )
    assert len(calls) == 2
    reopened.close()


def test_offer_update_downloads_only_after_click(app, tmp_path, monkeypatch):
    window = Window(
        settings=QSettings(str(tmp_path / "accept.ini"), QSettings.IniFormat)
    )
    window.show()
    release = dict(version="9.0.0", files=[dict(size=1024)], notes="New release")
    downloads = []
    monkeypatch.setattr(updates, "latest_release", lambda *args: release)

    def download(*args):
        downloads.append(args[0]["version"])
        return tmp_path

    monkeypatch.setattr(updates, "download_update", download)
    monkeypatch.setattr(
        updates, "launch_installer", lambda *args: pytest.fail("Unrequested install")
    )
    startup_check(window, monkeypatch)
    pump(
        app,
        lambda: (
            not window.update_page.running()
            and not window.update_offer.isHidden()
            and window.update_offer.update.isEnabled()
        ),
    )
    assert not downloads
    with monkeypatch.context() as context:
        context.setattr(updates.sys, "frozen", True, raising=False)
        # Config is not part of this UI test (a frozen executable resolves its
        # bundle through _MEIPASS, which the source test does not have).
        context.setattr(
            "colorpro.update_dialog.load_config", lambda: {"state_root": str(tmp_path)}
        )
        window.update_offer.update.click()
        pump(
            app,
            lambda: (
                not window.update_page.running()
                and window.update_page.folder is not None
            ),
        )
    assert downloads == ["9.0.0"]
    assert (
        window.pages.currentIndex() == window.UPDATES and window.update_offer.isHidden()
    )
    assert window.update_page.action.text() == "Установить и закрыть"
    assert not window.install_pending and not window.update_page.install_started
    window.close()


@pytest.mark.parametrize("outcome", ["disabled", "current", "offline"])
def test_startup_no_unwanted_offer(app, tmp_path, monkeypatch, outcome):
    window = Window(settings=QSettings(str(tmp_path / "none.ini"), QSettings.IniFormat))
    window.show()
    calls = []

    def fetch(*args):
        calls.append(args)
        if outcome == "offline":
            raise ValueError("Offline")
        return None

    monkeypatch.setattr(updates, "latest_release", fetch)
    if outcome == "disabled":
        window.update_page.auto.setChecked(False)
    startup_check(window, monkeypatch)
    pump(app, lambda: not window.update_page.running())
    assert len(calls) == (0 if outcome == "disabled" else 1)
    assert window.update_offer.isHidden() and not window.busy()
    assert window.pages.currentIndex() == window.PHOTOS
    window.close()
