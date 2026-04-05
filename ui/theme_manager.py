"""
ui/theme_manager.py  –  Application-wide theme engine
======================================================
Responsibilities
----------------
* Apply Dark / Light / OLED themes by coordinating QFluentWidgets' built-in
  theme system with a supplementary QSS layer for rich, vibrant styling.
* Expose a single apply(theme_name) method safe to call at any time.
* Persist the chosen theme back to AppConfig on every change.
* Provide the amber accent colour (#F5A623) that matches the brand identity.
* Expose cycle() to rotate dark → light → oled → dark.

Design Tokens (v2 – deep, premium palette)
------------------------------------------
Dark mode moves from plain flat grays to rich, cool-purple-tinted surfaces
that evoke a professional music player (Spotify / Apple Music aesthetic):

    _BG       = #0d0d12   – deep, cool near-black (was #111114)
    _SURFACE  = #16161f   – rich card surface with purple tint (was #1c1c21)
    _SURFACE2 = #1e1e2a   – elevated / hover surface
    _BORDER   = #252533   – subtle borders (was #313139)
    _TEXT     = #eeeef5   – cooler white
    _TEXT_2   = #8888a8   – purple-tinted secondary text
    _TEXT_3   = #4a4a66   – deep muted / disabled text
    _ACCENT   = #F5A623   – amber brand colour (UNCHANGED)
    _SUCCESS  = #10b981   – vibrant emerald
    _ERROR    = #ef4444   – vivid red
    _WARNING  = #f59e0b   – warm amber-yellow

Cards gain:
  * Proper drop shadows via QGraphicsDropShadowEffect in component code
  * Amber-glow borders on hover (thick 2px, semi-opaque)
  * Rich dark scrollbars matching the surface colour

Light mode gains:
  * Cleaner, crisper white surfaces
  * Amber accent preserved

OLED mode:
  * True-black (#000000) for every major surface
  * Micro-contrast cards (#0a0a0a) for legibility
"""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication
from qfluentwidgets import setTheme, setThemeColor, Theme

from config import AppConfig


# ──────────────────────────────────────────────────────────────────────────────
# Brand constants
# ──────────────────────────────────────────────────────────────────────────────

ACCENT_COLOR:     str = "#F5A623"   # Amber – unchanged brand colour
ACCENT_COLOR_DIM: str = "#C47D0E"   # Dimmed amber for hover states

# Vibrant semantic colours used across all dark-variant components
SUCCESS_COLOR:    str = "#10b981"   # Emerald green (downloads done)
ERROR_COLOR:      str = "#ef4444"   # Vivid red (failed downloads)
WARNING_COLOR:    str = "#f59e0b"   # Amber-yellow (cancelled)
PROCESSING_COLOR: str = "#8b5cf6"   # Purple (FFmpeg processing)

# Full design-token exports so component files can import individual tokens
# without importing from theme_manager (no circular dependency risk)
BG_DARK:       str = "#0d0d12"
SURFACE_DARK:  str = "#16161f"
SURFACE2_DARK: str = "#1e1e2a"
BORDER_DARK:   str = "#252533"
TEXT_DARK:     str = "#eeeef5"
TEXT2_DARK:    str = "#8888a8"
TEXT3_DARK:    str = "#4a4a66"


# ──────────────────────────────────────────────────────────────────────────────
# QSS overlays
# ──────────────────────────────────────────────────────────────────────────────

