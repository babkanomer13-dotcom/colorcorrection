"""Sharpness during the gesture, not merely after a delayed refinement."""

import threading

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import QPointF, QSettings
from PySide6.QtGui import QPixmap

from colorpro.editor_render import (
    PreviewCancelled,
    PreviewRenderer,
    apply_rgb_lut,
    rgb_image,
)
from colorpro.files import collect_inputs
from colorpro.preview import CompareView
from colorpro.tests.test_editor_persistence import begin, pump, snapshot
from colorpro.ui import Window


def test_parameters_open_on_first_photo_and_keep_manual_hide(app, tmp_path):
    settings = QSettings(str(tmp_path / "panel.ini"), QSettings.Format.IniFormat)
    settings.setValue("auto_update", False)
    owner = Window(settings=settings)
    owner.show()
    for index in range(2):
        path = tmp_path / (str(index) + ".png")
        Image.new("RGB", (120, 160), (70, 100, 130)).save(path)
        result = tmp_path / (str(index) + "_СС.png")
        result.write_bytes(path.read_bytes())
        owner.queue.add(collect_inputs([path])[0])
        owner.queue.update(index, {"status": "corrected", "output": str(result)})
    owner.open_comparison()
    editor = owner.review.editor
    try:
        pump(
            app,
            lambda: (
                editor.active and editor.session is not None and not editor.running()
            ),
        )
        assert editor.isVisible() and owner.review.panel_toggle.isChecked()
        assert editor.levels_section.body.isVisible()
        assert not editor.export_dirty() and not editor.history
        owner.select_photo(1)
        pump(
            app,
            lambda: (
                editor.index == 1
                and editor.session is not None
                and not editor.running()
            ),
        )
        assert editor.isVisible() and not editor.export_dirty()
        owner.review.panel_toggle.click()
        owner.select_photo(0)
        pump(
            app,
            lambda: (
                editor.index == 0
                and editor.session is not None
                and not editor.running()
            ),
        )
        assert not editor.isVisible() and not owner.review.panel_toggle.isChecked()
    finally:
        owner.close()
        pump(app, lambda: not owner.isVisible())
    reopened = Window(settings=settings)
    reopened.show()
    try:
        pump(app, lambda: bool(reopened.queue.items))
        reopened.open_comparison()
        pump(app, lambda: reopened.compare.before is not None)
        assert not reopened.review.panel_toggle.isChecked()
        assert not reopened.review.editor.isVisible()
    finally:
        reopened.close()
        pump(app, lambda: not reopened.isVisible())


def test_default_panel_does_not_edit_unprocessed_photo_or_hidden_page(app, tmp_path):
    settings = QSettings(str(tmp_path / "panel.ini"), QSettings.Format.IniFormat)
    settings.setValue("auto_update", False)
    owner = Window(settings=settings)
    path = tmp_path / "source.png"
    Image.new("RGB", (120, 160), "gray").save(path)
    result = tmp_path / "source_СС.png"
    result.write_bytes(path.read_bytes())
    owner.queue.add(collect_inputs([path])[0])
    owner.show()
    owner.open_comparison()
    try:
        pump(
            app,
            lambda: (
                owner.compare.before is not None
                and not owner.preview_loader.isRunning()
            ),
        )
        assert not owner.review.editor.active
        owner.queue.update(0, {"status": "corrected", "output": str(result)})
        owner.selection_changed()
        owner.show_page(owner.PHOTOS)
        pump(app, lambda: not owner.preview_loader.isRunning())
        app.processEvents()
        assert not owner.review.editor.active
        owner.open_comparison()
        pump(
            app,
            lambda: (
                owner.review.editor.active and owner.review.editor.session is not None
            ),
        )
        assert owner.review.editor.isVisible()
    finally:
        owner.close()
        pump(app, lambda: not owner.isVisible())


@pytest.fixture
def large_editor(app, tmp_path):
    y, x = np.mgrid[:1200, :1800]
    pixels = np.stack(
        [(x % 2) * 160 + 30, (y % 2) * 120 + 50, (x * 17 + y * 23) % 256], axis=2
    ).astype(np.uint8)
    source, base = tmp_path / "source.png", tmp_path / "base.png"
    Image.fromarray(pixels).save(source)
    Image.fromarray(pixels).save(base)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("auto_update", False)
    owner = Window(settings=settings)
    owner.errors = []
    owner.error = owner.errors.append
    owner.queue.add(collect_inputs([source])[0])
    owner.queue.update(
        0, {"status": "corrected", "output": str(base), "base_output": str(base)}
    )
    owner.show()
    owner.open_comparison()
    owner.select_photo(0)
    editor = begin(app, owner)
    owner.compare.actual_size()
    pump(app, lambda: owner.compare.high_detail and editor.preview_idle())
    yield owner, editor
    owner.close()
    pump(app, lambda: not owner.isVisible())
    assert not owner.errors


