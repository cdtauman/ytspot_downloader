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
    ACCENT_COLOR, get_colors,
    SUCCESS_COLOR, ERROR_COLOR, WARNING_COLOR, PROCESSING_COLOR,
)


# ── Design tokens ──────────────────────────────────────────────────────────────

_SUCCESS     = SUCCESS_COLOR
_ERROR       = ERROR_COLOR
_WARNING     = WARNING_COLOR
_RADIUS      = 10
_THUMB_W     = 114
_THUMB_H     = 64

_STATUS_COLORS: dict[str, str] = {
    "queued":      "",          # resolved dynamically from get_colors().text_tertiary
    "downloading": ACCENT_COLOR,
    "processing":  PROCESSING_COLOR,
    "done":        SUCCESS_COLOR,
    "error":       ERROR_COLOR,
    "cancelled":   WARNING_COLOR,
    "paused":      "#f59e0b",   # amber
}

_PLATFORM_BADGE_LABELS: dict[str, str] = {
    "youtube":  "YT",
    "ytm":      "YTM",
    "ytmusic":  "YTM",
    "spotify":  "SP",
    "generic":  "URL",
    "hls":      "HLS",
    "dash":     "HLS",
}

_PLATFORM_COLORS: dict[str, tuple[str, str]] = {
    "youtube":  ("#cc2200", "#ffffff"),
    "ytmusic":  ("#cc2200", "#ffffff"),
    "ytm":      ("#cc2200", "#ffffff"),
    "spotify":  ("#1aa34a", "#ffffff"),
    "hls":      ("#0ea5e9", "#ffffff"),
    "dash":     ("#0ea5e9", "#ffffff"),
    "generic":  ("#6b65a0", "#ffffff"),
}


