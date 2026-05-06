"""
ui/theme_manager.py  –  Application-wide theme engine  (v3)
============================================================
Changelog v3
------------
* Vibrant Light Theme: completely redesigned with soft gradient surfaces,
  colorful pastel cards, and rich accent-driven highlights — no more gray.
* Custom Accent Colors: ThemeManager.set_accent(name_or_hex) lets the user
  choose from a curated palette (Amber, Emerald, Violet, Rose, Ocean) or
  supply any hex code.  All QSS overlays are rebuilt dynamically on change.
* Accent palette is exported as ACCENT_PALETTE (name → hex) so the Settings
  panel can render a swatch picker without hard-coding colors.
* ThemeManager.apply() signature unchanged — no callers need updating.
* Dead code removed.  Strict type hints.  Modular QSS builders.

Design Token Summary
--------------------
Dark  : deep cool-purple near-black surfaces + accent-driven highlights
Light : warm ivory/lavender base, colorful gradient cards, vivid accents
OLED  : true-black (#000) for OLED screens

Light Theme Palette (default Amber accent)
------------------------------------------
  _L_BG        = #faf9ff  – warm ivory-lavender base
  _L_SURFACE   = #ffffff  – pure-white card surface
  _L_SURFACE2  = #f0eeff  – soft lavender hover / elevated
  _L_BORDER    = #e2ddf8  – delicate periwinkle border
  _L_TEXT      = #1a1830  – deep indigo-black primary text
  _L_TEXT2     = #6b65a0  – medium muted purple-gray
  _L_TEXT3     = #b5b0d4  – light disabled text
  _L_ACCENT    = (dynamic) – user-chosen accent
  _L_GRAD_A    = #ede9ff  – gradient card start (soft violet)
  _L_GRAD_B    = #fff4e6  – gradient card end   (warm peach)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from qfluentwidgets import setTheme, setThemeColor, Theme

from config import AppConfig


# ──────────────────────────────────────────────────────────────────────────────
# Accent palette  (name → hex)
# ──────────────────────────────────────────────────────────────────────────────

ACCENT_PALETTE: Final[dict[str, str]] = {
    "Amber":  "#F5A623",   # original brand colour
    "Emerald": "#10b981",
    "Violet":  "#7c3aed",
    "Rose":    "#f43f5e",
    "Ocean":   "#0ea5e9",
    "Coral":   "#ff6b6b",
    "Mint":    "#06d6a0",
    "Gold":    "#f59e0b",
}

# Default accent (brand colour)
ACCENT_COLOR:     str = ACCENT_PALETTE["Amber"]
ACCENT_COLOR_DIM: str = "#C47D0E"   # dimmed variant – recomputed on accent change

# Semantic colours (theme-independent)
SUCCESS_COLOR:    str = "#10b981"
ERROR_COLOR:      str = "#ef4444"
WARNING_COLOR:    str = "#f59e0b"
PROCESSING_COLOR: str = "#8b5cf6"

# Dark-mode design token exports (consumed by component files)
BG_DARK:       str = "#0d0d12"
SURFACE_DARK:  str = "#16161f"
SURFACE2_DARK: str = "#1e1e2a"
BORDER_DARK:   str = "#252533"
TEXT_DARK:     str = "#eeeef5"
TEXT2_DARK:    str = "#8888a8"
TEXT3_DARK:    str = "#4a4a66"

# Light-mode design token exports
BG_LIGHT:       str = "#faf9ff"
SURFACE_LIGHT:  str = "#ffffff"
SURFACE2_LIGHT: str = "#f0eeff"
BORDER_LIGHT:   str = "#e2ddf8"
TEXT_LIGHT:     str = "#1a1830"
TEXT2_LIGHT:    str = "#6b65a0"
TEXT3_LIGHT:    str = "#b5b0d4"

_CYCLE_ORDER: list[str] = ["dark", "light", "oled"]


# ──────────────────────────────────────────────────────────────────────────────
# Theme-aware colour helper
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ThemeColors:
    bg:            str
    surface:       str
    surface2:      str
    border:        str
    text_primary:  str
    text_secondary: str
    text_tertiary: str
    accent:        str


def get_colors() -> "ThemeColors":
    """Return the correct colour set for the current theme (dark or light/oled)."""
    inst = ThemeManager._instance  # noqa: SLF001
    dark = (inst._current in ("dark", "oled")) if inst else True  # noqa: SLF001
    return ThemeColors(
        bg            = BG_DARK       if dark else BG_LIGHT,
        surface       = SURFACE_DARK  if dark else SURFACE_LIGHT,
        surface2      = SURFACE2_DARK if dark else SURFACE2_LIGHT,
        border        = BORDER_DARK   if dark else BORDER_LIGHT,
        text_primary  = TEXT_DARK     if dark else TEXT_LIGHT,
        text_secondary = TEXT2_DARK   if dark else TEXT2_LIGHT,
        text_tertiary = TEXT3_DARK    if dark else TEXT3_LIGHT,
        accent        = ACCENT_COLOR,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _dim_hex(hex_color: str, factor: float = 0.75) -> str:
    """Return a darkened version of a hex color (for hover/dim states)."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r2 = max(0, int(r * factor))
    g2 = max(0, int(g * factor))
    b2 = max(0, int(b * factor))
    return f"#{r2:02x}{g2:02x}{b2:02x}"


