"""Invigil look: warm paper, ink sidebar, vermilion for anything that needs a human."""
import re
from pathlib import Path

_CHEVRON = (Path(__file__).resolve().parent.parent / "assets" / "chevron.png").as_posix()
P = dict(chevron=_CHEVRON, paper="#F4F1EA", card="#FBF9F4", ink="#1B1F23", ink2="#2A2F35", muted="#6B6F73", line="#E2DCCF",
         hover="#F1ECE0", red="#D8432B", red_dark="#BE3A24", green="#2F8F5B", amber="#D9A441")
STATUS_COLORS = {"pending": ("#8A5A00", "#F6EBD3"), "confirmed": ("#B5301B", "#F8E4DE"), "dismissed": ("#555B5F", "#E9E5DA")}

_QSS = """
* { color: @ink; font-size: 13px; }
QMainWindow, QDialog, QWidget#root, QWidget#page { background: @paper; }
QWidget#sidebar { background: @ink; }
QLabel#wordmark { color: @paper; font-family: Georgia, 'Times New Roman', serif; font-size: 26px; font-weight: 700; }
QLabel#tagline { color: #8B9096; font-size: 12px; }
QPushButton#nav { color: #B9BDC2; text-align: left; padding: 11px 16px; border: none; border-radius: 10px; background: transparent; font-size: 14px; }
QPushButton#nav:hover { background: @ink2; color: white; }
QPushButton#nav:checked { background: @ink2; color: white; font-weight: 600; }
QLabel#sideChip { color: #B9BDC2; background: @ink2; border-radius: 10px; padding: 9px 12px; font-size: 12px; }
QPushButton#sideLink { color: #B9BDC2; text-align: left; padding: 8px 16px; border: none; background: transparent; font-size: 12px; }
QPushButton#sideLink:hover { color: white; }
QLabel#h1 { font-family: Georgia, 'Times New Roman', serif; font-size: 30px; font-weight: 700; }
QLabel#h2 { font-size: 15px; font-weight: 700; }
QLabel#muted { color: @muted; }
QFrame#card { background: @card; border: 1px solid @line; border-radius: 16px; }
QFrame#card QLabel { background: transparent; }
QLabel#kpiLabel { color: @muted; font-size: 11px; font-weight: 700; letter-spacing: 1px; }
QLabel#kpiValue { font-size: 32px; font-weight: 700; }
QLabel#kpiSub { color: @muted; font-size: 12px; }
QPushButton { font-weight: 600; }
QPushButton#primary { background: @red; color: white; border: none; border-radius: 10px; padding: 10px 20px; }
QPushButton#primary:hover { background: @red_dark; }
QPushButton#primary:disabled { background: #E6B7AD; }
QPushButton#ghost, QPushButton#mini { background: @card; border: 1px solid @line; border-radius: 10px; padding: 9px 16px; }
QPushButton#ghost:hover, QPushButton#mini:hover { background: @hover; }
QPushButton#ghost:disabled, QPushButton#mini:disabled { color: #A9A596; }
QPushButton#mini { padding: 5px 11px; border-radius: 8px; font-size: 12px; }
QPushButton#ok:hover { background: #DFF0E6; border-color: @green; }
QPushButton#no:hover { background: #F8E4DE; border-color: @red; }
QPushButton#seg { background: transparent; border: none; border-radius: 9px; padding: 7px 14px; color: @muted; }
QPushButton#seg:checked { background: @card; color: @ink; }
QFrame#segwrap { background: @hover; border-radius: 12px; border: none; }
QLineEdit, QComboBox { background: @card; border: 1px solid @line; border-radius: 10px; padding: 8px 12px; selection-background-color: @red; }
QLineEdit:focus, QComboBox:focus { border-color: @ink; }
QComboBox::drop-down { border: none; width: 30px; }
QComboBox::down-arrow { image: url(@chevron); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: @card; border: 1px solid @line; selection-background-color: @hover; selection-color: @ink; outline: none; }
QTableWidget { background: @card; border: none; border-radius: 16px; gridline-color: transparent; selection-background-color: @hover; selection-color: @ink; outline: none; }
QTableWidget::item { padding-left: 10px; border-top: 1px solid @line; }
QTableWidget::item:selected { background: @hover; color: @ink; }
QHeaderView { background: @card; }
QHeaderView::section { background: @card; color: @muted; border: none; border-bottom: 1px solid @line; padding: 12px 10px; font-size: 11px; font-weight: 700; }
QProgressBar { background: @hover; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; }
QProgressBar::chunk { background: @red; border-radius: 3px; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #D9D3C5; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QToolTip { background: @ink; color: white; border: none; padding: 5px 8px; }
"""

QSS = re.sub(r"@(\w+)", lambda m: P[m.group(1)], _QSS)
