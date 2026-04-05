"""
ui/theme_manager.py  –  Application-wide theme engine
======================================================
Responsibilities
----------------
* Apply Dark / Light / OLED themes by coordinating between QFluentWidgets'
  built-in theme system and a supplementary QSS layer for OLED-black
  background overrides.
* Expose a single apply(theme_name) method that is safe to call at any time
  (startup, settings save, or theme-cycle button click) without restarting
  the app.
* Persist the chosen theme back to AppConfig on every change.
* Provide the amber accent colour (#F5A623) that matches the existing brand
  identity established in the original CustomTkinter UI.
* Expose a cycle() method that rotates dark → light → oled → dark so a
  single toolbar button can act as a three-way toggle.

Design decisions
----------------
* Single source of truth: ThemeManager owns the theme state; AppConfig is
  only written here, never read for theme decisions after __init__.
* QFluentWidgets setTheme() + setThemeColor() cover ~95% of all surfaces.
  The remaining 5% (pure Qt native widgets used inside Fluent containers)
  are handled by a targeted QSS override injected via
  QApplication.setStyleSheet(), which is additive and does not clobber
  Fluent's own QSS.
* OLED mode reuses Theme.DARK from Fluent and then overrides every
  background token to #000000 via QSS.  This keeps Fluent's animation
  and border logic intact while achieving true-black for OLED screens.
* The accent colour is set once and never overridden by theme switching,
  so the amber brand colour persists across dark/light/oled transitions.

Usage
-----
>>> mgr = ThemeManager(config)
>>> mgr.apply("dark")     # on startup
>>> mgr.apply("light")    # after settings save
>>> new_theme = mgr.cycle()  # amber button in toolbar
>>> print(mgr.current)    # "light" / "dark" / "oled"
"""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication
from qfluentwidgets import setTheme, setThemeColor, Theme

from config import AppConfig


# ──────────────────────────────────────────────────────────────────────────────
# Brand constants  (single definition used everywhere in the UI layer)
# ──────────────────────────────────────────────────────────────────────────────

ACCENT_COLOR: str = "#F5A623"          # Amber – matches the original Tk palette
ACCENT_COLOR_DIM: str = "#C47D0E"      # Dimmed amber for hover states

# ──────────────────────────────────────────────────────────────────────────────
# QSS overlay fragments
# ──────────────────────────────────────────────────────────────────────────────

# ── Updated design tokens (modern dark palette) ────────────────────────────
# _BG      = #111114   — slightly warm near-black
# _SURFACE = #1c1c21   — card / panel surfaces
# _BORDER  = #313139   — borders and dividers
# _TEXT    = #f2f2f5   — primary text
# _TEXT_2  = #94949e   — secondary / caption text
# _TEXT_3  = #5a5a66   — muted / disabled text

# Applied on top of Fluent's own QSS in DARK mode.
# Keeps Fluent's border, radius, and animation rules; only targets backgrounds
# that Fluent leaves as system-default (typically raw QWidget / QFrame).
_DARK_QSS_OVERLAY: str = """
/* ── YTSpot Dark overlay ─────────────────────────────────────────────────── */
QWidget {
    background-color: #111114;
    color: #f2f2f5;
}
QScrollArea, QScrollArea > QWidget > QWidget {
    background-color: #111114;
}
QToolTip {
    background-color: #232329;
    color: #f2f2f5;
    border: 1px solid #313139;
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 12px;
}
QScrollBar:vertical {
    background: #111114;
    width: 6px;
    border-radius: 3px;
}
QScrollBar::handle:vertical {
    background: #313139;
    border-radius: 3px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #3e3e47; }
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical { height: 0; }
"""

# LIGHT mode overlay – minimal; Fluent handles almost everything natively.
_LIGHT_QSS_OVERLAY: str = """
/* ── YTSpot Light overlay ────────────────────────────────────────────────── */
QToolTip {
    background-color: #ffffff;
    color: #1a1a1a;
    border: 1px solid #d0d0d8;
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 12px;
}
"""

