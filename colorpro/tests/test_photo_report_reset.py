"""Recorded decisions and undoable source reset with real encoded files."""
# ruff: noqa: F811 -- imported pytest fixture is injected by name

import json
import threading
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import QSettings
from PySide6.QtGui import QPixmap

from colorpro import exporting
from colorpro.editor_render import rgb_image
from colorpro.files import collect_inputs, read_image
from colorpro.levels import LevelsSession, uses_original
from colorpro.photo_report import TOOLS, processing_report
from colorpro.preview import PreviewWorker
from colorpro.tests.test_editor_persistence import (  # noqa: F401
    begin,
    desktop,
    photo,
    pump,
    snapshot,
)
from colorpro.ui import Window
from colorpro.workspace import Workspace, atomic_json


@pytest.mark.parametrize("tool", list(TOOLS))
def test_report_uses_recorded_tool_and_physical_levels(tool):
    record = {"decision": {"tool": tool, "levels": [7, 244, 137, 3, 250]}}
    title, detail, note = processing_report(record)
    assert title == "V39 · " + TOOLS[tool]
    assert detail == "Вход: 7–244 · Гамма: 1,37 · Выход: 3–250 · Весь кадр"
    assert not note
    assert "отключена" in processing_report(record, original=True)[2]
    assert "ручные правки исходника" in processing_report(record, True, True)[2]
    assert "Поверх" in processing_report(record, False, True)[2]


def test_missing_or_malformed_report_never_invents_parameters():
    for record in ({}, {"decision": None}, {"decision": {"tool": "unknown"}}):
        assert "не сохранены" in processing_report(record)[1]
    for levels in (None, [0, 255, 1.2, 0, 255], [0, 255, 100], [255, 0, 100, 0, 255]):
        assert (
            "недоступны"
            in processing_report(
                {"decision": {"tool": "auto_color", "levels": levels}}
            )[1]
        )
    assert "не изменили" in processing_report({"reason": "no_pixel_changes"})[2]


def ready_original(app, editor):
    pump(
        app,
        lambda: editor.use_original and not editor.running() and editor.preview_idle(),
    )


def test_reset_removes_v39_and_manual_changes_only_from_current_frame(
    app, desktop, monkeypatch
):
    owner, editor = desktop, begin(app, desktop)
    owner.queue.results[0]["decision"] = {
        "tool": "auto_color",
        "levels": [3, 245, 123, 0, 255],
    }
    owner.queue.results[1]["decision"] = {
        "tool": "auto_tone",
        "levels": [0, 250, 115, 4, 254],
    }
    before = {item.path: Path(item.path).read_bytes() for item in owner.queue.items}
    outputs = {
        i: Path(r["output"]).read_bytes() for i, r in owner.queue.results.items()
    }
    writes = []
    save = exporting.save_result
    monkeypatch.setattr(
        exporting, "save_result", lambda *a: (writes.append(str(a[0])), save(*a))[1]
    )
    pump(app, editor.preview_idle)
    app.processEvents()
    viewport = owner.compare.size()
    editor.change_tone("brightness", 25)
    pump(app, editor.preview_idle)
    assert owner.compare.size() == viewport
    edited = editor.snapshot()
    owner.review.original_button.click()
    ready_original(app, editor)
    assert owner.compare.size() == viewport
    source, _, _ = read_image(owner.queue.items[0])
    assert np.array_equal(editor.session.render(editor.snapshot()), source)
    assert owner.compare.after.toImage() == QPixmap.fromImage(rgb_image(source)).toImage()
    assert "отключена" in owner.review.report_note.text()
    assert "Автоцвет" in owner.review.report_title.text()
    assert "1,23" in owner.review.report_detail.text()
    assert not writes  # Reset obeys the same deferred save boundary as sliders.
    assert all(
        Path(owner.queue.results[i]["output"]).read_bytes() == raw
        for i, raw in outputs.items()
    )
    history_size = len(editor.history)
    owner.review.original_button.click()
    assert len(editor.history) == history_size and not editor.running()
    editor.undo_edit()
    assert editor.snapshot() == edited and not editor.use_original
    editor.redo_edit()
    assert editor.use_original
    owner.select_photo(1)
    pump(
        app,
        lambda: (
            editor.index == 1 and editor.session is not None and not editor.running()
        ),
    )
    assert len(writes) == 1 and not editor.use_original
    assert "Автотон" in owner.review.report_title.text()
    assert "отключена" not in owner.review.report_note.text()
    record = owner.queue.results[0]
    assert (
        record["edit_base"] == "original" and record["decision"]["tool"] == "auto_color"
    )
    with Image.open(record["output"]) as result:
        assert np.array_equal(np.asarray(result), source)
    assert Path(owner.queue.results[1]["output"]).read_bytes() == outputs[1]
    assert all(Path(path).read_bytes() == raw for path, raw in before.items())
    owner.select_photo(0)
    ready_original(app, editor)
    editor.save_result()
    assert len(writes) == 1  # Repeat reset / save does not encode again.


