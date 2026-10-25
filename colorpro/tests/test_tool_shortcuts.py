"""Keyboard workflows use a disposable image and settings, never a user session."""

import json
import time

import pytest
from PIL import Image
from PySide6.QtCore import QEvent, QSettings, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit

from colorpro.files import collect_inputs
from colorpro.shortcuts import KEY_FORMAT, defaults, load_bindings
from colorpro.ui import Window

CTRL = Qt.KeyboardModifier.ControlModifier
ALT = Qt.KeyboardModifier.AltModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier


def pump(app, predicate):
    deadline = time.monotonic() + 10
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert predicate()


@pytest.fixture
def workspace(app, tmp_path):
    settings = QSettings(str(tmp_path / "keys.ini"), QSettings.Format.IniFormat)
    settings.setValue("auto_update", False)
    owner = Window(settings=settings)
    source, result = tmp_path / "исходник.png", tmp_path / "исходник_с.png"
    Image.new("RGB", (50, 60), (70, 100, 130)).save(source)
    result.write_bytes(source.read_bytes())
    items, _ = collect_inputs([source])
    owner.queue.add(items)
    owner.queue.update(0, {"status": "corrected", "output": str(result), "faces": []})
    owner.show()
    owner.show_page(owner.COMPARE)
    owner.select_photo(0)
    pump(app, lambda: owner.review.levels_button.isEnabled())
    owner.compare.setFocus()
    app.processEvents()
    yield owner
    editor = owner.review.editor
    pump(app, lambda: not editor.running())
    if editor.active:
        editor.end()
    pump(
        app,
        lambda: (
            not editor.active and not editor.preview_running() and editor.state_idle()
        ),
    )
    for worker in (owner.preview_loader, owner.thumbnail_worker):
        if worker and worker.isRunning():
            worker.requestInterruption()
            worker.wait(5000)
    app.processEvents()
    owner.close()


def ready(app, editor):
    pump(
        app,
        lambda: (
            editor.session is not None
            and not editor.running()
            and not editor.pending_tool
        ),
    )


def test_photoshop_default_commands():
    # Checked against CC 2014's shipped Default Keyboard Shortcuts.kys.
    expected = {
        "edit": "Ctrl+L",
        "hsl": "Ctrl+U",
        "balance": "Ctrl+B",
        "tone": "",
        "auto_tone": "Ctrl+Shift+L",
        "auto_contrast": "Ctrl+Alt+Shift+L",
        "auto_color": "Ctrl+Shift+B",
        "shortcuts": "Ctrl+Alt+Shift+K",
        "step_back": "Ctrl+Alt+Z",
        "redo": "Ctrl+Shift+Z",
        "channel_rgb": "Alt+2",
        "channel_red": "Alt+3",
        "channel_green": "Alt+4",
        "channel_blue": "Alt+5",
    }
    assert {key: defaults()[key] for key in expected} == expected
    assert "Ctrl+M" not in defaults().values()  # Curves is not shipped.


def test_upgrade_keeps_custom_keys_and_disables_only_new_conflicts():
    old = {"open": "Ctrl+U", "edit": "Ctrl+Shift+L", "save": "", "fullscreen": "F9"}
    bindings, conflicts = load_bindings(old)
    assert all(bindings[key] == value for key, value in old.items())
    assert bindings["hsl"] == bindings["auto_tone"] == ""
    assert bindings["balance"] == "Ctrl+B" and len(conflicts) == 2
    with pytest.raises(ValueError):
        load_bindings({"open": "Ctrl+U", "save": "Ctrl+U"})


@pytest.mark.parametrize(
    "key, section, control",
    [
        (Qt.Key.Key_L, "levels_section", "levels"),
        (Qt.Key.Key_U, "hsl_section", "hsl"),
        (Qt.Key.Key_B, "balance_section", "balance"),
    ],
)
def test_direct_open_focus_and_numeric_switch(app, workspace, key, section, control):
    owner, editor = workspace, workspace.review.editor
    result = editor.owner.queue.results[0]["output"]
    before = Image.open(result).tobytes()
    QTest.keyClick(owner.compare, key, CTRL)
    ready(app, editor)
    assert getattr(editor, section).body.isVisible()
    field = {
        "levels": editor.controls["input_black"][0],
        "hsl": editor.hsl_controls["hue"][0],
        "balance": editor.balance_controls[0][0],
    }[control]
    assert field.hasFocus() and field.lineEdit().selectedText()
    # Tool switching commits the typed value, without resetting any settings.
    field.lineEdit().setText("8")
    QTest.keyClick(field, Qt.Key.Key_L, CTRL)
    assert editor.controls["input_black"][0].hasFocus()
    assert editor.levels_section.body.isVisible()
    assert not editor.hsl_section.body.isVisible()
    assert not editor.balance_section.body.isVisible()
    assert {
        "levels": editor.settings[0]["input_black"],
        "hsl": editor.hsl["hue"],
        "balance": editor.balance["midtones"][0],
    }[control] == 8
    assert Image.open(result).tobytes() == before  # Still only a preview.


