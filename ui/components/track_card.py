"""
ui/components/track_card.py  –  Draggable download queue entry widget
======================================================================
Represents one track in the download queue panel.  Supports:

* Thumbnail display with a grey placeholder until the image loads.
* Checkbox for per-track selection (checked by default).
* Title, artist, duration, and platform badge labels.
* A vertical progress bar on the right edge that fills as the download
  progresses.
* A coloured status dot (queued / downloading / done / error / cancelled).
* Full drag-and-drop reordering:  the card is the drag source; the parent
  QueuePanel's scroll-area is the drop target.  The drag payload is the
  card's queue_index encoded as UTF-8 bytes so the panel can reorder its
  internal list correctly.
* A "remove" (×) button that is visible on hover and emits remove_requested.

Drag-and-drop protocol
-----------------------
Source (this card):
    mousePressEvent records the press position.
    mouseMoveEvent starts a QDrag with mimeData text = str(self.queue_index)
    when the cursor moves more than QApplication.startDragDistance().

Target (QueuePanel – implemented in ui/panels/queue_panel.py):
    dragEnterEvent  – accept if mimeData has text.
    dragMoveEvent   – draw a drop-indicator line between cards.
    dropEvent       – parse the source index, reorder the layout, emit
                      reorder_requested(from_index, to_index).
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (
    QByteArray, QMimeData, QPoint, QSize, Qt, Signal,
)
from PySide6.QtGui import (
    QColor, QDrag, QFont, QImage, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QHBoxLayout,
    QLabel, QProgressBar, QSizePolicy, QVBoxLayout, QWidget,
)
from qfluentwidgets import BodyLabel, CaptionLabel, ToolButton

from ui.theme_manager import ACCENT_COLOR


# ──────────────────────────────────────────────────────────────────────────────
# Design tokens  (local, so components stay self-contained)
# ──────────────────────────────────────────────────────────────────────────────

_BG_NORMAL   = "#18181b"
_BG_HOVER    = "#2a2a32"
_BG_DRAG     = "#1f1f28"
_BORDER      = "#2e2e35"
_TEXT        = "#f0f0f0"
_TEXT_2      = "#9090a0"
_TEXT_3      = "#55555f"
_SUCCESS     = "#34d399"
_ERROR       = "#f87171"
_WARNING     = "#fbbf24"
_RADIUS      = 8
_THUMB_W     = 96
_THUMB_H     = 54

# Status → dot colour
_STATUS_COLORS: dict[str, str] = {
    "queued":      _TEXT_3,
    "downloading": ACCENT_COLOR,
    "processing":  ACCENT_COLOR,
    "done":        _SUCCESS,
    "error":       _ERROR,
    "cancelled":   _WARNING,
}

# Platform badge colours  (bg, fg)
_PLATFORM_COLORS: dict[str, tuple[str, str]] = {
    "youtube":  ("#ff4444", "#ffffff"),
    "ytmusic":  ("#ff4444", "#ffffff"),
    "spotify":  ("#1db954", "#ffffff"),
    "default":  ("#2e2e35", _TEXT_2),
}


def _make_placeholder_pixmap(w: int = _THUMB_W, h: int = _THUMB_H) -> QPixmap:
    """Return a dark-grey rectangle with a centred play-triangle."""
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#1a1a20"))
    # Draw a simple triangle using raw pixel manipulation – no QPainter dependency
    cx, cy = w // 2, h // 2
    for row in range(h):
        for col in range(w):
            dy = abs(row - cy)
            dx = col - (cx - 10)
            if 0 < dx < 20 - dy and dy < 10:
                img.setPixelColor(col, row, QColor("#2a2a35"))
    return QPixmap.fromImage(img)


# ──────────────────────────────────────────────────────────────────────────────
# TrackCard
# ──────────────────────────────────────────────────────────────────────────────

class TrackCard(QFrame):
    """
    One entry in the download queue.

    Signals
    -------
    remove_requested(int)
        Emitted when the user clicks the × button.
        Payload is self.queue_index so the panel can find and remove it.
    selection_changed()
        Emitted when the checkbox state changes so the panel can update
        the "N of M selected" counter.
    """

    remove_requested  = Signal(int)   # queue_index
    selection_changed = Signal()

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def __init__(
        self,
        queue_index:   int,
        title:         str,
        artist:        str         = "",
        duration:      str         = "",
        platform:      str         = "youtube",
        thumbnail_url: str         = "",
        track_url:     str         = "",
        parent:        QWidget     = None,
    ) -> None:
        super().__init__(parent)

        # Public state read by the panel
        self.queue_index   = queue_index
        self.title         = title
        self.artist        = artist
        self.track_url     = track_url
        self.thumbnail_url = thumbnail_url

        self._drag_start_pos: Optional[QPoint] = None

        self._build(title, artist, duration, platform)
        self._apply_base_style()
        self._install_hover()

    # ── Public API ─────────────────────────────────────────────────────────────

    def is_selected(self) -> bool:
        return self._checkbox.isChecked()

    def set_selected(self, checked: bool) -> None:
        self._checkbox.setChecked(checked)

    def set_thumbnail(self, raw_bytes: bytes) -> None:
        """Decode raw image bytes and display the thumbnail."""
        pixmap = QPixmap()
        if pixmap.loadFromData(raw_bytes):
            pixmap = pixmap.scaled(
                _THUMB_W, _THUMB_H,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            # Centre-crop to exact thumbnail size
            x = (pixmap.width()  - _THUMB_W) // 2
            y = (pixmap.height() - _THUMB_H) // 2
            pixmap = pixmap.copy(x, y, _THUMB_W, _THUMB_H)
            self._thumb_label.setPixmap(pixmap)

    def set_status(self, status: str) -> None:
        """Update the status dot colour and progress bar visibility."""
        color = _STATUS_COLORS.get(status, _TEXT_3)
        self._status_dot.setStyleSheet(f"color: {color}; background: transparent;")

        if status == "downloading":
            self._progress_bar.setVisible(True)
        elif status in ("done", "error", "cancelled"):
            self._progress_bar.setVisible(False)
            if status == "done":
                self._progress_bar.setValue(100)

    def set_progress(self, fraction: float) -> None:
        """Update the vertical progress bar (0.0 – 1.0)."""
        value = int(max(0.0, min(1.0, fraction)) * 100)
        self._progress_bar.setValue(value)

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(
        self,
        title:    str,
        artist:   str,
        duration: str,
        platform: str,
    ) -> None:
        self.setFixedHeight(80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 6, 0, 6)
        outer.setSpacing(0)

        # ── Checkbox ──────────────────────────────────────────────────────────
        self._checkbox = QCheckBox()
        self._checkbox.setChecked(True)
        self._checkbox.setFixedSize(20, 20)
        self._checkbox.stateChanged.connect(lambda _: self.selection_changed.emit())
        self._checkbox.setStyleSheet(f"""
            QCheckBox::indicator {{
                width: 16px; height: 16px;
                border: 2px solid {_BORDER};
                border-radius: 4px;
                background: transparent;
            }}
            QCheckBox::indicator:checked {{
                background-color: {ACCENT_COLOR};
                border-color: {ACCENT_COLOR};
                image: none;
            }}
        """)
        outer.addWidget(self._checkbox)
        outer.addSpacing(10)

        # ── Thumbnail ─────────────────────────────────────────────────────────
        self._thumb_label = QLabel()
        self._thumb_label.setFixedSize(_THUMB_W, _THUMB_H)
        self._thumb_label.setPixmap(_make_placeholder_pixmap())
        self._thumb_label.setScaledContents(False)
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_label.setStyleSheet(
            f"border-radius: 4px; background: #1a1a20;"
        )
        outer.addWidget(self._thumb_label)
        outer.addSpacing(10)

        # ── Text block ────────────────────────────────────────────────────────
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.setContentsMargins(0, 0, 0, 0)

        self._title_lbl = BodyLabel(f"{self.queue_index}. {title}")
        self._title_lbl.setStyleSheet(f"color: {_TEXT}; background: transparent;")
        title_font = QFont()
        title_font.setPointSize(10)
        self._title_lbl.setFont(title_font)
        text_col.addWidget(self._title_lbl)

        self._artist_lbl = CaptionLabel(artist or "—")
        self._artist_lbl.setStyleSheet(f"color: {_TEXT_2}; background: transparent;")
        text_col.addWidget(self._artist_lbl)

        outer.addLayout(text_col, stretch=1)
        outer.addSpacing(8)

        # ── Badges (duration + platform) ──────────────────────────────────────
        badge_col = QVBoxLayout()
        badge_col.setSpacing(4)
        badge_col.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

        self._dur_badge   = self._make_badge(duration or "--:--", "default")
        self._plat_badge  = self._make_badge(platform.upper(), platform)
        badge_col.addWidget(self._dur_badge,  alignment=Qt.AlignmentFlag.AlignRight)
        badge_col.addWidget(self._plat_badge, alignment=Qt.AlignmentFlag.AlignRight)
        outer.addLayout(badge_col)
        outer.addSpacing(6)

        # ── Remove button ─────────────────────────────────────────────────────
        self._remove_btn = ToolButton()
        self._remove_btn.setText("✕")
        self._remove_btn.setFixedSize(28, 28)
        self._remove_btn.setVisible(False)
        self._remove_btn.clicked.connect(
            lambda: self.remove_requested.emit(self.queue_index)
        )
        self._remove_btn.setStyleSheet(f"""
            ToolButton {{
                background: transparent;
                border: none;
                color: {_TEXT_3};
                font-size: 11px;
            }}
            ToolButton:hover {{ color: {_ERROR}; }}
        """)
        outer.addWidget(self._remove_btn)
        outer.addSpacing(2)

        # ── Status dot ────────────────────────────────────────────────────────
        self._status_dot = QLabel("●")
        self._status_dot.setFixedWidth(16)
        self._status_dot.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self._status_dot.setStyleSheet(f"color: {_TEXT_3}; background: transparent;")
        outer.addWidget(self._status_dot)
        outer.addSpacing(2)

        # ── Vertical progress bar ─────────────────────────────────────────────
        self._progress_bar = QProgressBar()
        self._progress_bar.setOrientation(Qt.Orientation.Vertical)
        self._progress_bar.setFixedWidth(4)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setVisible(False)
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {_BORDER};
                border: none;
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background: {ACCENT_COLOR};
                border-radius: 2px;
            }}
        """)
        outer.addWidget(self._progress_bar)

    @staticmethod
    def _make_badge(text: str, kind: str) -> QLabel:
        bg, fg = _PLATFORM_COLORS.get(kind, _PLATFORM_COLORS["default"])
        lbl = QLabel(text)
        lbl.setFont(QFont("Consolas", 9))
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: 3px;"
            f" padding: 1px 5px;"
        )
        lbl.setFixedHeight(18)
        return lbl

    # ── Styling ───────────────────────────────────────────────────────────────

    def _apply_base_style(self) -> None:
        self.setStyleSheet(f"""
            TrackCard {{
                background-color: {_BG_NORMAL};
                border: 1px solid {_BORDER};
                border-radius: {_RADIUS}px;
            }}
        """)

    def _install_hover(self) -> None:
        for w in (self, self._thumb_label, self._title_lbl, self._artist_lbl):
            w.setMouseTracking(True)

    # ── Events ────────────────────────────────────────────────────────────────

    def enterEvent(self, event) -> None:
        self.setStyleSheet(f"""
            TrackCard {{
                background-color: {_BG_HOVER};
                border: 1px solid {ACCENT_COLOR};
                border-radius: {_RADIUS}px;
            }}
        """)
        self._remove_btn.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._apply_base_style()
        self._remove_btn.setVisible(False)
        super().leaveEvent(event)

    # ── Drag-and-drop source ──────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (
            event.buttons() & Qt.MouseButton.LeftButton
            and self._drag_start_pos is not None
        ):
            delta = (event.position().toPoint() - self._drag_start_pos).manhattanLength()
            if delta >= QApplication.startDragDistance():
                self._start_drag()
        super().mouseMoveEvent(event)

    def _start_drag(self) -> None:
        drag = QDrag(self)
        mime = QMimeData()
        # Encode the queue_index as plain text; the panel decodes it in dropEvent
        mime.setText(str(self.queue_index))
        drag.setMimeData(mime)

        # Render the card itself as the drag pixmap
        pixmap = self.grab()
        drag.setPixmap(pixmap.scaled(
            pixmap.width() // 2,
            pixmap.height() // 2,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))
        drag.setHotSpot(QPoint(drag.pixmap().width() // 2, drag.pixmap().height() // 2))

        # Visual feedback during drag
        self.setStyleSheet(f"""
            TrackCard {{
                background-color: {_BG_DRAG};
                border: 1px dashed {ACCENT_COLOR};
                border-radius: {_RADIUS}px;
                opacity: 0.7;
            }}
        """)
        drag.exec(Qt.DropAction.MoveAction)
        self._apply_base_style()
