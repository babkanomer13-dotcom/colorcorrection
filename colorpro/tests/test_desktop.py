import threading
import time
import zipfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageCms, JpegImagePlugin
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest

from colorpro.batch import Control, run_batch
from colorpro.files import collect_inputs, read_image, save_result
from colorpro.safety import validate_output_parent


@pytest.fixture
def photo(tmp_path):
    pixels = np.random.default_rng(8).integers(0, 255, (80, 100, 3), dtype=np.uint8)
    path = tmp_path / "Фото с пробелом.png"
    Image.fromarray(pixels).save(path)
    return path, pixels


class FakeEngine:
    device_name = "test"
    weight_sha256 = "synthetic"
    recipe_sha256 = "synthetic"
    closed = False

    def __init__(self, *args):
        pass

    def process(self, pixels):
        return pixels.copy(), dict(status="corrected", corrected_faces=0, faces=[])

    def close(self):
        self.closed = True


def test_files_roundtrip(photo, tmp_path):
    path, pixels = photo
    items, errors = collect_inputs([path, path])
    assert len(items) == 1 and not errors
    actual, metadata, digest = read_image(items[0])
    assert np.array_equal(actual, pixels) and len(digest) == 64
    output = tmp_path / "out.png"
    save_result(output, actual, metadata, "PNG")
    with Image.open(output) as image:
        assert np.array_equal(np.asarray(image), pixels)
        assert image.getexif()[274] == 1
        assert image.info["icc_profile"]
    with pytest.raises(FileExistsError):
        save_result(output, actual, metadata, "PNG")
    jpeg = tmp_path / "out.jpg"
    save_result(jpeg, actual, metadata, "JPEG")
    with Image.open(jpeg) as encoded:
        assert encoded.size == (100, 80)
        assert JpegImagePlugin.get_sampling(encoded) == 0  # Full 4:4:4, no colour downsampling.
        assert all(v == 1 for table in encoded.quantization.values() for v in table)
        assert encoded.info["icc_profile"] == metadata["icc_profile"]


def test_exif_rotate_and_icc(tmp_path):
    image = Image.fromarray(np.zeros((40, 60, 3), dtype=np.uint8))
    exif = Image.Exif()
    exif[274] = 6
    exif[271] = "Synthetic"
    path = tmp_path / "rotated.jpg"
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    image.save(path, exif=exif, icc_profile=profile)
    item = collect_inputs([path])[0][0]
    pixels, meta, _ = read_image(item)
    assert pixels.shape == (60, 40, 3)
    result = Image.Exif()
    result.load(meta["exif"])
    assert result[274] == 1 and result[40962] == 40 and result[40963] == 60
    assert result[271] == "Synthetic"


def test_dpi_and_existing_partial_preserved(photo, tmp_path):
    path, pixels = photo
    Image.fromarray(pixels).save(path, dpi=(300, 300))
    item = collect_inputs([path])[0][0]
    source, metadata, _ = read_image(item)
    assert abs(metadata["dpi"][0] - 300) < 0.01
    output = tmp_path / "output.png"
    partial = tmp_path / "output.png.partial"
    partial.write_bytes(b"previous work")
    with pytest.raises(FileExistsError):
        save_result(output, source, metadata, "PNG")
    assert partial.read_bytes() == b"previous work"
    assert not output.exists()


@pytest.mark.parametrize("mode", ["RGBA", "I;16", "CMYK"])
def test_unsupported_modes(tmp_path, mode):
    path = tmp_path / ("invalid.tiff" if mode in {"CMYK", "I;16"} else "invalid.png")
    Image.new(mode, (20, 20)).save(path)
    item = collect_inputs([path])[0][0]
    with pytest.raises(ValueError):
        read_image(item)


def test_bad_icc_rejected(tmp_path):
    path = tmp_path / "invalid.png"
    Image.new("RGB", (10, 10)).save(path, icc_profile=b"not a profile")
    with pytest.raises(ValueError):
        read_image(collect_inputs([path])[0][0])


def test_camera_mpo_primary_frame(tmp_path):
    path = tmp_path / "camera.jpg"
    first = Image.new("RGB", (60, 40), (80, 120, 160))
    second = Image.new("RGB", (60, 40), (5, 6, 7))
    first.save(path, format="MPO", save_all=True, append_images=[second])
    with Image.open(path) as original:
        assert original.n_frames == 2
        expected = np.array(original.convert("RGB"))
    pixels, meta, _ = read_image(collect_inputs([path])[0][0])
    assert np.array_equal(expected, pixels)
    assert "primary frame 0" in meta["container_note"]


