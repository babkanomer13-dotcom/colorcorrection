"""Render manual-workspace QA with generated pixels and isolated settings only."""

import os
import sys
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"


def main():
    import numpy as np
    from PIL import Image
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication

    from colorpro.files import collect_inputs
    from colorpro.ui import STYLE, Window

    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=False)
    app = QApplication([])
    for name in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
        QFontDatabase.addApplicationFont(
            str(Path(os.environ["WINDIR"]) / "Fonts" / name)
        )
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    settings = QSettings(str(output / "qa.ini"), QSettings.Format.IniFormat)
    settings.setValue("auto_update", False)
    window = Window(settings=settings)
    window.resize(1220, 820)
    window.show()
    window.show_page(window.SETTINGS)
    window.select_settings_section(1)
    app.processEvents()
    window.grab().save(str(output / "shortcuts.png"))
    files = []
    y, x = np.mgrid[0:360, 0:240]
    for i in range(12):
        pixels = np.stack(
            [(x + i * 15) % 256, (y // 2 + i * 20) % 256, (x + y + i * 30) % 256],
            axis=2,
        ).astype(np.uint8)
        photo = output / f"Frame_{i + 1:02}.png"
        Image.fromarray(pixels).save(photo)
        files.append(photo)
    items, errors = collect_inputs(files)
    assert not errors
    window.queue.add(items)
    for i, item in enumerate(items):
        corrected = output / (Path(item.path).stem + "_с.png")
        corrected.write_bytes(Path(item.path).read_bytes())
        window.queue.update(
            i,
            {"index": i, "status": "corrected", "output": str(corrected), "faces": []},
        )
    window.update_queue()
    window.show_page(window.COMPARE)
    window.select_photo(3)

    def pump(predicate):
        until = time.monotonic() + 20
        while not predicate() and time.monotonic() < until:
            app.processEvents()
            time.sleep(0.02)
        assert predicate()

    pump(
        lambda: (
            window.compare.after is not None and not window.preview_loader.isRunning()
        )
    )
    window.review.filmstrip.load_visible()
    pump(lambda: not window.thumbnail_worker or not window.thumbnail_worker.isRunning())
    app.processEvents()
    window.grab().save(str(output / "filmstrip.png"))
    window.review.editor.begin()
    pump(
        lambda: (
            window.review.editor.session is not None
            and not window.review.editor.running()
        )
    )
    window.review.editor.change("gamma", 112)
    pump(window.review.editor.preview_idle)
    app.processEvents()
    window.grab().save(str(output / "correction.png"))
    window.review.editor.levels_section.toggle.setChecked(False)
    if window.review.editor.tone_section is not None:
        window.review.editor.tone_section.toggle.setChecked(True)
        window.review.editor.change_tone("brightness", 14)
        window.review.editor.change_tone("contrast", 9)
        pump(window.review.editor.preview_idle)
        app.processEvents()
        window.grab().save(str(output / "brightness.png"))
        window.review.editor.tone_section.toggle.setChecked(False)
    window.review.editor.hsl_section.toggle.setChecked(True)
    window.review.editor.change_hsl("saturation", 15)
    window.review.editor.change_hsl("lightness", 4)
    pump(window.review.editor.preview_idle)
    app.processEvents()
    window.grab().save(str(output / "colour.png"))
    window.resize(980, 640)
    app.processEvents()
    window.review.editor.hsl_section.reveal()
    app.processEvents()
    assert window.size().width() == 980 and window.size().height() == 640
    assert window.review.editor.save.isVisible()
    window.grab().save(str(output / "colour-small.png"))
    window.review.editor.cancel_edit()
    window.show_page(window.SETTINGS)
    window.select_settings_section(1)
    app.processEvents()
    window.grab().save(str(output / "shortcuts-small.png"))
    window.close()
    pump(lambda: not window.isVisible())
    for worker in (window.preview_loader, window.thumbnail_worker):
        if worker and worker.isRunning():
            worker.requestInterruption()
            worker.wait(5000)
    app.processEvents()
    window.close()
    print("PASS: manual workspace rendered with synthetic images")


if __name__ == "__main__":
    main()
