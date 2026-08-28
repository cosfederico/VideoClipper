"""VideoClipper entry point.

Usage:
    python videoclipper.py
"""
import os
import sys

# Disables Qt Multimedia's hardware video decode (avoids a VP9/D3D11VA bug
# on Windows). Must be set before the PyQt6 import below.
os.environ.setdefault("QT_FFMPEG_DECODING_HW_DEVICE_TYPES", ",")

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
