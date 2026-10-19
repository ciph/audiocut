"""Shared colors, controls, and small vector icons for Audio Cut."""

from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer


LIGHT_COLORS = {
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
    "on_accent": "#FFFFFF",
    "input_border": "#DEE3EC", "button_border": "#E1E5ED",
    "hover": "#F1F4FB", "hover_border": "#CDD5E5", "pressed": "#E8EDFA",
    "disabled_text": "#AFB5C2", "disabled_background": "#F4F5F8", "disabled_border": "#E8EBF0",
    "disabled_accent": "#B5C1EB", "disabled_accent_text": "#F4F6FF",
    "quiet_hover": "#EBEFF8", "link_hover": "#274ABA", "check_border": "#C9D1DF",
    "track": "#E5E9F1", "progress": "#E7EBF5", "scrollbar": "#CCD3E0",
    "grid": "#EEF0F5", "wave_outside": "#CDD3DF",
}

DARK_COLORS = {
    "background": "#151922", "surface": "#1E2430", "text": "#E5EAF4",
    "muted": "#A6B1C5", "border": "#343D4F", "accent": "#8BA4FF",
    "accent_hover": "#A3B7FF", "accent_soft": "#29334E", "danger": "#FF929D",
    "fade": "#57CFD9", "on_accent": "#151D35",
    "input_border": "#414C62", "button_border": "#414C62",
    "hover": "#2B3445", "hover_border": "#65728A", "pressed": "#36435D",
    "disabled_text": "#758198", "disabled_background": "#202632", "disabled_border": "#30394A",
    "disabled_accent": "#374468", "disabled_accent_text": "#8592AF",
    "quiet_hover": "#2B3445", "link_hover": "#B6C5FF", "check_border": "#74829B",
    "track": "#3A465B", "progress": "#303B50", "scrollbar": "#56647D",
    "grid": "#303A4C", "wave_outside": "#59657D",
}
# Custom-painted widgets import this dictionary; update it in place on a switch.
COLORS = LIGHT_COLORS.copy()

