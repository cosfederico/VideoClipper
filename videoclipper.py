"""VideoClipper entry point.

Usage:
    python videoclipper.py
"""
import os
import sys

# Qt Multimedia's FFmpeg backend hardware-accelerates video decode (D3D11VA
# on Windows) by default, and its VP9 decoder has a well-known bug there:
# rapid seeking (e.g. dragging the timeline scrubber) can exhaust the
# hardware decoder's small fixed-size surface pool ("Static surface pool
# size exceeded" / "get_buffer() failed" in the log), leaving the viewport
# permanently black. This is unrelated to this app's own PyAV pipeline
# (probing/thumbnails/export never touch hardware acceleration - PyAV only
# uses it if you explicitly opt in) - it's inside Qt's own player. Software
# decode doesn't have this fixed-pool limitation, and at the resolutions
# this app deals with the CPU cost is a non-issue, so hardware decode is
# disabled outright. Must be set before any PyQt6 import - the FFmpeg
# plugin reads it once, at load time. See:
# https://doc.qt.io/qt-6/advanced-ffmpeg-configuration.html
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