def _lighten_hex(hex_color: str, alpha_hex: str = "22") -> str:
    """Return color + alpha suffix for rgba simulation via QSS hex8."""
    return f"{hex_color}{alpha_hex}"


# ──────────────────────────────────────────────────────────────────────────────
# QSS builders  (dynamic – rebuilt when accent changes)
# ──────────────────────────────────────────────────────────────────────────────

def _build_dark_qss(accent: str) -> str:
    dim = _dim_hex(accent)
    return f"""
/* ══════════════════════════════════════════════════════════════════════════
   YTSpot Dark Theme  v3  (deep purple-tinted premium palette)
   ══════════════════════════════════════════════════════════════════════════ */

QWidget {{
    background-color: #0d0d12;
    color: #eeeef5;
    selection-background-color: {accent};
    selection-color: #000000;
}}

QScrollArea, QScrollArea > QWidget > QWidget, QAbstractScrollArea {{
    background-color: #0d0d12;
    border: none;
}}

/* Thin modern scrollbars */
QScrollBar:vertical {{
    background: #0d0d12; width: 6px; border-radius: 3px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #252533; border-radius: 3px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {accent}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QScrollBar:horizontal {{
    background: #0d0d12; height: 6px; border-radius: 3px; margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: #252533; border-radius: 3px; min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{ background: {accent}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QToolTip {{
    background-color: #1e1e2a;
    color: #eeeef5;
    border: 1px solid {accent};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 12px;
}}

QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: #16161f;
    color: #eeeef5;
    border: 1px solid #252533;
    border-radius: 7px;
    padding: 6px 10px;
    selection-background-color: {accent};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {accent};
}}

QComboBox {{
    background-color: #16161f;
    color: #eeeef5;
    border: 1px solid #252533;
    border-radius: 7px;
    padding: 5px 10px;
}}
QComboBox:focus {{ border-color: {accent}; }}
QComboBox QAbstractItemView {{
    background-color: #16161f;
    color: #eeeef5;
    border: 1px solid #252533;
    selection-background-color: {accent};
    selection-color: #000000;
}}

QCheckBox {{ color: #eeeef5; spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 2px solid #252533;
    border-radius: 4px;
    background: #16161f;
}}
QCheckBox::indicator:checked {{
    background-color: {accent};
    border-color: {accent};
}}

QGroupBox {{
    border: 1px solid #252533;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 8px;
    color: #8888a8;
    font-size: 11px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: {accent};
}}

QProgressBar {{
    background-color: #1e1e2a;
    border: none;
    border-radius: 3px;
    color: transparent;
    height: 6px;
}}
QProgressBar::chunk {{
    background-color: {accent};
    border-radius: 3px;
}}

QStatusBar {{
    background-color: #0d0d12;
    color: #8888a8;
    border-top: 1px solid #252533;
}}

QMenu {{
    background-color: #16161f;
    color: #eeeef5;
    border: 1px solid #252533;
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{ padding: 6px 20px; border-radius: 4px; }}
QMenu::item:selected {{ background-color: #1e1e2a; color: {accent}; }}
QMenu::separator {{ background-color: #252533; height: 1px; margin: 4px 8px; }}

QSpinBox, QDoubleSpinBox {{
    background-color: #16161f;
    color: #eeeef5;
    border: 1px solid #252533;
    border-radius: 6px;
    padding: 4px 8px;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {accent}; }}

QSlider::groove:horizontal {{
    background: #252533; height: 4px; border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {accent};
    width: 14px; height: 14px;
    margin: -5px 0; border-radius: 7px;
}}
QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 2px; }}
"""