def test_parameter_steps_channels_and_history(app, workspace):
    owner, editor = workspace, workspace.review.editor
    QTest.keyClick(owner.compare, Qt.Key.Key_L, CTRL)
    ready(app, editor)
    gamma = editor.controls["gamma"][0]
    gamma.setFocus()
    gamma.lineEdit().setText(gamma.locale().toString(1.23, "f", 2))
    QTest.keyClick(gamma, Qt.Key.Key_Up, SHIFT)
    assert editor.settings[0]["gamma"] == 1.33
    QTest.keyClick(gamma, Qt.Key.Key_Down)
    assert editor.settings[0]["gamma"] == 1.32
    QTest.keyClick(gamma, Qt.Key.Key_3, ALT)
    assert editor.channel.currentIndex() == 1
    assert editor.settings[0]["gamma"] == 1.32
    black = editor.controls["input_black"][0]
    QTest.keyClick(black, Qt.Key.Key_Up, SHIFT)
    assert editor.settings[1]["input_black"] == 10
    QTest.keyClick(black, Qt.Key.Key_Z, CTRL | ALT)
    assert editor.settings[1]["input_black"] == 0
    # Local Ctrl+Z still belongs to the text editor; history has its own key.
    QTest.keyClick(black, Qt.Key.Key_Z, CTRL | SHIFT)
    assert editor.settings[1]["input_black"] == 10
    QTest.keyClick(editor.levels_section.toggle, Qt.Key.Key_2, ALT)
    assert editor.channel.currentIndex() == 0
    assert editor.settings[0]["gamma"] == 1.32
    gamma.setFocus()
    QTest.keyClick(gamma, Qt.Key.Key_Tab)
    assert editor.controls["input_white"][0].hasFocus()


@pytest.mark.parametrize(
    "key, modifiers, mode",
    [
        (Qt.Key.Key_L, CTRL | SHIFT, 1),
        (Qt.Key.Key_L, CTRL | ALT | SHIFT, 2),
        (Qt.Key.Key_B, CTRL | SHIFT, 0),
    ],
)
def test_auto_hotkeys_from_closed_editor_are_undoable(
    app, workspace, key, modifiers, mode
):
    from colorpro.levels import defaults as level_defaults
    from colorpro.manual_auto import auto_settings

    owner, editor = workspace, workspace.review.editor
    QTest.keyClick(owner.compare, key, modifiers)
    pump(
        app,
        lambda: (
            editor.session is not None and not editor.running() and bool(editor.history)
        ),
    )
    assert editor.auto_mode.currentIndex() == mode
    assert editor.settings == auto_settings(editor.session.pixels, mode)
    editor.undo_edit()
    assert editor.settings == level_defaults()


def test_custom_tone_hotkey_and_custom_keys_are_visible(app, workspace):
    owner, editor = workspace, workspace.review.editor
    owner.shortcuts.apply({"tone": "Ctrl+Shift+T", "hsl": "Ctrl+Alt+U"})
    QTest.keyClick(owner.compare, Qt.Key.Key_T, CTRL | SHIFT)
    ready(app, editor)
    assert editor.tone_section.body.isVisible()
    assert editor.tone_controls["brightness"][0].hasFocus()
    assert editor.tone_section.shortcut.text() == "Ctrl+Shift+T"
    assert editor.hsl_section.shortcut.text() == "Ctrl+Alt+U"
    assert json.loads(owner.settings.value("shortcuts_v1"))["hsl"] == "Ctrl+Alt+U"
    owner.shortcuts.apply({"tone": ""})
    assert not editor.tone_section.shortcut.isVisible()