# OLED mode: true-black (#000000) backgrounds for every major surface.
# Builds on top of _DARK_QSS_OVERLAY (both are applied together in OLED mode).
_OLED_QSS_OVERLAY: str = """
/* ── YTSpot OLED overlay (true-black) ───────────────────────────────────── */
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
/* Keep card surfaces subtly off-black so text is still legible */
QGroupBox,
QListWidget,
QListView,
QTreeView,
QTableView,
QTableWidget {
    background-color: #0a0a0a;
    border: 1px solid #1a1a1a;
}
/* Fluent NavigationPanel uses its own surface colour; override via object name */
#navigationPanel,
#navigationWidget {
    background-color: #000000;
}
QToolTip {
    background-color: #111111;
    color: #f2f2f5;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 12px;
}
QScrollBar:vertical,
QScrollBar:horizontal {
    background-color: #000000;
}
QScrollBar::handle:vertical,
QScrollBar::handle:horizontal {
    background-color: #2a2a2a;
    border-radius: 3px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover,
QScrollBar::handle:horizontal:hover {
    background-color: #3a3a3a;
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

    Example
    -------
    >>> mgr = ThemeManager(config)
    >>> mgr.apply(config.theme)          # restore saved theme at startup
    >>> new_theme = mgr.cycle()          # user clicks the theme button
    >>> print(mgr.current)               # "light"
    """

    def __init__(self, config: AppConfig) -> None:
        self._config  = config
        self._current = config.theme     # "dark" | "light" | "oled"
        # Apply the accent colour once; it survives all subsequent apply() calls
        self._set_accent()

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def current(self) -> str:
        """The name of the currently active theme: 'dark' | 'light' | 'oled'."""
        return self._current

    def apply(self, theme_name: str) -> None:
        """
        Switch the application to `theme_name` immediately.

        Safe to call from the main thread at any time – QFluentWidgets
        re-polishes all live widgets synchronously when setTheme() is called.

        Parameters
        ----------
        theme_name : "dark" | "light" | "oled"
            Any other value is silently treated as "dark".
        """
        if theme_name not in ("dark", "light", "oled"):
            theme_name = "dark"

        self._current = theme_name

        # 1. Tell QFluentWidgets which base theme to use
        #    OLED uses Theme.DARK as its base; our QSS layer does the rest.
        fluent_theme = (
            Theme.LIGHT if theme_name == "light" else Theme.DARK
        )
        setTheme(fluent_theme)

        # 2. Re-apply accent colour (setTheme() may reset it internally)
        self._set_accent()

        # 3. Inject our QSS overlay for the selected theme
        self._apply_qss(theme_name)

        # 4. Persist the choice
        self._config.theme = theme_name
        self._config.save()

    def cycle(self) -> str:
        """
        Advance to the next theme in the rotation (dark → light → oled → dark)
        and apply it immediately.

        Returns
        -------
        str
            The name of the newly active theme.
        """
        current_index = _CYCLE_ORDER.index(self._current) \
            if self._current in _CYCLE_ORDER else 0
        next_index = (current_index + 1) % len(_CYCLE_ORDER)
        next_theme = _CYCLE_ORDER[next_index]
        self.apply(next_theme)
        return next_theme

    def theme_display_label(self) -> str:
        """
        Return a short, emoji-prefixed label for the current theme suitable
        for display on a toolbar button or settings card.

        Returns e.g. "🌙 Dark", "☀️ Light", "⚫ OLED".
        """
        return {
            "dark":  "🌙  Dark",
            "light": "☀️  Light",
            "oled":  "⚫  OLED",
        }.get(self._current, "🌙  Dark")

    def next_theme_label(self) -> str:
        """
        Return the display label for the NEXT theme in the rotation,
        useful for setting tooltip text on a cycle button.
        """
        current_index = _CYCLE_ORDER.index(self._current) \
            if self._current in _CYCLE_ORDER else 0
        next_index = (current_index + 1) % len(_CYCLE_ORDER)
        next_theme = _CYCLE_ORDER[next_index]
        return {
            "dark":  "🌙  Dark",
            "light": "☀️  Light",
            "oled":  "⚫  OLED",
        }.get(next_theme, "🌙  Dark")

    def is_dark_variant(self) -> bool:
        """
        Return True for themes that use a dark background ("dark" and "oled").
        Useful for conditional icon selection (white vs. dark icons).
        """
        return self._current in ("dark", "oled")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _set_accent(self) -> None:
        """Set the global Fluent accent colour to the YTSpot amber brand colour."""
        setThemeColor(ACCENT_COLOR)

    @staticmethod
    def _apply_qss(theme_name: str) -> None:
        """
        Compose and inject the correct QSS overlay for the given theme.

        The overlay is additive: it appends to (or replaces) any previously
        set application-level stylesheet without touching Fluent's internal
        per-widget QSS.  We replace the whole sheet each call so there is no
        accumulation of stale rules across successive theme switches.
        """
        app = QApplication.instance()
        if app is None:
            return

        if theme_name == "oled":
            # OLED = Dark overlay + OLED true-black override
            qss = _DARK_QSS_OVERLAY + _OLED_QSS_OVERLAY
        elif theme_name == "light":
            qss = _LIGHT_QSS_OVERLAY
        else:
            # "dark" (default)
            qss = _DARK_QSS_OVERLAY

        app.setStyleSheet(qss)