def _build_light_qss(accent: str) -> str:
    """
    Build the vibrant Light Mode QSS overlay.

    Design vision
    -------------
    * Warm ivory-lavender base (#faf9ff) – feels airy, not sterile
    * Pure-white cards that pop off the base
    * Soft periwinkle borders that fade into the background
    * Accent colour drives every interactive element: focus rings,
      progress chunks, hover tints, selection highlights
    * Gradient header stripe on key containers (lavender → warm peach)
    * Colorful platform badges, vivid status indicators

    The goal: looks like a modern music app with a light, Material-inspired
    personality.
    """
    dim   = _dim_hex(accent)
    faint = accent + "1a"   # 10 % opacity QSS hex8 approximation (not CSS)
    return f"""
/* ══════════════════════════════════════════════════════════════════════════
   YTSpot Light Theme  v3  (vibrant, colorful, premium)
   ══════════════════════════════════════════════════════════════════════════ */

/* ── Global ────────────────────────────────────────────────────────────── */
QWidget {{
    background-color: #faf9ff;
    color: #1a1830;
    selection-background-color: {accent};
    selection-color: #ffffff;
    font-family: "Segoe UI", "SF Pro Display", system-ui, sans-serif;
}}

QMainWindow, QDialog, QDockWidget {{
    background-color: #faf9ff;
}}

/* ── Scroll areas ─────────────────────────────────────────────────────── */
QScrollArea, QScrollArea > QWidget > QWidget, QAbstractScrollArea {{
    background-color: #faf9ff;
    border: none;
}}

/* ── Scrollbars (thin, colorful) ──────────────────────────────────────── */
QScrollBar:vertical {{
    background: #ede9ff;
    width: 7px;
    border-radius: 3px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #c8c0f0;
    border-radius: 3px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {accent}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QScrollBar:horizontal {{
    background: #ede9ff;
    height: 7px;
    border-radius: 3px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: #c8c0f0;
    border-radius: 3px;
    min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{ background: {accent}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ── Tooltips ─────────────────────────────────────────────────────────── */
QToolTip {{
    background-color: #ffffff;
    color: #1a1830;
    border: 1.5px solid {accent};
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 500;
}}

/* ── Cards / Frames ───────────────────────────────────────────────────── */
QFrame {{
    background-color: #ffffff;
    border: 1px solid #e2ddf8;
    border-radius: 12px;
}}

/* ── Inputs ───────────────────────────────────────────────────────────── */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: #ffffff;
    color: #1a1830;
    border: 1.5px solid #e2ddf8;
    border-radius: 9px;
    padding: 7px 12px;
    selection-background-color: {accent};
    selection-color: #ffffff;
}}
QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover {{
    border-color: #c8c0f0;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 2px solid {accent};
    background-color: #fff8f0;
}}

/* ── ComboBox ─────────────────────────────────────────────────────────── */
QComboBox {{
    background-color: #ffffff;
    color: #1a1830;
    border: 1.5px solid #e2ddf8;
    border-radius: 9px;
    padding: 6px 12px;
    min-width: 80px;
}}
QComboBox:hover {{ border-color: #c8c0f0; }}
QComboBox:focus {{ border: 2px solid {accent}; }}
QComboBox::drop-down {{
    border: none;
    padding-right: 10px;
}}
QComboBox QAbstractItemView {{
    background-color: #ffffff;
    color: #1a1830;
    border: 1.5px solid #e2ddf8;
    border-radius: 8px;
    selection-background-color: {accent};
    selection-color: #ffffff;
    padding: 4px;
}}

/* ── CheckBox ─────────────────────────────────────────────────────────── */
QCheckBox {{ color: #1a1830; spacing: 8px; }}
QCheckBox::indicator {{
    width: 17px; height: 17px;
    border: 2px solid #c8c0f0;
    border-radius: 5px;
    background: #ffffff;
}}
QCheckBox::indicator:hover {{ border-color: {accent}; }}
QCheckBox::indicator:checked {{
    background-color: {accent};
    border-color: {accent};
}}

/* ── GroupBox ─────────────────────────────────────────────────────────── */
QGroupBox {{
    background-color: #f5f2ff;
    border: 1.5px solid #e2ddf8;
    border-radius: 12px;
    margin-top: 14px;
    padding-top: 10px;
    font-size: 11px;
    font-weight: 600;
    color: #6b65a0;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 10px;
    color: {accent};
    font-weight: 700;
    font-size: 12px;
}}

/* ── Progress bars  (vivid) ───────────────────────────────────────────── */
QProgressBar {{
    background-color: #ede9ff;
    border: none;
    border-radius: 5px;
    color: transparent;
    height: 8px;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {accent}, stop:1 {dim});
    border-radius: 5px;
}}

/* ── Status bar ───────────────────────────────────────────────────────── */
QStatusBar {{
    background-color: #f0eeff;
    color: #6b65a0;
    border-top: 1px solid #e2ddf8;
    font-size: 12px;
}}

/* ── Menu ─────────────────────────────────────────────────────────────── */
QMenu {{
    background-color: #ffffff;
    color: #1a1830;
    border: 1.5px solid #e2ddf8;
    border-radius: 10px;
    padding: 5px;
}}
QMenu::item {{
    padding: 7px 22px;
    border-radius: 6px;
    font-size: 13px;
}}
QMenu::item:selected {{
    background-color: #f0eeff;
    color: {accent};
    font-weight: 600;
}}
QMenu::separator {{
    background-color: #e2ddf8;
    height: 1px;
    margin: 4px 10px;
}}

/* ── SpinBox ──────────────────────────────────────────────────────────── */
QSpinBox, QDoubleSpinBox {{
    background-color: #ffffff;
    color: #1a1830;
    border: 1.5px solid #e2ddf8;
    border-radius: 7px;
    padding: 5px 10px;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {accent}; }}

/* ── Slider ───────────────────────────────────────────────────────────── */
QSlider::groove:horizontal {{
    background: #e2ddf8;
    height: 5px;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {accent};
    width: 15px; height: 15px;
    margin: -5px 0;
    border-radius: 8px;
}}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {accent}, stop:1 {dim});
    border-radius: 2px;
}}

/* ── Table / List views ───────────────────────────────────────────────── */
QTableView, QListView, QTreeView {{
    background-color: #ffffff;
    alternate-background-color: #f8f6ff;
    border: 1px solid #e2ddf8;
    border-radius: 8px;
    gridline-color: #f0eeff;
    color: #1a1830;
}}
QHeaderView::section {{
    background-color: #f0eeff;
    color: #6b65a0;
    border: none;
    border-bottom: 2px solid {accent};
    padding: 6px 10px;
    font-weight: 600;
    font-size: 12px;
}}
QTableView::item:selected, QListView::item:selected, QTreeView::item:selected {{
    background-color: {accent};
    color: #ffffff;
    border-radius: 4px;
}}

/* ── Navigation panel ─────────────────────────────────────────────────── */
#navigationPanel, #navigationWidget {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #ede9ff, stop:1 #fff4e6);
    border-right: 1px solid #e2ddf8;
}}

/* ── Tab widget ───────────────────────────────────────────────────────── */
QTabBar::tab {{
    background: #f0eeff;
    color: #6b65a0;
    border: 1px solid #e2ddf8;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 8px 18px;
    font-weight: 500;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: #ffffff;
    color: {accent};
    font-weight: 700;
    border-bottom: 3px solid {accent};
}}
QTabBar::tab:hover:!selected {{
    background: #e8e3ff;
    color: {accent};
}}
QTabWidget::pane {{
    background-color: #ffffff;
    border: 1px solid #e2ddf8;
    border-radius: 0 8px 8px 8px;
}}

/* ── Push buttons ─────────────────────────────────────────────────────── */
QPushButton {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {accent}, stop:1 {dim});
    color: #ffffff;
    border: none;
    border-radius: 9px;
    padding: 8px 20px;
    font-weight: 600;
    font-size: 13px;
}}
QPushButton:hover {{
    background: {dim};
}}
QPushButton:pressed {{
    background: {_dim_hex(accent, 0.60)};
}}
QPushButton:disabled {{
    background: #e2ddf8;
    color: #b5b0d4;
}}
QPushButton[flat="true"] {{
    background: transparent;
    color: {accent};
    border: 1.5px solid {accent};
    border-radius: 9px;
}}
QPushButton[flat="true"]:hover {{
    background: #f0eeff;
}}
"""


