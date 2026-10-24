"""Qt5 interaction acceptance; run with the staged Win7 PYTHONPATH and bundle."""

import os
import sys
import time
from pathlib import Path


def main():
    from colorpro.launcher import initialize

    initialize()
    import numpy as np
    from PIL import Image
    from PySide2.QtCore import QPoint, QPointF, QSettings, Qt
    from PySide2.QtGui import QColor, QFontDatabase, QKeySequence, QPalette, QWheelEvent
    from PySide2.QtTest import QTest
    from PySide2.QtWidgets import QApplication

    from colorpro.ui import STYLE, Window

    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=False)
    photo = output / "synthetic.png"
    pixels = np.zeros((100, 150, 3), dtype="uint8") + 100
    Image.fromarray(pixels).save(photo)

    class FakeEngine:
        device_name = "CPU test"
        weight_sha256 = recipe_sha256 = "test"

        def __init__(self, *args):
            pass

        def process(self, pixels):
            return pixels.copy(), dict(status="corrected", faces=[], corrected_faces=0)

        def close(self):
            pass

    app = QApplication([])
    for name in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
        QFontDatabase.addApplicationFont(
            str(Path(os.environ["WINDIR"]) / "Fonts" / name)
        )
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = Window(
        engine_factory=FakeEngine,
        settings=QSettings(str(output / "test.ini"), QSettings.IniFormat),
    )
    window.show()

    def pump(predicate):
        deadline = time.monotonic() + 15
        while not predicate() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.02)
        assert predicate()

    assert window.device.currentData() == "auto" and window.device.count() == 2
    window.show_page(window.SETTINGS)
    app.processEvents()
    window.grab().save(str(output / "settings.png"))
    window.select_settings_section(1)
    keys = window.shortcut_panel
    previous = dict(window.shortcuts.bindings)
    keys.editors["save"].setKeySequence(QKeySequence("Ctrl+O"))
    assert not keys.apply() and window.shortcuts.bindings == previous
    keys.editors["save"].setKeySequence(QKeySequence("Ctrl+Shift+S"))
    assert keys.apply() and window.shortcuts.bindings["save"] == "Ctrl+Shift+S"
    keys.search.setText("правки")
    assert keys.table.isRowHidden(0)
    app.processEvents()
    window.grab().save(str(output / "shortcuts.png"))
    window.select_settings_section(0)
    for combo in (window.device, window.format):
        combo.showPopup()
        app.processEvents()
        assert combo.view().palette().color(QPalette.Text) == QColor("#242424")
        combo.view().window().grab().save(
            str(output / ("device.png" if combo is window.device else "format.png"))
        )
        combo.hidePopup()
    window.import_files([str(photo)])
    pump(lambda: len(window.queue.items) == 1 and not window.busy())
    window.output.setText(str(output / "results"))
    QTest.mouseClick(window.start, Qt.LeftButton)
    pump(lambda: window.last_report is not None and not window.busy())
    pump(lambda: window.compare.after is not None)
    assert window.last_report["corrected"] == 1
    for index in (1, 2, 3, 4, 0):
        window.show_page(index)
        app.processEvents()
        assert window.pages.currentIndex() == index and len(window.queue.items) == 1
    window.preview_mode.setCurrentIndex(1)
    assert window.compare.mode == 1
    window.compare.set_zoom(2)
    assert window.compare.zoom == 2
    point = QPointF(window.compare.rect().center())
    wheel = QWheelEvent(
        point,
        point,
        QPoint(),
        QPoint(0, 120),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.NoScrollPhase,
        False,
    )
    app.sendEvent(window.compare, wheel)
    assert window.compare.zoom > 2
    zoom = window.compare.zoom
    center = QPointF(window.compare.center)
    QTest.keyClick(window.compare, Qt.Key_Return)
    assert window.compare.original_visible
    QTest.keyClick(window.compare, Qt.Key_Return)
    assert not window.compare.original_visible
    assert window.compare.zoom == zoom and window.compare.center == center
    window.open_comparison()
    app.processEvents()
    assert window.review.view.before is not None
    assert window.review.count.text() == "1 / 1"
    window.grab().save(str(output / "compare.png"))
    window.toggle_review_fullscreen()
    app.processEvents()
    assert window.isFullScreen() and not window.navigation.isVisible()
    window.escape_page()
    assert not window.isFullScreen()
    result = Path(window.queue.results[0]["output"])
    assert result.name == "synthetic.png"
    pump(lambda: not window.preview_loader.isRunning())
    window.compare.setFocus()
    QTest.keyClick(window.compare, Qt.Key_U, Qt.ControlModifier)
    pump(
        lambda: (
            window.review.editor.session is not None
            and not window.review.editor.running()
        )
    )
    editor = window.review.editor
    pump(lambda: editor.pending_tool is None)
    assert (
        editor.hsl_section.body.isVisible() and editor.hsl_controls["hue"][0].hasFocus()
    )
    hue = editor.hsl_controls["hue"][0]
    hue.lineEdit().setText("5")
    QTest.keyClick(hue, Qt.Key_B, Qt.ControlModifier)
    assert editor.hsl["hue"] == 5 and editor.balance_section.body.isVisible()
    balance = editor.balance_controls[0][0]
    QTest.keyClick(balance, Qt.Key_Up, Qt.ShiftModifier)
    assert editor.balance["midtones"][0] == 10
    QTest.keyClick(balance, Qt.Key_Z, Qt.ControlModifier | Qt.AltModifier)
    assert editor.balance["midtones"][0] == 0
    QTest.keyClick(balance, Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier)
    assert editor.balance["midtones"][0] == 10
    QTest.keyClick(balance, Qt.Key_L, Qt.ControlModifier)
    black = editor.controls["input_black"][0]
    QTest.keyClick(black, Qt.Key_3, Qt.AltModifier)
    assert editor.channel.currentIndex() == 1
    QTest.keyClick(black, Qt.Key_2, Qt.AltModifier)
    assert editor.channel.currentIndex() == 0
    editor.reset_all()
    window.review.editor.controls["gamma"][0].setValue(1.25)
    window.review.editor.change_hsl("lightness", 10)
    window.review.editor.change_balance(0, 12)
    window.review.editor.undo_edit()
    assert window.review.editor.balance["midtones"][0] == 0
    window.review.editor.redo_edit()
    assert window.review.editor.balance["midtones"][0] == 12
    if window.review.editor.tone_section is not None:
        window.review.editor.change_tone("brightness", 11)
    window.review.editor.render_preview()
    pump(window.review.editor.preview_idle)
    window.grab().save(str(output / "levels.png"))
    window.review.editor.save_result()
    pump(
        lambda: (
            not window.review.editor.running()
            and window.queue.results[0].get("manually_edited")
        )
    )
    with Image.open(result) as edited:
        assert np.asarray(edited).mean() > 100
    with Image.open(photo) as untouched:
        assert np.asarray(untouched).mean() == 100
    assert window.queue.results[0]["output"] == str(result)
    pump(lambda: not window.preview_loader.isRunning())
    window.review.editor.begin()
    pump(
        lambda: (
            window.review.editor.session is not None
            and not window.review.editor.running()
        )
    )
    window.review.editor.cancel_edit()
    pump(
        lambda: (
            not window.review.editor.active
            and not window.review.editor.preview_running()
        )
    )
    window.remove_selected()
    assert not window.queue.items and result.is_file() and photo.is_file()
    window.close()
    pump(lambda: not window.isVisible())
    print(
        "PASS: Qt5 dropdowns / queue / Photoshop tool hotkeys / numeric steps / channels / undo / shortcut editing / async preview / full-size save / original safe"
    )


if __name__ == "__main__":
    main()
