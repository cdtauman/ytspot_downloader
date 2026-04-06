"""
ui/panels/url_bar.py  –  URL entry bar
=======================================
Contains the main URL input field plus all associated controls:
  - Paste (⎘), Clear (✕), and Fetch Info buttons
  - A batch import button (opens a .txt file picker)
  - A clipboard-monitor indicator dot (green pulse when active)
  - A page-scrape shortcut (🕷) that hands the current URL to ScraperWorker

Signals emitted upward to AppWindow
------------------------------------
fetch_requested(str)        User pressed Enter or "Fetch Info".
batch_import_requested(str) User selected a .txt file; payload is file path.
scrape_requested(str)       User clicked the scrape button; payload is the URL.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout,
    QLabel, QSizePolicy, QWidget,
)
from qfluentwidgets import (
    LineEdit, PrimaryPushButton, ToolButton,
)

from config import AppConfig
from ui.theme_manager import ACCENT_COLOR
from ui.i18n import t


# ──────────────────────────────────────────────────────────────────────────────
# Design tokens
# ──────────────────────────────────────────────────────────────────────────────

_BG          = "#0e0e0f"
_SURFACE     = "#18181b"
_BORDER      = "#2e2e35"
_TEXT        = "#f0f0f0"
_TEXT_3      = "#55555f"
_SUCCESS     = "#34d399"


# ──────────────────────────────────────────────────────────────────────────────
# UrlBar
# ──────────────────────────────────────────────────────────────────────────────

class UrlBar(QFrame):
    """
    The URL-input bar shown at the top of the Queue view.

    Parameters
    ----------
    config : AppConfig – used to read/write batch_import_dir.
    parent : Optional Qt parent.
    """

    fetch_requested        = Signal(str)   # URL string
    batch_import_requested = Signal(str)   # absolute path to .txt file
    scrape_requested       = Signal(str)   # URL string

    def __init__(self, config: AppConfig, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._config          = config
        self._clipboard_active = False
        self._build()

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_url(self) -> str:
        """Return the current text in the URL field, stripped."""
        return self._url_entry.text().strip()

    def set_url(self, url: str) -> None:
        """Programmatically set the URL field (e.g., from ClipboardWorker)."""
        self._url_entry.setText(url)
        self._url_entry.setFocus()

    def set_fetching(self, fetching: bool) -> None:
        """Toggle the Fetch button between active and loading state."""
        if fetching:
            self._fetch_btn.setText(t("fetching_button"))
            self._fetch_btn.setEnabled(False)
        else:
            self._fetch_btn.setText(t("fetch_info_button"))
            self._fetch_btn.setEnabled(True)

    def clear_url(self) -> None:
        """Clear the URL field and reset the fetch button."""
        self._url_entry.clear()
        self.set_fetching(False)

    def set_clipboard_monitor_active(self, active: bool) -> None:
        """Update the clipboard indicator dot colour."""
        self._clipboard_active = active
        if active:
            self._clip_dot.setStyleSheet(
                f"color: {_SUCCESS}; background: transparent; font-size: 10px;"
            )
            self._clip_dot.setToolTip(t("clipboard_on_tooltip"))
        else:
            self._clip_dot.setStyleSheet(
                f"color: {_TEXT_3}; background: transparent; font-size: 10px;"
            )
            self._clip_dot.setToolTip(t("clipboard_off_tooltip"))

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(64)
        self.setStyleSheet(f"background: {_BG}; border: none;")

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(6)

        # ── Clipboard indicator dot ───────────────────────────────────────────
        self._clip_dot = QLabel("●")
        self._clip_dot.setFixedWidth(14)
        self._clip_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_clipboard_monitor_active(False)   # sets initial style + tooltip
        row.addWidget(self._clip_dot)

        # ── URL entry ─────────────────────────────────────────────────────────
        self._url_entry = LineEdit()
        self._url_entry.setPlaceholderText(t("url_placeholder"))
        self._url_entry.setMinimumHeight(40)
        self._url_entry.setClearButtonEnabled(True)
        self._url_entry.returnPressed.connect(self._on_fetch)
        self._url_entry.setStyleSheet(f"""
            LineEdit {{
                background: {_SURFACE};
                border: 1.5px solid {_BORDER};
                border-radius: 6px;
                color: {_TEXT};
                font-size: 13px;
                padding: 0 8px;
            }}
            LineEdit:focus {{
                border-color: {ACCENT_COLOR};
            }}
        """)
        row.addWidget(self._url_entry, stretch=1)

        # ── Paste button ──────────────────────────────────────────────────────
        paste_btn = self._tool_btn("⎘", t("paste_tooltip"))
        paste_btn.clicked.connect(self._on_paste)
        row.addWidget(paste_btn)

        # ── Batch import button ───────────────────────────────────────────────
        batch_btn = self._tool_btn("📄", t("batch_import_tooltip"))
        batch_btn.clicked.connect(self._on_batch_import)
        row.addWidget(batch_btn)

        # ── Scrape button ─────────────────────────────────────────────────────
        scrape_btn = self._tool_btn("🕷", t("scrape_tooltip"))
        scrape_btn.clicked.connect(self._on_scrape)
        row.addWidget(scrape_btn)

        # ── Fetch button ──────────────────────────────────────────────────────
        self._fetch_btn = PrimaryPushButton(t("fetch_info_button"))
        self._fetch_btn.setMinimumSize(120, 40)
        self._fetch_btn.setStyleSheet(f"""
            PrimaryPushButton {{
                background-color: {ACCENT_COLOR};
                color: #000000;
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-weight: bold;
            }}
            PrimaryPushButton:hover {{
                background-color: #e09418;
            }}
            PrimaryPushButton:disabled {{
                background-color: #5a3e0e;
                color: #888888;
            }}
        """)
        self._fetch_btn.clicked.connect(self._on_fetch)
        row.addWidget(self._fetch_btn)

    @staticmethod
    def _tool_btn(icon: str, tooltip: str) -> ToolButton:
        btn = ToolButton()
        btn.setText(icon)
        btn.setFixedSize(38, 38)
        btn.setToolTip(tooltip)
        btn.setStyleSheet(f"""
            ToolButton {{
                background: {_SURFACE};
                border: 1px solid {_BORDER};
                border-radius: 6px;
                font-size: 15px;
                color: {_TEXT};
            }}
            ToolButton:hover {{
                border-color: {ACCENT_COLOR};
                color: {ACCENT_COLOR};
            }}
        """)
        return btn

    # ── Slots ──────────────────────────────────────────────────────────────────

    def _on_fetch(self) -> None:
        url = self.get_url()
        if url:
            self.fetch_requested.emit(url)

    def _on_paste(self) -> None:
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        if clipboard:
            text = clipboard.text().strip()
            if text:
                self._url_entry.setText(text)
                self._url_entry.setFocus()

    def _on_batch_import(self) -> None:
        start_dir = self._config.batch_import_dir or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select URL batch file",
            start_dir,
            "Text files (*.txt);;All files (*.*)",
        )
        if path:
            self._config.batch_import_dir = str(Path(path).parent)
            self._config.save()
            self.batch_import_requested.emit(path)

    def _on_scrape(self) -> None:
        url = self.get_url()
        if url:
            self.scrape_requested.emit(url)
