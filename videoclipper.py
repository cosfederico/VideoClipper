"""VideoClipper entry point.

Usage:
    python videoclipper.py
"""
import os
import sys

# Disables Qt Multimedia's hardware video decode (avoids a VP9/D3D11VA bug
# on Windows - see CLAUDE.md). Must be set before the PyQt6 import below.
os.environ.setdefault("QT_FFMPEG_DECODING_HW_DEVICE_TYPES", ",")

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
