"""Shared colors, controls, and small vector icons for Audio Cut."""

from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QFont, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


COLORS = {
    "background": "#F6F7F9",
    "surface": "#FFFFFF",
    "text": "#26324A",
    "muted": "#657086",
    "border": "#E7EAF0",
    "accent": "#4167E8",
    "accent_hover": "#365BD5",
    "accent_soft": "#EDF1FF",
    "danger": "#C34F58",
    "fade": "#008C9E",
}

STYLE = """
QMenu { background: white; border: 1px solid #DEE3EC; border-radius: 8px; padding: 6px; }
QMenu::item { padding: 8px 30px 8px 42px; border-radius: 4px; }
QMenu::item:selected { background: #EDF1FF; color: #26324A; }
QMenu::item:disabled { color: #657086; }
QMenu::separator { height: 1px; background: #E7EAF0; margin: 3px 8px; }
QMenu::icon { width: 32px; height: 22px; left: 6px; }
QWidget { color: #26324A; font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; }
QMainWindow, QDialog { background: #F6F7F9; }
QWidget#centralWidget { background: #F6F7F9; }
QFrame#card, QFrame[card="true"], QWidget#playerCard, QWidget#editorCard, QFrame#editor {
    background: white; border: 1px solid #E7EAF0; border-radius: 16px;
}
QLabel { background: transparent; border: none; }
QLabel#title, QLabel#appTitle { font-size: 22px; font-weight: 600; }
QLabel#subtitle, QLabel#muted, QLabel[muted="true"] { color: #657086; }
QLabel#sectionTitle { font-size: 13px; font-weight: 600; }
QLabel#fileTitle { font-size: 20px; font-weight: 600; }
QLabel#timeLabel, QLabel#clock { font-size: 13px; color: #657086; }
QLabel#errorLabel, QLabel#validationLabel { color: #C34F58; font-size: 12px; }
QLabel#targetPathLabel { color: #657086; font-size: 12px; }
QPushButton, QToolButton {
    background: white; border: 1px solid #E1E5ED; border-radius: 9px;
    padding: 9px 15px; min-height: 18px; font-weight: 500;
}
QPushButton:hover, QToolButton:hover { background: #F1F4FB; border-color: #CDD5E5; }
QPushButton:pressed, QToolButton:pressed { background: #E8EDFA; }
QPushButton:focus, QToolButton:focus { border-color: #4167E8; }
QPushButton:disabled, QToolButton:disabled { color: #AFB5C2; background: #F4F5F8; border-color: #E8EBF0; }
QPushButton[primary="true"], QPushButton#primary, QPushButton#saveButton, QPushButton#playButton {
    background: #4167E8; color: white; border: 1px solid #4167E8;
}
QPushButton[primary="true"]:hover, QPushButton#primary:hover, QPushButton#saveButton:hover, QPushButton#playButton:hover {
    background: #365BD5; border-color: #365BD5;
}
QPushButton[primary="true"]:disabled, QPushButton#primary:disabled, QPushButton#saveButton:disabled, QPushButton#playButton:disabled {
    background: #B5C1EB; border-color: #B5C1EB; color: #F4F6FF;
}
QPushButton[quiet="true"], QToolButton[quiet="true"] { background: transparent; border-color: transparent; }
QPushButton[quiet="true"]:hover, QToolButton[quiet="true"]:hover { background: #EBEFF8; }
QPushButton#playButton { border-radius: 25px; padding: 0; }
QPushButton#modeToggle { padding: 0; border-radius: 10px; }
QPushButton#modeToggle:checked { background: #4167E8; border-color: #4167E8; }
QPushButton#modeToggle:checked:hover { background: #365BD5; border-color: #365BD5; }
QPushButton#modeToggle:focus { border: 2px solid #26324A; }
QPushButton#modeToggle:disabled { background: #E8EBF0; border-color: #E1E5ED; }
QPushButton#textButton { padding: 2px 4px; border: none; background: transparent; color: #4167E8; font-size: 12px; }
QPushButton#textButton:hover { color: #274ABA; }
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {
    background: white; border: 1px solid #DEE3EC; border-radius: 8px;
    padding: 9px 11px; min-height: 18px; selection-background-color: #4167E8;
}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus { border-color: #4167E8; }
QLineEdit:disabled, QComboBox:disabled, QDoubleSpinBox:disabled { color: #A1A8B6; background: #F5F6F8; }
QComboBox { padding-right: 26px; }
QComboBox::drop-down { border: none; width: 28px; }
QComboBox::down-arrow { image: url("@ASSETS@/chevron.svg"); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: white; border: 1px solid #E1E5ED; selection-background-color: #EDF1FF; selection-color: #26324A; outline: none; padding: 4px; }
QDoubleSpinBox { padding-right: 22px; }
QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 22px; border: none; background: transparent; }
QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 22px; border: none; background: transparent; }
QDoubleSpinBox::up-arrow { image: url("@ASSETS@/chevron-up.svg"); width: 9px; height: 9px; }
QDoubleSpinBox::down-arrow { image: url("@ASSETS@/chevron.svg"); width: 9px; height: 9px; }
QCheckBox { spacing: 9px; background: transparent; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #C9D1DF; border-radius: 5px; background: white; }
QCheckBox::indicator:checked { background: #4167E8; border-color: #4167E8; image: url("@ASSETS@/check.svg"); }
QCheckBox:disabled { color: #A1A8B6; }
QSlider::groove:horizontal { height: 4px; background: #E5E9F1; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #4167E8; border-radius: 2px; }
QSlider::handle:horizontal { width: 12px; height: 12px; margin: -4px 0; background: white; border: 2px solid #4167E8; border-radius: 7px; }
QProgressBar { border: none; background: #E7EBF5; height: 5px; border-radius: 2px; text-align: center; }
QProgressBar::chunk { background: #4167E8; border-radius: 2px; }
QStatusBar { background: transparent; color: #657086; font-size: 12px; }
QToolTip { background: #26324A; color: white; padding: 6px 9px; border: none; border-radius: 5px; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: #CCD3E0; border-radius: 3px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
""".replace("@ASSETS@", Path(__file__).with_name("assets").as_posix())


def apply_theme(app):
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(STYLE)


def icon(name, color="#26324A", size=20):
    shapes = {
        "open": '<path d="M3 7V5a1 1 0 0 1 1-1h5l2 3h8a1 1 0 0 1 1 1v2M3 8h17a1 1 0 0 1 1 1l-2 10H5L3 8Z"/>',
        "play": '<path d="m8 5 11 7-11 7V5Z" fill="currentColor" stroke-linejoin="round"/>',
        "pause": '<rect x="6" y="5" width="4" height="14" rx="1" fill="currentColor"/><rect x="14" y="5" width="4" height="14" rx="1" fill="currentColor"/>',
        "save": '<path d="M12 3v12m-4-4 4 4 4-4M4 15v5h16v-5"/>',
        "back": '<path d="m10 5-7 7 7 7M3 12h17"/>',
        "volume": '<path d="M4 9h4l5-4v14l-5-4H4V9Zm12-1a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/>',
        "scissors": '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="m8.5 7.5 12 12m-12-3 12-12"/>',
        "music": '<path d="M9 17V5l11-2v12M9 8l11-2"/><ellipse cx="6" cy="18" rx="3" ry="2.5"/><ellipse cx="17" cy="16" rx="3" ry="2.5"/>',
    }
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" color="{color}" stroke-width="1.7" '
        'stroke-linecap="round" stroke-linejoin="round">'
        + shapes.get(name, shapes["music"]) + "</svg>"
    )
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)
