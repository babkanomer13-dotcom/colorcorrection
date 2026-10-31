"""RetushPro-style save boundaries using real encoded results and GUI workers."""

import threading
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import QSettings

from colorpro import exporting
from colorpro.batch import Control, run_batch
from colorpro.files import collect_inputs
from colorpro.levels import digest
from colorpro.tests.test_desktop import FakeEngine
from colorpro.tests.test_editor_persistence import begin, pump
from colorpro.ui import Window
from colorpro.workspace import Workspace


@pytest.fixture
def processed(app, tmp_path, monkeypatch):
    settings = QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat)
    settings.setValue("auto_update", False)
    window = Window(engine_factory=FakeEngine, settings=settings)
    window.errors = []
    window.error = window.errors.append
    sources = tmp_path / "sources"
    sources.mkdir()
    for index in range(3):
        Image.new("RGB", (80, 100), (80 + index, 120, 160)).save(
            sources / f"photo{index}.png"
        )
    window.show()
    window.import_files([str(sources)])
    pump(app, lambda: len(window.queue.items) == 3 and not window.busy())
    window.format.setCurrentIndex(window.format.findData("PNG"))
    window.start_batch()
    pump(app, lambda: window.last_report is not None and not window.busy())
    writes = []
    encode = exporting.save_result

    def track(path, *args):
        writes.append(Path(path))
        return encode(path, *args)

    monkeypatch.setattr(exporting, "save_result", track)
    window.open_comparison()
    begin(app, window)
    yield window, writes
    window.close()
    pump(app, lambda: not window.isVisible())


def select(app, window, index):
    window.select_photo(index)
    editor = window.review.editor
    pump(
        app,
        lambda: (
            editor.active
            and editor.index == index
            and editor.session is not None
            and not editor.running()
        ),
    )
    return editor


def test_only_changed_photo_is_saved_on_navigation(app, processed):
    window, writes = processed
    editor = begin(app, window)
    output = Path(window.queue.results[0]["output"])
    before = (digest(output), output.stat().st_mtime_ns)
    assert not editor.save.isEnabled()
    for step in range(20):
        editor.controls["gamma"][0].setValue(1.01 + step / 100)
        window.select_photo(0)
    editor.flush_state()
    pump(app, lambda: editor.state_idle() and editor.preview_idle())
    assert not writes and (digest(output), output.stat().st_mtime_ns) == before
    expected = editor.session.render(editor.snapshot())
    select(app, window, 1)
    assert len(writes) == 1 and digest(output) != before[0]
    with Image.open(output) as photo:
        assert np.array_equal(np.asarray(photo), expected)
    assert Path(window.queue.results[0]["output"]) == output
    editor = select(app, window, 0)
    assert editor.settings[0]["gamma"] == 1.2 and not editor.save.isEnabled()
    editor.save_result()
    select(app, window, 1)
    assert len(writes) == 1


def test_table_selection_saves_each_changed_frame_once(app, processed):
    window, writes = processed
    editor = begin(app, window)
    for current, following, gamma in [(0, 1, 130), (1, 2, 80), (2, 0, 120)]:
        editor.change("gamma", gamma)
        window.table.selectRow(following)
        pump(
            app,
            lambda following=following: (
                editor.active
                and editor.index == following
                and editor.session is not None
                and not editor.running()
            ),
        )
        assert window.queue.results[current]["manual_levels"][0]["gamma"] == gamma / 100
    assert len(writes) == 3 and editor.settings[0]["gamma"] == 1.3


def test_failed_close_keeps_photo_open_and_retries(app, processed, monkeypatch):
    window, writes = processed
    editor = begin(app, window)
    encode = exporting.save_result

    def fail(*args):
        raise PermissionError("locked result")

    editor.change("gamma", 130)
    monkeypatch.setattr(exporting, "save_result", fail)
    window.close()
    pump(
        app,
        lambda: (
            bool(window.errors) and not editor.running() and editor.departure is None
        ),
    )
    assert window.isVisible() and editor.active and editor.export_dirty()
    monkeypatch.setattr(exporting, "save_result", encode)
    window.close()
    pump(app, lambda: not window.isVisible())
    assert len(writes) == 1


