"""
ui/panels/search_panel.py  –  Universal search panel
=====================================================
Full-panel search interface with:
  - A SearchLineEdit at the top
  - A SegmentedWidget tab bar for platform selection (YouTube / Spotify)
  - An incrementally populated results list of SearchResultCards
    grouped into coloured section headers: Tracks / Albums / Playlists /
    Artists / Channels
  - A results-count label and a "Clear results" button
  - An empty-state illustration shown before the first search

Signals emitted upward
----------------------
add_to_queue_requested(SearchResult)
    Forwarded from SearchResultCard.add_to_queue → AppWindow.
drill_down_requested(SearchResult)
    Forwarded from SearchResultCard.browse_requested → AppWindow.
    Signals the user wants to drill into an Album / Playlist / Artist /
    Channel; AppWindow starts a FetchWorker for that result's URL.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMenu,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, IndeterminateProgressRing,
    PushButton, SearchLineEdit,
)

from config import AppConfig
from core.search_engine import ResultKind, SearchResult
from ui.components.search_result_card import SearchResultCard
from ui.i18n import t
from ui.theme_manager import (
    ACCENT_COLOR,
    BG_DARK, SURFACE_DARK, BORDER_DARK,
    TEXT_DARK, TEXT2_DARK, TEXT3_DARK,
)


# ── Design tokens ──────────────────────────────────────────────────────────────
_BG      = BG_DARK       # "#0d0d12"
_SURFACE = SURFACE_DARK  # "#16161f"
_BORDER  = BORDER_DARK   # "#252533"
_TEXT    = TEXT_DARK     # "#eeeef5"
_TEXT_2  = TEXT2_DARK    # "#8888a8"
_TEXT_3  = TEXT3_DARK    # "#4a4a66"

logger = logging.getLogger(__name__)

# Section order and display labels
_SECTION_ORDER: list[ResultKind] = [
    ResultKind.TRACK,
    ResultKind.ALBUM,
    ResultKind.PLAYLIST,
    ResultKind.ARTIST,
    ResultKind.CHANNEL,
]

_SECTION_LABELS: dict[ResultKind, str] = {
    ResultKind.TRACK:    "Tracks",
    ResultKind.ALBUM:    "Albums",
    ResultKind.PLAYLIST: "Playlists",
    ResultKind.ARTIST:   "Artists",
    ResultKind.CHANNEL:  "Channels",
}

# ──────────────────────────────────────────────────────────────────────────────
# SearchPanel
# ──────────────────────────────────────────────────────────────────────────────

class SearchPanel(QWidget):
    """
    Full-height panel for the Search navigation tab.

    Parameters
    ----------
    config : AppConfig – to read/write last_search_query & last_search_platform.
    parent : Optional Qt parent.
    """

    add_to_queue_requested = Signal(object)   # SearchResult
    drill_down_requested   = Signal(object)   # SearchResult
    search_requested       = Signal(str)      # query to search

    def __init__(self, config: AppConfig, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._config    = config
        self._cards:    list[SearchResultCard] = []
        self._searching = False
        self._current_platform = "youtube"

        # Per-section containers and card lists (populated in _build)
        self._section_widgets:  dict[ResultKind, QWidget]           = {}
        self._section_layouts:  dict[ResultKind, QVBoxLayout]       = {}
        self._section_cards:    dict[ResultKind, list[SearchResultCard]] = {
            k: [] for k in _SECTION_ORDER
        }

        self._build()
        self._restore_state()

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_query(self) -> str:
        return self._search_box.text().strip()

    def get_platform(self) -> str:
        return self._current_platform

    def set_searching(self, searching: bool) -> None:
        """Show/hide the progress ring and lock the search field during a query."""
        self._searching = searching
        self._search_box.setEnabled(not searching)
        if searching:
            self._ring.setVisible(True)
            self._ring.start()
            self._results_lbl.setText(t("searching"))
        else:
            self._ring.stop()
            self._ring.setVisible(False)

    def add_result(self, result: SearchResult) -> SearchResultCard:
        """
        Add one SearchResultCard to the appropriate section.
        Called incrementally by AppWindow as SearchWorker emits result_ready.
        """
        logger.debug("[SearchPanel] Adding result to UI: %s (kind=%s)", result.title, result.kind)
        self._empty_widget.setVisible(False)

        kind = result.kind
        # Fallback: unknown kinds go into TRACK section
        if kind not in _SECTION_ORDER:
            kind = ResultKind.TRACK

        # Show the section header on the first card of that kind
        section_w = self._section_widgets.get(kind)
        if section_w and not section_w.isVisible():
            section_w.setVisible(True)

        section_layout = self._section_layouts.get(kind, self._section_layouts[ResultKind.TRACK])
        card = SearchResultCard(result, parent=self._results_container)
        card.add_to_queue.connect(self.add_to_queue_requested)
        card.browse_requested.connect(self.drill_down_requested)
        section_layout.addWidget(card)

        self._section_cards[kind].append(card)
        self._cards.append(card)
        self._update_count()
        return card

    def clear_results(self) -> None:
        """Remove all result cards and show the empty state."""
        for card in self._cards:
            card.deleteLater()
        self._cards.clear()
        for kind in _SECTION_ORDER:
            self._section_cards[kind].clear()
            w = self._section_widgets.get(kind)
            if w:
                w.setVisible(False)
        self._results_lbl.setText("")
        self._empty_widget.setVisible(True)

    def set_result_count(self, count: int) -> None:
        if count == 0:
            self._results_lbl.setText(t("no_results"))
        else:
            self._results_lbl.setText(
                t("results_count", n=count, plural=("s" if count != 1 else ""))
            )

    def save_state(self) -> None:
        """Persist the current query and platform to config."""
        self._config.last_search_query    = self.get_query()
        self._config.last_search_platform = self.get_platform()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(f"background: {_BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 0)
        root.setSpacing(10)

        # ── Top bar: search box + platform selector ───────────────────────────
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        self._search_box = SearchLineEdit()
        self._search_box.setPlaceholderText(t("search_placeholder"))
        self._search_box.setMinimumHeight(42)
        self._search_box.setStyleSheet(f"""
            SearchLineEdit {{
                background: {_SURFACE};
                border: 1.5px solid {_BORDER};
                border-radius: 8px;
                color: {_TEXT};
                font-size: 13px;
            }}
            SearchLineEdit:focus {{
                border-color: {ACCENT_COLOR};
            }}
        """)
        self._search_box.searchSignal.connect(self._on_search)
        self._search_box.returnPressed.connect(self._on_search_return)
        top_row.addWidget(self._search_box, stretch=1)

        # Platform selector button with dropdown menu
        self._platform_btn = PushButton(t("platform_youtube"))
        self._platform_btn.setFixedSize(140, 42)
        self._platform_menu = QMenu()

        youtube_action = self._platform_menu.addAction(t("platform_youtube"))
        youtube_action.triggered.connect(lambda: self._set_platform("youtube"))

        spotify_action = self._platform_menu.addAction(t("platform_spotify"))
        spotify_action.triggered.connect(lambda: self._set_platform("spotify"))

        both_action = self._platform_menu.addAction(t("platform_both"))
        both_action.triggered.connect(lambda: self._set_platform("both"))

        self._platform_btn.setMenu(self._platform_menu)
        self._current_platform = "youtube"
        top_row.addWidget(self._platform_btn)

        root.addLayout(top_row)

        # ── Sub-bar: result count + ring + clear button ───────────────────────
        sub_row = QHBoxLayout()
        sub_row.setSpacing(8)

        self._results_lbl = CaptionLabel("")
        self._results_lbl.setStyleSheet(
            f"color: {_TEXT_2}; background: transparent;"
        )
        sub_row.addWidget(self._results_lbl)

        self._ring = IndeterminateProgressRing()
        self._ring.setFixedSize(20, 20)
        self._ring.setVisible(False)
        sub_row.addWidget(self._ring)

        sub_row.addStretch()

        clear_btn = PushButton(t("clear_results"))
        clear_btn.setFixedHeight(28)
        clear_btn.setStyleSheet(f"""
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
        clear_btn.clicked.connect(self.clear_results)
        sub_row.addWidget(clear_btn)

        root.addLayout(sub_row)

        # ── Divider ───────────────────────────────────────────────────────────
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background: {_BORDER}; border: none;")
        root.addWidget(divider)

        # ── Scrollable results area ───────────────────────────────────────────
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
            QScrollBar::handle:vertical:hover {{ background: {ACCENT_COLOR}; }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

        self._results_container = QWidget()
        self._results_container.setStyleSheet(f"background: {_BG};")
        outer_layout = QVBoxLayout(self._results_container)
        outer_layout.setContentsMargins(0, 4, 0, 16)
        outer_layout.setSpacing(0)
        outer_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Empty state
        self._empty_widget = self._build_empty_state()
        outer_layout.addWidget(self._empty_widget)

        # ── Build one collapsible section per ResultKind ──────────────────────
        for kind in _SECTION_ORDER:
            section_w, cards_layout = self._build_section(kind)
            section_w.setVisible(False)      # hidden until first result arrives
            outer_layout.addWidget(section_w)
            self._section_widgets[kind]  = section_w
            self._section_layouts[kind]  = cards_layout

        outer_layout.addStretch()
        scroll.setWidget(self._results_container)
        root.addWidget(scroll, stretch=1)

    def _build_section(self, kind: ResultKind) -> tuple[QWidget, QVBoxLayout]:
        """Return (section_container, cards_layout) for one ResultKind."""
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 8, 0, 4)
        v.setSpacing(4)

        # Section header with amber left border
        header = QLabel(_SECTION_LABELS[kind].upper())
        header.setStyleSheet(f"""
            QLabel {{
                color: {_TEXT_2};
                font-size: 10px;
                font-weight: bold;
                letter-spacing: 1px;
                padding-left: 10px;
                border-left: 3px solid {ACCENT_COLOR};
                background: transparent;
            }}
        """)
        header.setFixedHeight(20)
        v.addWidget(header)

        # Cards go here
        cards_layout = QVBoxLayout()
        cards_layout.setSpacing(4)
        cards_layout.setContentsMargins(0, 4, 0, 0)
        v.addLayout(cards_layout)

        return container, cards_layout

    def _build_empty_state(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.setSpacing(12)

        icon = QLabel("🔍")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 52px; background: transparent;")
        v.addWidget(icon)

        hint = BodyLabel(t("search_empty_hint"))
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(f"color: {_TEXT_3}; background: transparent;")
        v.addWidget(hint)

        return w

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _restore_state(self) -> None:
        if self._config.last_search_query:
            self._search_box.setText(self._config.last_search_query)
        platform = self._config.last_search_platform
        if platform in ("youtube", "spotify", "both"):
            self._set_platform(platform)

    def _update_count(self) -> None:
        n = len(self._cards)
        self._results_lbl.setText(
            t("results_count", n=n, plural=("s" if n != 1 else ""))
        )

    def _on_search(self, query: str) -> None:
        query = query.strip()
        logger.debug("[SearchPanel] Search via icon: %r (Platform: %s)", query, self._current_platform)
        if query and not self._searching:
            self.clear_results()
            self.save_state()
            self.search_requested.emit(query)

    def _set_platform(self, platform: str) -> None:
        self._current_platform = platform
        if platform == "youtube":
            self._platform_btn.setText(t("platform_youtube"))
        elif platform == "spotify":
            self._platform_btn.setText(t("platform_spotify"))
        elif platform == "both":
            self._platform_btn.setText(t("platform_both"))

    def _on_search_return(self) -> None:
        query = self._search_box.text().strip()
        logger.debug("[SearchPanel] Search via Enter: %r (Platform: %s)", query, self._current_platform)
        if query and not self._searching:
            self.clear_results()
            self.save_state()
            self.search_requested.emit(query)