_DARK_QSS_OVERLAY: str = """
/* ══════════════════════════════════════════════════════════════════════════
   YTSpot Dark Theme Overlay – v2  (deep, purple-tinted premium palette)
   ══════════════════════════════════════════════════════════════════════════ */

/* ── Global reset ──────────────────────────────────────────────────────── */
QWidget {
    background-color: #0d0d12;
    color: #eeeef5;
    selection-background-color: #F5A623;
    selection-color: #000000;
}

/* ── Scroll areas ──────────────────────────────────────────────────────── */
QScrollArea,
QScrollArea > QWidget > QWidget,
QAbstractScrollArea {
    background-color: #0d0d12;
    border: none;
}

/* ── Thin, modern scrollbars ───────────────────────────────────────────── */
QScrollBar:vertical {
    background: #0d0d12;
    width: 6px;
    border-radius: 3px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #252533;
    border-radius: 3px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover {
    background: #F5A623;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical { background: transparent; }

QScrollBar:horizontal {
    background: #0d0d12;
    height: 6px;
    border-radius: 3px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #252533;
    border-radius: 3px;
    min-width: 28px;
}
QScrollBar::handle:horizontal:hover {
    background: #F5A623;
}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal { width: 0; }

/* ── Tooltips ───────────────────────────────────────────────────────────── */
QToolTip {
    background-color: #1e1e2a;
    color: #eeeef5;
    border: 1px solid #F5A623;
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 12px;
}

/* ── Dividers / separators ──────────────────────────────────────────────── */
QFrame[frameShape="4"],
QFrame[frameShape="HLine"] {
    background-color: #252533;
    border: none;
    max-height: 1px;
}
QFrame[frameShape="5"],
QFrame[frameShape="VLine"] {
    background-color: #252533;
    border: none;
    max-width: 1px;
}

/* ── Menu & context menu ────────────────────────────────────────────────── */
QMenu {
    background-color: #16161f;
    color: #eeeef5;
    border: 1px solid #252533;
    border-radius: 8px;
    padding: 4px;
}
QMenu::item {
    padding: 6px 20px;
    border-radius: 4px;
}
QMenu::item:selected {
    background-color: #1e1e2a;
    color: #F5A623;
}
QMenu::separator {
    background-color: #252533;
    height: 1px;
    margin: 4px 8px;
}

/* ── Input fields ───────────────────────────────────────────────────────── */
QLineEdit, QTextEdit, QPlainTextEdit {
    background-color: #16161f;
    color: #eeeef5;
    border: 1px solid #252533;
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: #F5A623;
    selection-color: #000000;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border-color: #F5A623;
    background-color: #1e1e2a;
}
QLineEdit:disabled {
    color: #4a4a66;
    background-color: #13131a;
}

/* ── ComboBox ────────────────────────────────────────────────────────────── */
QComboBox {
    background-color: #16161f;
    color: #eeeef5;
    border: 1px solid #252533;
    border-radius: 6px;
    padding: 5px 8px;
    min-height: 26px;
}
QComboBox:hover { border-color: #F5A623; }
QComboBox::drop-down {
    border: none;
    width: 22px;
}
QComboBox QAbstractItemView {
    background-color: #16161f;
    color: #eeeef5;
    border: 1px solid #252533;
    border-radius: 6px;
    selection-background-color: #F5A623;
    selection-color: #000000;
    padding: 2px;
}

/* ── Checkboxes ─────────────────────────────────────────────────────────── */
QCheckBox {
    color: #eeeef5;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #252533;
    border-radius: 3px;
    background: #16161f;
}
QCheckBox::indicator:checked {
    background: #F5A623;
    border-color: #F5A623;
}
QCheckBox::indicator:hover {
    border-color: #F5A623;
}

/* ── Progress bars ───────────────────────────────────────────────────────── */
QProgressBar {
    background-color: #252533;
    border: none;
    border-radius: 3px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    background-color: #F5A623;
    border-radius: 3px;
}

/* ── Tab widgets ─────────────────────────────────────────────────────────── */
QTabWidget::pane {
    background-color: #0d0d12;
    border: 1px solid #252533;
    border-radius: 8px;
}
QTabBar::tab {
    background: #16161f;
    color: #8888a8;
    border: 1px solid #252533;
    border-bottom: none;
    padding: 6px 16px;
    border-radius: 6px 6px 0 0;
}
QTabBar::tab:selected {
    background: #F5A623;
    color: #000000;
    font-weight: bold;
}
QTabBar::tab:hover:!selected { color: #eeeef5; }

/* ── Group boxes ─────────────────────────────────────────────────────────── */
QGroupBox {
    background-color: #16161f;
    border: 1px solid #252533;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 8px;
    color: #eeeef5;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    color: #8888a8;
}

/* ── List / tree / table views ───────────────────────────────────────────── */
QListView, QTreeView, QTableView {
    background-color: #0d0d12;
    alternate-background-color: #13131a;
    color: #eeeef5;
    border: 1px solid #252533;
    border-radius: 6px;
    gridline-color: #252533;
}
QHeaderView::section {
    background-color: #16161f;
    color: #8888a8;
    border: none;
    border-bottom: 1px solid #252533;
    padding: 5px 8px;
    font-weight: bold;
    font-size: 11px;
}
QListView::item:selected, QTreeView::item:selected {
    background-color: #1e1e2a;
    color: #F5A623;
    border-radius: 4px;
}
QListView::item:hover, QTreeView::item:hover {
    background-color: #16161f;
}

/* ── Spin boxes ──────────────────────────────────────────────────────────── */
QSpinBox, QDoubleSpinBox {
    background-color: #16161f;
    color: #eeeef5;
    border: 1px solid #252533;
    border-radius: 6px;
    padding: 4px 8px;
}
QSpinBox:focus, QDoubleSpinBox:focus { border-color: #F5A623; }

/* ── Slider ───────────────────────────────────────────────────────────────── */
QSlider::groove:horizontal {
    background: #252533;
    height: 4px;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #F5A623;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::sub-page:horizontal {
    background: #F5A623;
    border-radius: 2px;
}

/* ── Status bar / label strips ───────────────────────────────────────────── */
QStatusBar {
    background-color: #0d0d12;
    color: #8888a8;
    border-top: 1px solid #252533;
}
"""