def _make_placeholder_pixmap(w: int = _THUMB_W, h: int = _THUMB_H) -> QPixmap:
    c = get_colors()
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(QColor(c.border))
    # Draw a simple play triangle
    from PySide6.QtGui import QPainter, QPen, QBrush, QPolygon
    from PySide6.QtCore import QPoint as _QP
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QBrush(QColor(c.text_tertiary)))
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
    status_changed    = Signal(str)   # new status string

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
        category:      str         = "",
        total_tracks:  int         = 0,
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
        self.category      = category
        self.total_tracks  = total_tracks
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
        from ui.theme_manager import ThemeManager
        tm = ThemeManager.instance()
        if tm is not None:
            tm.theme_changed.connect(self._apply_theme)

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(
        self,
        title:    str,
        artist:   str,
        duration: str,
        platform: str,
    ) -> None:
        c = get_colors()
        self.setFixedHeight(90)
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
            f"border-radius: 6px; border: 1px solid {c.border};"
        )
        outer.addWidget(self._thumb_lbl)

        # Status dot
        self._dot = QLabel("●")
        self._dot.setFixedWidth(14)
        self._dot.setStyleSheet(f"color: {c.text_tertiary}; background: transparent; font-size: 10px;")
        outer.addWidget(self._dot)

        # Text column
        text_col = QVBoxLayout()
        text_col.setSpacing(1)

        self._title_lbl = BodyLabel(title[:80])
        self._title_lbl.setStyleSheet(f"color: {c.text_primary}; background: transparent;")
        title_font = QFont()
        title_font.setPointSize(10)
        self._title_lbl.setFont(title_font)
        text_col.addWidget(self._title_lbl)

        self._artist_lbl = CaptionLabel(artist or "—")
        self._artist_lbl.setStyleSheet(f"color: {c.text_secondary}; background: transparent;")
        text_col.addWidget(self._artist_lbl)

        # Progress bar (hidden until download starts)
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 1000)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(3)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {c.border};
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

        # Speed/ETA label (hidden until download starts)
        self._speed_lbl = CaptionLabel("")
        self._speed_lbl.setStyleSheet(
            f"color: {c.text_tertiary}; background: transparent; font-size: 9px;"
        )
        self._speed_lbl.setVisible(False)
        text_col.addWidget(self._speed_lbl)

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
        c = get_colors()
        colors = _PLATFORM_COLORS.get(kind.lower())
        if colors:
            bg, fg = colors
        else:
            bg, fg = c.border, c.text_secondary
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
        c = get_colors()
        bg = c.surface2 if hover else c.surface
        self.setStyleSheet(f"""
            QFrame#trackCard {{
                background: {bg};
                border: 1px solid {c.border};
                border-radius: {_RADIUS}px;
            }}
            QFrame#trackCard:hover {{
                border-color: {ACCENT_COLOR}44;
            }}
        """)

    def _apply_theme(self) -> None:
        """Re-apply all palette-dependent styles (called on theme change)."""
        c = get_colors()
        self._refresh_style(hover=False)
        self._thumb_lbl.setStyleSheet(f"border-radius: 6px; border: 1px solid {c.border};")
        self._title_lbl.setStyleSheet(f"color: {c.text_primary}; background: transparent;")
        self._artist_lbl.setStyleSheet(f"color: {c.text_secondary}; background: transparent;")
        self._speed_lbl.setStyleSheet(
            f"color: {c.text_tertiary}; background: transparent; font-size: 9px;"
        )
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {c.border}; border: none; border-radius: 1px;
            }}
            QProgressBar::chunk {{
                background: {ACCENT_COLOR}; border-radius: 1px;
            }}
        """)
        # Refresh dot color for current status
        color = _STATUS_COLORS.get(self._status, "") or c.text_tertiary
        self._dot.setStyleSheet(f"color: {color}; background: transparent; font-size: 10px;")
        # Refresh platform badge
        plat_label = _PLATFORM_BADGE_LABELS.get(self._platform, self._platform.upper()[:4])
        self._plat_badge.setText(plat_label)
        colors = _PLATFORM_COLORS.get(self._platform)
        if colors:
            bg_p, fg_p = colors
        else:
            bg_p, fg_p = c.border, c.text_secondary
        self._plat_badge.setStyleSheet(f"""
            QLabel {{
                background: {bg_p}; color: {fg_p};
                border-radius: 4px; padding: 1px 6px;
                font-size: 10px; font-weight: 600;
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
        """Load and scale the thumbnail while preserving native aspect ratio."""
        if pixmap.isNull():
            return
            
        w = pixmap.width()
        h = pixmap.height()
        target_h = _THUMB_H
        
        # If the image is square (or very close), make the container square
        if w > 0 and h > 0 and (w / h) < 1.2:
            target_w = _THUMB_H
        else:
            target_w = _THUMB_W
            
        self._thumb_lbl.setFixedSize(target_w, target_h)
        
        # Scale to fit within target bounds (KeepAspectRatio)
        scaled = pixmap.scaled(
            target_w, target_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        
        self._thumb_lbl.setPixmap(scaled)

    def set_progress(self, fraction: float) -> None:
        self._progress_bar.setValue(int(fraction * 1000))
        self._progress_bar.setVisible(fraction > 0.0 and self._status not in ("done", "error", "cancelled"))

    def update_speed(self, speed_bps: Optional[float], eta_seconds: Optional[float]) -> None:
        """Show speed/ETA below the progress bar while downloading."""
        if speed_bps and speed_bps > 0:
            if speed_bps >= 1_048_576:
                speed_str = f"{speed_bps / 1_048_576:.1f} MB/s"
            else:
                speed_str = f"{speed_bps / 1024:.0f} KB/s"
            if eta_seconds and eta_seconds > 0:
                m, s = divmod(int(eta_seconds), 60)
                eta_str = f"{m}:{s:02d}"
            else:
                eta_str = "—"
            self._speed_lbl.setText(f"{speed_str} · ETA {eta_str}")
            self._speed_lbl.setVisible(True)
        else:
            self._speed_lbl.setVisible(False)

    def set_status(self, status: str) -> None:
        """
        Update the visual state.

        status : one of "queued" | "downloading" | "processing" |
                         "done" | "error" | "cancelled" | "paused"
        """
        self._status = status
        self.status_changed.emit(status)
        color = _STATUS_COLORS.get(status, "") or get_colors().text_tertiary
        self._dot.setStyleSheet(
            f"color: {color}; background: transparent; font-size: 10px;"
        )

        # Update button visibility
        self._pause_btn.setVisible(status == "downloading")
        self._resume_btn.setVisible(status == "paused")

        # Hide speed label when not downloading
        if status not in ("downloading", "processing"):
            self._speed_lbl.setVisible(False)
            self._speed_lbl.setText("")

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
