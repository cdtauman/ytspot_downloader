"""
ui/dialogs/tab_select_dialog.py  –  Channel tab selection dialog (Card Grid B)
================================================================================
Three-state UX:
  1. DISCOVERING — spinner + "מגלה טאבים…"
  2. READY       — card grid of discovered tabs, each toggleable
  3. SCANNING    — progress bar while ChannelScrapeWorker runs

The dialog is modal and returns via exec().  After exec() returns Accepted, the
caller can read .selected_tabs (list[TabInfo]) and .scrape_results
(dict[tab_name → list[VideoInfo]]).
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QFrame, QSizePolicy, QScrollArea, QWidget,
    QProgressBar,
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, PrimaryPushButton, PushButton, SubtitleLabel,
)

from core.channel_tab_discoverer import TabInfo, DiscoveryResult
from core.duplicate_detector import VideoInfo
from ui.theme_manager import get_colors, ACCENT_COLOR, SUCCESS_COLOR


# ── Discovery QThread ─────────────────────────────────────────────────────────

class _DiscoveryWorker(QThread):
    finished = Signal(object)   # DiscoveryResult

    def __init__(self, url: str, parent=None) -> None:
        super().__init__(parent)
        self._url = url

    def run(self) -> None:
        from core.channel_tab_discoverer import discover_tabs
        result = discover_tabs(self._url)
        self.finished.emit(result)


# ── Tab toggle card ───────────────────────────────────────────────────────────

class _TabCard(QFrame):
    toggled = Signal(bool)

    def __init__(self, tab: TabInfo, parent=None) -> None:
        super().__init__(parent)
        self._tab     = tab
        self._checked = True
        self._build()

    @property
    def tab(self) -> TabInfo:
        return self._tab

    @property
    def is_checked(self) -> bool:
        return self._checked

    def _build(self) -> None:
        c = get_colors()
        self.setFixedSize(148, 110)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_style()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._icon_lbl = QLabel(self._tab.icon)
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_lbl.setStyleSheet("font-size: 26px; background: transparent;")

        self._name_lbl = BodyLabel(self._tab.name)
        self._name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name_lbl.setStyleSheet(f"color: {c.text_primary}; background: transparent; font-weight: 600;")

        self._count_lbl = CaptionLabel("")
        self._count_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._count_lbl.setStyleSheet(f"color: {c.text_secondary}; background: transparent;")
        self._count_lbl.hide()

        self._check_lbl = QLabel("✓")
        self._check_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._check_lbl.setStyleSheet(
            f"color: {SUCCESS_COLOR}; background: transparent; font-size: 13px; font-weight: bold;"
        )

        lay.addWidget(self._icon_lbl)
        lay.addWidget(self._name_lbl)
        lay.addWidget(self._count_lbl)
        lay.addStretch()
        lay.addWidget(self._check_lbl)

    def _refresh_style(self) -> None:
        c = get_colors()
        if self._checked:
            border_color = ACCENT_COLOR
            bg = c.surface2
        else:
            border_color = c.border
            bg = c.surface
        self.setStyleSheet(f"""
            _TabCard {{
                background: {bg};
                border: 2px solid {border_color};
                border-radius: 12px;
            }}
        """)

    def set_count(self, n: int) -> None:
        if n >= 0:
            self._count_lbl.setText(f"{n:,} פריטים")
            self._count_lbl.show()

    def mousePressEvent(self, event) -> None:
        self._checked = not self._checked
        self._check_lbl.setVisible(self._checked)
        self._refresh_style()
        self.toggled.emit(self._checked)
        super().mousePressEvent(event)


# ── Main dialog ───────────────────────────────────────────────────────────────

class TabSelectDialog(QDialog):
    """
    Modal dialog for channel tab selection + scraping.

    After exec() returns QDialog.DialogCode.Accepted:
      .selected_tabs   → list[TabInfo] the user confirmed
      .scrape_results  → dict[str, list[VideoInfo]]  (populated after scraping)
      .channel_name    → str
    """

    def __init__(
        self,
        channel_url:  str,
        cookies_file: Optional[str] = None,
        proxy_url:    Optional[str] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._url         = channel_url
        self._cookies     = cookies_file
        self._proxy       = proxy_url
        self._cards:      list[_TabCard] = []
        self._discovery:  Optional[_DiscoveryWorker] = None
        self._scraper:    Optional[QThread] = None

        # Public output
        self.selected_tabs:  list[TabInfo]               = []
        self.scrape_results: dict[str, list[VideoInfo]]  = {}
        self.channel_name:   str                         = ""

        self._build()
        self._start_discovery()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        c = get_colors()
        self.setWindowTitle("ייבוא ערוץ יוטיוב")
        self.setMinimumWidth(520)
        self.setModal(True)
        self.setStyleSheet(f"background: {c.bg};")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # Title
        self._title = SubtitleLabel("ייבוא ערוץ יוטיוב")
        self._title.setStyleSheet(f"color: {c.text_primary};")
        root.addWidget(self._title)

        # Subtitle / status line
        self._subtitle = CaptionLabel("מגלה טאבים זמינים…")
        self._subtitle.setStyleSheet(f"color: {c.text_secondary};")
        root.addWidget(self._subtitle)

        # Spinner label (shown during discovery)
        self._spinner = QLabel("⏳")
        self._spinner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._spinner.setStyleSheet("font-size: 32px;")
        root.addWidget(self._spinner)

        # Card grid (hidden until discovery finishes)
        self._grid_widget = QWidget()
        self._grid_widget.setStyleSheet("background: transparent;")
        self._grid_layout = QGridLayout(self._grid_widget)
        self._grid_layout.setSpacing(10)
        self._grid_widget.hide()
        root.addWidget(self._grid_widget)

        # Progress bar (hidden until scanning)
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {c.border};
                border-radius: 3px;
                border: none;
            }}
            QProgressBar::chunk {{
                background: {ACCENT_COLOR};
                border-radius: 3px;
            }}
        """)
        self._progress_bar.hide()
        root.addWidget(self._progress_bar)

        self._progress_label = CaptionLabel("")
        self._progress_label.setStyleSheet(f"color: {c.text_secondary};")
        self._progress_label.hide()
        root.addWidget(self._progress_label)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._cancel_btn = PushButton("ביטול")
        self._scan_btn   = PrimaryPushButton("סרוק טאבים נבחרים")
        self._scan_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self.reject)
        self._scan_btn.clicked.connect(self._on_scan_clicked)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addWidget(self._scan_btn)
        root.addLayout(btn_row)

        # Animate the spinner
        self._dot_count = 0
        self._spin_timer = QTimer(self)
        self._spin_timer.timeout.connect(self._tick_spinner)
        self._spin_timer.start(600)

    # ── Discovery ──────────────────────────────────────────────────────────────

    def _start_discovery(self) -> None:
        self._discovery = _DiscoveryWorker(self._url, parent=self)
        self._discovery.finished.connect(self._on_discovery_done)
        self._discovery.start()

    def _on_discovery_done(self, result: DiscoveryResult) -> None:
        self._spin_timer.stop()
        self._spinner.hide()
        self.channel_name = result.channel_name

        if result.error and not result.tabs:
            self._subtitle.setText(f"שגיאה בגילוי טאבים: {result.error}")
            self._scan_btn.setEnabled(False)
            return

        if result.channel_name:
            self._title.setText(f"ייבוא: {result.channel_name}")

        self._subtitle.setText(
            f"נמצאו {len(result.tabs)} טאבים — בחר מה לסרוק:"
            + (f"\n⚠ {result.error}" if result.error else "")
        )

        self._populate_grid(result.tabs)
        self._grid_widget.show()
        self._scan_btn.setEnabled(True)
        self.adjustSize()

    def _populate_grid(self, tabs: list[TabInfo]) -> None:
        cols = 3
        for i, tab in enumerate(tabs):
            card = _TabCard(tab)
            card.toggled.connect(self._on_card_toggled)
            self._cards.append(card)
            self._grid_layout.addWidget(card, i // cols, i % cols)

    def _on_card_toggled(self, _: bool) -> None:
        any_on = any(c.is_checked for c in self._cards)
        self._scan_btn.setEnabled(any_on)

    def _tick_spinner(self) -> None:
        frames = ["⏳", "⌛"]
        self._dot_count = (self._dot_count + 1) % len(frames)
        self._spinner.setText(frames[self._dot_count])

    # ── Scanning ───────────────────────────────────────────────────────────────

    def _on_scan_clicked(self) -> None:
        from ui.workers.channel_scrape_worker import ChannelScrapeWorker

        self.selected_tabs = [c.tab for c in self._cards if c.is_checked]
        if not self.selected_tabs:
            return

        self._scan_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._subtitle.setText("סורק טאבים נבחרים…")
        self._progress_bar.show()
        self._progress_label.show()

        total_tabs = len(self.selected_tabs)
        self._tabs_done = 0
        self._total_tabs = total_tabs

        self._scraper = ChannelScrapeWorker(
            channel_url=self._url,
            selected_tabs=self.selected_tabs,
            cookies_file=self._cookies,
            proxy_url=self._proxy,
            parent=self,
        )
        self._scraper.tab_started.connect(self._on_tab_started)
        self._scraper.tab_progress.connect(self._on_tab_progress)
        self._scraper.tab_done.connect(self._on_tab_done)
        self._scraper.all_done.connect(self._on_all_done)
        self._scraper.error.connect(self._on_scrape_error)
        self._scraper.start()

    def _on_tab_started(self, tab_name: str) -> None:
        self._progress_label.setText(f"סורק: {tab_name}…")

    def _on_tab_progress(self, tab_name: str, current: int, total: int) -> None:
        self._progress_label.setText(f"מרחיב פלייליסטים: {current}/{total}")
        if total > 0:
            pct = int(self._tabs_done / self._total_tabs * 100
                      + current / total * (100 / self._total_tabs))
            self._progress_bar.setValue(min(pct, 99))

    def _on_tab_done(self, tab_name: str, count: int) -> None:
        self._tabs_done += 1
        # Update the count label on the matching card
        for card in self._cards:
            if card.tab.name == tab_name:
                card.set_count(count)
                break
        pct = int(self._tabs_done / self._total_tabs * 100)
        self._progress_bar.setValue(pct)

    def _on_all_done(self, results: dict) -> None:
        self.scrape_results = results
        total_items = sum(len(v) for v in results.values())
        self._progress_bar.setValue(100)
        self._progress_label.setText(f"סריקה הושלמה — {total_items:,} פריטים")
        self.accept()

    def _on_scrape_error(self, msg: str) -> None:
        self._subtitle.setText(f"שגיאת סריקה: {msg}")
        self._scan_btn.setEnabled(True)
        self._cancel_btn.setEnabled(True)
        self._progress_bar.hide()
        self._progress_label.hide()

    # ── Close guard ───────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        if self._discovery and self._discovery.isRunning():
            self._discovery.quit()
        if self._scraper and self._scraper.isRunning():
            self._scraper.cancel()
            self._scraper.quit()
        super().closeEvent(event)