def test_zip_and_traversal(photo, tmp_path):
    path, pixels = photo
    archive = tmp_path / "photos.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.write(path, "folder/photo.png")
        z.write(path, "../unsafe.png")
    items, errors = collect_inputs([archive])
    assert len(items) == 1 and len(errors) == 1
    assert np.array_equal(read_image(items[0])[0], pixels)
    assert not (tmp_path / "unsafe.png").exists()


def test_input_change_rejected(photo):
    path, _ = photo
    item = collect_inputs([path])[0][0]
    with path.open("ab") as f:
        f.write(b"changed")
    with pytest.raises(ValueError, match="изменился"):
        read_image(item)


def test_readonly_archive(tmp_path):
    archive = tmp_path / "archive"
    for value in (archive, archive / "results", archive / "sub/../result"):
        with pytest.raises(ValueError, match="защищён"):
            validate_output_parent(value, [archive])
    assert validate_output_parent(tmp_path / "safe", [archive]) == tmp_path / "safe"
    with pytest.raises(ValueError):
        validate_output_parent("relative/path", [archive])


def test_batch_report_and_unique_outputs(photo, tmp_path):
    item = collect_inputs([photo[0]])[0][0]
    events = []
    reports = [
        run_batch(
            [item], tmp_path / "out", "v39", "cuda", "PNG", Control(), events.append, FakeEngine
        )
        for _ in range(2)
    ]
    assert reports[0]["output"] != reports[1]["output"]
    for report in reports:
        assert report["state"] == "completed" and report["corrected"] == 1
        assert Path(report["output"], "report.json").is_file()
        assert report["source_files_modified"] is False
    assert any(e["type"] == "preview" for e in events)


def test_pause_cancel_and_error(photo, tmp_path):
    control = Control()
    control.resume.clear()
    results = []
    waiter = threading.Thread(target=lambda: results.append(control.wait()))
    waiter.start()
    time.sleep(0.03)
    assert waiter.is_alive()
    control.cancel()
    waiter.join(1)
    assert results == [False]
    item = collect_inputs([photo[0]])[0][0]
    report = run_batch(
        [item], tmp_path / "cancelled", "v39", "cuda", "PNG", control, lambda x: None, FakeEngine
    )
    assert report["state"] == "cancelled" and report["remaining"] == 1

    class Broken(FakeEngine):
        def process(self, pixels):
            raise ValueError("synthetic failure")

    report = run_batch(
        [item], tmp_path / "broken", "v39", "cuda", "PNG", Control(), lambda x: None, Broken
    )
    assert report["errors"] == 1 and report["corrected"] == 0


def pump(app, predicate, seconds=8):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert predicate()


def test_ui_import_process_compare_and_remove(app, photo, tmp_path):
    from colorpro.ui import Window

    window = Window(
        engine_factory=FakeEngine,
        settings=QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat),
    )
    window.show()
    assert not hasattr(window, "model")
    assert window.pages.count() == 4
    assert window.device.currentData() == "auto" and window.device.count() == 3
    assert "100%" in window.format.itemText(1)
    assert not window.start.isEnabled()
    window.import_files([str(photo[0])])
    pump(app, lambda: len(window.queue.items) == 1 and not window.busy())
    assert window.start.isEnabled()
    window.output.setText(str(tmp_path / "processed"))
    QTest.mouseClick(window.start, Qt.MouseButton.LeftButton)
    pump(app, lambda: window.last_report is not None and not window.busy())
    pump(app, lambda: window.compare.after is not None)
    assert window.last_report["corrected"] == 1
    assert window.worker.args[2] == "v39"
    for page in (1, 2, 3, 0):
        QTest.mouseClick(window.nav_buttons[page], Qt.MouseButton.LeftButton)
        app.processEvents()
        assert window.pages.currentIndex() == page
        assert len(window.queue.items) == 1 and window.compare.after is not None
    assert window.open_folder.isEnabled() and window.expand.isEnabled()
    window.preview_mode.setCurrentIndex(1)
    assert window.compare.mode == 1
    window.compare.set_zoom(2)
    assert window.compare.zoom == 2
    window.compare.reset_zoom()
    assert window.compare.zoom == 1
    output = Path(window.queue.results[0]["output"])
    QTest.mouseClick(window.remove, Qt.MouseButton.LeftButton)
    assert not window.queue.items and output.exists() and photo[0].exists()
    window.close()
    pump(app, lambda: not window.isVisible())


