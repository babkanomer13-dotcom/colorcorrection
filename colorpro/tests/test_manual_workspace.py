import json

import pytest
from PIL import Image
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit

from colorpro.files import collect_inputs
from colorpro.shortcuts import defaults, physical_key, validate_bindings
from colorpro.ui import Window


def window(app, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("auto_update", False)
    owner = Window(settings=settings)
    owner.show()
    app.processEvents()
    return owner


def test_binding_validation():
    base = defaults()
    assert validate_bindings({}) == base
    base["save"] = ""
    assert validate_bindings(base)["save"] == ""
    for broken in (
        {"open": "Ctrl+S"},
        {"open": "Alt+F4"},
        {"open": "Ctrl+K, Ctrl+L"},
        {"open": 123},
        {"open": "Ctrl+"},
        {"unknown": "Ctrl+N"},
    ):
        with pytest.raises(ValueError):
            validate_bindings(broken)


def test_shortcut_settings_persist_and_conflicts_atomic(app, tmp_path):
    owner = window(app, tmp_path)
    try:
        panel = owner.shortcut_panel
        before = dict(owner.shortcuts.bindings)
        panel.editors["save"].setKeySequence(QKeySequence("Ctrl+O"))
        assert not panel.apply()
        assert owner.shortcuts.bindings == before
        panel.editors["save"].setKeySequence(QKeySequence("Ctrl+Shift+S"))
        assert panel.apply()
        assert (
            json.loads(owner.settings.value("shortcuts_v1"))["save"] == "Ctrl+Shift+S"
        )
        panel.search.setText("правки")
        assert any(
            panel.table.isRowHidden(row) for row in range(panel.table.rowCount())
        )
        owner.shortcuts.apply({"fullscreen": "F9"})
        assert owner.review.fullscreen.toolTip() == "F9"
        assert "F11" not in owner.review.fullscreen.text()
        panel.editors["save"].findChild(QLineEdit).clear()
        assert panel.editors["save"].keySequence().isEmpty()
        assert panel.apply()
        assert owner.shortcuts.bindings["save"] == ""
        owner.toggle_review_fullscreen()
        assert owner.review.fullscreen.text() == "Вернуться"
        owner.escape_page()
        assert owner.review.fullscreen.text() == "На весь экран"
    finally:
        owner.close()


def test_hotkeys_dont_steal_text_or_number_input(app, tmp_path):
    owner = window(app, tmp_path)
    try:
        owner.show_page(owner.SETTINGS)
        owner.output.setFocus()
        app.processEvents()
        before = owner.pages.currentIndex()
        QTest.keyClick(owner.output, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
        assert owner.pages.currentIndex() == before
        owner.output.setText("abc")
        QTest.keyClick(owner.output, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        assert owner.output.selectedText() == "abc"
        owner.show_page(owner.COMPARE)
        owner.compare.setFocus()
        QTest.keyClick(owner.compare, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
        assert owner.pages.currentIndex() == owner.SETTINGS
    finally:
        owner.close()


def test_save_hotkey_commits_focused_numeric_value(app, tmp_path, monkeypatch):
    owner = window(app, tmp_path)
    editor = owner.review.editor
    try:
        owner.show_page(owner.COMPARE)
        editor.active = True
        editor.session = object()
        editor.show()
        app.processEvents()
        spin = editor.controls["gamma"][0]
        spin.setFocus()
        spin.lineEdit().setText(spin.locale().toString(1.37, "f", 2))
        assert editor.settings[0]["gamma"] == 1
        saved = []
        # Isolate dispatch/commit from full-image I/O and histogram refresh.
        monkeypatch.setattr(editor, "refresh_controls", lambda *a: None)
        monkeypatch.setattr(
            editor, "save_result", lambda: saved.append(editor.settings[0]["gamma"])
        )
        QTest.keyClick(spin, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
        assert saved == [1.37]
    finally:
        editor.active = False
        editor.session = None
        editor.timer.stop()
        owner.close()


def test_filmstrip_models_all_queue_and_syncs_selection(app, tmp_path):
    owner = window(app, tmp_path)
    try:
        files = []
        for i in range(24):
            path = tmp_path / (f"Кадр_{i}.png")
            Image.new("RGB", (30, 40), (i * 10, 80, 100)).save(path)
            files.append(path)
        items, errors = collect_inputs(files)
        assert not errors
        owner.queue.add(items)
        owner.show_page(owner.COMPARE)
        rail = owner.review.filmstrip
        assert rail.model.rowCount() == 24
        owner.select_photo(20)
        assert rail.view.currentIndex().row() == 20
        owner.select_relative(-1)
        assert rail.view.currentIndex().row() == 19
        rail.view.setFocus()
        QTest.keyClick(rail.view, Qt.Key.Key_Down)
        assert owner.table.selectionModel().selectedRows()[0].row() == 20
        owner.select_photo(19)
        # A cache update must not snap the scroll position to the selected frame.
        rail.view.verticalScrollBar().setValue(0)
        rail.select(19)
        assert rail.view.verticalScrollBar().value() == 0
        owner.queue.reset([])
        assert rail.model.rowCount() == 0
    finally:
        # Tests use the same cooperative worker shutdown as the application.
        owner.close()

        for worker in (owner.preview_loader, owner.thumbnail_worker):
            if worker and worker.isRunning():
                worker.requestInterruption()
                worker.wait(5000)
        app.processEvents()
        owner.close()


def test_russian_layout_uses_physical_key():
    from PySide6.QtCore import QEvent

    event = QKeyEvent(
        QEvent.Type.KeyPress,
        0x0414,
        Qt.KeyboardModifier.ControlModifier,
        0,
        ord("L"),
        0,
        "д",
    )
    assert physical_key(event) == ord("L")


def test_saved_manual_result_keeps_output_and_queue_metadata(app, tmp_path):
    owner = window(app, tmp_path)
    try:
        source, result = tmp_path / "source.png", tmp_path / "source_с.png"
        Image.new("RGB", (20, 30), "gray").save(source)
        result.write_bytes(source.read_bytes())
        items, _ = collect_inputs([source])
        owner.queue.add(items)
        previous = {
            "index": 0,
            "status": "needs_attention",
            "reason": "check colour",
            "output": str(result),
            "faces": [{"id": "synthetic"}],
            "seconds": 2.5,
        }
        owner.queue.update(0, dict(previous))
        owner.last_report = {"output": str(tmp_path), "records": [dict(previous)]}
        owner.manual_result_saved(
            0, {"manual_hsl": {"hue": 5, "saturation": 0, "lightness": 0}}
        )
        saved = owner.queue.results[0]
        assert saved["status"] == "corrected" and saved["reason"] is None
        for key in ("output", "faces", "seconds", "index"):
            assert saved[key] == previous[key]
        report = json.loads((tmp_path / "report.json").read_text(encoding="utf8"))
        assert report["corrected"] == 1 and report["attention"] == 0
        assert report["records"][0] == saved
    finally:
        owner.close()


def test_undo_redo_parameters_without_pixel_mutation(app, tmp_path):
    owner = window(app, tmp_path)
    try:
        editor = owner.review.editor
        original = editor.settings[0]["gamma"]
        editor.change("gamma", 125)
        assert editor.settings[0]["gamma"] == 1.25
        editor.undo_edit()
        assert editor.settings[0]["gamma"] == original
        editor.redo_edit()
        assert editor.settings[0]["gamma"] == 1.25
        editor.reset_all()
        editor.undo_edit()
        assert editor.settings[0]["gamma"] == 1.25
        editor.change_hsl("saturation", 20)
        assert editor.hsl["saturation"] == 20
        editor.undo_edit()
        assert editor.hsl["saturation"] == 0
        editor.redo_edit()
        assert editor.hsl["saturation"] == 20
        editor.change_balance(0, 20)
        assert editor.balance["midtones"][0] == 20
        editor.balance_band.setCurrentIndex(0)
        assert editor.balance_controls[0][0].value() == 0
        editor.change_balance(2, -15)
        editor.undo_edit()
        assert editor.balance["shadows"][2] == 0
        assert editor.balance["midtones"][0] == 20
        editor.begin_gesture()
        editor.change("gamma", 130)
        editor.change("gamma", 140)
        editor.change("gamma", 150)
        editor.end_gesture()
        editor.undo_edit()
        assert editor.settings[0]["gamma"] == 1.25
    finally:
        owner.close()


def test_manual_auto_matches_original_operators():
    import numpy as np
    from colorcorrection.auto_color import auto_color
    from colorcorrection.auto_contrast import auto_contrast
    from colorcorrection.auto_tone import auto_tone
    from colorcorrection.levels_operator import apply_rgb_lut

    from colorpro.levels import levels_lut
    from colorpro.manual_auto import auto_settings

    rng = np.random.default_rng(120)
    inputs = [
        rng.integers(10, 230, (101, 151, 3), dtype=np.uint8),
        np.full((30, 50, 3), 100, dtype=np.uint8),
        np.zeros((20, 20, 3), dtype=np.uint8),
        np.full((20, 20, 3), 255, dtype=np.uint8),
    ]
    for pixels in inputs:
        for mode, original in enumerate((auto_color, auto_tone, auto_contrast)):
            assert np.array_equal(
                apply_rgb_lut(pixels, levels_lut(auto_settings(pixels, mode))),
                original(pixels),
            )


@pytest.mark.parametrize("cancel", [False, True])
def test_async_preview_latest_wins_and_cancel_discards_result(
    app, tmp_path, monkeypatch, cancel
):
    import threading
    import time
    from types import SimpleNamespace

    import numpy as np
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QPixmap

    import colorpro.levels_panel as panel_module
    from colorpro.levels import histogram
    from colorpro.manual_hsl import apply_hsl

    owner = window(app, tmp_path)
    editor = owner.review.editor
    pixels = np.random.default_rng(71).integers(0, 256, (60, 80, 3), dtype=np.uint8)
    editor.session = SimpleNamespace(preview=pixels, histogram=histogram(pixels))
    editor.active = True
    started, release = threading.Event(), threading.Event()
    encode = panel_module.preview_bytes

    def delayed(values):
        started.set()
        assert release.wait(5)
        return encode(values)

    def pump(predicate):
        deadline = time.monotonic() + 8
        while not predicate() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        assert predicate()

    monkeypatch.setattr(panel_module, "preview_bytes", delayed)
    try:
        editor.render_preview()
        pump(started.is_set)
        editor.change_hsl("saturation", 30)
        editor.render_preview()
        editor.change_hsl("saturation", -15)
        editor.render_preview()
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(True))
        pump(lambda: bool(ticks))  # UI events continue while the worker is blocked.
        expected = QPixmap()
        expected.loadFromData(encode(apply_hsl(pixels, editor.hsl)), "PNG")
        if cancel:
            editor.end()
            owner.compare.after = QPixmap(3, 4)
            expected = owner.compare.after.copy()
        release.set()
        pump(editor.preview_idle)
        assert owner.compare.after.toImage() == expected.toImage()
    finally:
        release.set()
        pump(lambda: not editor.preview_running())
        if editor.active:
            editor.end()
        owner.close()