def _build_oled_qss(accent: str) -> str:
    return f"""
/* ══════════════════════════════════════════════════════════════════════════
   YTSpot OLED Theme  v3  (true-black for OLED displays)
   ══════════════════════════════════════════════════════════════════════════ */

QWidget, QFrame, QScrollArea, QScrollArea > QWidget > QWidget,
QMainWindow, QDialog, QDockWidget, QStackedWidget,
QTabWidget, QTabWidget::pane {{
    background-color: #000000;
}}

QGroupBox, QListWidget, QListView, QTreeView, QTableView, QTableWidget {{
    background-color: #0a0a0a;
    border-color: #1a1a1a;
}}

#navigationPanel, #navigationWidget {{ background-color: #000000; }}

QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {{
    background-color: #0a0a0a;
    border-color: #1e1e1e;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QComboBox:focus {{ border-color: {accent}; }}

QScrollBar:vertical, QScrollBar:horizontal {{ background-color: #000000; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background-color: #2a2a2a; border-radius: 3px;
}}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
    background-color: {accent};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; height: 0; }}

QMenu {{ background-color: #0a0a0a; border-color: #1e1e1e; }}
QMenu::item:selected {{ background-color: #141414; color: {accent}; }}

QToolTip {{
    background-color: #111111;
    color: #eeeef5;
    border: 1px solid {accent};
    border-radius: 6px;
    padding: 5px 10px;
}}

QProgressBar {{
    background-color: #1a1a1a;
    border: none; border-radius: 3px; color: transparent;
}}
QProgressBar::chunk {{ background-color: {accent}; border-radius: 3px; }}

QPushButton {{
    background-color: {accent};
    color: #000000;
    border: none; border-radius: 8px;
    padding: 8px 18px; font-weight: 600;
}}
QPushButton:hover {{ background-color: {_dim_hex(accent)}; }}
"""


