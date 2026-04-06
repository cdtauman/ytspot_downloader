"""
ui/components/search_result_card.py  –  Category-aware search result widget
===========================================================================
Displays one result from SearchEngine in the search panel.  Adapts its
layout and action button to the ResultKind of the result:

  TRACK    – thumbnail + title/artist/duration/views  + "＋ Add" button
  ALBUM    – thumbnail + title/item_count             + "Browse" button
  PLAYLIST – thumbnail + title/item_count             + "Browse" button
  ARTIST   – circular avatar placeholder + name       + "Browse" button
  CHANNEL  – square icon + name                       + "Browse" button

Signals
-------
add_to_queue(SearchResult)
    Emitted for TRACK cards when the user clicks "＋ Add".
browse_requested(SearchResult)
    Emitted for ALBUM / PLAYLIST / ARTIST / CHANNEL cards when the user
    clicks "Browse".  SearchPanel forwards this to AppWindow for drill-down.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QSizePolicy, QVBoxLayout, QWidget,
)
from qfluentwidgets import BodyLabel, CaptionLabel, PrimaryPushButton, PushButton

from core.search_engine import ResultKind, SearchResult
from ui.theme_manager import (
    ACCENT_COLOR,
    BG_DARK, SURFACE_DARK, SURFACE2_DARK, BORDER_DARK,
    TEXT_DARK, TEXT2_DARK, TEXT3_DARK,
)


# ──────────────────────────────────────────────────────────────────────────────
# Design tokens
# ──────────────────────────────────────────────────────────────────────────────

_BG_NORMAL  = SURFACE_DARK     # "#16161f"
_BG_HOVER   = SURFACE2_DARK    # "#1e1e2a"
_BORDER     = BORDER_DARK      # "#252533"
_TEXT       = TEXT_DARK        # "#eeeef5"
_TEXT_2     = TEXT2_DARK       # "#8888a8"
_TEXT_3     = TEXT3_DARK       # "#4a4a66"
_RADIUS     = 8
_THUMB_W    = 80
_THUMB_H    = 45

_PLATFORM_COLORS: dict[str, tuple[str, str]] = {
    "YOUTUBE":  ("#cc2200", "#ffffff"),   # deeper YouTube red
    "YTMUSIC":  ("#cc2200", "#ffffff"),
    "SPOTIFY":  ("#1aa34a", "#ffffff"),   # richer Spotify green
    "UNKNOWN":  (_BORDER, _TEXT_2),
}

# ResultKind icon characters shown in the avatar placeholder for non-track kinds
_KIND_ICONS: dict[ResultKind, str] = {
    ResultKind.ARTIST:   "🎤",
    ResultKind.ALBUM:    "💿",
    ResultKind.PLAYLIST: "🎵",
    ResultKind.CHANNEL:  "📺",
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
    Compact, category-aware card for one SearchResult.

    Parameters
    ----------
    result : SearchResult dataclass from core.search_engine.
    parent : Optional Qt parent.
    """

    add_to_queue     = Signal(object)   # SearchResult  – TRACK only
    browse_requested = Signal(object)   # SearchResult  – ALBUM/PLAYLIST/ARTIST/CHANNEL

    def __init__(
        self,
        result: SearchResult,
        parent: QWidget = None,
    ) -> None:
        super().__init__(parent)
        self._result = result
        self._build()
        self._apply_base_style()

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(10)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 90))
        self.setGraphicsEffect(shadow)

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def result(self) -> SearchResult:
        return self._result

    def set_thumbnail(self, raw_bytes: bytes) -> None:
        """Load the thumbnail from raw image bytes (called by ThumbnailWorker)."""
        if not hasattr(self, "_thumb_label"):
            return
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
        r    = self._result
        kind = r.kind

        self.setFixedHeight(68)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(0)

        # ── Rank label ────────────────────────────────────────────────────────
        rank_lbl = QLabel(f"{r.result_index}.")
        rank_lbl.setFixedWidth(24)
        rank_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rank_lbl.setStyleSheet(f"color: {_TEXT_3}; font-size: 10px; background: transparent;")
        row.addWidget(rank_lbl)
        row.addSpacing(6)

        # ── Thumbnail / avatar ────────────────────────────────────────────────
        self._thumb_label = self._build_thumb(kind)
        row.addWidget(self._thumb_label)
        row.addSpacing(10)

        # ── Text column ───────────────────────────────────────────────────────
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.setContentsMargins(0, 0, 0, 0)

        title_lbl = BodyLabel(r.title)
        title_lbl.setStyleSheet(f"color: {_TEXT}; background: transparent;")
        title_font = QFont()
        title_font.setPointSize(10)
        title_lbl.setFont(title_font)
        title_lbl.setMaximumWidth(360)
        text_col.addWidget(title_lbl)

        sub_lbl = CaptionLabel(self._build_sub_text(r, kind))
        sub_lbl.setStyleSheet(f"color: {_TEXT_2}; background: transparent;")
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
        row.addSpacing(8)

        # ── Action button ─────────────────────────────────────────────────────
        if kind == ResultKind.TRACK:
            btn = PrimaryPushButton("＋  Add")
            btn.setFixedSize(72, 30)
            btn.clicked.connect(lambda: self.add_to_queue.emit(self._result))
        else:
            btn = PushButton("Browse  →")
            btn.setFixedSize(84, 30)
            btn.setStyleSheet(f"""
                PushButton {{
                    background: transparent;
                    border: 1px solid {ACCENT_COLOR};
                    border-radius: 6px;
                    color: {ACCENT_COLOR};
                    font-size: 11px;
                }}
                PushButton:hover {{
                    background: {ACCENT_COLOR};
                    color: #000000;
                }}
            """)
            btn.clicked.connect(lambda: self.browse_requested.emit(self._result))

        row.addWidget(btn, alignment=Qt.AlignmentFlag.AlignVCenter)

    def _build_thumb(self, kind: ResultKind) -> QLabel:
        """Return a thumbnail label; for non-track kinds show a styled icon."""
        lbl = QLabel()
        lbl.setFixedSize(_THUMB_W, _THUMB_H)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if kind == ResultKind.TRACK:
            lbl.setPixmap(_placeholder_pixmap())
            lbl.setStyleSheet("border-radius: 4px; background: #1a1a20;")
        elif kind == ResultKind.ARTIST:
            # Circular avatar style
            icon = _KIND_ICONS.get(kind, "?")
            lbl.setText(icon)
            lbl.setStyleSheet(f"""
                background: #1e1e30;
                border-radius: {_THUMB_H // 2}px;
                border: 1px solid {_BORDER};
                font-size: 22px;
            """)
        else:
            # Album / Playlist / Channel – square with icon
            icon = _KIND_ICONS.get(kind, "?")
            lbl.setText(icon)
            lbl.setStyleSheet(f"""
                background: #1a1a28;
                border-radius: 6px;
                border: 1px solid {_BORDER};
                font-size: 22px;
            """)
        return lbl

    @staticmethod
    def _build_sub_text(r: SearchResult, kind: ResultKind) -> str:
        """Build the secondary info line based on the result kind."""
        if kind == ResultKind.TRACK:
            parts = []
            if r.artist:
                parts.append(r.artist)
            if r.duration_str:
                parts.append(r.duration_str)
            vc = r.view_count_str() if hasattr(r, "view_count_str") else ""
            if vc:
                parts.append(vc)
            return "  ·  ".join(parts) if parts else "—"

        if kind == ResultKind.ARTIST:
            return r.artist or r.platform.name.capitalize()

        if kind in (ResultKind.ALBUM, ResultKind.PLAYLIST):
            parts = []
            if r.artist:
                parts.append(r.artist)
            if r.item_count:
                label = "tracks" if kind == ResultKind.ALBUM else "items"
                parts.append(f"{r.item_count} {label}")
            return "  ·  ".join(parts) if parts else kind.name.capitalize()

        if kind == ResultKind.CHANNEL:
            vc = r.view_count_str() if hasattr(r, "view_count_str") else ""
            return vc or "Channel"

        return "—"

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
