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
    from PySide2.QtCore import QSettings, Qt
    from PySide2.QtGui import QColor, QFontDatabase, QPalette
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
        QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / name))
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = Window(
        engine_factory=FakeEngine, settings=QSettings(str(output / "test.ini"), QSettings.IniFormat)
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
    window.remove_selected()
    assert not window.queue.items and result.is_file() and photo.is_file()
    window.close()
    print("PASS: Qt5 dropdowns / import / queue / process / preview / zoom / large view / remove")


if __name__ == "__main__":
    main()
