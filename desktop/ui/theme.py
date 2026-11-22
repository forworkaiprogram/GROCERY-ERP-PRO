"""Arabic-first application theme: QSS for light and dark modes.

Pure presentation. The QSS targets every object name used by the shell
(sidebar, navBtn, cards, tables) and by the stock widgets, so all pages
are styled without per-widget code. Explicit palettes kill the Windows
dark-mode "black screen" class of bugs.
"""

from __future__ import annotations

_LIGHT_QSS = """
* { font-family: 'Segoe UI', 'Tahoma'; font-size: 13px; color: #102a43; }
QMainWindow, QDialog { background: #eef2f7; }
#sidebar { background: #16283f; }
#brandLabel { color: #ffffff; font-size: 17px; font-weight: bold; padding: 10px; }
#navBtn {
    color: #dce6f2; background: transparent; border: none;
    text-align: right; padding: 10px 12px; border-radius: 8px; font-size: 14px;
}
#navBtn:hover { background: #21385a; }
#navBtn:checked { background: #1976d2; color: #ffffff; font-weight: bold; }
#ghostBtn { color: #dce6f2; background: #21385a; border: none; border-radius: 8px; padding: 8px; }
#ghostBtn:hover { background: #2c4a75; }
#logoutBtn { color: #ffffff; background: #b23b3b; border: none; border-radius: 8px; padding: 8px; }
#logoutBtn:hover { background: #97302f; }
#statusbar { background: #16283f; color: #e3ebf5; }
QStatusBar QLabel { color: #e3ebf5; padding: 0 8px; }
#card { background: #ffffff; border-radius: 10px; border: 1px solid #dbe4ee; }
#cardTitle { color: #52667a; font-size: 12px; }
#cardValue { color: #102a43; font-size: 20px; font-weight: bold; }
#pageHeader { font-size: 19px; font-weight: bold; color: #102a43; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {
    background: #ffffff; border: 1px solid #c3cfdd; border-radius: 6px; padding: 6px 8px;
}
QLineEdit:focus, QComboBox:focus { border-color: #1976d2; }
QPushButton {
    background: #1976d2; color: #ffffff; border: none; border-radius: 6px; padding: 7px 14px;
}
QPushButton:hover { background: #1565c0; }
QPushButton:disabled { background: #9db4cc; }
QTableWidget {
    background: #ffffff; alternate-background-color: #f5f8fc;
    border: 1px solid #dbe4ee; border-radius: 6px; gridline-color: #e4ebf3;
}
QHeaderView::section {
    background: #16283f; color: #e3ebf5; padding: 7px; border: none; font-weight: bold;
}
QTableCornerButton::section { background: #16283f; }
QTabWidget::pane { border: 1px solid #dbe4ee; border-radius: 6px; background: #ffffff; }
QTabBar::tab {
    padding: 8px 18px; background: #dde5ef; border-top-right-radius: 6px;
    border-top-left-radius: 6px; margin-right: 3px; color: #41546a;
}
QTabBar::tab:selected { background: #ffffff; color: #102a43; font-weight: bold; }
QScrollBar:vertical { background: #eef2f7; width: 10px; }
QScrollBar::handle:vertical { background: #b7c4d3; border-radius: 5px; min-height: 30px; }
QListWidget { background: #ffffff; border: 1px solid #dbe4ee; border-radius: 6px; }
#warningCard { background: #fff6de; border: 1px solid #e7c96b; border-radius: 8px; color: #7a5c00; padding: 8px; }
"""

