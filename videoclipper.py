"""VideoClipper entry point.

Usage:
    python videoclipper.py
"""
import sys

from PyQt6.QtWidgets import QApplication

from videoclipper.main_window import MainWindow
from videoclipper.style import STYLESHEET


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("VideoClipper")
    app.setStyleSheet(STYLESHEET)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
