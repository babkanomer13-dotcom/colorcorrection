"""Real Qt input, delayed disk writes and rendered pixels, not UI-only mocks."""
# ruff: noqa: F811 -- imported pytest fixture is injected by name

import threading
import time

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt, QTimer
from PySide6.QtGui import QKeyEvent, QPixmap
from PySide6.QtTest import QTest

from colorpro.editor_render import PreviewRenderer, rgb_image
from colorpro.tests.test_editor_persistence import (  # noqa: F401
    begin,
    desktop,
    pump,
    snapshot,
)


@pytest.mark.parametrize("mode", [0, 2])
def test_hold_enter_repeat_focus_loss_and_inputs(app, desktop, mode):
    owner = desktop
    editor = begin(app, owner)
    pump(app, editor.preview_idle)
    view = owner.compare
    owner.review.mode.setCurrentIndex(mode)
    view.set_zoom(3)
    view.center = QPointF(0.4, 0.6)
    view.setFocus()
    current = editor.snapshot()
    for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
        QTest.keyPress(view, key)
        assert view.original_visible  # No processEvents/timer wait required.
        app.sendEvent(
            view, QKeyEvent(QEvent.Type.KeyPress, key, Qt.NoModifier, "", True)
        )
        app.sendEvent(
            view, QKeyEvent(QEvent.Type.KeyRelease, key, Qt.NoModifier, "", True)
        )
        assert view.original_visible
        QTest.keyRelease(view, key)
        assert not view.original_visible
    assert view.zoom == 3 and view.center == QPointF(0.4, 0.6)
    assert editor.snapshot() == current
    QTest.keyPress(view, Qt.Key.Key_Return)
    app.sendEvent(owner, QEvent(QEvent.Type.WindowDeactivate))
    assert not view.original_visible
    QTest.keyRelease(view, Qt.Key.Key_Return)
    spin = editor.controls["gamma"][0]
    spin.setFocus()
    spin.lineEdit().setText(spin.locale().toString(1.37, "f", 2))
    QTest.keyClick(spin, Qt.Key.Key_Return)
    assert editor.settings[0]["gamma"] == 1.37 and not view.original_visible
    # Key recording and ordinary text fields retain Enter too.
    owner.shortcuts.apply({"original": "F8"})
    view.setFocus()
    QTest.keyPress(view, Qt.Key.Key_F8)
    assert view.original_visible
    QTest.keyRelease(view, Qt.Key.Key_F8)
    assert not view.original_visible
    assert str(owner.settings.value("comparison_mode")) == str(mode)
    if mode == 0:
        left, right = [view.target_rect(p) for p in view.panes()]
        assert left.size() == right.size()
        assert left.top() == right.top()
        assert left.left() - view.panes()[0].left() == pytest.approx(
            right.left() - view.panes()[1].left()
        )


def test_delayed_writer_latest_snapshot_and_close_barrier(app, desktop, monkeypatch):
    owner = desktop
    editor = begin(app, owner)
    entered, release = threading.Event(), threading.Event()
    written = []
    save = owner.workspace.save_edit

    def delayed(**value):
        if not written:
            entered.set()
            assert release.wait(8)
        save(**value)
        written.append(value["current"][0][0]["gamma"])

    monkeypatch.setattr(owner.workspace, "save_edit", delayed)
    try:
        editor.controls["gamma"][0].setValue(1.1)
        editor.flush_state()
        pump(app, entered.is_set)
        for value in (1.2, 1.3, 1.4):
            editor.controls["gamma"][0].setValue(value)
            editor.flush_state()
        owner.select_photo(1)
        owner.select_photo(0)  # Returning cancels the pending departure.
        editor.controls["gamma"][0].setValue(1.6)
        editor.flush_state()
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(True))
        pump(app, lambda: bool(ticks))
        assert not written and editor.dirty and editor.save_inflight
        owner.close()
        assert owner.isVisible()
        release.set()
        pump(app, lambda: not owner.isVisible())
        assert written == [1.1, 1.6]
        state = owner.workspace.load_edit(
            owner.queue.items[0], owner.queue.results[0]["base_output"]
        )
        assert state["current"][0][0]["gamma"] == 1.6
        assert not owner.errors
    finally:
        release.set()
        pump(app, editor.state_idle)


