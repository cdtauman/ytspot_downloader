"""
ui/components/search_result_card.py  –  Search result display widget
=====================================================================
Displays one result from SearchEngine in the search panel.  Lighter than
TrackCard (no drag-and-drop, no progress bar, no checkbox) but shares the
same visual language: dark surface, amber accent on interaction, thumbnail
with placeholder, platform badge.

Signals
-------
add_to_queue(SearchResult)
    Emitted when the user clicks the "＋ Add" button.  The search panel
    connects this to AppWindow._on_add_search_result_to_queue().
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel,
    QSizePolicy, QVBoxLayout, QWidget,
)
from qfluentwidgets import BodyLabel, CaptionLabel, PrimaryPushButton

from core.search_engine import SearchResult
from ui.theme_manager import ACCENT_COLOR


# ──────────────────────────────────────────────────────────────────────────────
# Design tokens
# ──────────────────────────────────────────────────────────────────────────────

_BG_NORMAL  = "#18181b"
_BG_HOVER   = "#2a2a32"
_BORDER     = "#2e2e35"
_TEXT       = "#f0f0f0"
_TEXT_2     = "#9090a0"
_TEXT_3     = "#55555f"
_RADIUS     = 8
_THUMB_W    = 80
_THUMB_H    = 45

_PLATFORM_COLORS: dict[str, tuple[str, str]] = {
    "YOUTUBE":  ("#ff4444", "#ffffff"),
    "YTMUSIC":  ("#ff4444", "#ffffff"),
    "SPOTIFY":  ("#1db954", "#ffffff"),
    "UNKNOWN":  ("#2e2e35", "#9090a0"),
}


def _placeholder_pixmap(w: int = _THUMB_W, h: int = _THUMB_H) -> QPixmap:
    from PySide6.QtGui import QImage
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#1a1a20"))
    return QPixmap.fromImage(img)


# ──────────────────────────────────────────────────────────────────────────────
# SearchResultCard
# ──────────────────────────────────────────────────────────────────────────────

class SearchResultCard(QFrame):
    """
    Compact card for one SearchResult.

    Parameters
    ----------
    result : SearchResult dataclass from core.search_engine.
    parent : Optional Qt parent.
    """

    add_to_queue = Signal(object)   # SearchResult

    def __init__(
        self,
        result: SearchResult,
        parent: QWidget = None,
    ) -> None:
        super().__init__(parent)
        self._result = result
        self._build()
        self._apply_base_style()

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def result(self) -> SearchResult:
        return self._result

    def set_thumbnail(self, raw_bytes: bytes) -> None:
        """Load the thumbnail from raw image bytes (called by ThumbnailWorker)."""
        pixmap = QPixmap()
        if pixmap.loadFromData(raw_bytes):
            pixmap = pixmap.scaled(
                _THUMB_W, _THUMB_H,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (pixmap.width()  - _THUMB_W) // 2
            y = (pixmap.height() - _THUMB_H) // 2
            pixmap = pixmap.copy(x, y, _THUMB_W, _THUMB_H)
            self._thumb_label.setPixmap(pixmap)

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        r = self._result
        self.setFixedHeight(68)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(0)

        # ── Rank label ────────────────────────────────────────────────────────
        rank_lbl = QLabel(f"{r.result_index}.")
        rank_lbl.setFixedWidth(28)
        rank_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rank_lbl.setStyleSheet(f"color: {_TEXT_3}; font-size: 10px; background: transparent;")
        row.addWidget(rank_lbl)
        row.addSpacing(4)

        # ── Thumbnail ─────────────────────────────────────────────────────────
        self._thumb_label = QLabel()
        self._thumb_label.setFixedSize(_THUMB_W, _THUMB_H)
        self._thumb_label.setPixmap(_placeholder_pixmap())
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_label.setStyleSheet("border-radius: 3px; background: #1a1a20;")
        row.addWidget(self._thumb_label)
        row.addSpacing(10)

        # ── Text ──────────────────────────────────────────────────────────────
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.setContentsMargins(0, 0, 0, 0)

        title_lbl = BodyLabel(r.title)
        title_lbl.setStyleSheet(f"color: {_TEXT}; background: transparent;")
        title_font = QFont()
        title_font.setPointSize(10)
        title_lbl.setFont(title_font)
        title_lbl.setMaximumWidth(340)

        # Build sub-line: artist  ·  duration  ·  views
        parts = []
        if r.artist:
            parts.append(r.artist)
        if r.duration_str:
            parts.append(r.duration_str)
        if r.view_count_str():
            parts.append(r.view_count_str())
        sub_text = "  ·  ".join(parts) if parts else "—"

        sub_lbl = CaptionLabel(sub_text)
        sub_lbl.setStyleSheet(f"color: {_TEXT_2}; background: transparent;")

        text_col.addWidget(title_lbl)
        text_col.addWidget(sub_lbl)
        row.addLayout(text_col, stretch=1)
        row.addSpacing(8)

        # ── Platform badge ────────────────────────────────────────────────────
        platform_str = r.platform.name.upper()
        bg, fg = _PLATFORM_COLORS.get(platform_str, _PLATFORM_COLORS["UNKNOWN"])
        plat_lbl = QLabel(platform_str)
        plat_lbl.setFont(QFont("Consolas", 8))
        plat_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        plat_lbl.setFixedHeight(18)
        plat_lbl.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: 3px; padding: 0 5px;"
        )
        row.addWidget(plat_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(10)

        # ── Add button ────────────────────────────────────────────────────────
        add_btn = PrimaryPushButton("＋  Add")
        add_btn.setFixedSize(72, 30)
        add_btn.clicked.connect(lambda: self.add_to_queue.emit(self._result))
        row.addWidget(add_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

    # ── Styling ───────────────────────────────────────────────────────────────

    def _apply_base_style(self) -> None:
        self.setStyleSheet(f"""
            SearchResultCard {{
                background-color: {_BG_NORMAL};
                border: 1px solid {_BORDER};
                border-radius: {_RADIUS}px;
            }}
        """)

    def enterEvent(self, event) -> None:
        self.setStyleSheet(f"""
            SearchResultCard {{
                background-color: {_BG_HOVER};
                border: 1px solid {ACCENT_COLOR};
                border-radius: {_RADIUS}px;
            }}
        """)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._apply_base_style()
        super().leaveEvent(event)