def test_brightness_drag_keeps_native_detail_until_new_pixels_ready(
    app, large_editor, monkeypatch
):
    owner, editor = large_editor
    view = owner.compare
    previous = view.after_detail
    entered, release = threading.Event(), threading.Event()
    render = editor.preview_renderer.render

    def delayed(*args):
        entered.set()
        assert release.wait(8)
        return render(*args)

    monkeypatch.setattr(editor.preview_renderer, "render", delayed)
    slider = editor.tone_controls["brightness"][1]
    slider.sliderPressed.emit()
    try:
        slider.setValue(30)
        assert view.after_detail is previous  # Never flash the 640 px overview.
        pump(app, entered.is_set)
        assert view.after_detail is previous
        release.set()
        pump(app, editor.preview_idle)
        assert editor.group_change  # Still dragging; no release/refinement needed.
        region, shown = view.after_detail
        x0, y0, x1, y1 = region
        expected = editor.session.render(editor.snapshot())[y0:y1, x0:x1]
        assert shown.size().width() == x1 - x0
        assert shown.size().height() == y1 - y0
        assert shown.toImage() == QPixmap.fromImage(rgb_image(expected)).toImage()
    finally:
        release.set()
        slider.sliderReleased.emit()


@pytest.mark.parametrize("mode", [0, 1, 2])
def test_every_frame_of_brightness_gesture_keeps_native_pixels(app, large_editor, mode):
    owner, editor = large_editor
    owner.compare.set_mode(mode)
    owner.compare.actual_size()
    pump(app, editor.preview_idle)
    slider = editor.tone_controls["brightness"][1]
    slider.sliderPressed.emit()
    for brightness in (-30, 25, -10, 40):
        slider.setValue(brightness)
        pump(app, editor.preview_idle)
        assert editor.group_change
        region, frame = owner.compare.after_detail
        x0, y0, x1, y1 = region
        expected = editor.session.render(editor.snapshot())[y0:y1, x0:x1]
        assert frame.toImage() == QPixmap.fromImage(rgb_image(expected)).toImage()
    current = owner.compare.after_detail[1].cacheKey()
    slider.sliderReleased.emit()
    app.processEvents()
    assert not editor.preview_running() and editor.preview_idle()
    assert owner.compare.after_detail[1].cacheKey() == current


def test_viewport_input_is_cached_at_display_resolution(app, monkeypatch):
    pixels = np.zeros((2000, 3000, 3), dtype=np.uint8)
    view = CompareView()
    view.resize(1800, 1200)
    view.set_pixmaps(QPixmap.fromImage(rgb_image(pixels[::4, ::4])), None)
    view.native_size = (3000, 2000)
    view.set_mode(2)
    monkeypatch.setattr(view, "devicePixelRatioF", lambda: 1.5)
    region, size = view.preview_spec(pixels.shape)
    assert region == (0, 0, 3000, 2000) and max(size) > 1200
    assert size[0] >= round(view.drawn_size()[0] * 1.5)
    renderer = PreviewRenderer()
    first = renderer.viewport(pixels, region, size)
    for brightness in (-10, 10, 30):
        settings = snapshot()
        settings[1]["brightness"] = brightness
        assert renderer.viewport(pixels, region, size) is first
        frame = renderer.render(first, settings, True)
        assert (frame.width(), frame.height()) == size
    view.set_zoom(3)
    view.center = QPointF(0.6, 0.4)
    next_region, next_size = view.preview_spec(pixels.shape)
    second = renderer.viewport(pixels, next_region, next_size)
    assert second is not first and second.shape[1::-1] == next_size
    with pytest.raises(PreviewCancelled):
        renderer.viewport(pixels, region, size, lambda: True)


def test_accelerated_preview_lut_matches_original_rgb_operator():
    from colorcorrection.levels_operator import apply_rgb_lut as reference

    rng = np.random.default_rng(191)
    pixels = rng.integers(0, 256, (240, 400, 3), dtype=np.uint8)
    pixels[0, :256] = np.arange(256, dtype=np.uint8)[:, None]
    for _ in range(6):
        lut = rng.integers(0, 256, (3, 256), dtype=np.uint8)
        assert np.array_equal(apply_rgb_lut(pixels, lut), reference(pixels, lut))