def test_small_window_layout(app, tmp_path):
    from colorpro.ui import Window

    window = Window(settings=QSettings(str(tmp_path / "small.ini"), QSettings.Format.IniFormat))
    window.resize(980, 640)
    window.show()
    app.processEvents()
    assert window.start.isVisible() and window.start.geometry().right() < window.width()
    assert not window.output.isVisible()
    window.show_page(1)
    app.processEvents()
    assert window.output.isVisible()
    assert window.output.mapTo(window, window.output.rect().bottomRight()).x() < window.width()
    window.close()


def test_white_workspace_and_popup(app, tmp_path):
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QWidget

    from colorpro.preview import CompareDialog
    from colorpro.ui import Window

    settings = QSettings(str(tmp_path / "white.ini"), QSettings.Format.IniFormat)
    settings.setValue("device", "cuda")  # Old machine-specific setting is not reused.
    window = Window(settings=settings)
    window.show()
    app.processEvents()
    assert window.device.currentData() == "auto"
    body = window.findChild(QWidget, "body")
    assert body.grab().toImage().pixelColor(1, 1) == QColor("white")
    assert window.compare.grab().toImage().pixelColor(10, 50) == QColor("white")
    window.show_page(1)
    app.processEvents()
    for combo in (window.device, window.format):
        combo.showPopup()
        app.processEvents()
        palette = combo.view().palette()
        assert palette.color(QPalette.ColorRole.Text) == QColor("#242424")
        assert palette.color(QPalette.ColorRole.Base) == QColor("white")
        assert palette.color(QPalette.ColorRole.HighlightedText) == QColor("white")
        combo.hidePopup()
    dialog = CompareDialog(window)
    dialog.show()
    app.processEvents()
    assert dialog.grab().toImage().pixelColor(1, 1) == QColor("white")
    assert dialog.view.grab().toImage().pixelColor(10, 50) == QColor("white")
    dialog.close()
    window.close()


def test_settings_persist_and_dropdown_keyboard(app, tmp_path):
    from colorpro.ui import Window

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = Window(settings=settings)
    window.show()
    window.show_page(1)
    window.device.setFocus()
    QTest.keyClick(window.device, Qt.Key.Key_End)
    assert window.device.currentData() == "cpu"
    assert settings.value("device_mode") == "cpu"
    window.format.setCurrentIndex(1)
    assert settings.value("format") == "JPEG"
    window.output.setText(str(tmp_path / "new-output"))
    window.output.editingFinished.emit()
    window.close()
    reopened = Window(settings=settings)
    assert reopened.device.currentData() == "cpu"
    assert reopened.format.currentData() == "JPEG"
    assert reopened.output.text() == str(tmp_path / "new-output")
    reopened.close()


def test_processing_survives_navigation(app, photo, tmp_path):
    from colorpro.ui import Window

    release = threading.Event()
    entered = threading.Event()

    class WaitingEngine(FakeEngine):
        def process(self, pixels):
            entered.set()
            assert release.wait(5)
            return super().process(pixels)

    window = Window(
        engine_factory=WaitingEngine,
        settings=QSettings(str(tmp_path / "nav.ini"), QSettings.Format.IniFormat),
    )
    window.show()
    window.output.setText(str(tmp_path / "processed"))
    window.import_files([str(photo[0])])
    pump(app, lambda: len(window.queue.items) == 1 and not window.busy())
    window.start_batch()
    try:
        pump(app, entered.is_set)
        for index in (1, 2, 3, 0):
            QTest.mouseClick(window.nav_buttons[index], Qt.MouseButton.LeftButton)
            assert window.pages.currentIndex() == index
            assert window.busy() and not window.device.isEnabled()
            assert len(window.queue.items) == 1
    finally:
        release.set()
        pump(app, lambda: not window.busy() and window.last_report is not None)
    assert window.last_report["corrected"] == 1
    window.close()
    pump(app, lambda: not window.isVisible())


def test_kernel_lock_release(tmp_path):
    from colorpro.engine import BatchLease

    path = tmp_path / "batch.lock"
    one = BatchLease(path)
    with pytest.raises(RuntimeError, match="пачка"):
        BatchLease(path)
    one.close()
    two = BatchLease(path)
    two.close()