def test_continuous_drag_renders_before_release(app, desktop):
    editor = begin(app, desktop)
    pump(app, editor.preview_idle)
    slider = editor.hsl_controls["saturation"][1]
    slider.sliderPressed.emit()
    keys = set()
    started = time.monotonic()
    value = -40
    while time.monotonic() - started < 0.6:
        slider.setValue(value)
        value = value + 1 if value < 40 else -40
        app.processEvents()
        if desktop.compare.after:
            keys.add(desktop.compare.after.cacheKey())
        time.sleep(0.008)
    assert len(keys) >= 4  # A trailing debounce would present no drag frames.
    slider.setValue(27)
    slider.sliderReleased.emit()
    pump(app, editor.preview_idle)
    expected = QPixmap.fromImage(rgb_image(editor.session.render(editor.snapshot())))
    assert desktop.compare.after.toImage() == expected.toImage()
    assert len(editor.history) == 1


def test_undo_during_disk_write_autosaves_without_navigation(app, desktop, monkeypatch):
    owner = desktop
    editor = begin(app, owner)
    editor.flush_state()
    pump(app, editor.state_idle)
    save = owner.workspace.save_edit
    entered, release = threading.Event(), threading.Event()

    def delayed(**value):
        entered.set()
        assert release.wait(8)
        save(**value)

    monkeypatch.setattr(owner.workspace, "save_edit", delayed)
    try:
        editor.change("gamma", 130)
        editor.flush_state()
        pump(app, entered.is_set)
        editor.undo_edit()  # Back to the already-saved pixels, but new history.
        release.set()
        pump(app, lambda: editor.state_idle() and not editor.autosave.isActive())
        state = owner.workspace.load_edit(owner.queue.items[0], editor.session.path)
        assert state["current"][0][0]["gamma"] == 1
        assert state["future"][0][0][0]["gamma"] == 1.3
    finally:
        release.set()
        pump(app, editor.state_idle)


def test_refined_native_view_matches_full_export(app, desktop):
    editor = begin(app, desktop)
    editor.change("gamma", 120)
    editor.change_tone("brightness", 13)
    editor.change_balance(1, -10)
    editor.change_hsl("saturation", 30)
    view = desktop.compare
    view.actual_size()
    view.set_zoom(max(view.zoom, 4))
    pump(app, lambda: view.high_detail and editor.preview_idle())
    region, pixmap = view.after_detail
    x0, y0, x1, y1 = region
    expected = editor.session.render(editor.snapshot())[y0:y1, x0:x1]
    assert pixmap.toImage() == QPixmap.fromImage(rgb_image(expected)).toImage()
    assert (x1 - x0) * (y1 - y0) < editor.session.pixels.shape[
        0
    ] * editor.session.pixels.shape[1]


def test_preview_hsl_change_reuses_lut_without_changing_math(monkeypatch):
    import colorpro.editor_render as module
    from colorpro.manual_hsl import apply_hsl
    from colorpro.manual_tone import combined_lut

    pixels = np.random.default_rng(82).integers(0, 256, (160, 240, 3), dtype=np.uint8)
    render = PreviewRenderer()
    first = snapshot(1.2)
    second = snapshot(1.2)
    second[2]["saturation"] = 25
    apply = module.apply_rgb_lut
    calls = []

    def counted(*args):
        calls.append(True)
        return apply(*args)

    monkeypatch.setattr(module, "apply_rgb_lut", counted)
    render.render(pixels, first, True)
    actual = render.render(pixels, second, True)
    expected = apply_hsl(
        apply(pixels, combined_lut(second[0], second[1], second[3])), second[2]
    )
    assert len(calls) == 1 and actual == rgb_image(expected)