def test_russian_physical_tool_shortcuts_and_recording_guard(app, workspace):
    owner, editor = workspace, workspace.review.editor
    event = QKeyEvent(QEvent.Type.KeyPress, 0x0413, CTRL, 0, ord("U"), 0, "г")
    app.sendEvent(owner.compare, event)
    ready(app, editor)
    assert editor.hsl_section.body.isVisible()
    editor.end()
    owner.show_shortcut_settings()
    pump(
        app, lambda: not editor.active and owner.pages.currentIndex() == owner.SETTINGS
    )
    recorder = owner.shortcut_panel.editors["tone"]
    recorder.setFocus()
    QTest.keyClick(recorder, Qt.Key.Key_B, CTRL)
    assert not editor.active
    assert recorder.keySequence().toString(KEY_FORMAT) == "Ctrl+B"
    # A plain letter assignment must not swallow text being typed into a number.
    owner.shortcuts.apply({"hsl": "U"})
    owner.show_page(owner.COMPARE)
    pump(app, lambda: editor.active or owner.review.levels_button.isEnabled())
    if not editor.active:
        editor.begin()
    ready(app, editor)
    # Reopening now preserves expanded groups; establish a closed HSL group
    # explicitly before testing that plain typing cannot activate it.
    editor.activate_tool("levels")
    field = editor.controls["gamma"][0]
    field.setFocus()
    QTest.keyClick(field, Qt.Key.Key_U)
    assert not editor.hsl_section.body.isVisible()


def test_shortcut_settings_default_command_and_text_guard(app, workspace):
    owner = workspace
    QTest.keyClick(owner.compare, Qt.Key.Key_K, CTRL | ALT | SHIFT)
    assert owner.pages.currentIndex() == owner.SETTINGS
    assert owner.settings_sections.currentIndex() == 1
    owner.shortcut_panel.search.setFocus()
    QTest.keyClick(owner.shortcut_panel.search, Qt.Key.Key_L, CTRL)
    assert not owner.review.editor.active
    owner.shortcut_panel.search.setText("abc")
    QTest.keyClick(owner.shortcut_panel.search, Qt.Key.Key_A, CTRL)
    assert owner.shortcut_panel.search.selectedText() == "abc"


def test_saved_settings_migration_notice(app, tmp_path):
    settings = QSettings(str(tmp_path / "old.ini"), QSettings.Format.IniFormat)
    settings.setValue("auto_update", False)
    settings.setValue(
        "shortcuts_v1", json.dumps({"open": "Ctrl+U", "edit": "Ctrl+Alt+L"})
    )
    owner = Window(settings=settings)
    try:
        assert owner.shortcuts.bindings["open"] == "Ctrl+U"
        assert owner.shortcuts.bindings["edit"] == "Ctrl+Alt+L"
        assert owner.shortcuts.bindings["hsl"] == ""
        assert "конфликта" in owner.shortcut_panel.message.text()
        assert not owner.shortcuts.load_error
        assert owner.shortcut_panel.editors["hsl"].findChild(QLineEdit).text() == ""
    finally:
        owner.close()


def test_busy_editor_cannot_start_second_operation(app, workspace, monkeypatch):
    import threading

    import colorpro.manual_auto as auto_module

    owner, editor = workspace, workspace.review.editor
    QTest.keyClick(owner.compare, Qt.Key.Key_L, CTRL)
    ready(app, editor)
    calculate = auto_module.auto_settings
    entered, release = threading.Event(), threading.Event()

    def slow(pixels, mode):
        entered.set()
        assert release.wait(10)
        return calculate(pixels, mode)

    monkeypatch.setattr(auto_module, "auto_settings", slow)
    try:
        QTest.keyClick(editor.controls["input_black"][0], Qt.Key.Key_B, CTRL | SHIFT)
        pump(app, entered.is_set)
        first = editor.task
        QTest.keyClick(owner.compare, Qt.Key.Key_U, CTRL)
        QTest.keyClick(owner.compare, Qt.Key.Key_L, CTRL | SHIFT)
        QTest.keyClick(owner.compare, Qt.Key.Key_S, CTRL)
        assert editor.task is first and editor.active
        assert not editor.hsl_section.body.isVisible()
    finally:
        release.set()
        pump(app, lambda: not editor.running())
        app.processEvents()