_DARK_QSS = """
* { font-family: 'Segoe UI', 'Tahoma'; font-size: 13px; color: #e3ebf5; }
QMainWindow, QDialog { background: #101b2b; }
#sidebar { background: #0b1421; }
#brandLabel { color: #ffffff; font-size: 17px; font-weight: bold; padding: 10px; }
#navBtn {
    color: #c7d4e4; background: transparent; border: none;
    text-align: right; padding: 10px 12px; border-radius: 8px; font-size: 14px;
}
#navBtn:hover { background: #1b2c44; }
#navBtn:checked { background: #1976d2; color: #ffffff; font-weight: bold; }
#ghostBtn { color: #c7d4e4; background: #1b2c44; border: none; border-radius: 8px; padding: 8px; }
#ghostBtn:hover { background: #24395a; }
#logoutBtn { color: #ffffff; background: #b23b3b; border: none; border-radius: 8px; padding: 8px; }
#statusbar { background: #0b1421; color: #c7d4e4; }
QStatusBar QLabel { color: #c7d4e4; padding: 0 8px; }
#card { background: #18283d; border-radius: 10px; border: 1px solid #22334c; }
#cardTitle { color: #93a7bd; font-size: 12px; }
#cardValue { color: #ffffff; font-size: 20px; font-weight: bold; }
#pageHeader { font-size: 19px; font-weight: bold; color: #ffffff; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {
    background: #18283d; border: 1px solid #2c3f5c; border-radius: 6px; padding: 6px 8px; color: #e3ebf5;
}
QLineEdit:focus, QComboBox:focus { border-color: #1976d2; }
QPushButton { background: #1976d2; color: #ffffff; border: none; border-radius: 6px; padding: 7px 14px; }
QPushButton:hover { background: #1565c0; }
QPushButton:disabled { background: #35507a; }
QTableWidget {
    background: #18283d; alternate-background-color: #142030;
    border: 1px solid #22334c; border-radius: 6px; gridline-color: #22334c;
}
QHeaderView::section {
    background: #0b1421; color: #c7d4e4; padding: 7px; border: none; font-weight: bold;
}
QTableCornerButton::section { background: #0b1421; }
QTabWidget::pane { border: 1px solid #22334c; border-radius: 6px; background: #18283d; }
QTabBar::tab {
    padding: 8px 18px; background: #142030; border-top-right-radius: 6px;
    border-top-left-radius: 6px; margin-right: 3px; color: #93a7bd;
}
QTabBar::tab:selected { background: #18283d; color: #ffffff; font-weight: bold; }
QScrollBar:vertical { background: #101b2b; width: 10px; }
QScrollBar::handle:vertical { background: #35507a; border-radius: 5px; min-height: 30px; }
QListWidget { background: #18283d; border: 1px solid #22334c; border-radius: 6px; }
#warningCard { background: #3d3214; border: 1px solid #7a6a1e; border-radius: 8px; color: #ffd970; padding: 8px; }
"""

_LIGHT_PALETTE_COLORS = {
    "window": "#eef2f7",
    "base": "#ffffff",
    "text": "#102a43",
}
_DARK_PALETTE_COLORS = {
    "window": "#101b2b",
    "base": "#18283d",
    "text": "#e3ebf5",
}


def current_qss(theme: str = "light") -> str:
    return _DARK_QSS if theme == "dark" else _LIGHT_QSS


def configured_theme(db) -> str:
    row = db.query_one("SELECT value FROM app_config WHERE key='theme'")
    return row["value"] if row and row["value"] in ("light", "dark") else "light"


def apply_theme(app, theme: str = "light") -> None:
    from PySide6.QtGui import QColor, QPalette

    colors = _DARK_PALETTE_COLORS if theme == "dark" else _LIGHT_PALETTE_COLORS
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(colors["window"]))
    palette.setColor(QPalette.Base, QColor(colors["base"]))
    palette.setColor(QPalette.AlternateBase, QColor(colors["window"]))
    palette.setColor(QPalette.Text, QColor(colors["text"]))
    palette.setColor(QPalette.WindowText, QColor(colors["text"]))
    palette.setColor(QPalette.Button, QColor(colors["base"]))
    palette.setColor(QPalette.ButtonText, QColor(colors["text"]))
    palette.setColor(QPalette.ToolTipBase, QColor(colors["base"]))
    palette.setColor(QPalette.ToolTipText, QColor(colors["text"]))
    app.setPalette(palette)
    app.setStyleSheet(current_qss(theme))
