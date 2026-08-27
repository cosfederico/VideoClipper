"""A small dark, modern QSS theme for the whole app."""

BG0 = "#14151a"
BG1 = "#1b1d23"
BG2 = "#23252d"
BG3 = "#2b2e38"
BORDER = "#343747"
TEXT = "#e8eaf0"
MUTED = "#8d93a3"
ACCENT = "#5b8cff"
ACCENT_HOVER = "#6f9bff"
ACCENT_PRESSED = "#4a76e0"
DANGER = "#ff5c5c"

STYLESHEET = f"""
* {{
    font-family: "Segoe UI", "Inter", "Helvetica Neue", sans-serif;
    font-size: 13px;
    color: {TEXT};
}}

QMainWindow, QDialog {{
    background: {BG0};
}}

#topBar {{
    background: {BG1};
    border-bottom: 1px solid {BORDER};
}}

#appTitle {{
    font-size: 16px;
    font-weight: 600;
    color: {TEXT};
}}

QWidget#leftPane, QWidget#rightPane {{
    background: {BG0};
}}

QSplitter::handle {{
    background: {BORDER};
    width: 1px;
}}

/* ---- Buttons ---- */
QPushButton {{
    background: {BG2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 14px;
    color: {TEXT};
}}
QPushButton:hover {{
    background: {BG3};
    border-color: #454a5e;
}}
QPushButton:pressed {{
    background: {BG1};
}}
QPushButton:disabled {{
    color: {MUTED};
    background: {BG1};
    border-color: {BORDER};
}}

QPushButton#primaryButton {{
    background: {ACCENT};
    border: none;
    color: white;
    font-weight: 600;
    padding: 8px 18px;
}}
QPushButton#primaryButton:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#primaryButton:pressed {{ background: {ACCENT_PRESSED}; }}
QPushButton#primaryButton:disabled {{ background: {BG2}; color: {MUTED}; }}

QPushButton#openVideoBtn {{
    background: {ACCENT};
    border: none;
    color: white;
    font-weight: 600;
    font-size: 15px;
    padding: 14px 28px;
    border-radius: 10px;
}}
QPushButton#openVideoBtn:hover {{ background: {ACCENT_HOVER}; }}

QLabel#openVideoHint {{
    color: {MUTED};
    margin-top: 10px;
}}

QPushButton#markerStart, QPushButton#markerEnd {{
    border-radius: 8px;
    padding: 7px 16px;
    font-weight: 600;
}}
QPushButton#markerStart {{ border: 1px solid #3d7a4f; color: #8be0a4; }}
QPushButton#markerStart:hover:!disabled {{ background: #1c3324; }}
QPushButton#markerEnd {{ border: 1px solid #7a3d3d; color: #e08b8b; }}
QPushButton#markerEnd:hover:!disabled {{ background: #331c1c; }}

QToolButton {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 4px;
    color: {MUTED};
}}
QToolButton:hover {{ background: {BG3}; color: {TEXT}; }}
QToolButton#deleteClipBtn:hover {{ color: {DANGER}; }}

QToolButton#playBtn {{
    background: {BG2};
    border: 1px solid {BORDER};
    border-radius: 20px;
    font-size: 16px;
    min-width: 36px;
    min-height: 36px;
}}
QToolButton#playBtn:hover {{ background: {BG3}; }}

/* ---- Inputs ---- */
QLineEdit, QComboBox, QSpinBox {{
    background: {BG2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {BG2};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
}}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    background: {BG2};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}

QSlider::groove:horizontal {{
    height: 4px;
    background: {BG3};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {ACCENT};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 2px;
}}

/* ---- Panels / cards ---- */
QFrame#card {{
    background: {BG1};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}

QFrame#clipItem {{
    background: {BG1};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame#clipItem:hover {{
    border-color: {ACCENT};
}}

QLabel#clipName {{ font-weight: 600; }}
QLabel#clipDuration {{ color: {MUTED}; font-size: 11px; }}
QLabel#panelHeader {{ font-size: 14px; font-weight: 600; }}
QLabel#panelCount {{
    color: {MUTED};
    background: {BG2};
    border-radius: 9px;
    padding: 1px 8px;
    font-size: 11px;
}}
QLabel#emptyHint {{ color: {MUTED}; padding: 24px; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#sectionLabel {{ color: {MUTED}; font-size: 11px; font-weight: 600; }}
QLabel#warningLabel {{ color: #f4b860; }}

QLabel#timeCurrent {{
    font-weight: 600;
    padding: 2px 5px;
    border-radius: 4px;
}}
QLabel#timeCurrent:hover {{ background: {BG2}; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: {BG3};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
}}
QScrollBar::handle:horizontal {{
    background: {BG3};
    border-radius: 5px;
    min-width: 24px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QStatusBar {{
    background: {BG1};
    color: {MUTED};
    border-top: 1px solid {BORDER};
}}

QProgressBar {{
    background: {BG2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    text-align: center;
    height: 22px;
    color: {TEXT};
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 7px;
}}

QMenuBar {{
    background: {BG1};
    border-bottom: 1px solid {BORDER};
    padding: 2px 4px;
}}
QMenuBar::item {{
    padding: 5px 10px;
    border-radius: 4px;
    background: transparent;
}}
QMenuBar::item:selected {{ background: {BG3}; }}
QMenuBar::item:pressed {{ background: {ACCENT}; color: white; }}

QMenu {{
    background: {BG2};
    border: 1px solid {BORDER};
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 20px;
    border-radius: 4px;
}}
QMenu::item:selected {{ background: {ACCENT}; }}

QMessageBox {{ background: {BG1}; }}
"""
