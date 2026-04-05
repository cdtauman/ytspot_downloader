"""
ui/panels/queue_panel.py  –  Smart drag-and-drop download queue
================================================================
The main panel shown on the Queue navigation tab.  Responsibilities:
  - Add / remove TrackCards and keep a canonical ordered list.
  - Accept drag-and-drop reordering from TrackCard drag sources.
  - "Select All / Deselect All" header checkbox.
  - Expose get_selected_cards() for DownloadWorker job building.
  - Show a friendly empty state before any tracks are loaded.
  - Draw a live drop-indicator line between cards during a drag.

Signals emitted upward
----------------------
selection_changed(int)    Number of currently selected cards changed.
card_removed(int)         A card's remove button was clicked; payload is queue_index.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (
    Qt, QPoint, Signal,
)
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)
from qfluentwidgets import BodyLabel, CaptionLabel, PushButton

from ui.components.track_card import TrackCard
from ui.i18n import t
from ui.theme_manager import ACCENT_COLOR


# ── Design tokens ──────────────────────────────────────────────────────────────
_BG      = "#111114"
_SURFACE = "#1c1c21"
_BORDER  = "#313139"
_TEXT    = "#f2f2f5"
_TEXT_2  = "#94949e"
_TEXT_3  = "#5a5a66"


# ──────────────────────────────────────────────────────────────────────────────
# Drop-indicator overlay
# ──────────────────────────────────────────────────────────────────────────────

class _DropIndicator(QWidget):
    """
    A 2-px horizontal amber line drawn between cards to show the drop target.
    Parented to the scroll-content widget and positioned manually.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedHeight(2)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(QPen(QColor(ACCENT_COLOR), 2))
        painter.drawLine(0, 0, self.width(), 0)

    def show_at_y(self, y: int) -> None:
        self.setGeometry(8, y - 1, self.parent().width() - 16, 2)
        self.raise_()
        self.show()


# ──────────────────────────────────────────────────────────────────────────────
# Scroll content widget  (accepts drops)
# ──────────────────────────────────────────────────────────────────────────────

class _DropArea(QWidget):
    """
    The inner widget of the scroll area.  Overrides drag events so that
    TrackCards can be reordered by dragging.
    """

    reorder_requested = Signal(int, int)   # (from_queue_index, to_queue_index)

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._indicator = _DropIndicator(self)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 12)
        self._layout.setSpacing(4)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)

    @property
    def cards_layout(self) -> QVBoxLayout:
        return self._layout

    # ── Drag-and-drop target ──────────────────────────────────────────────────

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasText():
            event.acceptProposedAction()
            insert_y = self._insertion_y(event.position().toPoint())
            self._indicator.show_at_y(insert_y)

    def dragLeaveEvent(self, event) -> None:
        self._indicator.hide()

    def dropEvent(self, event) -> None:
        self._indicator.hide()
        if not event.mimeData().hasText():
            return

        try:
            from_index = int(event.mimeData().text())
        except ValueError:
            return

        drop_pos    = event.position().toPoint()
        to_index    = self._card_index_at(drop_pos)

        if to_index != from_index:
            self.reorder_requested.emit(from_index, to_index)

        event.acceptProposedAction()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _insertion_y(self, pos: QPoint) -> int:
        """Return the Y coordinate of the nearest card gap to the cursor."""
        for i in range(self._layout.count()):
            item = self._layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                mid_y  = widget.y() + widget.height() // 2
                if pos.y() < mid_y:
                    return widget.y()
        # Below all cards
        last = self._layout.itemAt(self._layout.count() - 1)
        if last and last.widget():
            w = last.widget()
            return w.y() + w.height()
        return pos.y()

    def _card_index_at(self, pos: QPoint) -> int:
        """Return the logical queue_index of the card nearest the drop position."""
        best_index    = 0
        best_distance = float("inf")
        for i in range(self._layout.count()):
            item = self._layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), TrackCard):
                card    = item.widget()
                card_cy = card.y() + card.height() // 2
                dist    = abs(pos.y() - card_cy)
                if dist < best_distance:
                    best_distance = dist
                    best_index    = card.queue_index
        return best_index


# ──────────────────────────────────────────────────────────────────────────────
# QueuePanel
# ──────────────────────────────────────────────────────────────────────────────

