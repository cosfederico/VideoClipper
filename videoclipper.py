"""VideoClipper entry point.

Usage:
    python videoclipper.py
"""
import os
import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from videoclipper.main_window import MainWindow
from videoclipper.style import STYLESHEET

_ICON_PATH = os.path.join(os.path.dirname(__file__), "videoclipper", "assets", "icon.png")


def main():
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("VideoClipper.VideoClipper")

    app = QApplication(sys.argv)
    app.setApplicationName("VideoClipper")
    app.setWindowIcon(QIcon(_ICON_PATH))
    app.setStyleSheet(STYLESHEET)

    window = MainWindow()
    window.setWindowIcon(QIcon(_ICON_PATH))
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