# ──────────────────────────────────────────────────────────────────────────────
# Smoke-test  (python -m ui.theme_manager)
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
    from PySide6.QtCore import QTimer

    # Minimal AppConfig stub so we can test without a real config file
    class _StubConfig:
        theme: str = "dark"
        def save(self) -> None:
            print(f"  [config.save()]  theme persisted as: {self.theme!r}")

    print("=" * 60)
    print("ThemeManager  –  smoke-test (visual)")
    print("=" * 60)
    print()

    app = QApplication(sys.argv)
    cfg = _StubConfig()
    mgr = ThemeManager(cfg)  # type: ignore[arg-type]

    # ── Offline assertions (no window required) ───────────────────────────────
    print("── 1. cycle() rotation ──")
    assert mgr.current == "dark",  f"Expected 'dark', got {mgr.current!r}"

    n1 = mgr.cycle()
    assert n1 == "light",  f"dark → expected 'light', got {n1!r}"
    assert cfg.theme == "light", "Config not updated after cycle()"
    print(f"  dark  → cycle() → {n1!r}  ✅")

    n2 = mgr.cycle()
    assert n2 == "oled",  f"light → expected 'oled', got {n2!r}"
    print(f"  light → cycle() → {n2!r}  ✅")

    n3 = mgr.cycle()
    assert n3 == "dark",  f"oled → expected 'dark', got {n3!r}"
    print(f"  oled  → cycle() → {n3!r}  ✅")
    print()

    print("── 2. apply() with invalid name defaults to 'dark' ──")
    mgr.apply("nonsense")
    assert mgr.current == "dark", f"Expected 'dark', got {mgr.current!r}"
    print("  apply('nonsense') → 'dark'  ✅")
    print()

    print("── 3. is_dark_variant() ──")
    mgr.apply("dark")
    assert mgr.is_dark_variant() is True
    mgr.apply("oled")
    assert mgr.is_dark_variant() is True
    mgr.apply("light")
    assert mgr.is_dark_variant() is False
    print("  dark → True, oled → True, light → False  ✅")
    print()

    print("── 4. theme_display_label() / next_theme_label() ──")
    mgr.apply("dark")
    label = mgr.theme_display_label()
    next_label = mgr.next_theme_label()
    print(f"  current label : {label!r}")
    print(f"  next label    : {next_label!r}")
    assert "Dark"  in label,       "Expected 'Dark' in current label"
    assert "Light" in next_label,  "Expected 'Light' in next label"
    print("  ✅")
    print()

    print("── 5. Visual window (cycles through themes automatically) ──")

    # Build a minimal Fluent window so we can see the QSS changes live
    window = QWidget()
    window.setWindowTitle("ThemeManager visual test")
    window.setMinimumSize(480, 200)
    layout = QVBoxLayout(window)

    info_label = QLabel()
    info_label.setWordWrap(True)
    layout.addWidget(info_label)

    theme_order = ["dark", "light", "oled"]
    _idx = [0]

    def _switch_theme() -> None:
        theme = theme_order[_idx[0] % len(theme_order)]
        mgr.apply(theme)
        info_label.setText(
            f"Active theme : {mgr.theme_display_label()}\n"
            f"Next theme   : {mgr.next_theme_label()}\n"
            f"Dark variant : {mgr.is_dark_variant()}\n\n"
            f"(Window will auto-cycle through all three themes)"
        )
        window.setWindowTitle(f"ThemeManager – {mgr.theme_display_label()}")
        _idx[0] += 1

    _switch_theme()   # apply immediately
    window.show()

    # Auto-cycle every 1.5 s so each theme is visible for inspection
    timer = QTimer()
    timer.setInterval(1500)
    timer.timeout.connect(_switch_theme)
    timer.start()

    # Close after three full cycles (9 switches × 1.5 s = 13.5 s)
    QTimer.singleShot(13_500, app.quit)

    print("  Window opened – cycling Dark → Light → OLED every 1.5 s.")
    print("  Window will close automatically after 3 full cycles.")
    print()
    print("All offline assertions passed ✅")

    sys.exit(app.exec())