def test_undo_to_saved_values_and_repeated_save_do_not_encode(app, processed):
    window, writes = processed
    editor = begin(app, window)
    editor.change("gamma", 120)
    editor.undo_edit()
    editor.save_result()
    assert not writes and not editor.export_dirty()
    editor.redo_edit()
    editor.save_result()
    pump(app, lambda: not editor.running() and not editor.export_dirty())
    for _ in range(3):
        editor.save_result()
    assert len(writes) == 1 and not editor.save.isEnabled()
    editor.undo_edit()
    select(app, window, 1)
    assert len(writes) == 2


def test_failed_photo_save_blocks_switch_then_can_retry(app, processed, monkeypatch):
    window, writes = processed
    editor = begin(app, window)
    output = Path(window.queue.results[0]["output"])
    before = digest(output)
    encode = exporting.save_result

    def fail(*args):
        raise PermissionError("disk unavailable")

    editor.change("gamma", 130)
    monkeypatch.setattr(exporting, "save_result", fail)
    window.select_photo(1)
    pump(
        app,
        lambda: (
            bool(window.errors) and not editor.running() and editor.departure is None
        ),
    )
    assert (
        editor.active and editor.index == 0 and window.table.currentIndex().row() == 0
    )
    assert editor.export_dirty() and digest(output) == before
    monkeypatch.setattr(exporting, "save_result", encode)
    select(app, window, 1)
    assert len(writes) == 1 and digest(output) != before


def test_report_warning_does_not_repeat_photo_save(app, processed, monkeypatch):
    from colorpro import ui

    window, writes = processed
    editor = begin(app, window)

    def fail(*args):
        raise OSError("report unavailable")

    monkeypatch.setattr(ui, "write_json", fail)
    editor.change("gamma", 130)
    editor.save_result()
    pump(app, lambda: not editor.running() and not editor.export_dirty())
    assert window.errors and len(writes) == 1 and not editor.save.isEnabled()
    editor.save_result()
    select(app, window, 1)
    assert len(writes) == 1


def test_latest_switch_waits_for_same_photo_write(app, processed, monkeypatch):
    window, writes = processed
    editor = begin(app, window)
    entered, release = threading.Event(), threading.Event()
    encode = exporting.save_result

    def delayed(*args):
        entered.set()
        assert release.wait(10)
        return encode(*args)

    other_hashes = [digest(window.queue.results[i]["output"]) for i in (1, 2)]
    monkeypatch.setattr(exporting, "save_result", delayed)
    try:
        editor.change("gamma", 130)
        window.select_photo(1)
        pump(app, entered.is_set)
        window.select_photo(2)
        release.set()
        pump(
            app,
            lambda: (
                editor.index == 2
                and editor.session is not None
                and not editor.running()
            ),
        )
    finally:
        release.set()
    assert len(writes) == 1
    assert [digest(window.queue.results[i]["output"]) for i in (1, 2)] == other_hashes


def test_close_and_reopen_does_not_resave_committed_result(app, processed):
    window, writes = processed
    editor = begin(app, window)
    editor.change("gamma", 140)
    output = Path(window.queue.results[0]["output"])
    window.close()
    pump(app, lambda: not window.isVisible())
    assert len(writes) == 1
    before = (digest(output), output.stat().st_mtime_ns)
    restored = Window(engine_factory=FakeEngine, settings=window.settings)
    restored.errors = []
    restored.error = restored.errors.append
    restored.show()
    try:
        pump(app, lambda: len(restored.queue.items) == 3 and not restored.busy())
        restored.open_comparison()
        new_editor = restored.review.editor
        pump(
            app,
            lambda: (
                new_editor.active
                and new_editor.session is not None
                and not new_editor.running()
            ),
        )
        assert not restored.errors
        assert new_editor.settings[0]["gamma"] == 1.4 and not new_editor.export_dirty()
    finally:
        restored.close()
        pump(app, lambda: not restored.isVisible())
    assert len(writes) == 1 and (digest(output), output.stat().st_mtime_ns) == before