STYLE = """
QMenu { background: @surface@; border: 1px solid @input_border@; border-radius: 8px; padding: 6px; }
QMenu::item { padding: 8px 30px 8px 42px; border-radius: 4px; }
QMenu::item:selected { background: @accent_soft@; color: @text@; }
QMenu::item:disabled { color: @muted@; }
QMenu::separator { height: 1px; background: @border@; margin: 3px 8px; }
QMenu::icon { width: 32px; height: 22px; left: 6px; }
QWidget { color: @text@; font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; }
QMainWindow, QDialog { background: @background@; }
QWidget#centralWidget, QWidget#windowHeader { background: @background@; }
QFrame#card, QFrame[card="true"], QWidget#playerCard, QWidget#editorCard, QFrame#editor {
    background: @surface@; border: 1px solid @border@; border-radius: 16px;
}
QLabel { background: transparent; border: none; }
QLabel#title, QLabel#appTitle { font-size: 22px; font-weight: 600; }
QLabel#subtitle, QLabel#muted, QLabel[muted="true"] { color: @muted@; }
QLabel#sectionTitle { font-size: 13px; font-weight: 600; }
QLabel#fileTitle { font-size: 20px; font-weight: 600; }
QLabel#timeLabel, QLabel#clock { font-size: 13px; color: @muted@; }
QLabel#errorLabel, QLabel#validationLabel { color: @danger@; font-size: 12px; }
QLabel#targetPathLabel { color: @muted@; font-size: 12px; }
QPushButton, QToolButton {
    background: @surface@; border: 1px solid @button_border@; border-radius: 9px;
    padding: 9px 15px; min-height: 18px; font-weight: 500;
}
QPushButton:hover, QToolButton:hover { background: @hover@; border-color: @hover_border@; }
QPushButton:pressed, QToolButton:pressed { background: @pressed@; }
QPushButton:focus, QToolButton:focus { border-color: @accent@; }
QPushButton:disabled, QToolButton:disabled { color: @disabled_text@; background: @disabled_background@; border-color: @disabled_border@; }
QPushButton[primary="true"], QPushButton#primary, QPushButton#saveButton, QPushButton#playButton {
    background: @accent@; color: @on_accent@; border: 1px solid @accent@;
}
QPushButton[primary="true"]:hover, QPushButton#primary:hover, QPushButton#saveButton:hover, QPushButton#playButton:hover {
    background: @accent_hover@; border-color: @accent_hover@;
}
QPushButton[primary="true"]:disabled, QPushButton#primary:disabled, QPushButton#saveButton:disabled, QPushButton#playButton:disabled {
    background: @disabled_accent@; border-color: @disabled_accent@; color: @disabled_accent_text@;
}
QPushButton[quiet="true"], QToolButton[quiet="true"] { background: transparent; border-color: transparent; }
QPushButton[quiet="true"]:hover, QToolButton[quiet="true"]:hover { background: @quiet_hover@; }
QPushButton#playButton { border-radius: 25px; padding: 0; min-height: 48px; max-height: 48px; }
QPushButton#modeToggle, QPushButton#themeToggle { padding: 0; border-radius: 10px; min-height: 38px; }
QPushButton#modeToggle:checked { background: @accent@; border-color: @accent@; }
QPushButton#modeToggle:checked:hover { background: @accent_hover@; border-color: @accent_hover@; }
QPushButton#modeToggle:focus { border: 2px solid @text@; }
QPushButton#modeToggle:disabled { background: @disabled_border@; border-color: @button_border@; }
QPushButton#windowControl, QPushButton#windowClose { background: transparent; border: none; padding: 0; min-height: 32px; border-radius: 7px; }
QPushButton#windowControl:hover { background: @hover@; }
QPushButton#windowClose:hover { background: @accent_soft@; border: 1px solid @danger@; }
QPushButton#textButton { padding: 2px 4px; border: none; background: transparent; color: @accent@; font-size: 12px; }
QPushButton#textButton:hover { color: @link_hover@; }
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {
    background: @surface@; border: 1px solid @input_border@; border-radius: 8px;
    padding: 9px 11px; min-height: 18px; selection-background-color: @accent@; selection-color: @on_accent@;
}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus { border-color: @accent@; }
QLineEdit:disabled, QComboBox:disabled, QDoubleSpinBox:disabled { color: @disabled_text@; background: @disabled_background@; }
QComboBox { padding-right: 26px; }
QComboBox::drop-down { border: none; width: 28px; }
QComboBox::down-arrow { image: url("@ASSETS@/chevron.svg"); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: @surface@; border: 1px solid @button_border@; selection-background-color: @accent_soft@; selection-color: @text@; outline: none; padding: 4px; }
QDoubleSpinBox { padding-right: 22px; }
QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 22px; border: none; background: transparent; }
QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 22px; border: none; background: transparent; }
QDoubleSpinBox::up-arrow { image: url("@ASSETS@/chevron-up.svg"); width: 9px; height: 9px; }
QDoubleSpinBox::down-arrow { image: url("@ASSETS@/chevron.svg"); width: 9px; height: 9px; }
QCheckBox { spacing: 9px; background: transparent; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid @check_border@; border-radius: 5px; background: @surface@; }
QCheckBox::indicator:checked { background: #4167E8; border-color: @accent@; image: url("@ASSETS@/check.svg"); }
QCheckBox:disabled { color: @disabled_text@; }
QSlider::groove:horizontal { height: 4px; background: @track@; border-radius: 2px; }
QSlider::sub-page:horizontal { background: @accent@; border-radius: 2px; }
QSlider::handle:horizontal { width: 12px; height: 12px; margin: -4px 0; background: @surface@; border: 2px solid @accent@; border-radius: 7px; }
QProgressBar { border: none; background: @progress@; height: 5px; border-radius: 2px; text-align: center; }
QProgressBar::chunk { background: @accent@; border-radius: 2px; }
QStatusBar { background: transparent; color: @muted@; font-size: 12px; }
QToolTip { background: @text@; color: @background@; padding: 6px 9px; border: none; border-radius: 5px; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: @scrollbar@; border-radius: 3px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
""".replace("@ASSETS@", Path(__file__).with_name("assets").as_posix())


def apply_theme(app, dark=False):
    if app.style().objectName().lower() != "fusion":
        app.setStyle("Fusion")
    COLORS.update(DARK_COLORS if dark else LIGHT_COLORS)
    app.setProperty("dark_theme", dark)
    app.setFont(QFont("Microsoft YaHei UI", 10))
    palette = QPalette()
    for role, token in {
        "Window": "background", "WindowText": "text", "Base": "surface",
        "AlternateBase": "accent_soft", "Text": "text", "Button": "surface",
        "ButtonText": "text", "Highlight": "accent", "HighlightedText": "on_accent",
        "ToolTipBase": "text", "ToolTipText": "background", "PlaceholderText": "muted",
        "Light": "hover_border", "Mid": "border", "Dark": "background",
    }.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(COLORS[token]))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(COLORS["disabled_text"]))
    app.setPalette(palette)
    style = STYLE
    for token, color in COLORS.items():
        style = style.replace("@" + token + "@", color)
    app.setStyleSheet(style)


def icon(name, color=None, size=20):
    color = color or COLORS["text"]
    shapes = {
        "minimize": '<path d="M5 12h14"/>',
        "maximize": '<rect x="5" y="5" width="14" height="14" rx="1"/>',
        "restore": '<path d="M9 5V3h12v12h-2"/><rect x="3" y="9" width="12" height="12" rx="1"/>',
        "close": '<path d="m6 6 12 12M18 6 6 18"/>',
        "moon": '<path d="M20.5 13a8.5 8.5 0 0 1-9.5-9.5A8.5 8.5 0 1 0 20.5 13Z"/>',
        "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
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
