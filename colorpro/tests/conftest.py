import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest


@pytest.fixture(scope="session")
def app():
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication

    from colorpro.ui import STYLE

    application = QApplication.instance() or QApplication([])
    for name in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
        QFontDatabase.addApplicationFont(os.path.join(os.environ["WINDIR"], "Fonts", name))
    application.setStyle("Fusion")
    application.setStyleSheet(STYLE)
    yield application
