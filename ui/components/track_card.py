"""
ui/components/track_card.py  –  Draggable download queue entry  (v3)
=====================================================================
Changelog v3
------------
* Pause button (⏸) visible when status == "downloading".
  Emits pause_requested(queue_index).
* Resume button (▶) visible when status == "paused".
  Emits resume_requested(queue_index).
* Both buttons replace the single cancel-level control; the remove (×)
  button is always available on hover.
* Status dot gains a "paused" state (amber/warning colour).
* All existing public API is unchanged (set_status, set_progress, etc.).
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QByteArray, QMimeData, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QGraphicsDropShadowEffect,
    QHBoxLayout, QLabel, QProgressBar, QSizePolicy, QVBoxLayout, QWidget,
)
from qfluentwidgets import BodyLabel, CaptionLabel, ToolButton

from ui.theme_manager import (
    ACCENT_COLOR,
    BG_DARK, SURFACE_DARK, SURFACE2_DARK, BORDER_DARK,
    TEXT_DARK, TEXT2_DARK, TEXT3_DARK,
    SUCCESS_COLOR, ERROR_COLOR, WARNING_COLOR, PROCESSING_COLOR,
)


# ── Design tokens ──────────────────────────────────────────────────────────────

_BG_NORMAL   = SURFACE_DARK
_BG_HOVER    = SURFACE2_DARK
_BG_DRAG     = "#1a1a26"
_BORDER      = BORDER_DARK
_TEXT        = TEXT_DARK
_TEXT_2      = TEXT2_DARK
_TEXT_3      = TEXT3_DARK
_SUCCESS     = SUCCESS_COLOR
_ERROR       = ERROR_COLOR
_WARNING     = WARNING_COLOR
_RADIUS      = 10
_THUMB_W     = 64
_THUMB_H     = 64

_STATUS_COLORS: dict[str, str] = {
    "queued":      _TEXT_3,
    "downloading": ACCENT_COLOR,
    "processing":  PROCESSING_COLOR,
    "done":        _SUCCESS,
    "error":       _ERROR,
    "cancelled":   _WARNING,
    "paused":      "#f59e0b",   # amber – NEW
}

_PLATFORM_COLORS: dict[str, tuple[str, str]] = {
    "youtube":  ("#cc2200", "#ffffff"),
    "ytmusic":  ("#cc2200", "#ffffff"),
    "spotify":  ("#1aa34a", "#ffffff"),
    "default":  (_BORDER, _TEXT_2),
}


def _make_placeholder_pixmap(w: int = _THUMB_W, h: int = _THUMB_H) -> QPixmap:
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(QColor(BORDER_DARK))
    # Draw a simple play triangle
    from PySide6.QtGui import QPainter, QPen, QBrush, QPolygon
    from PySide6.QtCore import QPoint as _QP
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QBrush(QColor(TEXT3_DARK)))
    painter.setPen(Qt.PenStyle.NoPen)
    cx, cy = w // 2, h // 2
    s = min(w, h) // 5
    tri = QPolygon([_QP(cx - s, cy - s), _QP(cx + s, cy), _QP(cx - s, cy + s)])
    painter.drawPolygon(tri)
    painter.end()
    return QPixmap.fromImage(img)


class TrackCard(QFrame):
    """
    One entry in the download queue panel.

    Parameters
    ----------
    title, artist, duration, platform, queue_index : track metadata.
    parent : optional Qt parent.
    """

    # ── Signals ───────────────────────────────────────────────────────────────
    remove_requested  = Signal(int)    # queue_index
    selection_changed = Signal()      # checkbox toggled
    pause_requested   = Signal(int)    # queue_index
    resume_requested  = Signal(int)    # queue_index
    reorder_requested = Signal(int, int)  # (from_index, to_index)

    # ── Constructor ───────────────────────────────────────────────────────────

    def __init__(
        self,
        title:        str,
        artist:       str          = "",
        duration:     str          = "",
        platform:     str          = "youtube",
        queue_index:  int          = 0,
        track_url:    str          = "",
        album:        str          = "",
        parent_artist: str         = "",
        release_type:  str         = "",
        album_index:   int         = 0,
        thumbnail_url: str         = "",
        parent:       QWidget      = None,
    ) -> None:
        super().__init__(parent)
        self.queue_index = queue_index
        self.track_url   = track_url
        self.title       = title
        self.artist      = artist
        self.album       = album
        self.parent_artist = parent_artist
        self.release_type  = release_type
        self.album_index   = album_index
        self.thumbnail_url = thumbnail_url
        # Ensure platform is a string
        if hasattr(platform, "value"):
            plat_str = platform.value
        else:
            plat_str = str(platform).lower()
        self._platform = plat_str
        self._status   = "queued"
        self._drag_start_pos: Optional[QPoint] = None
        
        # Action buttons (pause/resume are hidden by default)
        self._pause_btn:  Optional[ToolButton] = None
        self._resume_btn: Optional[ToolButton] = None
        self._remove_btn: Optional[ToolButton] = None

        self._build(title, artist, duration, plat_str)
        self._apply_shadow()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(
        self,
        title:    str,
        artist:   str,
        duration: str,
        platform: str,
    ) -> None:
        self.setFixedHeight(82)
        self.setObjectName("trackCard")
        self._refresh_style(hover=False)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(10)

        # Checkbox
        self._check = QCheckBox()
        self._check.setChecked(True)
        self._check.setFixedSize(20, 20)
        self._check.stateChanged.connect(lambda: self.selection_changed.emit())
        outer.addWidget(self._check)

        # Thumbnail
        self._thumb_lbl = QLabel()
        self._thumb_lbl.setFixedSize(_THUMB_W, _THUMB_H)
        self._thumb_lbl.setScaledContents(False)
        self._thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_lbl.setPixmap(_make_placeholder_pixmap())
        self._thumb_lbl.setStyleSheet(
            f"border-radius: 6px; border: 1px solid {_BORDER};"
        )
        outer.addWidget(self._thumb_lbl)

        # Status dot
        self._dot = QLabel("●")
        self._dot.setFixedWidth(14)
        self._dot.setStyleSheet(f"color: {_TEXT_3}; background: transparent; font-size: 10px;")
        outer.addWidget(self._dot)

        # Text column
        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        self._title_lbl = BodyLabel(title[:80])
        self._title_lbl.setStyleSheet(f"color: {_TEXT}; background: transparent;")
        title_font = QFont()
        title_font.setPointSize(10)
        self._title_lbl.setFont(title_font)
        text_col.addWidget(self._title_lbl)

        self._artist_lbl = CaptionLabel(artist or "—")
        self._artist_lbl.setStyleSheet(f"color: {_TEXT_2}; background: transparent;")
        text_col.addWidget(self._artist_lbl)

        # Progress bar (hidden until download starts)
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 1000)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(3)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {_BORDER};
                border: none;
                border-radius: 1px;
            }}
            QProgressBar::chunk {{
                background: {ACCENT_COLOR};
                border-radius: 1px;
            }}
        """)
        self._progress_bar.setVisible(False)
        text_col.addWidget(self._progress_bar)

        outer.addLayout(text_col, stretch=1)
        outer.addSpacing(8)

        # Badge column
        badge_col = QVBoxLayout()
        badge_col.setSpacing(4)
        badge_col.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

        self._dur_badge  = self._make_badge(duration or "--:--", "default")
        self._plat_badge = self._make_badge(platform.upper(), platform)
        badge_col.addWidget(self._dur_badge,  alignment=Qt.AlignmentFlag.AlignRight)
        badge_col.addWidget(self._plat_badge, alignment=Qt.AlignmentFlag.AlignRight)
        outer.addLayout(badge_col)
        outer.addSpacing(4)

        # Action buttons column
        btn_col = QVBoxLayout()
        btn_col.setSpacing(4)
        btn_col.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Remove button (shown on hover)
        self._remove_btn = ToolButton()
        self._remove_btn.setText("✕")
        self._remove_btn.setFixedSize(28, 28)
        self._remove_btn.setVisible(False)
        self._remove_btn.setToolTip("Remove from queue")
        self._remove_btn.clicked.connect(
            lambda: self.remove_requested.emit(self.queue_index)
        )
        self._remove_btn.setStyleSheet(self._action_btn_style(_ERROR))
        btn_col.addWidget(self._remove_btn)
 
        # Pause button (hidden by default)
        self._pause_btn = ToolButton()
        self._pause_btn.setText("⏸")
        self._pause_btn.setFixedSize(28, 28)
        self._pause_btn.setVisible(False)
        self._pause_btn.setToolTip("Pause download")
        self._pause_btn.clicked.connect(lambda: self.pause_requested.emit(self.queue_index))
        self._pause_btn.setStyleSheet(self._action_btn_style(ACCENT_COLOR))
        btn_col.addWidget(self._pause_btn)
 
        # Resume button (hidden by default)
        self._resume_btn = ToolButton()
        self._resume_btn.setText("▶")
        self._resume_btn.setFixedSize(28, 28)
        self._resume_btn.setVisible(False)
        self._resume_btn.setToolTip("Resume download")
        self._resume_btn.clicked.connect(lambda: self.resume_requested.emit(self.queue_index))
        self._resume_btn.setStyleSheet(self._action_btn_style(SUCCESS_COLOR))
        btn_col.addWidget(self._resume_btn)
 
        outer.addLayout(btn_col)

    @staticmethod
    def _action_btn_style(color: str) -> str:
        return f"""
            ToolButton {{
                color: {color};
                background: transparent;
                border: none;
                border-radius: 4px;
                font-size: 13px;
            }}
            ToolButton:hover {{
                background: rgba(255,255,255,0.07);
            }}
        """

    def _make_badge(self, text: str, kind: str) -> QLabel:
        lbl = QLabel(text)
        fg_bg = _PLATFORM_COLORS.get(kind.lower(), _PLATFORM_COLORS["default"])
        bg, fg = fg_bg
        lbl.setStyleSheet(f"""
            QLabel {{
                background: {bg};
                color: {fg};
                border-radius: 4px;
                padding: 1px 6px;
                font-size: 10px;
                font-weight: 600;
            }}
        """)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return lbl

    def _apply_shadow(self) -> None:
        fx = QGraphicsDropShadowEffect(self)
        fx.setBlurRadius(12)
        fx.setXOffset(0)
        fx.setYOffset(2)
        fx.setColor(QColor(0, 0, 0, 60))
        self.setGraphicsEffect(fx)

    def _refresh_style(self, hover: bool) -> None:
        bg = _BG_HOVER if hover else _BG_NORMAL
        self.setStyleSheet(f"""
            QFrame#trackCard {{
                background: {bg};
                border: 1px solid {_BORDER};
                border-radius: {_RADIUS}px;
            }}
            QFrame#trackCard:hover {{
                border-color: {ACCENT_COLOR}44;
            }}
        """)

    # ── Public API ─────────────────────────────────────────────────────────────

    def is_selected(self) -> bool:
        return self._check.isChecked()

    def set_selected(self, checked: bool) -> None:
        self._check.setChecked(checked)

    @property
    def platform(self) -> str:
        """Return the platform identifier (e.g., 'spotify', 'youtube')."""
        return self._platform

    def get_status(self) -> str:
        return self._status

    def set_thumbnail(self, pixmap: QPixmap) -> None:
        """Load and center-crop the thumbnail to prevent stretching."""
        if pixmap.isNull():
            return
            
        target_w = self._thumb_lbl.width()
        target_h = self._thumb_lbl.height()
        
        # 1. Scale to cover the target area (KeepAspectRatioByExpanding)
        scaled = pixmap.scaled(
            target_w, target_h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation
        )
        
        # 2. Center crop
        x = (scaled.width()  - target_w) // 2
        y = (scaled.height() - target_h) // 2
        cropped = scaled.copy(x, y, target_w, target_h)
        
        self._thumb_lbl.setPixmap(cropped)

    def set_progress(self, fraction: float) -> None:
        self._progress_bar.setValue(int(fraction * 1000))
        self._progress_bar.setVisible(fraction > 0.0 and self._status not in ("done", "error", "cancelled"))

    def set_status(self, status: str) -> None:
        """
        Update the visual state.

        status : one of "queued" | "downloading" | "processing" |
                         "done" | "error" | "cancelled" | "paused"
        """
        self._status = status
        color = _STATUS_COLORS.get(status, _TEXT_3)
        self._dot.setStyleSheet(
            f"color: {color}; background: transparent; font-size: 10px;"
        )

        # Update button visibility
        self._pause_btn.setVisible(status == "downloading")
        self._resume_btn.setVisible(status == "paused")
        # Remove button is only for queued, but we keep it available until started
        # self._remove_btn.setVisible(status == "queued") 
        # (handeled by enter/leaveEvent for better UX)
 
        # Disable checkbox once download is in flight
        self._check.setEnabled(status == "queued")

    def set_artist(self, artist: str) -> None:
        self._artist_lbl.setText(artist or "—")

    def set_title(self, title: str) -> None:
        self._title_lbl.setText(title[:80])

    def update_queue_index(self, new_index: int) -> None:
        self.queue_index = new_index

    # ── Hover events ──────────────────────────────────────────────────────────

    def enterEvent(self, event) -> None:
        self._refresh_style(hover=True)
        if self._status == "queued":
            self._remove_btn.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._refresh_style(hover=False)
        self._remove_btn.setVisible(False)
        super().leaveEvent(event)

    # ── Drag & drop ───────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (
            self._drag_start_pos is not None
            and (event.buttons() & Qt.MouseButton.LeftButton)
            and (
                event.position().toPoint() - self._drag_start_pos
            ).manhattanLength() >= QApplication.startDragDistance()
        ):
            drag = QDrag(self)
            mime = QMimeData()
            mime.setText(str(self.queue_index))
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.MoveAction)
        super().mouseMoveEvent(event)