class QueuePanel(QWidget):
    """
    The download queue panel.

    Parameters
    ----------
    parent : Optional Qt parent widget.
    """

    selection_changed = Signal(int)   # count of selected cards
    card_removed      = Signal(int)   # queue_index of removed card

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._cards: list[TrackCard] = []   # ordered list of all cards
        self._build()

    # ── Public API ─────────────────────────────────────────────────────────────

    def add_card(
        self,
        index:         int,
        title:         str,
        artist:        str         = "",
        duration:      str         = "",
        platform:      str         = "youtube",
        thumbnail_url: str         = "",
        track_url:     str         = "",
    ) -> TrackCard:
        """
        Create and append a new TrackCard.  Hides the empty state on first add.
        Returns the card so the caller can keep a card_key → card mapping.
        """
        if not self._cards:
            self._empty_widget.setVisible(False)

        card = TrackCard(
            queue_index=index,
            title=title,
            artist=artist,
            duration=duration,
            platform=platform,
            thumbnail_url=thumbnail_url,
            track_url=track_url,
            parent=self._drop_area,
        )
        card.remove_requested.connect(self._on_card_remove)
        card.selection_changed.connect(self._on_selection_change)

        self._drop_area.cards_layout.addWidget(card)
        self._cards.append(card)
        self._update_header()
        return card

    def clear(self) -> None:
        """Remove all cards and show the empty state."""
        for card in self._cards:
            card.deleteLater()
        self._cards.clear()
        self._empty_widget.setVisible(True)
        self._update_header()

    def get_all_cards(self) -> list[TrackCard]:
        return list(self._cards)

    def get_selected_cards(self) -> list[TrackCard]:
        return [c for c in self._cards if c.is_selected()]

    def card_by_index(self, queue_index: int) -> Optional[TrackCard]:
        for c in self._cards:
            if c.queue_index == queue_index:
                return c
        return None

    def set_all_selected(self, checked: bool) -> None:
        for c in self._cards:
            c.set_selected(checked)
        self._on_selection_change()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(f"background: {_BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────────
        header = QFrame()
        header.setFixedHeight(44)
        header.setStyleSheet(
            f"background: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        h_row = QHBoxLayout(header)
        h_row.setContentsMargins(12, 0, 12, 0)
        h_row.setSpacing(8)

        self._all_chk = QCheckBox(t("select_deselect_all"))
        self._all_chk.setChecked(True)
        self._all_chk.setStyleSheet(f"""
            QCheckBox {{
                color: {_TEXT_2};
                font-size: 12px;
                background: transparent;
            }}
            QCheckBox::indicator {{
                width: 15px; height: 15px;
                border: 1.5px solid {_BORDER};
                border-radius: 3px;
                background: transparent;
            }}
            QCheckBox::indicator:checked {{
                background-color: {ACCENT_COLOR};
                border-color: {ACCENT_COLOR};
            }}
        """)
        self._all_chk.stateChanged.connect(
            lambda s: self.set_all_selected(bool(s))
        )
        h_row.addWidget(self._all_chk)
        h_row.addStretch()

        self._count_lbl = CaptionLabel(t("no_tracks_loaded"))
        self._count_lbl.setStyleSheet(
            f"color: {_TEXT_3}; background: transparent;"
        )
        h_row.addWidget(self._count_lbl)

        clear_done_btn = PushButton(t("clear_completed"))
        clear_done_btn.setFixedHeight(26)
        clear_done_btn.setStyleSheet(f"""
            PushButton {{
                background: transparent;
                border: 1px solid {_BORDER};
                border-radius: 6px;
                color: {_TEXT_2};
                font-size: 11px;
                padding: 0 8px;
            }}
            PushButton:hover {{
                border-color: {ACCENT_COLOR};
                color: {ACCENT_COLOR};
            }}
        """)
        clear_done_btn.clicked.connect(self._clear_completed)
        h_row.addWidget(clear_done_btn)

        root.addWidget(header)

        # ── Scroll area ───────────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background: {_BG}; border: none; }}
            QScrollBar:vertical {{
                background: {_BG};
                width: 6px;
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: {_BORDER};
                border-radius: 3px;
                min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{ background: #3e3e47; }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

        self._drop_area = _DropArea()
        self._drop_area.setStyleSheet(f"background: {_BG};")
        self._drop_area.reorder_requested.connect(self._on_reorder)

        # Empty state (inside drop area so it fills the space)
        self._empty_widget = self._build_empty_state()
        self._drop_area.cards_layout.addWidget(self._empty_widget)

        scroll.setWidget(self._drop_area)
        root.addWidget(scroll, stretch=1)

    def _build_empty_state(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.setSpacing(12)

        icon_lbl = QLabel("⬇")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(f"font-size: 52px; background: transparent; color: {_BORDER};")
        v.addWidget(icon_lbl)

        hint = BodyLabel(t("queue_empty_hint"))
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(f"color: {_TEXT_3}; background: transparent;")
        v.addWidget(hint)

        return w

    # ── Slots ──────────────────────────────────────────────────────────────────

    def _on_card_remove(self, queue_index: int) -> None:
        card = self.card_by_index(queue_index)
        if card:
            self._cards.remove(card)
            card.deleteLater()
            if not self._cards:
                self._empty_widget.setVisible(True)
            self._update_header()
            self.card_removed.emit(queue_index)
            self._on_selection_change()

    def _on_selection_change(self) -> None:
        self._update_header()
        self.selection_changed.emit(len(self.get_selected_cards()))

    def _on_reorder(self, from_index: int, to_index: int) -> None:
        """
        Reorder _cards list and re-insert the dragged widget in the layout.
        """
        from_card = self.card_by_index(from_index)
        to_card   = self.card_by_index(to_index)
        if from_card is None or to_card is None or from_card is to_card:
            return

        layout = self._drop_area.cards_layout

        # Remove from layout and list
        layout.removeWidget(from_card)
        self._cards.remove(from_card)

        # Find new position in layout
        to_layout_idx = layout.indexOf(to_card)
        if to_layout_idx < 0:
            layout.addWidget(from_card)
            self._cards.append(from_card)
        else:
            layout.insertWidget(to_layout_idx, from_card)
            to_list_idx = self._cards.index(to_card)
            self._cards.insert(to_list_idx, from_card)

    def _clear_completed(self) -> None:
        """Remove all cards whose status is 'done'."""
        to_remove = []
        for card in self._cards:
            style = card._status_dot.styleSheet()  # noqa: SLF001
            if "#34d399" in style:   # _SUCCESS colour
                to_remove.append(card)
        for card in to_remove:
            self._cards.remove(card)
            card.deleteLater()
        if not self._cards:
            self._empty_widget.setVisible(True)
        self._update_header()
        self._on_selection_change()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _update_header(self) -> None:
        n = len(self._cards)
        if n == 0:
            self._count_lbl.setText(t("no_tracks_loaded"))
        else:
            sel = len(self.get_selected_cards())
            self._count_lbl.setText(t("sel_of_n", sel=sel, n=n))
