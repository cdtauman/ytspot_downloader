"""
ui/app_window.py  –  Main application window  (v4 — controller architecture)
==============================================================================
Changelog v4
------------
* Decomposed into three controllers (P3-4):
    - FetchController  : fetch / scrape / batch-import flows
    - SearchController : search flows (YouTube, Spotify)
    - DownloadController: download / pause / resume / job-building
  AppWindow is now the pure mediator: it owns panels, wires signals between
  controllers and panels, and handles strictly UI-level concerns (tray, drag
  & drop, accessibility, clipboard, close event, queue card management).

All v3 functionality preserved unchanged.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QByteArray, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication, QFrame, QSystemTrayIcon, QMenu, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    FluentIcon, FluentWindow, MessageBox,
    NavigationItemPosition, setTheme, setThemeColor, Theme,
    InfoBar, InfoBarPosition,
)

# ── Backend ────────────────────────────────────────────────────────────────────
from config import AppConfig
from core.history_db import DownloadRecord, HistoryDB
from core.services import ServiceContainer
from core.search_engine import SearchResult, ResultKind
from core.update_checker import ReleaseInfo
from ui.workers.offline_monitor import OfflineMonitor
from core.downloader import AudioQuality, DownloadEngine, DownloadRequest, MediaType, VideoQuality
from core.playlist_parser import ParseResult, SourcePlatform, UrlKind, classify_url
from error_handler import classify_error, ErrorInfo, ErrorSeverity, probe_connectivity

# ── Controllers ────────────────────────────────────────────────────────────────
from ui.controllers.fetch_controller    import FetchController
from ui.controllers.search_controller  import SearchController
from ui.controllers.download_controller import DownloadController

# ── Workers ────────────────────────────────────────────────────────────────────
from ui.workers.thumbnail_worker import ThumbnailWorker
from ui.workers.clipboard_worker import ClipboardWorker
from ui.workers.update_worker    import UpdateWorker

# ── Panels ─────────────────────────────────────────────────────────────────────
from ui.panels.url_bar           import UrlBar
from ui.panels.search_panel      import SearchPanel
from ui.panels.queue_panel       import QueuePanel
from ui.panels.history_panel     import HistoryPanel
from ui.panels.options_bar       import OptionsBar
from ui.panels.status_bar        import StatusBar
from ui.panels.settings_panel    import SettingsPanel
from ui.panels.converter_panel   import ConverterPanel

# ── Components ─────────────────────────────────────────────────────────────────
from ui.components.track_card     import TrackCard
from ui.components.update_banner  import UpdateBanner
from ui.components.offline_banner import OfflineBanner

# ── Theme / i18n ───────────────────────────────────────────────────────────────
from ui.i18n         import t, set_language
from ui.theme_manager import ThemeManager, ACCENT_COLOR

logger = logging.getLogger(__name__)


# ── High-contrast QSS for accessibility mode ──────────────────────────────────
_A11Y_QSS = """
QWidget { background: #000000 !important; color: #ffffff !important; }
QFrame  { background: #000000 !important; border: 2px solid #ffff00 !important; }
QPushButton { background: #111111 !important; color: #ffff00 !important;
               border: 2px solid #ffff00 !important; }
QPushButton:focus { outline: 3px solid #00ffff !important; }
QLabel  { color: #ffffff !important; background: transparent !important; }
QLineEdit { background: #111111 !important; color: #ffffff !important;
             border: 2px solid #ffff00 !important; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: #ffff00 !important; }
"""


# ──────────────────────────────────────────────────────────────────────────────
# _DownloadBar  (inline widget — unchanged from v2/v3)
# ──────────────────────────────────────────────────────────────────────────────

class _DownloadBar(QFrame):
    from PySide6.QtCore import Signal as _Signal
    download_clicked = _Signal()

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QHBoxLayout, QLabel
        from qfluentwidgets import PrimaryPushButton

        self.setFixedHeight(58)
        self.setStyleSheet("background: #18181b; border-top: 1px solid #2e2e35;")

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 8, 16, 8)

        self._count_lbl = QLabel(t("no_tracks_selected"))
        self._count_lbl.setStyleSheet(
            "color: #9090a0; font-size: 12px; background: transparent;"
        )
        row.addWidget(self._count_lbl)
        row.addStretch()

        self._dl_btn = PrimaryPushButton(t("download_selected"))
        self._dl_btn.setFixedSize(190, 38)
        self._dl_btn.setEnabled(False)
        self._dl_btn.setStyleSheet(f"""
            PrimaryPushButton {{
                background-color: {ACCENT_COLOR};
                color: #000000; border: none; border-radius: 6px;
                font-size: 13px; font-weight: bold;
            }}
            PrimaryPushButton:hover {{ background-color: #e09418; }}
            PrimaryPushButton:disabled {{ background-color: #5a3e0e; color: #888888; }}
        """)
        self._dl_btn.clicked.connect(self.download_clicked)
        row.addWidget(self._dl_btn)

    def set_count(self, selected: int, total: int) -> None:
        if total == 0:
            self._count_lbl.setText(t("no_tracks_selected"))
            self._dl_btn.setEnabled(False)
        else:
            self._count_lbl.setText(
                t("selected_of_total", selected=selected, total=total,
                  plural=('' if total == 1 else 's'))
            )
            self._dl_btn.setEnabled(selected > 0)

    def set_downloading(self, downloading: bool) -> None:
        self._dl_btn.setEnabled(not downloading)
        self._dl_btn.setText(
            t("download_downloading") if downloading else t("download_selected")
        )


# ──────────────────────────────────────────────────────────────────────────────
# AppWindow  (mediator — owns panels, wires controllers)
# ──────────────────────────────────────────────────────────────────────────────

class AppWindow(FluentWindow):
    """
    Top-level application window.

    Responsibilities (v4):
      * Build panels and controllers
      * Wire all Qt signals between controllers ↔ panels
      * Manage queue card lifecycle (_add_track_to_queue, thumbnails)
      * System tray, drag & drop, accessibility, hotkeys, close event
      * Cross-controller mediation (e.g. search drill-down → fetch)
    """

    def __init__(
        self,
        config:   AppConfig,
        services: "ServiceContainer",
        db:       Optional[HistoryDB] = None,
    ) -> None:
        super().__init__()

        # ── Core references ───────────────────────────────────────────────────
        self._cfg    = config
        self._svc    = services
        self._db     = services.db if db is None else db
        self._engine = services.engine
        self._theme  = ThemeManager(config)

        # ── URL routing state (needed when building download jobs) ─────────────
        self._last_playlist_title: str               = ""
        self._last_url_kind:       Optional[UrlKind] = None

        # ── Queue card routing ────────────────────────────────────────────────
        self._index_to_card: dict[int, TrackCard]      = {}
        self._thumb_workers: set[ThumbnailWorker]      = set()

        # ── Misc background workers ───────────────────────────────────────────
        self._clipboard_worker: Optional[ClipboardWorker] = None
        self._net_monitor:      Optional[OfflineMonitor]  = None
        self._tray:             Optional[QSystemTrayIcon] = None

        # ── Build ─────────────────────────────────────────────────────────────
        self._build_panels()
        self._build_controllers()
        self._configure_window()
        self._register_navigation()
        self._connect_signals()
        self._restore_state()
        self._setup_tray()
        self._setup_drag_drop()

        QTimer.singleShot(300,  self._start_background_workers)
        QTimer.singleShot(1200, self._check_auto_resume)

    # ──────────────────────────────────────────────────────────────────────────
    # Panel construction
    # ──────────────────────────────────────────────────────────────────────────

    def _build_panels(self) -> None:
        self._url_bar         = UrlBar(self._cfg)
        self._options_bar     = OptionsBar(self._cfg)
        self._queue_panel     = QueuePanel()
        self._search_panel    = SearchPanel(self._cfg)
        self._history_panel   = HistoryPanel(self._db, self._cfg)
        self._status_bar      = StatusBar()
        self._update_banner   = UpdateBanner()
        self._offline_banner  = OfflineBanner()
        self._dl_bar          = _DownloadBar()
        self._converter_panel = ConverterPanel()
        self._settings_panel  = SettingsPanel(self._cfg, self._theme)

        # Queue composite wrapper
        queue_wrapper = QWidget()
        queue_wrapper.setObjectName("queuePage")
        queue_wrapper.setAcceptDrops(True)
        vl = QVBoxLayout(queue_wrapper)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        vl.addWidget(self._offline_banner)
        vl.addWidget(self._update_banner)
        vl.addWidget(self._url_bar)
        vl.addWidget(self._options_bar)

        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setFixedHeight(1)
        div.setStyleSheet("background: #2e2e35; border: none;")
        vl.addWidget(div)

        vl.addWidget(self._queue_panel, stretch=1)
        vl.addWidget(self._dl_bar)
        vl.addWidget(self._status_bar)
        self._queue_wrapper = queue_wrapper

    # ──────────────────────────────────────────────────────────────────────────
    # Controller construction
    # ──────────────────────────────────────────────────────────────────────────

    def _build_controllers(self) -> None:
        self._fetch_ctrl    = FetchController(self._cfg, parent=self)
        self._search_ctrl   = SearchController(self._cfg, parent=self)
        self._download_ctrl = DownloadController(
            config=self._cfg,
            engine=self._engine,
            db=self._db,
            parent=self,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # FluentWindow configuration
    # ──────────────────────────────────────────────────────────────────────────

    def _configure_window(self) -> None:
        self.setWindowTitle(t("app_name"))
        self.setMinimumSize(980, 680)
        self.resize(1100, 760)
        self._theme.apply(self._cfg.theme)
        self.navigationInterface.setExpandWidth(200)
        if self._cfg.accessibility_mode:
            self._apply_accessibility(True)

    def _register_navigation(self) -> None:
        self.addSubInterface(
            self._queue_wrapper, FluentIcon.DOWNLOAD, t("queue"),
            position=NavigationItemPosition.TOP,
        )
        self._search_panel.setObjectName("searchPage")
        self.addSubInterface(
            self._search_panel, FluentIcon.SEARCH, t("search"),
            position=NavigationItemPosition.TOP,
        )
        self._history_panel.setObjectName("historyPage")
        self.addSubInterface(
            self._history_panel, FluentIcon.HISTORY, t("history"),
            position=NavigationItemPosition.TOP,
        )
        self._converter_panel.setObjectName("converterPage")
        self.addSubInterface(
            self._converter_panel, FluentIcon.SYNC, "Converter",
            position=NavigationItemPosition.TOP,
        )
        self._settings_panel.setObjectName("settingsPage")
        self._settings_panel.clipboard_monitor_changed.connect(
            self._on_clipboard_setting_change
        )
        self._settings_panel.accessibility_changed.connect(self._apply_accessibility)
        self._settings_panel.login_fix_requested.connect(
            lambda: self._run_cookie_wizard_ui(prompt_for_url=True)
        )
        self._settings_panel.settings_saved.connect(
            lambda: self._options_bar.apply_config(self._cfg)
        )
        self._settings_panel.settings_saved.connect(self._on_settings_saved)
        self.addSubInterface(
            self._settings_panel, FluentIcon.SETTING, t("settings"),
            position=NavigationItemPosition.BOTTOM,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Signal wiring  (AppWindow is the mediator — all connections live here)
    # ──────────────────────────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        # ── URL bar → FetchController ──────────────────────────────────────────
        self._url_bar.fetch_requested.connect(self._start_fetch)
        self._url_bar.batch_import_requested.connect(self._fetch_ctrl.batch_import)
        self._url_bar.scrape_requested.connect(self._on_scrape)

        # ── FetchController → panels / AppWindow ──────────────────────────────
        self._fetch_ctrl.track_fetched.connect(self._add_track_to_queue)
        self._fetch_ctrl.fetch_finished.connect(self._on_fetch_finished)
        self._fetch_ctrl.fetch_error.connect(self._on_fetch_error)
        self._fetch_ctrl.fetching_changed.connect(self._url_bar.set_fetching)
        self._fetch_ctrl.status_update.connect(self._status_bar.set_status)
        self._fetch_ctrl.cancel_visible.connect(self._status_bar.set_cancel_visible)
        self._fetch_ctrl.scrape_finished.connect(self._on_scrape_done)

        # ── Options bar ────────────────────────────────────────────────────────
        self._options_bar.options_changed.connect(self._on_options_changed)

        # ── Queue panel ────────────────────────────────────────────────────────
        self._queue_panel.selection_changed.connect(self._on_selection_changed)
        self._queue_panel.pause_resume_triggered.connect(self._on_global_pause_resume)
        self._queue_panel.card_removed.connect(self._on_card_removed)

        # ── Download bar → download flow ───────────────────────────────────────
        self._dl_bar.download_clicked.connect(self._on_download)

        # ── Status bar cancel ──────────────────────────────────────────────────
        self._status_bar.cancel_requested.connect(self._on_cancel)

        # ── SearchPanel → SearchController → AppWindow ────────────────────────
        self._search_panel.search_requested.connect(self._on_search)
        self._search_panel.add_to_queue_requested.connect(
            self._on_add_search_result_to_queue
        )
        self._search_panel.drill_down_requested.connect(self._on_search_drill_down)

        self._search_ctrl.result_ready.connect(self._on_search_result_ready)
        self._search_ctrl.result_to_queue.connect(self._on_result_to_queue)
        self._search_ctrl.search_error.connect(self._on_search_error)
        self._search_ctrl.searching_changed.connect(self._search_panel.set_searching)

        # ── DownloadController → panels / AppWindow ───────────────────────────
        self._download_ctrl.status_update.connect(self._status_bar.set_status)
        self._download_ctrl.metrics_update.connect(self._status_bar.set_metrics)
        self._download_ctrl.overall_progress.connect(self._status_bar.set_progress)
        self._download_ctrl.cancel_visible.connect(self._status_bar.set_cancel_visible)
        self._download_ctrl.downloading_changed.connect(self._dl_bar.set_downloading)
        self._download_ctrl.job_count_changed.connect(self._on_job_count_changed)
        self._download_ctrl.show_success_bar.connect(self._on_track_finished_ui)
        self._download_ctrl.show_error_dialog.connect(self._on_track_error_ui)
        self._download_ctrl.batch_finished.connect(self._on_all_downloads_finished)
        self._download_ctrl.batch_started.connect(self._save_queue_state)
        self._download_ctrl.browser_lock_warning.connect(self._on_browser_lock_warning)

        # ── History panel ──────────────────────────────────────────────────────
        self._history_panel.redownload_requested.connect(self._on_redownload)
        self._history_panel.open_folder_requested.connect(self._on_open_folder)

    # ──────────────────────────────────────────────────────────────────────────
    # Background workers startup
    # ──────────────────────────────────────────────────────────────────────────

    def _start_background_workers(self) -> None:
        self._clipboard_worker = ClipboardWorker(parent=self)
        self._clipboard_worker.url_detected.connect(self._on_clipboard_url)
        if self._cfg.clipboard_monitor:
            self._clipboard_worker.start()
        self._url_bar.set_clipboard_monitor_active(self._cfg.clipboard_monitor)

        if self._cfg.check_updates:
            self._update_worker = UpdateWorker(parent=self)
            self._update_worker.update_available.connect(self._on_update_found)
            self._update_worker.start()

        self._net_monitor = OfflineMonitor(parent=self)
        self._net_monitor.went_offline.connect(self._on_went_offline)
        self._net_monitor.came_online.connect(self._on_came_online)
        self._net_monitor.start()

        if self._cfg.global_hotkeys_enabled:
            self._register_hotkeys()

    # ──────────────────────────────────────────────────────────────────────────
    # Offline monitor
    # ──────────────────────────────────────────────────────────────────────────

    def _on_went_offline(self) -> None:
        self._offline_banner.show()
        self._status_bar.set_status("📡  No internet connection.")

    def _on_came_online(self) -> None:
        self._offline_banner.hide()
        self._status_bar.set_status("✅  Internet connection restored.")

    # ──────────────────────────────────────────────────────────────────────────
    # System Tray
    # ──────────────────────────────────────────────────────────────────────────

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = QSystemTrayIcon(self)
        self._tray.setToolTip("YTSpot Downloader")
        try:
            from PySide6.QtGui import QPixmap
            px = QPixmap(32, 32)
            px.fill(Qt.GlobalColor.transparent)
            self._tray.setIcon(QIcon(px))
        except Exception:
            pass
        menu = QMenu(self)
        menu.addAction("Open", self._tray_open)
        menu.addSeparator()
        menu.addAction("Cancel All Downloads", self._on_cancel)
        menu.addSeparator()
        menu.addAction("Quit", self._tray_quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _tray_open(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _tray_quit(self) -> None:
        self._cfg.tray_on_close = False
        self.close()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._tray_open()

    # ──────────────────────────────────────────────────────────────────────────
    # Drag & Drop URL support
    # ──────────────────────────────────────────────────────────────────────────

    def _setup_drag_drop(self) -> None:
        wrapper = self._queue_wrapper

        def _drag_enter(event) -> None:
            md = event.mimeData()
            if md.hasUrls() or md.hasText():
                event.acceptProposedAction()
            else:
                event.ignore()

        def _drop(event) -> None:
            md = event.mimeData()
            urls: list[str] = []
            if md.hasUrls():
                urls = [u.toString() for u in md.urls() if u.scheme() in ("http", "https")]
            elif md.hasText():
                for line in md.text().splitlines():
                    line = line.strip()
                    if line.startswith(("http://", "https://")):
                        urls.append(line)
            for url in urls:
                try:
                    classify_url(url)
                    self._url_bar.set_url(url)
                    self._start_fetch(url)
                    break
                except Exception:
                    continue
            event.acceptProposedAction()

        wrapper.dragEnterEvent = _drag_enter   # type: ignore[method-assign]
        wrapper.dropEvent      = _drop          # type: ignore[method-assign]

    # ──────────────────────────────────────────────────────────────────────────
    # Accessibility
    # ──────────────────────────────────────────────────────────────────────────

    def _apply_accessibility(self, enabled: bool) -> None:
        app = QApplication.instance()
        if app is None:
            return
        if enabled:
            existing = app.styleSheet()
            if _A11Y_QSS not in existing:
                app.setStyleSheet(existing + _A11Y_QSS)
        else:
            qss = app.styleSheet().replace(_A11Y_QSS, "")
            app.setStyleSheet(qss)
            self._theme.apply(self._cfg.theme)

    # ──────────────────────────────────────────────────────────────────────────
    # Global hotkeys
    # ──────────────────────────────────────────────────────────────────────────

    def _register_hotkeys(self) -> None:
        try:
            import keyboard  # type: ignore[import]
            keyboard.add_hotkey("ctrl+alt+p", self._on_cancel)
            keyboard.add_hotkey("ctrl+alt+y", self._tray_open)
            logger.info("[AppWindow] Global hotkeys registered.")
        except ImportError:
            logger.warning("[AppWindow] 'keyboard' library not installed; hotkeys disabled.")
        except Exception as exc:
            logger.warning("[AppWindow] Global hotkey registration failed: %s", exc)

    # ──────────────────────────────────────────────────────────────────────────
    # Auto-resume  (queue persistence)
    # ──────────────────────────────────────────────────────────────────────────

    def _check_auto_resume(self) -> None:
        saved = self._cfg.queue_state
        if not saved:
            return
        box = MessageBox(
            "Resume Downloads?",
            f"YTSpot has {len(saved)} unfinished download(s) from a previous session.\n"
            "Would you like to restore and resume them?",
            self,
        )
        if box.exec():
            self._restore_queue_state(saved)
            self._cfg.queue_state = []
            self._cfg.save()

    def _restore_queue_state(self, saved: list[dict]) -> None:
        from core.playlist_parser import TrackMeta
        logger.debug("[AppWindow] Restoring %d queue items", len(saved))
        for item in saved:
            try:
                meta = TrackMeta(
                    title=item.get("title", "Unknown"),
                    artist=item.get("artist", ""),
                    url=item.get("url", ""),
                    duration_str=item.get("duration_str", ""),
                    thumbnail_url=item.get("thumbnail_url", ""),
                    platform=SourcePlatform[item.get("platform", "YOUTUBE")],
                )
                self._add_track_to_queue(meta)
            except Exception as exc:
                logger.debug("[AppWindow] Failed to restore queue item: %s", exc)

    def _save_queue_state(self) -> None:
        cards = self._queue_panel.get_all_cards()
        state = [
            {
                "title":         c.title,
                "artist":        c.artist,
                "url":           c.track_url,
                "duration_str":  "",
                "thumbnail_url": "",
                "platform":      getattr(c, "platform_name", "YOUTUBE"),
            }
            for c in cards
        ]
        self._cfg.queue_state = state
        self._cfg.save()

    # ──────────────────────────────────────────────────────────────────────────
    # Download flow  (thin delegates to DownloadController)
    # ──────────────────────────────────────────────────────────────────────────

    def _on_download(self) -> None:
        selected = self._queue_panel.get_selected_cards()
        if not selected:
            self._status_bar.set_status(f"\u26a0  {t('no_tracks_selected')}")
            return
        opts = self._options_bar.get_options()
        self._download_ctrl.start_batch(
            selected, opts, self._last_url_kind, self._last_playlist_title
        )

    def _on_global_pause_resume(self, pause: bool) -> None:
        if pause:
            self._download_ctrl.global_pause()
            self._queue_panel.set_pause_resume_state(True)
            self._status_bar.set_status(t("cancelling"))
        else:
            to_resume = [
                c for c in self._queue_panel.get_all_cards()
                if c.get_status() in ("queued", "paused", "cancelled", "error")
                and c.is_selected()
            ]
            self._queue_panel.set_pause_resume_state(False)
            if to_resume:
                self._on_download()

    def _on_pause_track(self, queue_index: int) -> None:
        card = self._index_to_card.get(queue_index)
        if card:
            self._download_ctrl.pause_track(card)

    def _on_resume_track(self, queue_index: int) -> None:
        card = self._index_to_card.get(queue_index)
        if card:
            self._download_ctrl.resume_track(card)

    # ── Download signal handlers (UI-only — card updates done in controller) ──

    def _on_track_finished_ui(self, output_path: str) -> None:
        InfoBar.success(
            title="Downloaded",
            content=Path(output_path).name[:60] if output_path else "Track saved.",
            orient=Qt.Orientation.Horizontal,
            position=InfoBarPosition.BOTTOM_RIGHT,
            duration=4000,
            parent=self,
        )

    def _on_track_error_ui(self, err: object, failing_url: str = "") -> None:
        """Throttled error reporter to prevent 'messagebox storms' on batch failures."""
        import time
        now = time.time()
        # Suppress popups if we showed one in the last 5 seconds
        if hasattr(self, "_last_error_time") and (now - self._last_error_time < 5.0):
            return
            
        self._last_error_time = now
        
        headline = "Download failed"
        detail = str(err)

        if hasattr(err, "headline"):
            headline = err.headline
            detail = err.detail
        elif hasattr(err, "error_message"):
            detail = err.error_message
            
        msg = MessageBox(headline, detail, self)
        
        # 1. Handle Login/Sign-in blocks — offer the wizard
        if any(x in detail for x in ["Please sign in", "sign in", "PO Token", 
                                      "account cookies", "אימות", "חשבון", "Cookies",
                                      "DPAPI", "Chrome", "bot", "visitor_data"]):
            msg.yesButton.setText("🔑 פתח אשף התחברות (מומלץ)")
            msg.cancelButton.setText("סגור")
            if msg.exec():
                self._run_cookie_wizard_ui()
                
        # 2. Handle Signature / Manual "Puzzle" solving
        elif any(x in detail for x in ["Signature", "n challenge"]):
            msg.yesButton.setText("🔧 תיקון ידני בדפדפן")
            msg.cancelButton.setText("סגור")
            if msg.exec() and failing_url:
                self._run_cookie_wizard_ui()
        else:
            msg.cancelButton.hide()
            msg.exec()

    def _run_cookie_wizard_ui(self, prompt_for_url: bool = False) -> None:
        from qfluentwidgets import InfoBar
        from PySide6.QtWidgets import QInputDialog
        from PySide6.QtCore import QThread, Signal as QSignal

        target_url = "https://www.youtube.com"
        if prompt_for_url:
            url, ok = QInputDialog.getText(
                self, "אשף התחברות לאתרים", "הזן את כתובת האתר שברצונך להתחבר אליו:",
                text=target_url
            )
            if not ok or not url:
                return
            target_url = url
            
        # Instruct the user what to do before the browser opens
        from PySide6.QtWidgets import QMessageBox
        info_msg = (
            "כעת ייפתח חלון דפדפן.\n\n"
            f"1. התחבר לחשבון שלך באתר: {target_url}\n"
            "2. לאחר ההתחברות, פשוט סגור את חלון הדפדפן.\n\n"
            "התוכנה תשמור את פרטי ההתחברות באופן אוטומטי."
        )
        QMessageBox.information(self, "אשף התחברות לאתרים", info_msg)

        # Run the wizard in a background thread so the Qt UI stays responsive.
        class WizardThread(QThread):
            done = QSignal(bool)
            def __init__(self, url): 
                super().__init__()
                self._url = url
            def run(self):
                from core.cookie_wizard import run_cookie_wizard
                result = run_cookie_wizard(start_url=self._url)
                self.done.emit(result)

        self._wizard_thread = WizardThread(target_url)
        
        def on_wizard_done(success: bool):
            if success:
                InfoBar.success(
                    title="ההתחברות הצליחה",
                    content="פרטי ההתחברות לאתר נשמרו. ניתן להתחיל להוריד מחדש.",
                    parent=self,
                    duration=6000
                )
                # Switch to file mode automatically if it was on browser mode
                if self._cfg.cookies_browser:
                    self._cfg.cookies_browser = ""
                    self._cfg.save()
                    self._options_bar.apply_config(self._cfg)
            else:
                InfoBar.warning(
                    title="האשף נסגר ללא שמירה",
                    content="לא נשמרו cookies. ייתכן שהאשף נסגר לפני ההתחברות.",
                    parent=self,
                    duration=5000
                )
        
        self._wizard_thread.done.connect(on_wizard_done)
        self._wizard_thread.start()

    def _on_browser_lock_warning(self, browser_name: str) -> None:
        """Friendly warning for 'Simple Users' when Chrome/Edge etc is open."""
        title = f"{browser_name} פתוח"
        content = (
            f"דפדפן {browser_name} פתוח כרגע.\n\n"
            "ווינדוס לא מאפשר לתוכנה לגשת ל-Cookies בזמן שהדפדפן פתוח.\n"
            "כדי שההורדה תעבוד, עליך לסגור את כל חלונות הדפדפן ולנסות שוב."
        )
        msg = MessageBox(title, content, self)
        msg.yesButton.setText("סגרתי, נסה שוב")
        msg.cancelButton.setText("ביטול")
        if msg.exec():
            # Retry download flow (trigger the button click logic)
            self._on_download()
      
    def _on_job_count_changed(self, current: int, total: int) -> None:
        if current < total:
            self._status_bar.set_status(
                t("download_progress_count", current=current + 1, total=total)
            )

    def _on_all_downloads_finished(self) -> None:
        self._queue_panel.set_pause_resume_state(False)
        self._cfg.queue_state = []
        self._cfg.save()
        if self._tray and not self.isVisible():
            self._tray.showMessage(
                "YTSpot Downloader",
                "All downloads complete!",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Fetch flow  (delegates to FetchController; AppWindow updates routing state)
    # ──────────────────────────────────────────────────────────────────────────

    def _start_fetch(self, url: str) -> None:
        """Entry point for all fetching, intercepting channel URLs to ask what to scrape."""
        platform, kind = classify_url(url)
        if platform == SourcePlatform.YOUTUBE and kind == UrlKind.ARTIST:
            # Pop up custom dialog for channel scraping options
            from PySide6.QtWidgets import QDialog, QVBoxLayout, QCheckBox, QHBoxLayout
            from qfluentwidgets import PrimaryPushButton, PushButton, SubtitleLabel

            dialog = QDialog(self)
            dialog.setWindowTitle("אפשרויות סריקת ערוץ")
            dialog.setFixedSize(350, 250)
            
            layout = QVBoxLayout(dialog)
            layout.addWidget(SubtitleLabel("בחר מה ברצונך להוריד מהערוץ:"))
            
            cb_videos = QCheckBox("סרטונים")
            cb_shorts = QCheckBox("קצרים")
            cb_releases = QCheckBox("פריטי תוכן")
            cb_playlists = QCheckBox("פלייליסטים")
            
            # Default to videos
            cb_videos.setChecked(True)
            
            layout.addWidget(cb_videos)
            layout.addWidget(cb_shorts)
            layout.addWidget(cb_releases)
            layout.addWidget(cb_playlists)
            
            btn_layout = QHBoxLayout()
            ok_btn = PrimaryPushButton("התחל גירוד")
            cancel_btn = PushButton("ביטול")
            btn_layout.addWidget(ok_btn)
            btn_layout.addWidget(cancel_btn)
            
            layout.addLayout(btn_layout)
            
            ok_btn.clicked.connect(dialog.accept)
            cancel_btn.clicked.connect(dialog.reject)
            
            if dialog.exec() == QDialog.DialogCode.Accepted:
                channel_tabs = []
                if cb_videos.isChecked(): channel_tabs.append("סרטונים")
                if cb_shorts.isChecked(): channel_tabs.append("קצרים")
                if cb_releases.isChecked(): channel_tabs.append("פריטי תוכן")
                if cb_playlists.isChecked(): channel_tabs.append("פלייליסטים")
                
                if not channel_tabs:
                    channel_tabs = ["סרטונים"]
                    
                self._fetch_ctrl.fetch(url, channel_tabs)
            else:
                self._status_bar.set_status("בוטל על ידי המשתמש")
        else:
            self._fetch_ctrl.fetch(url)

    def _on_fetch_finished(self, result) -> None:
        if hasattr(result, "playlist_title") and result.playlist_title:
            self._last_playlist_title = result.playlist_title
        if hasattr(result, "kind"):
            self._last_url_kind = result.kind

        if hasattr(result, "error") and result.error and not getattr(result, "tracks", None):
            err = classify_error(Exception(result.error))
            self._status_bar.set_status(err.status_line())
            MessageBox(err.headline, err.detail, self).exec()
            return

        n = len(self._queue_panel.get_all_cards())
        self._status_bar.set_status(
            t("fetch_done", n=n, plural=("" if n == 1 else "s"))
        )

    def _on_fetch_error(self, msg: str) -> None:
        err = classify_error(Exception(msg))
        self._status_bar.set_status(err.status_line())
        MessageBox(err.headline, err.detail, self).exec()

    def _on_scrape(self, url: str) -> None:
        self._status_bar.set_status(t("scraping"))
        self._fetch_ctrl.scrape(url)

    def _on_scrape_done(self, urls: list) -> None:
        if not urls:
            self._status_bar.set_status(t("scrape_no_urls"))
            return
        self._url_bar.set_url(urls[0])
        self._status_bar.set_status(t("scrape_multi_found", count=len(urls)))

    def _on_redownload(self, record: DownloadRecord) -> None:
        self._url_bar.set_url(record.url)
        self.switchTo(self._queue_wrapper)
        self._fetch_ctrl.fetch(record.url)

    def _on_open_folder(self, record: DownloadRecord) -> None:
        folder = Path(record.output_path).parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # ──────────────────────────────────────────────────────────────────────────
    # Search flow  (delegates to SearchController; AppWindow mediates drill-down)
    # ──────────────────────────────────────────────────────────────────────────

    def _on_search(self, query: str) -> None:
        self._search_ctrl.search(query, self._search_panel._current_platform)

    def _on_search_result_ready(self, result: SearchResult) -> None:
        card = self._search_panel.add_result(result)
        if result.thumbnail_url:
            tw = ThumbnailWorker(0, result.thumbnail_url, parent=self)
            tw.thumbnail_ready.connect(lambda _, data, c=card: c.set_thumbnail(data))
            tw.start()

    def _on_add_search_result_to_queue(self, result: SearchResult) -> None:
        self._search_ctrl.add_to_queue(result)

    def _on_result_to_queue(self, meta) -> None:
        self._add_track_to_queue(meta)
        self.switchTo(self._queue_wrapper)

    def _on_search_drill_down(self, result: SearchResult) -> None:
        """Cross-controller: search drill-down triggers a fetch."""
        logger.debug(
            "[AppWindow] Drill-down: kind=%s url=%s", result.kind.value, result.url
        )
        self._last_playlist_title = (
            result.title if result.kind in (ResultKind.ALBUM, ResultKind.PLAYLIST) else ""
        )
        self._last_url_kind = (
            UrlKind.PLAYLIST if result.kind == ResultKind.PLAYLIST else
            (UrlKind.ALBUM   if result.kind == ResultKind.ALBUM    else UrlKind.ARTIST)
        )
        self._url_bar.set_url(result.url)
        self.switchTo(self._queue_wrapper)
        self._start_fetch(result.url)

    def _on_search_error(self, msg: str) -> None:
        err = classify_error(Exception(msg))
        self._status_bar.set_status(err.status_line())
        MessageBox(err.headline, err.detail, self).exec()

    # ──────────────────────────────────────────────────────────────────────────
    # Queue card management  (AppWindow owns card creation and index routing)
    # ──────────────────────────────────────────────────────────────────────────

    def _add_track_to_queue(self, data) -> None:
        idx = len(self._queue_panel.get_all_cards()) + 1
        get = (
            lambda k, d="": data.get(k, d) if isinstance(data, dict)
            else getattr(data, k, d)
        )

        card = self._queue_panel.add_card(
            index=idx,
            title=get("title", "Unknown"),
            artist=get("artist", ""),
            duration=get("duration", "") if isinstance(data, dict) else get("duration_str", ""),
            platform=get("platform", "youtube"),
            track_url=get("track_url", "") if isinstance(data, dict) else get("url", ""),
            album=get("album", ""),
            parent_artist=get("parent_artist", ""),
            release_type=get("release_type", ""),
            album_index=get("album_index", 0),
            thumbnail_url=get("thumbnail_url", ""),
            category=get("category", ""),
            total_tracks=get("total_tracks", 0),
        )

        card.remove_requested.connect(self._on_card_removed)
        card.pause_requested.connect(self._on_pause_track)
        card.resume_requested.connect(self._on_resume_track)

        self._index_to_card[idx] = card
        self._update_dl_bar()

        thumb_url = get("thumbnail_url", "")
        if thumb_url:
            tw = ThumbnailWorker(idx, thumb_url, parent=self)
            self._thumb_workers.add(tw)
            tw.finished.connect(lambda t=tw: self._thumb_workers.discard(t))
            tw.thumbnail_ready.connect(
                lambda idx, data, c=card: self._set_card_thumb(c, data)
            )
            tw.start()

    def _set_card_thumb(self, card: TrackCard, data: bytes) -> None:
        from PySide6.QtGui import QPixmap
        px = QPixmap()
        px.loadFromData(data)
        if not px.isNull():
            card.set_thumbnail(px)

    def _on_selection_changed(self, count: int) -> None:
        total = len(self._queue_panel.get_all_cards())
        self._dl_bar.set_count(count, total)

    def _on_card_removed(self, queue_index: int) -> None:
        self._index_to_card.pop(queue_index, None)
        self._update_dl_bar()

    def _on_options_changed(self) -> None:
        pass

    def _update_dl_bar(self) -> None:
        cards    = self._queue_panel.get_all_cards()
        selected = self._queue_panel.get_selected_cards()
        self._dl_bar.set_count(len(selected), len(cards))

    # ──────────────────────────────────────────────────────────────────────────
    # Clipboard
    # ──────────────────────────────────────────────────────────────────────────

    def _on_clipboard_url(self, url: str) -> None:
        self._url_bar.set_url(url)
        InfoBar.info(
            title="Clipboard",
            content=f"Detected: {url[:60]}",
            orient=Qt.Orientation.Horizontal,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self,
        )

    def _on_clipboard_setting_change(self, checked: bool) -> None:
        self._cfg.clipboard_monitor = checked
        self._cfg.save()
        if checked:
            self._clipboard_worker.start()
        else:
            self._clipboard_worker.stop()
        self._url_bar.set_clipboard_monitor_active(checked)

    # ──────────────────────────────────────────────────────────────────────────
    # Updates
    # ──────────────────────────────────────────────────────────────────────────

    def _on_update_found(self, release: ReleaseInfo) -> None:
        self._update_banner.set_release(release)
        self._update_banner.show()

    # ──────────────────────────────────────────────────────────────────────────
    # Cancel  (cancels all in-flight operations)
    # ──────────────────────────────────────────────────────────────────────────

    def _on_cancel(self) -> None:
        self._fetch_ctrl.cancel()
        self._search_ctrl.cancel()
        self._download_ctrl.cancel_all()
        self._status_bar.set_cancel_visible(False)
        self._status_bar.set_status(t("cancelling"))

    # ──────────────────────────────────────────────────────────────────────────
    # Settings
    # ──────────────────────────────────────────────────────────────────────────

    def _on_settings_saved(self) -> None:
        set_language(self._cfg.language)
        QApplication.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft
            if self._cfg.language == "he"
            else Qt.LayoutDirection.LeftToRight
        )
        try:
            self.setWindowTitle(t("app_name"))
        except Exception:
            pass
        try:
            self._settings_panel.refresh()
        except Exception:
            pass
        self._options_bar.apply_config(self._cfg)
        self._update_dl_bar()

    # ──────────────────────────────────────────────────────────────────────────
    # Window state
    # ──────────────────────────────────────────────────────────────────────────

    def _restore_state(self) -> None:
        state_hex = self._cfg.window_state
        if state_hex:
            try:
                self.restoreGeometry(QByteArray.fromHex(state_hex.encode()))
            except Exception:
                pass

    def _save_state(self) -> None:
        self._cfg.window_state = self.saveGeometry().toHex().data().decode()
        self._cfg.save()

    # ──────────────────────────────────────────────────────────────────────────
    # Close event
    # ──────────────────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        """
        Clean shutdown sequence:
        1. Tray intercept (if enabled)
        2. Persist window state and queue
        3. Stop non-threaded monitors (clipboard, network)
        4. Cancel + join threaded workers (download first, then others)
        5. Unregister global hotkeys
        6. Close the database (via ServiceContainer)
        7. Accept the close event
        """
        # 1. Tray intercept
        if self._cfg.tray_on_close and self._tray and self._tray.isVisible():
            event.ignore()
            self.hide()
            self._tray.showMessage(
                "YTSpot Downloader",
                "Running in the background. Double-click the tray icon to restore.",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
            return

        logger.info("[AppWindow] closeEvent — beginning shutdown sequence")

        # 2. Persist state
        self._save_state()
        self._save_queue_state()

        # 3. Stop non-threaded monitors
        if hasattr(self, "_net_monitor") and self._net_monitor:
            self._net_monitor.stop()
        if self._clipboard_worker:
            self._clipboard_worker.stop()

        # 4. Cancel + join workers
        dl_worker = self._download_ctrl._dl_worker  # noqa: SLF001
        if dl_worker and dl_worker.isRunning():
            logger.info("[AppWindow] Shutting down DownloadWorker…")
            dl_worker.shutdown(timeout_ms=3000)

        fetch_worker  = self._fetch_ctrl._fetch_worker    # noqa: SLF001
        search_worker = self._search_ctrl._search_worker  # noqa: SLF001
        scraper_worker= self._fetch_ctrl._scraper_worker  # noqa: SLF001
        for attr_name, w in (
            ("FetchWorker",  fetch_worker),
            ("SearchWorker", search_worker),
            ("ScraperWorker",scraper_worker),
        ):
            if w and w.isRunning():
                if hasattr(w, "cancel"):
                    w.cancel()
                finished = w.wait(2000)
                if not finished:
                    logger.warning("[AppWindow] %s did not finish within 2s", attr_name)

        # 5. Hotkeys
        try:
            import keyboard
            keyboard.unhook_all()
        except Exception:
            pass

        # 6. Tray hide + DB close
        if self._tray:
            self._tray.hide()
        if hasattr(self, "_svc"):
            self._svc.close()
            logger.info("[AppWindow] Services closed — shutdown complete")

        event.accept()
