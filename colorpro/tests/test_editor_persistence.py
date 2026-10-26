import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QPointF, QSettings, Qt
from PySide6.QtTest import QTest

from colorpro.exporting import export_folder, export_photo
from colorpro.files import collect_inputs, read_image
from colorpro.levels import defaults
from colorpro.manual_balance import balance_defaults
from colorpro.manual_hsl import hsl_defaults
from colorpro.manual_tone import tone_defaults
from colorpro.ui import Window
from colorpro.workspace import Workspace, atomic_json, identity


def pump(app, predicate):
    deadline = time.monotonic() + 12
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert predicate()


def snapshot(gamma=1.0):
    value = [defaults(), tone_defaults(), hsl_defaults(), balance_defaults()]
    value[0][0]["gamma"] = gamma
    return value


def photo(directory, name="photo.png", color=(70, 100, 130)):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    Image.new("RGB", (80, 100), color).save(path)
    items, errors = collect_inputs([path])
    assert not errors
    return items[0]


def test_atomic_failure_preserves_committed_state(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    atomic_json(path, {"value": 1})

    def fail(*args):
        raise PermissionError("locked")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(PermissionError):
        atomic_json(path, {"value": 2})
    assert json.loads(path.read_text()) == {"value": 1}
    assert not list(tmp_path.glob("*.tmp"))


def test_per_photo_history_recovery_and_source_replacement(tmp_path):
    store = Workspace(tmp_path / "state")
    a, b = photo(tmp_path / "a"), photo(tmp_path / "b")
    assert identity(a) != identity(b)
    store.save_edit(a, a.path, snapshot(1.2), [snapshot()] * 110, [snapshot(1.3)])
    reopened = Workspace(store.root)
    assert reopened.load_edit(b, b.path) is None
    state = reopened.load_edit(a, a.path)
    assert state["current"][0][0]["gamma"] == 1.2
    assert len(state["history"]) == 100 and len(state["future"]) == 1
    with pytest.raises(ValueError):
        reopened.load_edit(a, b.path)
    Path(a.path).write_bytes(b"changed")
    with pytest.raises(ValueError):
        store.save_edit(a, a.path, snapshot(), [], [])


def test_recover_worker_result_after_gui_did_not_commit(tmp_path):
    store = Workspace(tmp_path / "state")
    item = photo(tmp_path / "in")
    store.save_queue([item], {0: {"status": "running"}}, 0)
    store.save_processed(item, {"status": "corrected", "output": item.path})
    items, records, selected = Workspace(store.root).load_queue()
    assert items == [item] and selected == 0
    assert records[0]["status"] == "corrected"


def test_export_beside_custom_collision_and_source_protection(tmp_path):
    a, b = photo(tmp_path / "a"), photo(tmp_path / "b")
    pixels, meta, _ = read_image(a)
    original = Path(a.path).read_bytes()
    first = export_photo(a, pixels, meta, "PNG", "beside", "", [a.path, b.path])
    assert Path(first["output"]) == tmp_path / "a/ColorPro/photo_СС.png"
    second = export_photo(b, pixels, meta, "PNG", "beside", "")
    assert Path(second["output"]) == tmp_path / "b/ColorPro/photo_СС.png"
    custom = tmp_path / "shared"
    one = export_photo(a, pixels, meta, "PNG", "custom", str(custom))
    two = export_photo(b, pixels, meta, "PNG", "custom", str(custom))
    assert Path(one["output"]).name == Path(two["output"]).name == "photo_СС.png"
    assert Path(two["output"]).parent.name == "2"
    updated = export_photo(
        b, pixels + 1, meta, "PNG", "custom", str(custom), previous=two
    )
    assert updated["output"] == two["output"]
    source_folder_export = export_photo(
        a, pixels, meta, "PNG", "custom", str(tmp_path / "a")
    )
    assert (
        source_folder_export["output"] != a.path
        and Path(a.path).read_bytes() == original
    )
    exported, _ = collect_inputs([first["output"]])
    assert export_folder(exported[0], "beside", "") == tmp_path / "a/ColorPro"


def test_export_refuses_external_changes(tmp_path):
    item = photo(tmp_path / "in")
    pixels, meta, _ = read_image(item)
    first = export_photo(item, pixels, meta, "JPEG", "beside", "")
    path = Path(first["output"])
    path.write_bytes(b"external changes")
    with pytest.raises(ValueError, match="другой программой"):
        export_photo(item, pixels, meta, "JPEG", "beside", "", previous=first)
    assert path.read_bytes() == b"external changes"


def test_folder_import_skips_exports_and_duplicates(tmp_path):
    a = photo(tmp_path / "input")
    photo(tmp_path / "input/ColorPro")
    b = photo(tmp_path / "input/sub")
    items, errors = collect_inputs([tmp_path / "input", a.path])
    assert not errors and {item.path for item in items} == {a.path, b.path}
    items, errors = collect_inputs([tmp_path / "input"], excluded=[b.path])
    assert not errors and items == [a]


@pytest.fixture
def desktop(app, tmp_path):
    settings = QSettings(str(tmp_path / "desktop.ini"), QSettings.Format.IniFormat)
    settings.setValue("auto_update", False)
    owner = Window(settings=settings)
    owner.errors = []
    owner.error = owner.errors.append
    for number in range(3):
        item = photo(tmp_path / ("source" + str(number)))
        base = photo(tmp_path / ("base" + str(number)), color=(80 + number, 90, 100))
        owner.queue.add([item])
        owner.queue.update(
            number,
            {
                "status": "corrected",
                "base_output": base.path,
                "output": base.path,
                "faces": [],
            },
        )
    owner.show()
    owner.show_page(owner.COMPARE)
    owner.select_photo(0)
    pump(app, lambda: owner.review.levels_button.isEnabled())
    yield owner
    editor = owner.review.editor
    pump(app, lambda: not editor.running())
    if editor.active:
        editor.leave(lambda: None)
    pump(app, lambda: not editor.active and not editor.preview_running())
    owner.close()
    pump(app, lambda: not owner.isVisible())


def begin(app, owner):
    if owner.review.editor.active:
        pump(
            app,
            lambda: (
                owner.review.editor.session is not None
                and not owner.review.editor.running()
            ),
        )
        return owner.review.editor
    pump(app, lambda: owner.review.levels_button.isEnabled())
    owner.review.editor.begin()
    try:
        pump(
            app,
            lambda: (
                owner.review.editor.session is not None
                and not owner.review.editor.running()
            ),
        )
    except AssertionError:
        pytest.fail(
            str(
                (
                    owner.review.editor.active,
                    owner.review.editor.status.text(),
                    owner.busy(),
                    owner.table.currentIndex().row(),
                    owner.errors,
                )
            )
        )
    return owner.review.editor


def test_rapid_switch_preserves_independent_values_and_history(app, desktop):
    owner = desktop
    editor = begin(app, owner)
    editor.controls["gamma"][0].setValue(1.2)
    owner.select_photo(1)
    owner.select_photo(2)  # Latest request wins while the previous preview finishes.
    pump(
        app,
        lambda: (
            editor.active
            and editor.index == 2
            and editor.session is not None
            and owner.table.currentIndex().row() == 2
        ),
    )
    editor = begin(app, owner)
    assert editor.settings[0]["gamma"] == 1
    editor.controls["gamma"][0].setValue(0.8)
    owner.select_photo(0)
    pump(
        app,
        lambda: (
            editor.active
            and editor.index == 0
            and editor.session is not None
            and owner.table.currentIndex().row() == 0
        ),
    )
    editor = begin(app, owner)
    assert editor.settings[0]["gamma"] == 1.2
    assert editor.history
    editor.undo_edit()
    assert editor.settings[0]["gamma"] == 1
    editor.redo_edit()
    assert editor.settings[0]["gamma"] == 1.2
    assert not owner.errors


def test_autosave_does_not_export_and_enter_keeps_view(app, desktop):
    owner = desktop
    item = owner.queue.items[0]
    base = Path(owner.queue.results[0]["base_output"])
    original = base.read_bytes()
    editor = begin(app, owner)
    gamma = editor.controls["gamma"][0]
    gamma.setValue(1.25)
    pump(app, lambda: owner.workspace.edit_path(item).is_file())
    assert base.read_bytes() == original
    owner.compare.set_zoom(3)
    owner.compare.center = QPointF(0.4, 0.6)
    pos = QPointF(owner.compare.center)
    gamma.setFocus()
    QTest.keyClick(gamma, Qt.Key.Key_Return)
    assert not owner.compare.original_visible
    owner.compare.setFocus()
    QTest.keyPress(owner.compare, Qt.Key.Key_Return)
    assert owner.compare.original_visible
    QTest.keyRelease(owner.compare, Qt.Key.Key_Return)
    assert not owner.compare.original_visible
    assert owner.compare.zoom == 3 and owner.compare.center == pos
    gamma.setFocus()
    QTest.keyClick(gamma, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert editor.settings[0]["gamma"] == 1
    QTest.keyClick(
        gamma,
        Qt.Key.Key_Z,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    assert editor.settings[0]["gamma"] == 1.25


def test_failed_autosave_blocks_navigation(app, desktop, monkeypatch):
    owner = desktop
    editor = begin(app, owner)
    editor.controls["gamma"][0].setValue(1.3)
    save = owner.workspace.save_edit

    def fail(*args, **kwargs):
        raise PermissionError("disk unavailable")

    monkeypatch.setattr(owner.workspace, "save_edit", fail)
    owner.select_photo(1)
    pump(app, lambda: bool(owner.errors))
    assert editor.active and editor.index == 0 and owner.table.currentIndex().row() == 0
    assert editor.settings[0]["gamma"] == 1.3
    monkeypatch.setattr(owner.workspace, "save_edit", save)
    assert editor.flush_state()


def test_close_reopen_restores_queue_and_edit(app, desktop):
    owner = desktop
    editor = begin(app, owner)
    editor.controls["gamma"][0].setValue(1.4)
    owner.close()
    pump(app, lambda: not owner.isVisible())
    reopened = Window(settings=owner.settings)
    reopened.show()
    try:
        pump(app, lambda: len(reopened.queue.items) == 3)
        reopened.show_page(reopened.COMPARE)
        pump(app, lambda: reopened.review.editor.session is not None)
        new_editor = begin(app, reopened)
        assert new_editor.settings[0]["gamma"] == 1.4
        assert new_editor.history
    finally:
        reopened.close()
        pump(app, lambda: not reopened.isVisible())


def test_completed_queue_opens_editor_without_reprocessing(app, desktop):
    assert desktop.pending_indices() == []
    desktop.show_page(desktop.PHOTOS)
    assert desktop.start.text() == "Перейти"
    desktop.start_batch()
    assert desktop.pages.currentIndex() == desktop.COMPARE and desktop.worker is None
    desktop.queue.update(1, {"status": "error"})
    desktop.update_queue()
    assert desktop.pending_indices() == [1]
    assert desktop.start.text() == "Начать цветокоррекцию"


def test_committed_state_survives_abrupt_process_exit(tmp_path):
    item = photo(tmp_path / "source")
    root = tmp_path / "state"
    script = (
        "import os,sys; from colorpro.launcher import initialize; initialize(); "
        "from colorpro.workspace import Workspace; from colorpro.files import collect_inputs; "
        "w=Workspace(sys.argv[1]); item=collect_inputs([sys.argv[2]])[0][0]; "
        "w.save_queue([item], {0:{'status':'running'}},0); os._exit(7)"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, str(root), item.path],
        timeout=20,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 7, result.stderr
    items, records, _ = Workspace(root).load_queue()
    assert items == [item] and records[0]["status"] == "cancelled"


def test_native_pixels_only_for_current_canvas_and_anchored_zoom(app, desktop):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QWheelEvent

    owner = desktop
    view = owner.compare
    pump(app, lambda: view.native_size is not None)
    view.actual_size()
    pump(app, lambda: view.high_detail and not owner.detail_loader.isRunning())
    assert view.before.size().width() == 80 and view.before.size().height() == 100
    assert view.drawn_size() == pytest.approx((80, 100))
    # Use enough zoom for the cursor's anchor not to be constrained by an edge.
    view.set_zoom(5)
    view.center = QPointF(0.5, 0.5)
    pane = view.panes()[0]
    point = pane.center() + QPointF(30, 20)
    before = view.target_rect(pane)
    anchor = (
        (point.x() - before.x()) / before.width(),
        (point.y() - before.y()) / before.height(),
    )
    event = QWheelEvent(
        point,
        point,
        QPoint(),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    app.sendEvent(view, event)
    after = view.target_rect(pane)
    actual = (
        (point.x() - after.x()) / after.width(),
        (point.y() - after.y()) / after.height(),
    )
    assert actual == pytest.approx(anchor)
    assert all(not hasattr(pair[0], "width") for pair in owner.previews.values())


def test_remember_layout_and_multiselect(app, desktop):
    from PySide6.QtCore import QItemSelectionModel

    owner = desktop
    owner.toggle_sidebar()
    pump(app, lambda: owner.navigation.width() == 78)
    assert all(not nav.text() and nav.toolTip() for nav in owner.nav_buttons[:5])
    assert owner.profile_button.isVisible()
    rail = owner.review.filmstrip
    selection = rail.view.selectionModel()
    selection.select(rail.model.index(1), QItemSelectionModel.SelectionFlag.Select)
    selection.select(rail.model.index(2), QItemSelectionModel.SelectionFlag.Select)
    assert len(owner.queue.checked) >= 2
    owner.review.rail_toggle.click()
    assert not rail.isVisible()
    assert str(owner.settings.value("filmstrip_visible")).lower() == "false"
    owner.show_page(owner.PHOTOS)
    owner.show_page(owner.COMPARE)
    assert not rail.isVisible()


def test_pending_batch_preserves_finished_records(app, desktop):
    from colorpro.tests.test_desktop import FakeEngine

    owner = desktop
    owner.engine_factory = FakeEngine
    previous = dict(owner.queue.results[0])
    owner.queue.update(1, {"status": "error"})
    owner.start_batch()
    pump(app, lambda: owner.last_report is not None and not owner.busy())
    assert (
        owner.last_report["total"] == 1
        and owner.last_report["records"][0]["index"] == 1
    )
    assert owner.queue.results[0] == previous
    assert owner.queue.results[1]["status"] == "corrected"
    assert owner.pending_indices() == []


def test_export_registry_survives_empty_queue(tmp_path):
    store = Workspace(tmp_path / "state")
    item = photo(tmp_path / "sources")
    pixels, metadata, _ = read_image(item)
    result = export_photo(
        item,
        pixels,
        metadata,
        "PNG",
        "custom",
        str(tmp_path / "sources/shared"),
        registry=store,
    )
    store.save_queue([], {}, -1)
    reopened = Workspace(store.root)
    assert reopened.export_paths() == [result["output"]]
    inputs, errors = collect_inputs(
        [tmp_path / "sources"], excluded=reopened.export_paths()
    )
    assert inputs == [item] and not errors


def test_edit_rejects_replaced_processed_base(tmp_path):
    from colorpro.levels import digest

    store = Workspace(tmp_path / "state")
    item = photo(tmp_path / "source")
    base = photo(tmp_path / "base")
    store.save_edit(item, base.path, snapshot(1.3), [], [], base_sha=digest(base.path))
    Image.new("RGB", (80, 100), (0, 0, 0)).save(base.path)
    with pytest.raises(ValueError, match="Базовое изображение"):
        store.load_edit(item, base.path)


def test_repeat_processing_identical_base_keeps_edits(tmp_path):
    from colorpro.levels import digest

    store = Workspace(tmp_path / "state")
    item = photo(tmp_path / "source")
    first = photo(tmp_path / "job1")
    second = photo(tmp_path / "job2")
    assert first.path != second.path and digest(first.path) == digest(second.path)
    store.save_edit(
        item, first.path, snapshot(1.3), [snapshot()], [], base_sha=digest(first.path)
    )
    restored = store.load_edit(item, second.path, digest(second.path))
    assert restored["current"][0][0]["gamma"] == 1.3 and len(restored["history"]) == 1


def test_hidden_parameters_stay_hidden_after_frame_switch(app, desktop):
    editor = begin(app, desktop)
    editor.activate_tool("hsl")
    desktop.review.panel_toggle.click()
    assert not editor.isVisible()
    desktop.select_photo(1)
    pump(
        app,
        lambda: (
            editor.active
            and editor.index == 1
            and editor.session is not None
            and not editor.running()
        ),
    )
    assert not editor.isVisible() and not desktop.review.panel_toggle.isChecked()
    assert editor.hsl_section.toggle.isChecked()
    assert str(desktop.settings.value("last_tool")) == "hsl"


def test_large_queue_and_bounded_caches(app, desktop, tmp_path):
    from dataclasses import replace

    owner = desktop
    item = photo(tmp_path / "large")
    items = [replace(item, member=f"frame_{i:05d}.png") for i in range(10000)]
    owner.workspace.save_queue(items, {}, 9999)
    restored, _, selected = owner.workspace.load_queue()
    assert len(restored) == 10000 and selected == 9999
    for number in range(10000):
        owner.preview_sizes[number] = (1500, 1000)
        owner.cache_preview(number, (b"preview", b"result"))
    assert len(owner.previews) == len(owner.preview_sizes) == 8
    owner.clear_queue()
    assert not owner.previews and not owner.preview_sizes


def test_repeated_navigation_keeps_values_separate(app, desktop):
    owner = desktop
    for number in range(30):
        index = number % 3
        owner.select_photo(index)
        pump(app, lambda index=index: owner.table.currentIndex().row() == index)
        editor = begin(app, owner)
        editor.controls["gamma"][0].setValue(1 + index / 10)
        assert editor.flush_state()
        pump(app, editor.state_idle)
    for index, item in enumerate(owner.queue.items):
        saved = owner.workspace.load_edit(
            item, owner.queue.results[index]["base_output"]
        )
        assert saved["current"][0][0]["gamma"] == 1 + index / 10
    assert len(owner.previews) <= 8 and not owner.errors
