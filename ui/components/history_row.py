"""
ui/components/history_row.py  –  One row in the download history panel
=======================================================================
Displays a single DownloadRecord inside the HistoryPanel's scroll list.
Designed to be dense but readable: one row = 52px, showing date, title,
artist, platform badge, media type, duration, file size, a folder-open
button, and a re-download button.

Signals
-------
open_folder_requested(DownloadRecord)
    Emitted when the user clicks the 📁 button.
    HistoryPanel calls QDesktopServices.openUrl(parent_dir) in response.

redownload_requested(DownloadRecord)
    Emitted when the user clicks the ↺ button.
    AppWindow adds the URL back to the queue.

delete_requested(DownloadRecord)
    Emitted when the user clicks the × button.
    HistoryPanel removes the row and calls HistoryDB.delete(record.id).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel,
    QSizePolicy, QWidget,
)
from qfluentwidgets import CaptionLabel, ToolButton

from core.history_db import DownloadRecord
from ui.theme_manager import ACCENT_COLOR


# ──────────────────────────────────────────────────────────────────────────────
# Design tokens
# ──────────────────────────────────────────────────────────────────────────────

_BG_NORMAL   = "#18181b"
_BG_HOVER    = "#1f1f23"
_BORDER      = "#2e2e35"
_TEXT        = "#f0f0f0"
_TEXT_2      = "#9090a0"
_TEXT_3      = "#55555f"
_ERROR       = "#f87171"
_RADIUS      = 6

_PLATFORM_COLORS: dict[str, tuple[str, str]] = {
    "youtube":  ("#ff4444", "#ffffff"),
    "ytmusic":  ("#ff4444", "#ffffff"),
    "spotify":  ("#1db954", "#ffffff"),
    "unknown":  ("#2e2e35", "#9090a0"),
}

_TYPE_COLORS: dict[str, tuple[str, str]] = {
    "audio": ("#2563eb", "#ffffff"),
    "video": ("#7c3aed", "#ffffff"),
}


# ──────────────────────────────────────────────────────────────────────────────
# HistoryRow
# ──────────────────────────────────────────────────────────────────────────────

class HistoryRow(QFrame):
    """
    Dense single-row widget for one DownloadRecord.

    Parameters
    ----------
    record : DownloadRecord from core.history_db.
    parent : Optional Qt parent widget.
    """

    open_folder_requested = Signal(object)    # DownloadRecord
    redownload_requested  = Signal(object)    # DownloadRecord
    delete_requested      = Signal(object)    # DownloadRecord

    def __init__(
        self,
        record: DownloadRecord,
        parent: QWidget = None,
    ) -> None:
        super().__init__(parent)
        self._record = record
        self._build()
        self._apply_base_style()

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def record(self) -> DownloadRecord:
        return self._record

    def record_id(self) -> int:
        return self._record.id

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        r = self._record
        self.setFixedHeight(52)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 4, 6, 4)
        row.setSpacing(0)

        # ── Date ──────────────────────────────────────────────────────────────
        date_lbl = CaptionLabel(r.display_date())
        date_lbl.setFixedWidth(116)
        date_lbl.setStyleSheet(f"color: {_TEXT_3}; background: transparent;")
        row.addWidget(date_lbl)
        row.addSpacing(6)

        # ── Title + artist ────────────────────────────────────────────────────
        from PySide6.QtWidgets import QVBoxLayout as _VB
        text_col = _VB()
        text_col.setSpacing(1)
        text_col.setContentsMargins(0, 0, 0, 0)

        title_lbl = QLabel(_truncate(r.title, 52))
        title_lbl.setStyleSheet(f"color: {_TEXT}; background: transparent; font-size: 11px;")
        title_lbl.setFont(QFont("Consolas", 10))

        artist_lbl = CaptionLabel(_truncate(r.artist or "—", 40))
        artist_lbl.setStyleSheet(f"color: {_TEXT_2}; background: transparent;")

        text_col.addWidget(title_lbl)
        text_col.addWidget(artist_lbl)
        row.addLayout(text_col, stretch=1)
        row.addSpacing(8)

        # ── Platform badge ────────────────────────────────────────────────────
        plat   = r.platform.lower()
        bg, fg = _PLATFORM_COLORS.get(plat, _PLATFORM_COLORS["unknown"])
        plat_lbl = _badge(plat.upper(), bg, fg, width=60)
        row.addWidget(plat_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(6)

        # ── Type badge ────────────────────────────────────────────────────────
        type_bg, type_fg = _TYPE_COLORS.get(r.media_type, ("#2e2e35", "#9090a0"))
        type_lbl = _badge(r.media_type.upper(), type_bg, type_fg, width=46)
        row.addWidget(type_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(6)

        # ── Duration ──────────────────────────────────────────────────────────
        dur_lbl = CaptionLabel(r.duration_str())
        dur_lbl.setFixedWidth(52)
        dur_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dur_lbl.setStyleSheet(f"color: {_TEXT_2}; background: transparent;")
        row.addWidget(dur_lbl)
        row.addSpacing(4)

        # ── File size ─────────────────────────────────────────────────────────
        size_lbl = CaptionLabel(r.file_size_str())
        size_lbl.setFixedWidth(60)
        size_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        size_lbl.setStyleSheet(f"color: {_TEXT_2}; background: transparent;")
        row.addWidget(size_lbl)
        row.addSpacing(4)

        # ── Action buttons ────────────────────────────────────────────────────
        # Open folder
        open_btn = self._action_btn("📁", f"Open folder in file manager")
        open_btn.clicked.connect(
            lambda: self.open_folder_requested.emit(self._record)
        )
        row.addWidget(open_btn)
        row.addSpacing(2)

        # Re-download
        redl_btn = self._action_btn("↺", "Re-add to download queue")
        redl_btn.clicked.connect(
            lambda: self.redownload_requested.emit(self._record)
        )
        row.addWidget(redl_btn)
        row.addSpacing(2)

        # Delete from history
        del_btn = self._action_btn("✕", "Remove from history")
        del_btn.setStyleSheet(f"""
            ToolButton {{
                background: transparent;
                border: none;
                color: {_TEXT_3};
                font-size: 11px;
            }}
            ToolButton:hover {{ color: {_ERROR}; }}
        """)
        del_btn.clicked.connect(
            lambda: self.delete_requested.emit(self._record)
        )
        row.addWidget(del_btn)

    @staticmethod
    def _action_btn(icon_text: str, tooltip: str) -> ToolButton:
        btn = ToolButton()
        btn.setText(icon_text)
        btn.setFixedSize(28, 28)
        btn.setToolTip(tooltip)
        btn.setStyleSheet(f"""
            ToolButton {{
                background: transparent;
                border: none;
                color: {_TEXT_3};
                font-size: 12px;
            }}
            ToolButton:hover {{
                color: {ACCENT_COLOR};
            }}
        """)
        return btn

    # ── Styling ───────────────────────────────────────────────────────────────

    def _apply_base_style(self) -> None:
        self.setStyleSheet(f"""
            HistoryRow {{
                background-color: {_BG_NORMAL};
                border: 1px solid {_BORDER};
                border-radius: {_RADIUS}px;
            }}
        """)

    def enterEvent(self, event) -> None:
        self.setStyleSheet(f"""
            HistoryRow {{
                background-color: {_BG_HOVER};
                border: 1px solid {ACCENT_COLOR};
                border-radius: {_RADIUS}px;
            }}
        """)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._apply_base_style()
        super().leaveEvent(event)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _truncate(text: str, max_chars: int) -> str:
    """Truncate a string and append '…' if it exceeds max_chars."""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _badge(text: str, bg: str, fg: str, width: int = 60) -> QLabel:
    """Create a small coloured pill label."""
    lbl = QLabel(text)
    lbl.setFont(QFont("Consolas", 8))
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setFixedSize(width, 18)
    lbl.setStyleSheet(
        f"background: {bg}; color: {fg}; border-radius: 3px; padding: 0 4px;"
    )
    return lbl
