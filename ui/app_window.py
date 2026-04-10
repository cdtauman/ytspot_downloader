"""
ui/app_window.py  –  Main application window  (v3)
====================================================
Changelog v3
------------
* OfflineMonitor integrated: OfflineBanner shown/hidden at top of queue.
* System Tray: close → tray when config.tray_on_close is True.
* Drag & Drop URLs: QueueWrapper and QueuePanel accept dragged/dropped
  URLs from the browser.  Accepted URLs are auto-fetched.
* ConverterPanel registered as a dedicated navigation tab.
* Pause / Resume: TrackCard.pause_requested / resume_requested wired to
  DownloadWorker.cancel_track() and a resumable re-queue.
* Duplicate Detection: before building each DownloadRequest, calls
  duplicate_checker.find_duplicate(); action determined by config.
* Accessibility Mode: applies a high-contrast QSS when toggled.
* Auto-resume: on startup, if config.queue_state is non-empty, prompts
  to re-populate the queue from saved TrackMeta data.
* Global Hotkeys: optional registration via the `keyboard` library.
* All v2 functionality preserved unchanged.
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
from core.offline_monitor import OfflineMonitor
from downloader import (
    AudioQuality, DownloadEngine, DownloadRequest, MediaType, VideoQuality,
)
from error_handler import classify_error, ErrorInfo, ErrorSeverity, probe_connectivity
from playlist_parser import ParseResult, SourcePlatform, UrlKind, classify_url

# ── Workers ────────────────────────────────────────────────────────────────────
from ui.workers.fetch_worker     import FetchWorker
from ui.workers.download_worker  import DownloadWorker
from ui.workers.thumbnail_worker import ThumbnailWorker
from ui.workers.clipboard_worker import ClipboardWorker
from ui.workers.search_worker    import SearchWorker
from ui.workers.scraper_worker   import ScraperWorker
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
from ui.i18n        import t, set_language
from ui.theme_manager import ThemeManager, ACCENT_COLOR

logger = logging.getLogger(__name__)


# ── Quality maps ───────────────────────────────────────────────────────────────
_AUDIO_QUALITY_MAP = {
    "Best (320k)":   AudioQuality.BEST,
    "High (256k)":   AudioQuality.HIGH,
    "Medium (192k)": AudioQuality.MEDIUM,
    "Low (128k)":    AudioQuality.LOW,
}
_VIDEO_QUALITY_MAP = {
    "Best":  VideoQuality.BEST,
    "1080p": VideoQuality.HIGH,
    "720p":  VideoQuality.MEDIUM,
    "480p":  VideoQuality.LOW,
    "Worst": VideoQuality.WORST,
}

# High-contrast QSS for accessibility mode
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
# _DownloadBar  (inline widget – unchanged from v2)
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
# AppWindow
# ──────────────────────────────────────────────────────────────────────────────

class AppWindow(FluentWindow):
    """Top-level application window.  Owns all panels, workers, and engines."""

    def __init__(
        self,
        config: AppConfig,
        services: "ServiceContainer",
        db: Optional[HistoryDB] = None,
    ) -> None:
        super().__init__()

        # ── Unpack services ───────────────────────────────────────────────
        self._cfg    = config
        self._svc    = services
        self._db     = services.db if db is None else db
        self._engine = services.engine
        self._theme  = ThemeManager(config)

        # Worker references
        self._fetch_worker:   Optional[FetchWorker]   = None
        self._dl_worker:      Optional[DownloadWorker] = None
        self._search_worker:  Optional[SearchWorker]  = None
        self._scraper_worker: Optional[ScraperWorker] = None
        self._resume_workers: list[DownloadWorker]    = []  # per-track resume workers (prevent GC)

        # Card routing
        self._index_to_card: dict[int,  TrackCard] = {}
        self._key_to_card:   dict[str,  TrackCard] = {}
        self._card_progress: dict[str,  float]     = {}
        self._thumb_workers: set[ThumbnailWorker] = set()

        # Pause state: card_key → DownloadRequest (for resuming)
        self._paused_requests: dict[str, DownloadRequest] = {}

        # Last fetch metadata
        self._last_playlist_title: str              = ""
        self._last_url_kind:       Optional[UrlKind] = None

        # Tray
        self._tray: Optional[QSystemTrayIcon] = None

        # Build everything
        self._build_panels()
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
        self._url_bar        = UrlBar(self._cfg)
        self._options_bar    = OptionsBar(self._cfg)
        self._queue_panel    = QueuePanel()
        self._search_panel   = SearchPanel(self._cfg)
        self._history_panel  = HistoryPanel(self._db, self._cfg)
        self._status_bar     = StatusBar()
        self._update_banner  = UpdateBanner()
        self._offline_banner = OfflineBanner()
        self._dl_bar         = _DownloadBar()
        self._converter_panel = ConverterPanel()
        self._settings_panel = SettingsPanel(self._cfg, self._theme)

        # Queue composite
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
    # FluentWindow configuration
    # ──────────────────────────────────────────────────────────────────────────

    def _configure_window(self) -> None:
        self.setWindowTitle(t("app_name"))
        self.setMinimumSize(980, 680)
        self.resize(1100, 760)
        self._theme.apply(self._cfg.theme)
        self.navigationInterface.setExpandWidth(200)

        # Apply accessibility mode if enabled
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
        self._settings_panel.accessibility_changed.connect(
            self._apply_accessibility
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
    # Signal wiring
    # ──────────────────────────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        self._url_bar.fetch_requested.connect(self._on_fetch)
        self._url_bar.batch_import_requested.connect(self._on_batch_import)
        self._url_bar.scrape_requested.connect(self._on_scrape)

        self._options_bar.options_changed.connect(self._on_options_changed)

        self._queue_panel.selection_changed.connect(self._on_selection_changed)
        self._queue_panel.pause_resume_triggered.connect(self._on_global_pause_resume)
        self._queue_panel.card_removed.connect(self._on_card_removed)

        self._dl_bar.download_clicked.connect(self._on_download)
        self._status_bar.cancel_requested.connect(self._on_cancel)

        self._search_panel.search_requested.connect(self._on_search)
        self._search_panel.add_to_queue_requested.connect(
            self._on_add_search_result_to_queue
        )
        self._search_panel.drill_down_requested.connect(self._on_search_drill_down)

        self._history_panel.redownload_requested.connect(self._on_redownload)
        self._history_panel.open_folder_requested.connect(self._on_open_folder)

    # ──────────────────────────────────────────────────────────────────────────
    # Background workers startup
    # ──────────────────────────────────────────────────────────────────────────

    def _start_background_workers(self) -> None:
        # Clipboard monitor
        self._clipboard_worker = ClipboardWorker(parent=self)
        self._clipboard_worker.url_detected.connect(self._on_clipboard_url)
        if self._cfg.clipboard_monitor:
            self._clipboard_worker.start()
        self._url_bar.set_clipboard_monitor_active(self._cfg.clipboard_monitor)

        # Update checker
        if self._cfg.check_updates:
            self._update_worker = UpdateWorker(parent=self)
            self._update_worker.update_available.connect(self._on_update_found)
            self._update_worker.start()

        # Offline monitor
        self._net_monitor = OfflineMonitor(parent=self)
        self._net_monitor.went_offline.connect(self._on_went_offline)
        self._net_monitor.came_online.connect(self._on_came_online)
        self._net_monitor.start()

        # Global hotkeys (optional)
        if self._cfg.global_hotkeys_enabled:
            self._register_hotkeys()

    # ──────────────────────────────────────────────────────────────────────────
    # Offline monitor handlers
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

        # Use app icon if set; otherwise a generic icon
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
        self._cfg.tray_on_close = False   # prevent intercept in closeEvent
        self.close()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._tray_open()

    # ──────────────────────────────────────────────────────────────────────────
    # Drag & Drop URL support (queue wrapper)
    # ──────────────────────────────────────────────────────────────────────────

    def _setup_drag_drop(self) -> None:
        """Patch the queue wrapper to accept URL drag-drops."""
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
                    classify_url(url)   # raises if unsupported
                    self._url_bar.set_url(url)
                    self._on_fetch(url)
                    break               # fetch the first valid URL
                except Exception:
                    continue
            event.acceptProposedAction()

        wrapper.dragEnterEvent = _drag_enter   # type: ignore[method-assign]
        wrapper.dropEvent      = _drop          # type: ignore[method-assign]

    # ──────────────────────────────────────────────────────────────────────────
    # Accessibility
    # ──────────────────────────────────────────────────────────────────────────

    def _apply_accessibility(self, enabled: bool) -> None:
        """Toggle high-contrast QSS overlay for accessibility mode."""
        app = QApplication.instance()
        if app is None:
            return
        if enabled:
            existing = app.styleSheet()
            if _A11Y_QSS not in existing:
                app.setStyleSheet(existing + _A11Y_QSS)
        else:
            # Remove the a11y overlay and re-apply the normal theme
            qss = app.styleSheet().replace(_A11Y_QSS, "")
            app.setStyleSheet(qss)
            self._theme.apply(self._cfg.theme)

    # ──────────────────────────────────────────────────────────────────────────
    # Global hotkeys
    # ──────────────────────────────────────────────────────────────────────────

    def _register_hotkeys(self) -> None:
        try:
            import keyboard  # type: ignore[import]
            keyboard.add_hotkey("ctrl+alt+p", self._on_cancel)            # pause all
            keyboard.add_hotkey("ctrl+alt+y", self._tray_open)            # open window
            logger.info("[AppWindow] Global hotkeys registered.")
        except ImportError:
            logger.warning("[AppWindow] 'keyboard' library not installed; hotkeys disabled.")
        except Exception as exc:
            logger.warning("[AppWindow] Global hotkey registration failed: %s", exc)

    # ──────────────────────────────────────────────────────────────────────────
    # Auto-resume (smart queue persistence)
    # ──────────────────────────────────────────────────────────────────────────

    def _check_auto_resume(self) -> None:
        """If a previous queue state was saved, offer to restore it."""
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
        """Re-populate the queue from serialised TrackMeta-like dicts."""
        logger.debug("PlaylistParser.parse: restoring %d items", len(saved))
        from playlist_parser import TrackMeta
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
        """Serialise current queue to config for crash recovery."""
        cards = self._queue_panel.get_all_cards()
        state = [
            {
                "title":        c.title,
                "artist":       c.artist,
                "url":          c.track_url,
                "duration_str": "",
                "thumbnail_url": "",
                "platform":     getattr(c, "platform_name", "YOUTUBE"),
            }
            for c in cards
        ]
        self._cfg.queue_state = state
        self._cfg.save()

    # ──────────────────────────────────────────────────────────────────────────
    # Pause / Resume
    # ──────────────────────────────────────────────────────────────────────────

    def _on_pause_track(self, queue_index: int) -> None:
        """
        Cancel the in-flight download for this card (leaving the .part file)
        and mark the card as paused so it can be resumed later.
        """
        card = self._index_to_card.get(queue_index)
        if card is None:
            return
        key = str(id(card))

        # Store the original request for resuming
        req = self._active_request_for_key(key)
        if req is not None:
            req_copy = DownloadRequest(
                url=req.url,
                output_dir=req.output_dir,
                media_type=req.media_type,
                audio_quality=req.audio_quality,
                video_quality=req.video_quality,
                audio_format=req.audio_format,
                embed_thumbnail=req.embed_thumbnail,
                embed_metadata=req.embed_metadata,
                forced_title=req.forced_title,
                forced_artist=req.forced_artist,
                forced_index=req.forced_index,
                playlist_name=req.playlist_name,
                sponsorblock=req.sponsorblock,
                resumable=True,   # ← pick up .part on resume
                embed_lyrics=req.embed_lyrics,
                replay_gain=req.replay_gain,
                musicbrainz=req.musicbrainz,
                square_thumbnails=req.square_thumbnails,
                clean_filename=req.clean_filename,
                cookies_file=req.cookies_file,
            )
            self._paused_requests[key] = req_copy

        # Cancel only this track
        if self._dl_worker:
            self._dl_worker.cancel_track(key)

        card.set_status("paused")

        # Persist paused state for app-level resume
        paused = self._cfg.paused_items
        paused.append({
            "card_key":  key,
            "title":     card.title,
            "artist":    card.artist,
            "url":       card.track_url,
        })
        self._cfg.paused_items = paused
        self._cfg.save()

    def _on_resume_track(self, queue_index: int) -> None:
        """
        Re-submit the paused download request with continuedl=True.
        """
        card = self._index_to_card.get(queue_index)
        if card is None:
            return
        key = str(id(card))
        req = self._paused_requests.pop(key, None)
        if req is None:
            logger.warning("[AppWindow] No paused request found for card %s", key)
            return

        # Remove from paused_items
        paused = [p for p in self._cfg.paused_items if p.get("card_key") != key]
        self._cfg.paused_items = paused
        self._cfg.save()

        card.set_status("queued")
        card.set_progress(0.0)

        # Start a single-job DownloadWorker for this track.
        # Store in _resume_workers to prevent premature garbage collection.
        self._key_to_card[key] = card
        resume_worker = DownloadWorker(
            jobs=[(key, req)],
            engine=self._engine,
            db=self._db,
            max_workers=1,
            parent=self,
        )
        self._resume_workers.append(resume_worker)
        resume_worker.track_progress.connect(self._on_track_progress)
        resume_worker.track_status.connect(self._on_track_status)
        resume_worker.track_finished.connect(self._on_track_finished)
        resume_worker.job_error.connect(self._on_track_error)
        resume_worker.all_finished.connect(self._on_all_downloads_finished)
        resume_worker.all_finished.connect(
            lambda w=resume_worker: self._resume_workers.remove(w) if w in self._resume_workers else None
        )
        resume_worker.start()

    def _active_request_for_key(self, key: str) -> Optional[DownloadRequest]:
        """
        Retrieve the DownloadRequest currently running for a card key by
        inspecting the active worker's job list.
        """
        if self._dl_worker is None:
            return None
        for card_key, req in self._dl_worker._jobs:  # noqa: SLF001
            if card_key == key:
                return req
        return None

    # ──────────────────────────────────────────────────────────────────────────
    # Download flow
    # ──────────────────────────────────────────────────────────────────────────

    def _on_download(self) -> None:
        selected = self._queue_panel.get_selected_cards()
        if not selected:
            self._status_bar.set_status(f"⚠  {t('no_tracks_selected')}")
            return

        opts       = self._options_bar.get_options()
        is_audio   = opts["is_audio"]
        media_type = MediaType.AUDIO if is_audio else MediaType.VIDEO
        audio_q    = _AUDIO_QUALITY_MAP.get(opts["quality_label"], AudioQuality.BEST)
        video_q    = _VIDEO_QUALITY_MAP.get(opts["quality_label"], VideoQuality.HIGH)
        output_dir = opts["output_dir"]

        try:
            Path(output_dir).expanduser().mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError) as exc:
            MessageBox(
                t("cannot_write_output_title"),
                t("cannot_write_output_detail", path=output_dir, exc=exc),
                self,
            ).exec()
            return

        _multi_kinds = {UrlKind.PLAYLIST, UrlKind.ALBUM, UrlKind.ARTIST}
        is_multi = self._last_url_kind in _multi_kinds

        jobs: list[tuple[str, DownloadRequest]] = []
        self._key_to_card.clear()

        # We will determine `clean_filename` per-card instead of globally
        unique_artists = set(c.artist for c in selected if c.artist)
        is_multi_batch = len(unique_artists) > 1

        for card in selected:
            track_playlist_name: Optional[str] = None
            is_parent_discography = False
            if self._cfg.playlist_subfolders:
                # 1. Check for YTM Discography specific metadata first
                parent = (card.parent_artist or "").strip()
                kind   = (card.release_type or "").strip()
                album  = (card.album or "").strip()

                if parent:
                    # Robust categorization
                    is_live = "live" in card.title.lower() or "הופעה" in card.title

                    # Platform-specific categorization
                    is_spotify = card.platform == SourcePlatform.SPOTIFY.value
                    
                    if kind == "album": 
                        category = "אלבומים"
                    elif not is_spotify and (kind == "performance" or is_live):
                        category = "הופעות חיות"
                    elif not is_spotify and kind == "video":
                        category = "סרטונים"
                    elif not is_spotify and kind == "playlist":
                        category = "פלייליסטים"
                    else:
                        category = "סינגלים ו-EP"
                    
                    # Hierarchy: Artist / Category / [Album if exists]
                    # Flatten singles/performances: Only real albums get a subfolder.
                    if kind == "album" and album:
                        clean_album = album.replace("Album - ", "").replace("Album -", "").strip()
                        track_playlist_name = f"{parent}/{category}/{clean_album}"
                    else:
                        track_playlist_name = f"{parent}/{category}"
                    
                    # Only set discography mode if we are actually coming from an Artist-level kind
                    # or if the parent is clearly different from the album name to avoid A/Category/A.
                    is_parent_discography = (getattr(self, "_last_url_kind", None) == UrlKind.ARTIST)
                
                # 2. Fallback to existing logic for other URL kinds
                elif is_multi:
                    # General playlist or artist discography without parent mapping
                    if self._last_url_kind == UrlKind.ARTIST:
                        album_part = card.album if card.album else "Singles & EPs"
                        track_playlist_name = f"{card.artist}/{album_part}"
                    else:
                        # General playlist: just the playlist title as folder
                        track_playlist_name = self._last_playlist_title or "Playlist"
                elif card.artist:
                    album_part = card.album if card.album else "Singles & EPs"
                    # Keep output_dir as the base root from config
            # Hierarchy (Artist / Category / Album) is now handled entirely by playlist_name 
            # via _get_dynamic_folder to avoid redundancies like Artist/Artist
            output_dir = str(Path(self._cfg.output_dir))
            if self._cfg.duplicate_action != "overwrite":
                from core.duplicate_checker import find_duplicate
                dup = find_duplicate(
                    output_dir=output_dir,
                    title=card.title,
                    artist=card.artist,
                    index=card.queue_index if self._cfg.playlist_index_prefix else None,
                    include_index=self._cfg.playlist_index_prefix,
                    duration_s=None,
                    playlist_name=self._get_dynamic_folder(card, track_playlist_name),
                )
                if dup is not None:
                    if self._cfg.duplicate_action == "skip":
                        card.set_status("done")
                        continue
                    else:  # "warn"
                        box = MessageBox(
                            "Duplicate Detected",
                            f'"{card.title}" already exists:\n{dup}\n\n'
                            "Download again and overwrite?",
                            self,
                        )
                        if not box.exec():
                            card.set_status("done")
                            continue

            # Smart clean filename:
            # 1. If the batch has multiple different artists, we MUST keep artist name to avoid confusion.
            # 2. If it's a "Single Artist" batch (e.g. Odeya playlist), we can use clean filenames.
            # 3. Exception: If the track artist doesn't match the parent artist, keep it.
            is_clean = not is_multi_batch
            if is_multi_batch and card.artist and card.parent_artist:
                # If this specific track artist matches parent, we can still clean it
                if card.artist.strip().lower() == card.parent_artist.strip().lower():
                    is_clean = True

            req = DownloadRequest(
                url=card.track_url,
                output_dir=output_dir,
                media_type=media_type,
                audio_quality=audio_q,
                video_quality=video_q,
                audio_format=opts["audio_format"] if is_audio else "mp4",
                embed_thumbnail=self._cfg.embed_thumbnail,
                embed_metadata=self._cfg.embed_metadata,
                forced_title=card.title,
                forced_artist=card.artist,
                forced_album=card.album,
                forced_duration=getattr(card, "duration_sec", None),
                forced_index=(
                    card.album_index if (card.release_type == "album" and card.album_index > 0)
                    else (None if card.release_type == "playlist" 
                          else (card.queue_index if (self._cfg.playlist_index_prefix and not is_parent_discography) else None))
                ),
                cookies_file=self._cfg.cookies_file or None,
                cookies_browser=self._cfg.cookies_browser or None,
                playlist_name=self._get_dynamic_folder(card, track_playlist_name, is_parent_discography),
                thumbnail_url=card.thumbnail_url,
                # v3 feature flags
                sponsorblock=self._cfg.sponsorblock_enabled,
                embed_lyrics=self._cfg.lyrics_enabled,
                replay_gain=self._cfg.replay_gain_enabled,
                musicbrainz=self._cfg.musicbrainz_enabled,
                square_thumbnails=self._cfg.square_thumbnails,
                clean_filename=is_clean,
            )
            key = str(id(card))
            self._key_to_card[key] = card
            jobs.append((key, req))

        if not jobs:
            return

        self._engine._cancel_event.clear()  # noqa: SLF001
        for card in selected:
            card.set_status("queued")
            card.set_progress(0.0)

        self._dl_bar.set_downloading(True)
        self._status_bar.set_cancel_visible(True)
        n = len(jobs)
        self._status_bar.set_status(
            t("starting_downloads", n=n, plural=("" if n == 1 else "s"))
        )

        self._dl_worker = DownloadWorker(
            jobs=jobs,
            engine=self._engine,
            config=self._cfg,
            db=self._db,
            max_workers=self._cfg.max_parallel_downloads,
            parent=self,
        )
        self._dl_worker.track_progress.connect(self._on_track_progress)
        self._dl_worker.track_status.connect(self._on_track_status)
        self._dl_worker.track_finished.connect(self._on_track_finished)
        self._dl_worker.overall_progress.connect(self._status_bar.set_progress)
        self._dl_worker.metrics.connect(self._status_bar.set_metrics)
        self._dl_worker.status_msg.connect(self._status_bar.set_status)
        self._dl_worker.job_count_changed.connect(self._on_job_count_changed)
        self._dl_worker.job_error.connect(self._on_track_error)
        self._dl_worker.all_finished.connect(self._on_all_downloads_finished)
        self._dl_worker.start()

        # Persist queue state for crash recovery
        self._save_queue_state()

    # ── Download signal handlers ───────────────────────────────────────────────

    def _on_track_progress(self, key: str, fraction: float) -> None:
        prev = self._card_progress.get(key, 0.0)
        if fraction - prev < 0.01 and fraction < 1.0:
            return
        self._card_progress[key] = fraction
        card = self._key_to_card.get(key)
        if card:
            card.set_progress(fraction)
            if card._status != "downloading":
                card.set_status("downloading")

    def _on_global_pause_resume(self, pause: bool) -> None:
        if pause:
            if self._dl_worker:
                self._dl_worker.cancel()
            self._queue_panel.set_pause_resume_state(True)
            self._status_bar.set_status(t("cancelling"))
        else:
            # Resume: find cards that are 'queued', 'paused', 'cancelled', or 'error'
            to_resume = []
            for card in self._queue_panel.get_all_cards():
                if card.get_status() in ("queued", "paused", "cancelled", "error") and card.is_selected():
                    to_resume.append(card)
            
            if to_resume:
                self._queue_panel.set_pause_resume_state(False)
                # Re-trigger download for these items
                # We can't easily call _on_download because it reads selected cards.
                # Let's just use the existing _on_download logic.
                self._on_download()
            else:
                self._queue_panel.set_pause_resume_state(False)

    def _on_track_status(self, key: str, status: str) -> None:
        card = self._key_to_card.get(key)
        if card:
            card.set_status(status)

    def _on_job_count_changed(self, current: int, total: int) -> None:
        if current < total:
            self._status_bar.set_status(t("download_progress_count", current=current + 1, total=total))

    def _on_track_finished(self, key: str, output_path: str) -> None:
        card = self._key_to_card.get(key)
        if card:
            card.set_status("done")
            card.set_progress(1.0)
        InfoBar.success(
            title="Downloaded",
            content=Path(output_path).name[:60] if output_path else "Track saved.",
            orient=Qt.Orientation.Horizontal,
            position=InfoBarPosition.BOTTOM_RIGHT,
            duration=4000,
            parent=self,
        )

    def _on_track_error(self, key: str, err: object) -> None:
        card = self._key_to_card.get(key)
        if card:
            card.set_status("error")
        if hasattr(err, "headline"):
            MessageBox(err.headline, err.detail, self).exec()

    def _on_all_downloads_finished(self) -> None:
        self._dl_bar.set_downloading(False)
        self._status_bar.set_cancel_visible(False)
        self._status_bar.set_metrics("", "")
        self._queue_panel.set_pause_resume_state(False)
        # Clear saved queue state once all done
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
    # Fetch flow  (unchanged from v2 structure)
    # ──────────────────────────────────────────────────────────────────────────

    def _on_fetch(self, url: str) -> None:
        """
        Entry point for fetching content from a URL (single or playlist).
        """
        logger.debug(f"[AppWindow] _on_fetch: url={url}")
        if not url.strip():
            return
        if self._fetch_worker and self._fetch_worker.isRunning():
            self._fetch_worker.cancel()
            self._fetch_worker.wait(500)

        self._url_bar.set_fetching(True)
        self._status_bar.set_status(t("fetching"))
        self._status_bar.set_cancel_visible(True)

        self._fetch_worker = FetchWorker(
            url,
            cookies_file=self._cfg.cookies_file,
            proxy_url=self._cfg.proxy_server_url,
            proxy_token=self._cfg.spotify_app_api_key,
            parent=self
        )
        self._fetch_worker.track_found.connect(self._on_track_meta)
        self._fetch_worker.finished.connect(self._on_fetch_finished)
        self._fetch_worker.error.connect(self._on_fetch_error)
        self._fetch_worker.start()

    def _on_track_meta(self, meta, index: int, total: int) -> None:
        self._add_track_to_queue(meta)
        self._status_bar.set_status(
            t("fetching_progress", n=index, total=total)
            if total > 1
            else t("fetching_single", title=meta.get("title", "")[:50])
        )

    def _add_track_to_queue(self, data) -> None:
        idx = len(self._queue_panel.get_all_cards()) + 1

        # Support both dict (from FetchWorker) and objects (from SearchWorker)
        get = lambda k, d="": data.get(k, d) if isinstance(data, dict) else getattr(data, k, d)

        # Call QueuePanel.add_card which creates the TrackCard correctly
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
        )

        # Connect AppWindow-specific handlers
        card.remove_requested.connect(self._on_card_removed)
        card.pause_requested.connect(self._on_pause_track)
        card.resume_requested.connect(self._on_resume_track)

        self._index_to_card[idx] = card
        self._update_dl_bar()

        # Fire thumbnail load
        thumb_url = get("thumbnail_url", "")
        if thumb_url:
            tw = ThumbnailWorker(idx, thumb_url, parent=self)
            self._thumb_workers.add(tw)
            
            # Cleanup on finish
            tw.finished.connect(lambda t=tw: self._thumb_workers.discard(t))
            
            # Use card local variable in lambda
            tw.thumbnail_ready.connect(lambda idx, data, c=card: self._set_card_thumb(c, data))
            tw.start()

    def _set_card_thumb(self, card: TrackCard, data: bytes) -> None:
        from PySide6.QtGui import QPixmap
        px = QPixmap()
        px.loadFromData(data)
        if not px.isNull():
            card.set_thumbnail(px)

    def _on_fetch_finished(self, result) -> None:
        self._url_bar.set_fetching(False)
        self._status_bar.set_cancel_visible(False)
        if hasattr(result, "playlist_title") and result.playlist_title:
            self._last_playlist_title = result.playlist_title
        if hasattr(result, "kind"):
            self._last_url_kind = result.kind

        # Surface any fetch-time error that was caught inside PlaylistParser
        # (e.g. unsupported URL, geo-block, Spotify proxy not configured).
        # These are stored in result.error rather than raising an exception,
        # so without this check they would be silently discarded.
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
        self._url_bar.set_fetching(False)
        self._status_bar.set_cancel_visible(False)
        err = classify_error(Exception(msg))
        self._status_bar.set_status(err.status_line())
        MessageBox(err.headline, err.detail, self).exec()

    def _on_search_error(self, msg: str) -> None:
        self._search_panel.set_searching(False)
        err = classify_error(Exception(msg))
        self._status_bar.set_status(err.status_line())
        MessageBox(err.headline, err.detail, self).exec()

    # ──────────────────────────────────────────────────────────────────────────
    # Search flow
    # ──────────────────────────────────────────────────────────────────────────

    def _on_search(self, query: str) -> None:
        if self._search_worker and self._search_worker.isRunning():
            self._search_worker.cancel()
        self._search_worker = SearchWorker(
            query=query,
            platform=self._search_panel._current_platform,
            youtube_max_results=self._cfg.youtube_max_results,
            spotify_max_results=self._cfg.spotify_max_results,
            cookies_file=self._cfg.cookies_file,
            spotify_client_id=self._cfg.spotify_app_api_key,
            spotify_client_secret="",
            proxy_url=self._cfg.proxy_server_url,
            proxy_token=self._cfg.spotify_app_api_key,
            parent=self
        )
        self._search_worker.result_ready.connect(
            self._on_search_result_ready
        )
        self._search_worker.finished.connect(
            lambda: self._search_panel.set_searching(False)
        )
        self._search_worker.error.connect(self._on_search_error)
        self._search_panel.set_searching(True)
        self._search_worker.start()

    def _on_search_result_ready(self, result: SearchResult) -> None:
        """Add a search result card and immediately start fetching its thumbnail."""
        card = self._search_panel.add_result(result)
        if result.thumbnail_url:
            tw = ThumbnailWorker(0, result.thumbnail_url, parent=self)
            # Route the raw bytes to the card's set_thumbnail method
            tw.thumbnail_ready.connect(
                lambda _, data, c=card: c.set_thumbnail(data)
            )
            tw.start()

    def _on_add_search_result_to_queue(self, result: SearchResult) -> None:
        from playlist_parser import TrackMeta
        meta = TrackMeta(
            title=result.title,
            artist=result.artist,
            url=result.url,
            duration_str=result.duration_str,
            thumbnail_url=result.thumbnail_url,
            platform=result.platform,
            album=result.album,
            release_type=result.release_type,
        )
        self._add_track_to_queue(meta)
        self.switchTo(self._queue_wrapper)

    def _on_search_drill_down(self, result: SearchResult) -> None:
        """User clicked 'Drill Down' (Mshicha) on a search result card."""
        logger.debug(f"[AppWindow] _on_search_drill_down: kind={result.kind.value}, url={result.url}")
        self._url_bar.set_url(result.url)
        self.switchTo(self._queue_wrapper)
        
        # Clear previous playlist/album metadata context to ensure fresh fetch
        self._last_playlist_title = result.title if result.kind in (ResultKind.ALBUM, ResultKind.PLAYLIST) else ""
        self._last_url_kind = UrlKind.PLAYLIST if result.kind == ResultKind.PLAYLIST else \
                            (UrlKind.ALBUM if result.kind == ResultKind.ALBUM else UrlKind.ARTIST)
                            
        self._on_fetch(result.url)

    # ──────────────────────────────────────────────────────────────────────────
    # Scrape
    # ──────────────────────────────────────────────────────────────────────────

    def _on_scrape(self, url: str) -> None:
        if self._scraper_worker and self._scraper_worker.isRunning():
            self._scraper_worker.cancel()
        self._status_bar.set_status(t("scraping"))
        self._scraper_worker = ScraperWorker(url, cookies_file=self._cfg.cookies_file, parent=self)
        self._scraper_worker.finished.connect(self._on_scrape_done)
        self._scraper_worker.error.connect(
            lambda msg: self._status_bar.set_status(f"⚠  {msg}")
        )
        self._scraper_worker.start()

    def _on_scrape_done(self, urls: list) -> None:
        if not urls:
            self._status_bar.set_status(t("scrape_no_urls"))
            return
        self._url_bar.set_url(urls[0])
        self._status_bar.set_status(
            t("scrape_multi_found", count=len(urls))
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Batch import
    # ──────────────────────────────────────────────────────────────────────────

    def _on_batch_import(self, file_path: str) -> None:
        from core.batch_importer import BatchImporter
        try:
            result = BatchImporter.from_text_file(file_path)
        except Exception as exc:
            MessageBox(t("batch_import_failed"), str(exc), self).exec()
            return
        if not result.urls:
            self._status_bar.set_status(
                t("no_urls_found", filename=Path(file_path).name)
            )
            return
        self._status_bar.set_status(result.summary())
        self._url_bar.set_url(result.urls[0])
        self._on_fetch(result.urls[0])

    # ──────────────────────────────────────────────────────────────────────────
    # History
    # ──────────────────────────────────────────────────────────────────────────

    def _on_redownload(self, record: DownloadRecord) -> None:
        self._url_bar.set_url(record.url)
        self.switchTo(self._queue_wrapper)
        self._on_fetch(record.url)

    def _on_open_folder(self, record: DownloadRecord) -> None:
        path   = Path(record.output_path)
        folder = path.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

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

    # ──────────────────────────────────────────────────────────────────────────
    # Updates
    # ──────────────────────────────────────────────────────────────────────────

    def _on_update_found(self, release: ReleaseInfo) -> None:
        self._update_banner.set_release(release)
        self._update_banner.show()

    # ──────────────────────────────────────────────────────────────────────────
    # Queue helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _on_selection_changed(self, count: int) -> None:
        total = len(self._queue_panel.get_all_cards())
        self._dl_bar.set_count(count, total)

    def _on_card_removed(self, queue_index: int) -> None:
        self._index_to_card.pop(queue_index, None)
        self._update_dl_bar()

    def _on_options_changed(self) -> None:
        pass

    def _get_dynamic_folder(self, card, fallback: Optional[str] = None, is_discography: bool = False) -> str:
        """
        Constructs a folder path like 'Artist / Category / Album' while avoiding redundancy.
        Includes a de-duplication pass to prevent paths like 'Name / אלבומים / Name'.
        """
        artist = (card.parent_artist or card.artist or "").strip()
        album  = (card.album or "").strip()
        rel_type = (card.release_type or "album").lower()

        # Grouping names (Hebrew as requested)
        CAT_ALBUMS  = "אלבומים"
        CAT_SINGLES = "סינגלים ו-EP"

        path_parts = []
        
        # 1. Root Artist segment (Only for non-albums in Discography)
        if is_discography and artist and rel_type != "album":
            path_parts.append(artist)

        # 2. Category & Album Folder
        if is_discography:
            if rel_type == "album":
                # User requested flattened albums: skip Artist/Albums prefix
                if album:
                    path_parts.append(album.replace("Album - ", "").strip())
            else:
                path_parts.append(CAT_SINGLES)
        elif album:
            # For non-discography (single album), just use Album Name directly
            path_parts.append(album.replace("Album - ", "").strip())
        elif artist:
            # Fallback for single tracks
            path_parts.append(artist)

        # 3. Smart De-duplication Pass (Case-insensitive)
        seen = []
        for part in path_parts:
            # Check if this part is a case-insensitive duplicate of the last or root
            if not seen or part.lower() != seen[-1].lower():
                seen.append(part)

        return "/".join(seen)

    def _update_dl_bar(self) -> None:
        cards    = self._queue_panel.get_all_cards()
        selected = self._queue_panel.get_selected_cards()
        self._dl_bar.set_count(len(selected), len(cards))

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

    def _on_clipboard_setting_change(self, checked: bool) -> None:
        self._cfg.clipboard_monitor = checked
        self._cfg.save()
        if checked:
            self._clipboard_worker.start()
        else:
            self._clipboard_worker.stop()
        self._url_bar.set_clipboard_monitor_active(checked)

    # ──────────────────────────────────────────────────────────────────────────
    # Cancel
    # ──────────────────────────────────────────────────────────────────────────

    def _on_cancel(self) -> None:
        if self._fetch_worker and self._fetch_worker.isRunning():
            self._fetch_worker.cancel()
            self._url_bar.set_fetching(False)
        if self._dl_worker and self._dl_worker.isRunning():
            self._engine.cancel_all()
        if self._search_worker and self._search_worker.isRunning():
            self._search_worker.cancel()
        if self._scraper_worker and self._scraper_worker.isRunning():
            self._scraper_worker.cancel()
        self._status_bar.set_cancel_visible(False)
        self._status_bar.set_status(t("cancelling"))

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
    # Close event (with tray support)
    # ──────────────────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        """
        Clean shutdown sequence.

        Order matters:
        1. Tray intercept (if enabled).
        2. Persist window state and queue.
        3. Stop non-threaded monitors (clipboard, network).
        4. Cancel + join threaded workers (download first, then others).
        5. Unregister global hotkeys.
        6. Close the database (via ServiceContainer).
        7. Accept the close event.
        """
        # ── 1. Tray intercept ─────────────────────────────────────────────────
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

        # ── 2. Persist state ──────────────────────────────────────────────────
        self._save_state()
        self._save_queue_state()

        # ── 3. Stop non-threaded monitors ─────────────────────────────────────
        if hasattr(self, "_net_monitor"):
            self._net_monitor.stop()
            logger.debug("[AppWindow] Network monitor stopped")
        if hasattr(self, "_clipboard_worker"):
            self._clipboard_worker.stop()
            logger.debug("[AppWindow] Clipboard monitor stopped")

        # ── 4. Cancel + join threaded workers ─────────────────────────────────
        if self._dl_worker and self._dl_worker.isRunning():
            logger.info("[AppWindow] Shutting down DownloadWorker…")
            self._dl_worker.shutdown(timeout_ms=3000)

        other_workers = []
        for attr in ("_fetch_worker", "_search_worker", "_scraper_worker"):
            w = getattr(self, attr, None)
            if w and w.isRunning():
                other_workers.append((attr, w))

        for attr_name, w in other_workers:
            logger.debug("[AppWindow] Cancelling %s…", attr_name)
            if hasattr(w, "cancel"):
                w.cancel()

        for attr_name, w in other_workers:
            finished = w.wait(2000)
            if finished:
                logger.debug("[AppWindow] %s joined cleanly", attr_name)
            else:
                logger.warning(
                    "[AppWindow] %s did not finish within 2s — abandoning", attr_name,
                )

        # ── 5. Global hotkeys ─────────────────────────────────────────────────
        try:
            import keyboard
            keyboard.unhook_all()
            logger.debug("[AppWindow] Global hotkeys unregistered")
        except Exception:
            pass

        # ── 6. Hide tray & close DB (via services) ───────────────────────────
        if self._tray:
            self._tray.hide()

        if hasattr(self, "_svc"):
            self._svc.close()
            logger.info("[AppWindow] Services closed — shutdown complete")
        else:
            self._db.close()
            logger.info("[AppWindow] Database closed (legacy) — shutdown complete")

        super().closeEvent(event)