_LIGHT_QSS_OVERLAY: str = """
/* ══════════════════════════════════════════════════════════════════════════
   YTSpot Light Theme Overlay
   ══════════════════════════════════════════════════════════════════════════ */

QToolTip {
    background-color: #ffffff;
    color: #1a1a1a;
    border: 1px solid #F5A623;
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 12px;
}

QScrollBar:vertical {
    background: #f0f0f5;
    width: 6px;
    border-radius: 3px;
}
QScrollBar::handle:vertical {
    background: #c0c0cc;
    border-radius: 3px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #F5A623; }
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical { height: 0; }

QScrollBar:horizontal {
    background: #f0f0f5;
    height: 6px;
    border-radius: 3px;
}
QScrollBar::handle:horizontal {
    background: #c0c0cc;
    border-radius: 3px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover { background: #F5A623; }
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal { width: 0; }

QProgressBar {
    background-color: #e0e0e8;
    border: none;
    border-radius: 3px;
    color: transparent;
}
QProgressBar::chunk {
    background-color: #F5A623;
    border-radius: 3px;
}
"""

_OLED_QSS_OVERLAY: str = """
/* ══════════════════════════════════════════════════════════════════════════
   YTSpot OLED Overlay – true-black backgrounds for OLED screens
   ══════════════════════════════════════════════════════════════════════════ */

QWidget,
QFrame,
QScrollArea,
QScrollArea > QWidget > QWidget,
QMainWindow,
QDialog,
QDockWidget,
QStackedWidget,
QTabWidget,
QTabWidget::pane {
    background-color: #000000;
}

/* Keep card surfaces a hair off-black for legibility */
QGroupBox,
QListWidget,
QListView,
QTreeView,
QTableView,
QTableWidget {
    background-color: #0a0a0a;
    border-color: #1a1a1a;
}

#navigationPanel,
#navigationWidget {
    background-color: #000000;
}

QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {
    background-color: #0a0a0a;
    border-color: #1e1e1e;
}

QScrollBar:vertical, QScrollBar:horizontal {
    background-color: #000000;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background-color: #2a2a2a;
    border-radius: 3px;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background-color: #F5A623;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; height: 0; }

QMenu {
    background-color: #0a0a0a;
    border-color: #1e1e1e;
}
QMenu::item:selected { background-color: #141414; }

QToolTip {
    background-color: #111111;
    color: #eeeef5;
    border: 1px solid #F5A623;
    border-radius: 6px;
    padding: 5px 10px;
}

QProgressBar {
    background-color: #1a1a1a;
    border: none;
    border-radius: 3px;
    color: transparent;
}
QProgressBar::chunk {
    background-color: #F5A623;
    border-radius: 3px;
}
"""

# ──────────────────────────────────────────────────────────────────────────────
# Cycle order
# ──────────────────────────────────────────────────────────────────────────────

_CYCLE_ORDER: list[str] = ["dark", "light", "oled"]


# ──────────────────────────────────────────────────────────────────────────────
# ThemeManager
# ──────────────────────────────────────────────────────────────────────────────

class ThemeManager:
    """
    Manages Dark / Light / OLED theme switching for the application.

    Parameters
    ----------
    config : AppConfig
        The live application config instance.  ThemeManager reads the initial
        theme from config.theme and writes back on every change.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config  = config
        self._current = config.theme
        self._set_accent()

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def current(self) -> str:
        return self._current

    def apply(self, theme_name: str) -> None:
        """Switch to theme_name immediately and persist."""
        if theme_name not in ("dark", "light", "oled"):
            theme_name = "dark"

        self._current = theme_name

        fluent_theme = Theme.LIGHT if theme_name == "light" else Theme.DARK
        setTheme(fluent_theme)
        self._set_accent()
        self._apply_qss(theme_name)

        self._config.theme = theme_name
        self._config.save()

    def cycle(self) -> str:
        """Advance to the next theme (dark → light → oled → dark) and apply."""
        idx  = _CYCLE_ORDER.index(self._current) if self._current in _CYCLE_ORDER else 0
        next_theme = _CYCLE_ORDER[(idx + 1) % len(_CYCLE_ORDER)]
        self.apply(next_theme)
        return next_theme

    def theme_display_label(self) -> str:
        return {"dark": "🌙  Dark", "light": "☀️  Light", "oled": "⚫  OLED"}.get(
            self._current, "🌙  Dark"
        )

    def next_theme_label(self) -> str:
        idx  = _CYCLE_ORDER.index(self._current) if self._current in _CYCLE_ORDER else 0
        next_theme = _CYCLE_ORDER[(idx + 1) % len(_CYCLE_ORDER)]
        return {"dark": "🌙  Dark", "light": "☀️  Light", "oled": "⚫  OLED"}.get(
            next_theme, "🌙  Dark"
        )

    def is_dark_variant(self) -> bool:
        return self._current in ("dark", "oled")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _set_accent(self) -> None:
        setThemeColor(ACCENT_COLOR)

    @staticmethod
    def _apply_qss(theme_name: str) -> None:
        app = QApplication.instance()
        if app is None:
            return

        if theme_name == "oled":
            qss = _DARK_QSS_OVERLAY + _OLED_QSS_OVERLAY
        elif theme_name == "light":
            qss = _LIGHT_QSS_OVERLAY
        else:
            qss = _DARK_QSS_OVERLAY

        app.setStyleSheet(qss)