# ──────────────────────────────────────────────────────────────────────────────
# ThemeManager
# ──────────────────────────────────────────────────────────────────────────────

class ThemeManager(QObject):
    """
    Manages Dark / Light / OLED theme switching with dynamic accent colours.
    Singleton: obtain via ThemeManager.instance() after the first construction.

    Signals
    -------
    theme_changed  emitted whenever the theme or accent changes.

    Usage
    -----
    >>> tm = ThemeManager(config)          # first call creates the singleton
    >>> ThemeManager.instance()            # subsequent calls return same object
    >>> tm.apply("light")
    >>> tm.set_accent("Violet")
    >>> tm.cycle()
    """

    theme_changed = Signal()
    _instance: "Optional[ThemeManager]" = None

    @classmethod
    def instance(cls) -> "Optional[ThemeManager]":
        return cls._instance

    def __init__(self, config: AppConfig, parent: "Optional[QObject]" = None) -> None:
        super().__init__(parent)
        ThemeManager._instance = self
        self._config  = config
        self._current = config.theme
        saved_accent = getattr(config, "accent_color", None)
        self._accent  = saved_accent if saved_accent else ACCENT_COLOR
        self._apply_fluent()

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def current(self) -> str:
        return self._current

    @property
    def accent(self) -> str:
        return self._accent

    def apply(self, theme_name: str) -> None:
        """Switch to theme_name immediately and persist to config."""
        if theme_name not in ("dark", "light", "oled"):
            theme_name = "dark"
        self._current = theme_name
        self._apply_fluent()
        self._apply_qss()
        self._config.theme = theme_name
        self._config.save()
        self.theme_changed.emit()

    def cycle(self) -> str:
        """Advance to the next theme (dark → light → oled → dark) and apply."""
        try:
            idx = _CYCLE_ORDER.index(self._current)
        except ValueError:
            idx = 0
        next_theme = _CYCLE_ORDER[(idx + 1) % len(_CYCLE_ORDER)]
        self.apply(next_theme)
        return next_theme

    def set_accent(self, name_or_hex: str) -> None:
        """
        Change the active accent colour and rebuild all QSS immediately.

        Parameters
        ----------
        name_or_hex : A key from ACCENT_PALETTE (e.g. "Violet") or any valid
                      hex string (e.g. "#7c3aed").  Both "#" and bare hex
                      strings are accepted.
        """
        if name_or_hex in ACCENT_PALETTE:
            resolved = ACCENT_PALETTE[name_or_hex]
        elif name_or_hex.startswith("#") and len(name_or_hex) in (4, 7):
            resolved = name_or_hex
        elif len(name_or_hex) in (3, 6):
            resolved = f"#{name_or_hex}"
        else:
            return   # invalid – ignore silently

        self._accent = resolved
        # Persist if AppConfig has the field
        if hasattr(self._config, "accent_color"):
            self._config.accent_color = resolved
            self._config.save()

        self._apply_fluent()
        self._apply_qss()
        self.theme_changed.emit()

    def theme_display_label(self) -> str:
        return {"dark": "🌙  Dark", "light": "☀️  Light", "oled": "⚫  OLED"}.get(
            self._current, "🌙  Dark"
        )

    def next_theme_label(self) -> str:
        try:
            idx = _CYCLE_ORDER.index(self._current)
        except ValueError:
            idx = 0
        nxt = _CYCLE_ORDER[(idx + 1) % len(_CYCLE_ORDER)]
        return {"dark": "🌙  Dark", "light": "☀️  Light", "oled": "⚫  OLED"}.get(
            nxt, "🌙  Dark"
        )

    def is_dark_variant(self) -> bool:
        return self._current in ("dark", "oled")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _apply_fluent(self) -> None:
        """Sync QFluentWidgets built-in theme + accent colour."""
        fluent_theme = Theme.LIGHT if self._current == "light" else Theme.DARK
        setTheme(fluent_theme)
        setThemeColor(self._accent)

    def _apply_qss(self) -> None:
        """Rebuild and apply the QSS overlay for the current theme + accent."""
        app = QApplication.instance()
        if app is None:
            return

        if self._current == "oled":
            qss = _build_dark_qss(self._accent) + _build_oled_qss(self._accent)
        elif self._current == "light":
            qss = _build_light_qss(self._accent)
        else:
            qss = _build_dark_qss(self._accent)

        app.setStyleSheet(qss)
