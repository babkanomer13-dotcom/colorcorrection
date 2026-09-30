"""Local UI rendering QA with an existing completed report; no new inference."""

import argparse
import json
import os
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from colorpro.launcher import initialize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    initialize()
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication

    from colorpro.files import collect_inputs
    from colorpro.ui import STYLE, Window, icon

    app = QApplication([])
    for name in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "seguisym.ttf"):
        QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / name))
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    args.output.mkdir(parents=True, exist_ok=True)
    window = Window(
        settings=QSettings(str(args.output / "settings.ini"), QSettings.Format.IniFormat)
    )
    window.show()
    for size, name in [((1220, 820), "empty"), ((980, 640), "small")]:
        window.resize(*size)
        app.processEvents()
        window.grab().save(str(args.output / f"{name}.png"))
    for size, suffix in [((1220, 820), ""), ((980, 640), "-small")]:
        window.resize(*size)
        for page, name in ((1, "settings"), (2, "updates"), (3, "help")):
            window.show_page(page)
            app.processEvents()
            window.grab().save(str(args.output / f"{name}{suffix}.png"))
    window.resize(1220, 820)
    window.show_page(1)
    app.processEvents()
    for combo, name in ((window.device, "device-options"), (window.format, "format-options")):
        combo.showPopup()
        app.processEvents()
        combo.view().window().grab().save(str(args.output / f"{name}.png"))
        combo.hidePopup()
    window.show_page(0)
    report = json.loads(args.report.read_text(encoding="utf8"))
    items, errors = collect_inputs([r["input"]["path"] for r in report["records"]])
    assert not errors
    window.queue.add(items)
    for r in report["records"]:
        window.queue.update(r["index"], r)
    window.output_folder = report["output"]
    window.open_folder.setEnabled(True)
    window.update_queue()
    window.table.selectRow(1)
    deadline = time.monotonic() + 20
    while window.compare.after is None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    assert window.compare.after is not None
    for size, name in [((1220, 820), "result"), ((980, 640), "result-small")]:
        window.resize(*size)
        app.processEvents()
        window.grab().save(str(args.output / f"{name}.png"))
    window.resize(1220, 820)
    window.preview_mode.setCurrentIndex(1)
    app.processEvents()
    window.grab().save(str(args.output / "divider.png"))
    from colorpro.preview import CompareDialog

    large = CompareDialog(window)
    large.resize(1220, 820)
    large.show()
    app.processEvents()
    large.grab().save(str(args.output / "large.png"))
    large.close()
    qimage = icon().pixmap(256, 256).toImage()
    qimage.save(str(args.output / "colorpro-icon.png"))
    from PIL import Image

    with Image.open(args.output / "colorpro-icon.png") as image:
        image.save(
            args.output / "colorpro.ico",
            sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
    window.close()
    print(
        json.dumps(
            dict(
                status="PASS",
                output=str(args.output),
                views=["empty", "small", "result", "result-small", "divider"],
            )
        )
    )


if __name__ == "__main__":
    main()