def test_reset_and_history_survive_restart_with_hidden_panel(app, desktop):
    owner, editor = desktop, begin(app, desktop)
    editor.change("gamma", 130)
    edited = editor.snapshot()
    editor.reset_original()
    ready_original(app, editor)
    editor.change_tone("brightness", 10)
    expected = editor.session.render(editor.snapshot())
    owner.review.panel_toggle.click()
    owner.close()
    pump(app, lambda: not owner.isVisible())
    restored = Window(
        settings=QSettings(owner.settings.fileName(), QSettings.Format.IniFormat)
    )
    restored.show()
    try:
        pump(app, lambda: len(restored.queue.items) == 3)
        restored.open_comparison()
        current = begin(app, restored)
        assert current.use_original and not current.isVisible()
        assert np.array_equal(current.session.render(current.snapshot()), expected)
        assert not current.export_dirty()
        current.undo_edit()
        assert current.use_original and current.tone["brightness"] == 0
        current.undo_edit()
        assert current.snapshot() == edited and not current.use_original
        current.redo_edit()
        assert current.use_original
    finally:
        restored.close()
        pump(app, lambda: not restored.isVisible())


def test_reset_load_failure_preserves_current_correction(app, desktop, monkeypatch):
    editor = begin(app, desktop)
    editor.change_tone("brightness", 23)
    state, history = editor.snapshot(), list(editor.history)

    def fail():
        raise OSError("source unavailable")

    monkeypatch.setattr(editor.session, "prepare_original", fail)
    editor.reset_original()
    pump(app, lambda: not editor.running())
    assert editor.snapshot() == state and editor.history == history
    assert "source unavailable" in desktop.errors.pop()
    assert not editor.use_original


def test_navigation_waits_for_reset_and_saves_correct_photo(app, desktop, monkeypatch):
    editor = begin(app, desktop)
    entered, release = threading.Event(), threading.Event()
    prepare = editor.session.prepare_original

    def delayed():
        entered.set()
        assert release.wait(8)
        prepare()

    monkeypatch.setattr(editor.session, "prepare_original", delayed)
    try:
        editor.reset_original()
        pump(app, entered.is_set)
        desktop.select_photo(1)
        desktop.select_photo(2)
        assert editor.index == 0
        release.set()
        pump(
            app,
            lambda: (
                editor.index == 2
                and editor.session is not None
                and not editor.running()
            ),
        )
        assert desktop.queue.results[0]["edit_base"] == "original"
        assert "edit_base" not in desktop.queue.results[1]
        assert not editor.use_original
    finally:
        release.set()
        pump(app, lambda: not editor.running())


def test_source_reset_preview_worker_and_zip_member(app, tmp_path):
    import zipfile

    source = photo(tmp_path / "input", color=(70, 90, 110))
    base = photo(tmp_path / "base", color=(100, 120, 140))
    archive = tmp_path / "photos.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.write(source.path, "folder/исходник.png")
    item = collect_inputs([archive])[0][0]
    session = LevelsSession(base.path, item)
    session.prepare_original()
    state = snapshot() + ["original"]
    state[1]["brightness"] = 10
    workspace = Workspace(tmp_path / "state")
    workspace.save_edit(item, base.path, state, [snapshot()], [], base_sha=session.sha)
    worker = PreviewWorker(item.key, item, base.path, workspace=workspace, full=True)
    captured = []
    worker.loaded.connect(lambda *args: captured.append(args))
    worker.start()
    pump(app, lambda: bool(captured) and not worker.isRunning())
    assert not captured[0][3]
    assert captured[0][2] == rgb_image(session.render(state))
    assert captured[0][1] == rgb_image(session.original_pixels)


def test_source_base_validation_and_legacy_state_compatibility(tmp_path):
    source = photo(tmp_path / "source")
    store = Workspace(tmp_path / "state")
    store.save_edit(source, source.path, snapshot(), [], [])
    assert json.loads(store.edit_path(source).read_text())["schema"] == 1
    assert not uses_original(store.load_edit(source, source.path)["current"])
    state = snapshot() + ["original"]
    store.save_edit(source, source.path, state, [snapshot()], [])
    assert json.loads(store.edit_path(source).read_text())["schema"] == 2
    assert uses_original(store.load_edit(source, source.path)["current"])
    invalid = json.loads(store.edit_path(source).read_text())
    invalid["current"][4] = "other_photo"
    atomic_json(store.edit_path(source), invalid)
    with pytest.raises(ValueError, match="Повреждены параметры"):
        store.load_edit(source, source.path)