def test_new_preferences_do_not_relocate_existing_edited_photo(
    app, processed, tmp_path
):
    window, writes = processed
    editor = begin(app, window)
    old = window.queue.results[0]["output"]
    window.output.setText(str(tmp_path / "elsewhere"))
    window.save_mode.setCurrentIndex(window.save_mode.findData("custom"))
    window.format.setCurrentIndex(window.format.findData("JPEG"))
    editor.change("gamma", 130)
    select(app, window, 1)
    assert window.queue.results[0]["output"] == old and len(writes) == 1
    assert not (tmp_path / "elsewhere").exists()
    with Image.open(old) as photo:
        assert photo.format == "PNG"


def test_committed_result_recovers_when_queue_is_older(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (10, 10)).save(source)
    item = collect_inputs([source])[0][0]
    workspace = Workspace(tmp_path / "state")
    old = {"output": str(source), "manually_edited": True, "result_revision": 1}
    workspace.save_queue([item], {0: old})
    workspace.save_processed(item, dict(old, result_revision=2, export_sha256="new"))
    assert workspace.load_queue()[1][0]["export_sha256"] == "new"


@pytest.mark.parametrize("chosen", ["", "   ", "destination", "destination/ColorPro"])
def test_destinations_and_repeated_batch_reuse_output(tmp_path, chosen):
    source = tmp_path / "photo.png"
    Image.new("RGB", (30, 20), (90, 120, 150)).save(source)
    items = collect_inputs([source])[0]
    workspace = Workspace(tmp_path / "state")
    custom = str(tmp_path / chosen) if chosen.strip() else chosen
    policy = {
        "mode": "custom",
        "custom": custom,
        "protected": [str(source)],
        "workspace": str(workspace.root),
    }
    first = run_batch(
        items,
        workspace.jobs,
        "v39",
        "cpu",
        "PNG",
        Control(),
        lambda e: None,
        FakeEngine,
        policy,
    )
    second = run_batch(
        items,
        workspace.jobs,
        "v39",
        "cpu",
        "PNG",
        Control(),
        lambda e: None,
        FakeEngine,
        policy,
    )
    root = (
        tmp_path / "destination/ColorPro" if chosen.strip() else tmp_path / "ColorPro"
    )
    assert Path(first["records"][0]["output"]) == root / "photo_СС.png"
    assert first["records"][0]["output"] == second["records"][0]["output"]
    assert list(root.rglob("*.png")) == [root / "photo_СС.png"]


def test_destination_settings_choose_cancel_empty_and_restart(
    app, tmp_path, monkeypatch
):
    from colorpro import ui

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("auto_update", False)
    window = Window(settings=settings)
    assert not window.output.text() and window.save_mode.currentData() == "beside"
    destination = tmp_path / "chosen"
    monkeypatch.setattr(
        ui.QFileDialog, "getExistingDirectory", lambda *a: str(destination)
    )
    window.pick_output()
    assert window.save_mode.currentData() == "custom"
    assert str(destination / "ColorPro") in window.output_hint.text()
    monkeypatch.setattr(ui.QFileDialog, "getExistingDirectory", lambda *a: "")
    window.pick_output()
    assert window.output.text() == str(destination)
    window.close()
    restored = Window(
        settings=QSettings(settings.fileName(), QSettings.Format.IniFormat)
    )
    try:
        assert restored.output.text() == str(destination)
        assert restored.save_mode.currentData() == "custom"
        restored.output.clear()
        assert restored.export_policy()["mode"] == "beside"
        assert restored.settings.value("export_mode") == "beside"
    finally:
        restored.close()
