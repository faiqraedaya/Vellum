"""Entry point: build the application, apply the theme, show the window."""

import sys

from PySide6.QtWidgets import QApplication

from .gui.icons import app_icon
from .gui.theme import apply_theme
from .gui.window import MainWindow


def main() -> None:
    if sys.platform == "win32":
        # Without its own app id, Windows groups the window under python.exe
        # and shows Python's icon in the taskbar instead of this one.
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Vellum")
    app = QApplication(sys.argv)
    app.setApplicationName("Vellum")
    app.setApplicationVersion("2.0")
    app.setWindowIcon(app_icon())
    # Fusion first: it is the one style that honours a palette identically on
    # every platform, so the theme applied next lands the same way everywhere.
    app.setStyle("Fusion")
    apply_theme(app)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
