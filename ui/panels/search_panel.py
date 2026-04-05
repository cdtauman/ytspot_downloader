"""
ui/panels/search_panel.py  –  Universal search panel
=====================================================
Full-panel search interface with:
  - A SearchLineEdit at the top
  - A SegmentedWidget tab bar for platform selection (YouTube / Spotify)
  - An incrementally populated results list of SearchResultCards
  - A results-count label and a "Clear results" button
  - An empty-state illustration shown before the first search

Signals emitted upward
----------------------
add_to_queue_requested(SearchResult)
    Forwarded from SearchResultCard.add_to_queue → AppWindow.
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
from core.search_engine import SearchResult
from ui.components.search_result_card import SearchResultCard
from ui.i18n import t
from ui.theme_manager import ACCENT_COLOR


# ── Design tokens ──────────────────────────────────────────────────────────────
_BG       = "#111114"
_SURFACE  = "#1c1c21"
_BORDER   = "#313139"
_TEXT     = "#f2f2f5"
_TEXT_2   = "#94949e"
_TEXT_3   = "#5a5a66"

logger = logging.getLogger(__name__)

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
    search_requested       = Signal(str)       # query to search

    def __init__(self, config: AppConfig, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._config    = config
        self._cards:    list[SearchResultCard] = []
        self._searching = False
        self._current_platform = "youtube"
        self._build()
        self._restore_state()

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_query(self) -> str:
        return self._search_box.text().strip()

    def get_platform(self) -> str:
        """Return the currently selected platform."""
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
        Add one SearchResultCard to the results list.
        Called incrementally by AppWindow as SearchWorker emits result_ready.
        """
        logger.debug("[SearchPanel] Adding result to UI: %s", result.title)
        self._empty_widget.setVisible(False)
        card = SearchResultCard(result, parent=self._results_container)
        card.add_to_queue.connect(self.add_to_queue_requested)
        self._results_layout.addWidget(card)
        self._cards.append(card)
        self._update_count()
        return card

    def clear_results(self) -> None:
        """Remove all result cards and show the empty state."""
        for card in self._cards:
            card.deleteLater()
        self._cards.clear()
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
            QScrollBar::handle:vertical:hover {{ background: #3e3e47; }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

        self._results_container = QWidget()
        self._results_container.setStyleSheet(f"background: {_BG};")
        self._results_layout = QVBoxLayout(self._results_container)
        self._results_layout.setContentsMargins(0, 4, 0, 16)
        self._results_layout.setSpacing(4)
        self._results_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._empty_widget = self._build_empty_state()
        self._results_layout.addWidget(self._empty_widget)

        scroll.setWidget(self._results_container)
        root.addWidget(scroll, stretch=1)

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
        """Called by SearchLineEdit.searchSignal (user clicked the search icon)."""
        query = query.strip()
        logger.debug("[SearchPanel] Search requested via click icon: %r (Platform: %s)", query, self._current_platform)
        if query and not self._searching:
            self.clear_results()
            self.save_state()
            self.search_requested.emit(query)

    def _set_platform(self, platform: str) -> None:
        """Set the current platform and update button text."""
        self._current_platform = platform
        if platform == "youtube":
            self._platform_btn.setText(t("platform_youtube"))
        elif platform == "spotify":
            self._platform_btn.setText(t("platform_spotify"))
        elif platform == "both":
            self._platform_btn.setText(t("platform_both"))

    def _on_search_return(self) -> None:
        """Called when the user presses Enter in the search box."""
        query = self._search_box.text().strip()
        logger.debug("[SearchPanel] Search requested via Enter key: %r (Platform: %s)", query, self._current_platform)
        if query and not self._searching:
            self.clear_results()
            self.save_state()
            self.search_requested.emit(query)
