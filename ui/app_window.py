"""
ui/app_window.py  –  Main application window
=============================================
The top-level FluentWindow that owns every panel, every worker, and the
shared backend engine.  Its only job is wiring: it connects signals to slots
and delegates all visual work to the panels and all I/O to the workers.

Navigation structure (FluentWindow sidebar)
-------------------------------------------
  ⬇  Queue      (default)  →  UrlBar + OptionsBar + QueuePanel
  🔍  Search               →  SearchPanel
  🕐  History              →  HistoryPanel
  ⚙  Settings             →  SettingsPanel  (inline sub-interface)

Threading model
---------------
  FetchWorker      QThread   – one per Fetch click; cancelled on new Fetch
  DownloadWorker   QThread   – one per Download click
  ThumbnailWorker  QThread   – one per track card (fire-and-forget)
  SearchWorker     QThread   – one per search query; cancelled on new query
  ScraperWorker    QThread   – one per scrape request
  ClipboardWorker  QObject   – lives on main thread, driven by QTimer
  UpdateWorker     QThread   – started once at launch; never restarted

Card routing
------------
  _index_to_card : dict[int,  TrackCard]  queue_index → card
  _key_to_card   : dict[str, TrackCard]  str(id(card)) → card   (for downloads)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QByteArray, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import QApplication, QFrame, QVBoxLayout, QWidget

from qfluentwidgets import (
    FluentIcon, FluentWindow, MessageBox,
    NavigationItemPosition, setTheme, setThemeColor, Theme,
)

# ── Backend ────────────────────────────────────────────────────────────────────
from config import AppConfig
from core.history_db import DownloadRecord, HistoryDB
from core.search_engine import SearchResult
from core.update_checker import ReleaseInfo
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
from ui.panels.url_bar       import UrlBar
from ui.panels.search_panel  import SearchPanel
from ui.panels.queue_panel   import QueuePanel
from ui.panels.history_panel import HistoryPanel
from ui.panels.options_bar   import OptionsBar
from ui.panels.status_bar    import StatusBar

# ── Components ─────────────────────────────────────────────────────────────────
from ui.components.track_card    import TrackCard
from ui.components.update_banner import UpdateBanner

# ── Theme ──────────────────────────────────────────────────────────────────────
from ui.theme_manager import ACCENT_COLOR, ThemeManager
from ui.i18n import t, set_language

# ── Quality maps (mirrors options_bar.py) ─────────────────────────────────────
from ui.panels.options_bar import AUDIO_QUALITY_OPTIONS, VIDEO_QUALITY_OPTIONS

_AUDIO_QUALITY_MAP: dict[str, AudioQuality] = {
    "Best (320k)":   AudioQuality.BEST,
    "High (256k)":   AudioQuality.HIGH,
    "Medium (192k)": AudioQuality.MEDIUM,
    "Low (128k)":    AudioQuality.LOW,
}
_VIDEO_QUALITY_MAP: dict[str, VideoQuality] = {
    "Best":  VideoQuality.BEST,
    "1080p": VideoQuality.HIGH,
    "720p":  VideoQuality.MEDIUM,
    "480p":  VideoQuality.LOW,
    "Worst": VideoQuality.WORST,
}


# ──────────────────────────────────────────────────────────────────────────────
# Queue sub-interface  (contains UrlBar + OptionsBar + QueuePanel stacked)
# ──────────────────────────────────────────────────────────────────────────────

class _QueueInterface(QWidget):
    """
    Container widget registered as the Queue navigation sub-interface.
    Owns UrlBar, OptionsBar, UpdateBanner, and QueuePanel stacked vertically.
    """

    def __init__(
        self,
        url_bar:     UrlBar,
        options_bar: OptionsBar,
        queue_panel: QueuePanel,
        banner:      UpdateBanner,
        status_bar:  StatusBar,
        parent:      QWidget = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("queueInterface")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(banner)        # height=0 until update detected
        layout.addWidget(url_bar)
        layout.addWidget(options_bar)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: #2e2e35; border: none;")
        layout.addWidget(divider)

        layout.addWidget(queue_panel, stretch=1)
        layout.addWidget(status_bar)


# ──────────────────────────────────────────────────────────────────────────────
# Download bar  (bottom of the queue interface, above StatusBar)
# ──────────────────────────────────────────────────────────────────────────────

class _DownloadBar(QFrame):
    """
    Fixed footer bar inside the Queue sub-interface that shows the
    selected-track count and hosts the Download Selected button.
    """

    from PySide6.QtCore import Signal as _Signal
    download_clicked = _Signal()

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QHBoxLayout
        from qfluentwidgets import PrimaryPushButton

        self.setFixedHeight(58)
        self.setStyleSheet(
            "background: #18181b; border-top: 1px solid #2e2e35;"
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 8, 16, 8)

        from PySide6.QtWidgets import QLabel
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
                color: #000000;
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-weight: bold;
            }}
            PrimaryPushButton:hover {{ background-color: #e09418; }}
            PrimaryPushButton:disabled {{
                background-color: #5a3e0e;
                color: #888888;
            }}
        """)
        self._dl_btn.clicked.connect(self.download_clicked)
        row.addWidget(self._dl_btn)

    def set_count(self, selected: int, total: int) -> None:
        if total == 0:
            self._count_lbl.setText(t("no_tracks_selected"))
            self._dl_btn.setEnabled(False)
        else:
            self._count_lbl.setText(
                t("selected_of_total", selected=selected, total=total, plural=('' if total == 1 else 's'))
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
    """
    The application's top-level window.

    Parameters
    ----------
    config : AppConfig  – live config instance owned here for the app lifetime.
    db     : HistoryDB  – live database instance owned here.
    """

    def __init__(self, config: AppConfig, db: HistoryDB) -> None:
        super().__init__()

        # ── Owned singletons ──────────────────────────────────────────────────
        self._cfg    = config
        self._db     = db
        self._engine = DownloadEngine()
        self._theme  = ThemeManager(config)

        # ── Worker references (replaced on each use) ──────────────────────────
        self._fetch_worker:    Optional[FetchWorker]    = None
        self._dl_worker:       Optional[DownloadWorker] = None
        self._search_worker:   Optional[SearchWorker]   = None
        self._scraper_worker:  Optional[ScraperWorker]  = None

        # ── Card routing tables ───────────────────────────────────────────────
        self._index_to_card: dict[int, TrackCard] = {}   # queue_index → card
        self._key_to_card:   dict[str, TrackCard] = {}   # str(id(card)) → card
        self._card_progress: dict[str, float] = {}       # throttle progress updates

        # ── Last fetch metadata (for playlist sub-folder routing) ─────────────
        self._last_playlist_title: str             = ""
        self._last_url_kind:       Optional[UrlKind] = None

        # ── Build panels ──────────────────────────────────────────────────────
        self._build_panels()

        # ── Configure FluentWindow chrome ─────────────────────────────────────
        self._configure_window()

        # ── Register navigation sub-interfaces ───────────────────────────────
        self._register_navigation()

        # ── Wire signals ──────────────────────────────────────────────────────
        self._connect_signals()

        # ── Restore window state ──────────────────────────────────────────────
        self._restore_state()

        # ── Start background workers ──────────────────────────────────────────
        QTimer.singleShot(300, self._start_background_workers)

    # ──────────────────────────────────────────────────────────────────────────
    # Panel construction
    # ──────────────────────────────────────────────────────────────────────────

    def _build_panels(self) -> None:
        # Leaf panels
        self._url_bar      = UrlBar(self._cfg)
        self._options_bar  = OptionsBar(self._cfg)
        self._queue_panel  = QueuePanel()
        self._search_panel = SearchPanel(self._cfg)
        self._history_panel = HistoryPanel(self._db, self._cfg)
        self._status_bar   = StatusBar()
        self._update_banner = UpdateBanner()
        self._dl_bar       = _DownloadBar()

        from ui.panels.settings_panel import SettingsPanel
        self._settings_panel = SettingsPanel(self._cfg, self._theme)

        # Queue composite interface
        # Insert _dl_bar between queue_panel and status_bar by building
        # a wrapper that stacks them.
        queue_wrapper = QWidget()
        queue_wrapper.setObjectName("queueWrapper")
        vl = QVBoxLayout(queue_wrapper)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
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

        # Apply saved theme
        self._theme.apply(self._cfg.theme)

        # Fluent micro-customisation: title bar text colour to amber
        self.navigationInterface.setExpandWidth(200)

    def _register_navigation(self) -> None:
        """Register all sub-interfaces with the FluentWindow navigation bar."""

        # ── Queue (home) ──────────────────────────────────────────────────────
        self._queue_wrapper.setObjectName("queuePage")
        self.addSubInterface(
            self._queue_wrapper,
            FluentIcon.DOWNLOAD,
            t("queue"),
            position=NavigationItemPosition.TOP,
        )

        # ── Search ────────────────────────────────────────────────────────────
        self._search_panel.setObjectName("searchPage")
        self.addSubInterface(
            self._search_panel,
            FluentIcon.SEARCH,
            t("search"),
            position=NavigationItemPosition.TOP,
        )

        # ── History ───────────────────────────────────────────────────────────
        self._history_panel.setObjectName("historyPage")
        self.addSubInterface(
            self._history_panel,
            FluentIcon.HISTORY,
            t("history"),
            position=NavigationItemPosition.TOP,
        )

        # ── Settings (bottom of nav) ──────────────────────────────────────────
        self._settings_panel.setObjectName("settingsPage")
        self._settings_panel.theme_changed.connect(
            lambda _: None  # Theme cycle handled internally via signal
        )
        self._settings_panel.clipboard_monitor_changed.connect(
            self._on_clipboard_setting_change
        )
        self._settings_panel.settings_saved.connect(
            lambda: self._options_bar.apply_config(self._cfg)
        )
        self._settings_panel.settings_saved.connect(self._on_settings_saved)
        self.addSubInterface(
            self._settings_panel,
            FluentIcon.SETTING,
            t("settings"),
            position=NavigationItemPosition.BOTTOM,
        )


    # ──────────────────────────────────────────────────────────────────────────
    # Signal wiring
    # ──────────────────────────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        # ── URL bar ───────────────────────────────────────────────────────────
        self._url_bar.fetch_requested.connect(self._on_fetch)
        self._url_bar.batch_import_requested.connect(self._on_batch_import)
        self._url_bar.scrape_requested.connect(self._on_scrape)

        # ── Options bar ───────────────────────────────────────────────────────
        self._options_bar.options_changed.connect(self._on_options_changed)

        # ── Queue panel ───────────────────────────────────────────────────────
        self._queue_panel.selection_changed.connect(self._on_selection_changed)
        self._queue_panel.card_removed.connect(self._on_card_removed)

        # ── Download bar ──────────────────────────────────────────────────────
        self._dl_bar.download_clicked.connect(self._on_download)

        # ── Status bar ────────────────────────────────────────────────────────
        self._status_bar.cancel_requested.connect(self._on_cancel)

        # ── Search panel ──────────────────────────────────────────────────────
        self._search_panel.search_requested.connect(self._on_search)
        self._search_panel.add_to_queue_requested.connect(
            self._on_add_search_result_to_queue
        )
        self._search_panel.drill_down_requested.connect(self._on_search_drill_down)

        # ── History panel ─────────────────────────────────────────────────────
        self._history_panel.redownload_requested.connect(self._on_redownload)
        self._history_panel.open_folder_requested.connect(self._on_open_folder)

        # ── Update banner ─────────────────────────────────────────────────────
        self._update_banner.dismissed.connect(
            lambda: None   # no action needed; banner hides itself
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Background worker startup
    # ──────────────────────────────────────────────────────────────────────────

    def _start_background_workers(self) -> None:
        """Called 300 ms after the window is shown to avoid blocking startup."""
        
        # Check if FFmpeg is installed
        self._check_ffmpeg_availability()

        # Clipboard monitor (QObject on main thread)
        self._clipboard_worker = ClipboardWorker(parent=self)
        self._clipboard_worker.url_detected.connect(self._on_clipboard_url)
        if self._cfg.clipboard_monitor:
            self._clipboard_worker.start()
        self._url_bar.set_clipboard_monitor_active(self._cfg.clipboard_monitor)

        # Update checker (one-shot QThread)
        if self._cfg.check_updates:
            self._update_worker = UpdateWorker(parent=self)
            self._update_worker.update_available.connect(self._on_update_available)
            self._update_worker.start()

    def _check_ffmpeg_availability(self) -> None:
        """Check if FFmpeg is installed and show a warning if not."""
        import shutil
        
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            # FFmpeg not found - show warning dialog
            MessageBox(
                t("ffmpeg_missing_title"),
                t("ffmpeg_missing_detail"),
                parent=self,
            ).show()

    # ──────────────────────────────────────────────────────────────────────────
    # State save / restore
    # ──────────────────────────────────────────────────────────────────────────

    def _restore_state(self) -> None:
        if self._cfg.window_state and hasattr(self, "restoreState"):
            try:
                state = QByteArray.fromHex(
                    self._cfg.window_state.encode("ascii")
                )
                self.restoreState(state)
            except Exception:
                pass

    def _save_state(self) -> None:
        if hasattr(self, "saveState"):
            self._cfg.window_state = bytes(self.saveState().toHex()).decode("ascii")
        # Sync live options bar back to config
        opts = self._options_bar.get_options()
        self._cfg.output_dir   = opts["output_dir"]
        self._cfg.media_format = opts["format"]
        if opts["is_audio"]:
            self._cfg.audio_quality = opts["quality_label"]
        else:
            self._cfg.video_quality = opts["quality_label"]
        self._cfg.audio_format = opts["audio_format"]
        self._search_panel.save_state()
        self._cfg.save()

    # ──────────────────────────────────────────────────────────────────────────
    # Fetch flow
    # ──────────────────────────────────────────────────────────────────────────

    def _on_fetch(self, url: str) -> None:
        if not url:
            return

        self._pending_action = ("fetch", url)

        # Quick URL classification — only block truly invalid (non-http) input
        platform, _ = classify_url(url)
        if platform == SourcePlatform.UNKNOWN:
            MessageBox(
                t("unsupported_url_title"),
                t("unsupported_url_detail"),
                self,
            ).exec()
            return
        # GENERIC → any http/https URL; pass through to yt-dlp

        # Connectivity guard
        if not probe_connectivity(timeout=2.0):
            MessageBox(
                t("no_internet_title"),
                t("no_internet_detail"),
                self,
            ).exec()
            return

        # Cancel any in-flight fetch
        if self._fetch_worker and self._fetch_worker.isRunning():
            self._fetch_worker.cancel()
            self._fetch_worker.wait(1000)

        # Reset state
        self._index_to_card.clear()
        self._key_to_card.clear()
        self._queue_panel.clear()
        self._dl_bar.set_count(0, 0)

        # UI feedback
        self._url_bar.set_fetching(True)
        self._status_bar.start_indeterminate()
        self._status_bar.set_cancel_visible(True)
        self._status_bar.set_status(t("fetching_status"))

        cookies = self._cfg.cookies_file or None
        self._fetch_worker = FetchWorker(url=url, cookies_file=cookies, parent=self)
        self._fetch_worker.track_found.connect(self._on_track_found)
        self._fetch_worker.progress_msg.connect(self._status_bar.set_status)
        self._fetch_worker.soft_error.connect(
            lambda m: self._status_bar.set_status(f"⚠  {m[:100]}")
        )
        self._fetch_worker.finished.connect(self._on_fetch_finished)
        self._fetch_worker.error.connect(self._on_fetch_error)
        self._fetch_worker.start()

    def _on_track_found(self, data: dict) -> None:
        card = self._queue_panel.add_card(
            index=data["index"],
            title=data["title"],
            artist=data.get("artist", ""),
            duration=data.get("duration", ""),
            platform=data.get("platform", "youtube"),
            thumbnail_url=data.get("thumbnail_url", ""),
            track_url=data.get("track_url", ""),
            album=data.get("album", ""),
        )
        self._index_to_card[data["index"]] = card
        self._update_dl_bar()

        if data.get("thumbnail_url"):
            thumb = ThumbnailWorker(
                track_index=data["index"],
                url=data["thumbnail_url"],
                parent=self,
            )
            thumb.thumbnail_ready.connect(self._on_thumbnail_ready)
            thumb.start()

    def _on_thumbnail_ready(self, index: int, raw: bytes) -> None:
        card = self._index_to_card.get(index)
        if card:
            card.set_thumbnail(raw)

    def _on_fetch_finished(self, result: ParseResult) -> None:
        # Skip normal handling in batch-scrape mode
        if getattr(self, "_batch_mode", False):
            return
        self._url_bar.set_fetching(False)
        self._status_bar.stop_indeterminate()
        self._status_bar.set_cancel_visible(False)

        # Store playlist metadata for dynamic sub-folder creation at download time
        self._last_playlist_title = result.playlist_title or ""
        self._last_url_kind       = result.kind

        if result.cancelled:
            self._status_bar.set_status(t("fetch_cancelled"))
        elif result.error:
            err = classify_error(Exception(result.error))
            
            # If the parser says Unsupported URL, suggest using the scraper.
            if err.headline == "Unsupported URL":
                err.headline = t("unsupported_generic_title")
                err.detail = t("unsupported_generic_detail")
                
            self._status_bar.set_status(err.status_line())
            self._show_error_or_bypass(err)
        else:
            n = len(result.tracks)
            self._status_bar.set_status(
                t("tracks_loaded", n=n, plural=("s" if n != 1 else ""), summary=result.summary())
            )

    def _on_fetch_error(self, err: ErrorInfo) -> None:
        self._url_bar.set_fetching(False)
        self._status_bar.stop_indeterminate()
        self._status_bar.set_cancel_visible(False)
        
        # If the parser says Unsupported URL, suggest using the scraper.
        if err.headline == "Unsupported URL":
            err.headline = t("unsupported_generic_title")
            err.detail = t("unsupported_generic_detail")
            
        self._status_bar.set_status(err.status_line())
        self._show_error_or_bypass(err)

    def _show_error_or_bypass(self, err: ErrorInfo) -> None:
        """Helper to display the error, or offer the built-in bot bypass if applicable."""
        bot_headlines = {
            "Sign-in required", "Rate limited by YouTube", 
            "Access denied (403)", "Geo-restricted content"
        }
        raw_lower = err.raw.lower()
        needs_bypass = (
            err.headline in bot_headlines or 
            "bot" in raw_lower or 
            "challenge" in raw_lower or
            "captcha" in raw_lower or
            "impersonate" in raw_lower
        )

        if needs_bypass:
            from ui.components.browser_window import BotBypassWindow
            dialog = BotBypassWindow(
                target_url=self._url_bar.get_url(),
                error_detail=err.detail,
                parent=self
            )
            dialog.cookies_extracted.connect(self._on_bypass_cookies_saved)
            dialog.exec()
        else:
            MessageBox(err.headline, err.detail, self).exec()

    def _on_bypass_cookies_saved(self, cookies_path: str) -> None:
        """Called when BotBypassWindow successfully exports a cookies file."""
        self._cfg.cookies_file = cookies_path
        self._cfg.save()
        self._settings_panel.refresh()
        
        # Auto-resume the action that triggered the bot bypass
        action, url = getattr(self, "_pending_action", (None, None))
        
        from qfluentwidgets import InfoBar, InfoBarPosition
        
        if action == "scrape":
            InfoBar.success(
                title="Cookies Saved",
                content="Authentication successful. Resuming automated scan...",
                orient=Qt.Horizontal,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )
            self._on_scrape(url)
        elif action == "fetch":
            InfoBar.success(
                title="Cookies Saved",
                content="Authentication successful. Resuming fetch...",
                orient=Qt.Horizontal,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )
            self._on_fetch(url)
        else:
            InfoBar.success(
                title="Cookies Saved",
                content="Authentication successful. You may now continue.",
                orient=Qt.Horizontal,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )

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

        # Validate output directory
        try:
            Path(output_dir).expanduser().mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError) as exc:
            MessageBox(
                t("cannot_write_output_title"),
                t("cannot_write_output_detail", path=output_dir, exc=exc),
                self,
            ).exec()
            return

        # Determine playlist sub-folder (PLAYLIST / ALBUM / ARTIST → sub-folder)
        _multi_kinds = {UrlKind.PLAYLIST, UrlKind.ALBUM, UrlKind.ARTIST}
        is_multi = self._last_url_kind in _multi_kinds
        
        # Build job list
        jobs: list[tuple[int, DownloadRequest]] = []
        self._key_to_card.clear()

        for card in selected:
            # Determine playlist sub-folder per track
            track_playlist_name = None
            if is_multi:
                if self._last_url_kind == UrlKind.ARTIST:
                    # Artist flow: ArtistName / AlbumName (or Singles)
                    album_part = card.album if card.album else "Singles"
                    track_playlist_name = f"{card.artist}/{album_part}"
                elif self._last_url_kind == UrlKind.ALBUM:
                    # Album flow: ArtistName / AlbumName
                    track_playlist_name = f"{card.artist}/{self._last_playlist_title}"
                else:
                    # Playlist flow: PlaylistTitle
                    track_playlist_name = self._last_playlist_title

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
                forced_index=card.queue_index,
                cookies_file=self._cfg.cookies_file or None,
                playlist_name=track_playlist_name,
            )
            key = str(id(card))
            self._key_to_card[key] = card
            jobs.append((key, req))

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
        self._dl_worker.job_error.connect(self._on_job_error)
        self._dl_worker.all_finished.connect(self._on_all_downloads_finished)
        self._dl_worker.start()

    def _on_track_progress(self, card_key: str, fraction: float) -> None:
        # Throttle updates: skip if less than 2% change (reduce paint events)
        last_frac = self._card_progress.get(card_key, -0.1)
        if abs(fraction - last_frac) < 0.02:
            return
        self._card_progress[card_key] = fraction
        
        card = self._key_to_card.get(card_key)
        if card:
            card.set_progress(fraction)

    def _on_track_status(self, card_key: str, status: str) -> None:
        card = self._key_to_card.get(card_key)
        if card:
            card.set_status(status)

    def _on_track_finished(self, card_key: str, output_path: str) -> None:
        card = self._key_to_card.get(card_key)
        if card:
            card.set_status("done")
            card.set_progress(1.0)

    def _on_job_error(self, card_key: str, err: ErrorInfo) -> None:
        card = self._key_to_card.get(card_key)
        if card:
            card.set_status("error")
        self._status_bar.set_status(err.status_line())
        if err.severity == ErrorSeverity.CRITICAL:
            MessageBox(err.headline, err.detail, self).exec()

    def _on_all_downloads_finished(self) -> None:
        self._dl_bar.set_downloading(False)
        self._status_bar.set_cancel_visible(False)
        self._status_bar.set_metrics("", "")

    # ──────────────────────────────────────────────────────────────────────────
    # Cancel
    # ──────────────────────────────────────────────────────────────────────────

    def _on_cancel(self) -> None:
        if self._fetch_worker and self._fetch_worker.isRunning():
            self._fetch_worker.cancel()
            self._url_bar.set_fetching(False)
        if self._dl_worker and self._dl_worker.isRunning():
            self._engine.cancel()
        if self._search_worker and self._search_worker.isRunning():
            self._search_worker.cancel()
        if self._scraper_worker and self._scraper_worker.isRunning():
            self._scraper_worker.cancel()
        self._status_bar.set_cancel_visible(False)
        self._status_bar.set_status(t("cancelling"))

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

        # Feed each URL into the fetch pipeline sequentially by chaining fetches.
        # For simplicity, load them all at once by setting the first URL and
        # letting the user manually fetch; or auto-fetch the first URL.
        # Here we auto-fetch the first URL and display a summary.
        first_url = result.urls[0]
        self._url_bar.set_url(first_url)
        if len(result.urls) > 1:
            self._status_bar.set_status(
                t("batch_multi_loaded", count=result.found_count)
            )
        else:
            self._on_fetch(first_url)

    # ──────────────────────────────────────────────────────────────────────────
    # Page scraper
    # ──────────────────────────────────────────────────────────────────────────

    def _on_scrape(self, url: str) -> None:
        if not url:
            return
            
        self._pending_action = ("scrape", url)

        if self._scraper_worker and self._scraper_worker.isRunning():
            self._scraper_worker.cancel()
            self._scraper_worker.wait(500)

        self._status_bar.start_indeterminate()
        self._status_bar.set_cancel_visible(True)

        self._scraper_worker = ScraperWorker(
            page_url=url,
            cookies_file=self._cfg.cookies_file or None,
            parent=self,
        )
        self._scraper_worker.url_found.connect(self._on_scraped_url)
        self._scraper_worker.status_msg.connect(self._status_bar.set_status)
        self._scraper_worker.finished.connect(self._on_scrape_finished)
        self._scraper_worker.error.connect(self._on_scrape_error)
        self._scraper_worker.start()

    def _on_scraped_url(self, url: str) -> None:
        # Each discovered URL is immediately added to the fetch queue.
        # We batch them: collect during the scrape, then trigger fetches.
        if not hasattr(self, "_scraped_urls"):
            self._scraped_urls: list[str] = []
        self._scraped_urls.append(url)

    def _on_scrape_finished(self, count: int) -> None:
        self._status_bar.stop_indeterminate()
        self._status_bar.set_cancel_visible(False)

        urls = getattr(self, "_scraped_urls", [])
        self._scraped_urls = []

        # Filter: keep only real video page URLs, discard CDN thumbnails
        video_urls = [u for u in urls if self._is_real_video_url(u)]

        if not video_urls:
            self._status_bar.set_status("❌ 0 downloadable videos found (Blocked?)")
            # Show bypass dialog if we had raw URLs but they were all CDN thumbnails
            if urls:
                from error_handler import ErrorInfo, ErrorSeverity
                err_info = ErrorInfo(
                    severity=ErrorSeverity.ERROR,
                    headline="Access denied (403)",
                    detail=(
                        "The scanner found links on this page, but the target server "
                        "blocked yt-dlp from processing them. You may need to bypass "
                        "bot protection."
                    ),
                )
                self._show_error_or_bypass(err_info)
            return

        # Show the first URL in the bar for reference
        self._url_bar.set_url(video_urls[0])

        # Auto-fetch ALL video URLs into the download queue sequentially
        total = len(video_urls)
        self._status_bar.set_status(
            f"🔍  Found {total} video{'s' if total != 1 else ''} — fetching metadata…"
        )

        # Clear queue and start a sequential batch fetch
        self._index_to_card.clear()
        self._key_to_card.clear()
        self._queue_panel.clear()
        self._dl_bar.set_count(0, 0)

        self._batch_fetch_queue: list = list(video_urls)
        self._batch_fetch_total: int  = total
        self._batch_fetch_done:  int  = 0
        self._batch_mode:        bool = True

        self._fetch_next_in_batch()

    def _on_scrape_error(self, message: str) -> None:
        self._status_bar.stop_indeterminate()
        self._status_bar.set_cancel_visible(False)
        self._status_bar.set_status(t("scraper_error", message=message[:120]))
        
        # If the scraper hits a 403/Cloudflare/Bot block on the base page
        msg_lower = message.lower()
        if "403" in msg_lower or "429" in msg_lower or "bot" in msg_lower or "forbidden" in msg_lower:
            err_info = ErrorInfo(
                severity=ErrorSeverity.ERROR,
                headline="Access denied (403)",
                detail="The target website blocked the scanner. You must bypass bot protection to continue.",
                raw=message
            )
            self._show_error_or_bypass(err_info)

    # ──────────────────────────────────────────────────────────────────────────
    # Search flow
    # ──────────────────────────────────────────────────────────────────────────

    def _on_search(self, query: str) -> None:
        query = query.strip()
        if not query:
            return

        if self._search_worker and self._search_worker.isRunning():
            self._search_worker.cancel()
            self._search_worker.wait(500)
        platform = self._search_panel.get_platform()

        # All platforms (YouTube, Spotify via proxy, Both) are now supported
        self._search_panel.set_searching(True)
        self._status_bar.set_cancel_visible(True)

        self._search_worker = SearchWorker(
            query=query,
            platform=platform,
            youtube_max_results=self._cfg.youtube_max_results,
            spotify_max_results=self._cfg.spotify_max_results,
            cookies_file=self._cfg.cookies_file or None,
            spotify_client_id=self._cfg.spotify_client_id,
            spotify_client_secret=self._cfg.spotify_client_secret,
            parent=self,
        )
        self._search_worker.result_ready.connect(self._on_search_result)
        self._search_worker.status_msg.connect(self._status_bar.set_status)
        self._search_worker.finished.connect(self._on_search_finished)
        self._search_worker.error.connect(self._on_search_error)
        self._search_worker.start()

    def _on_search_result(self, result: SearchResult) -> None:
        card = self._search_panel.add_result(result)
        if result.thumbnail_url:
            thumb = ThumbnailWorker(
                track_index=result.result_index,
                url=result.thumbnail_url,
                parent=self,
            )
            # Route thumbnail to the search result card, not a track card
            thumb.thumbnail_ready.connect(
                lambda idx, raw, c=card: c.set_thumbnail(raw)
            )
            thumb.start()

    def _on_search_finished(self, count: int) -> None:
        self._search_panel.set_searching(False)
        self._search_panel.set_result_count(count)
        self._status_bar.set_cancel_visible(False)

    def _on_search_error(self, message: str) -> None:
        self._search_panel.set_searching(False)
        self._status_bar.set_cancel_visible(False)
        self._status_bar.set_status(t("search_error", message=message[:120]))

    def _on_add_search_result_to_queue(self, result: SearchResult) -> None:
        """
        Add a search result directly to the download queue as a TrackCard
        and switch to the Queue tab.
        """
        # Assign the next available queue index
        existing = self._queue_panel.get_all_cards()
        next_index = (max(c.queue_index for c in existing) + 1) if existing else 1

        card = self._queue_panel.add_card(
            index=next_index,
            title=result.title,
            artist=result.artist,
            duration=result.duration_str,
            platform=result.platform.name.lower(),
            thumbnail_url=result.thumbnail_url,
            track_url=result.url,
            album=result.album,
        )
        self._index_to_card[next_index] = card
        self._update_dl_bar()

        if result.thumbnail_url:
            thumb = ThumbnailWorker(
                track_index=next_index,
                url=result.thumbnail_url,
                parent=self,
            )
            thumb.thumbnail_ready.connect(self._on_thumbnail_ready)
            thumb.start()

        # Switch to Queue tab
        self.switchTo(self._queue_wrapper)
        self._status_bar.set_status(t("added_to_queue", title=result.title[:60]))

    def _on_search_drill_down(self, result: SearchResult) -> None:
        """
        Called when the user clicks "Browse" on an Album / Playlist / Artist /
        Channel card in the search panel.  Switches to the Queue tab and starts
        a FetchWorker for that result's URL so all the tracks load.
        """
        url = result.url
        if not url:
            return
        self._url_bar.set_url(url)
        self.switchTo(self._queue_wrapper)
        self._on_fetch(url)

    # ──────────────────────────────────────────────────────────────────────────
    # Clipboard monitor
    # ──────────────────────────────────────────────────────────────────────────

    def _on_clipboard_url(self, url: str) -> None:
        """
        Called when ClipboardWorker detects a new supported URL.
        Populates the URL bar and shows a brief status message.
        The user still has to press Fetch — we do not auto-fetch.
        """
        self._url_bar.set_url(url)
        self._status_bar.set_status(t("clipboard_url_detected"))
        # Switch to Queue tab so the user sees the populated URL bar
        self.switchTo(self._queue_wrapper)

    # ──────────────────────────────────────────────────────────────────────────
    # Update checker
    # ──────────────────────────────────────────────────────────────────────────

    def _on_update_available(self, info: ReleaseInfo) -> None:
        self._update_banner.show_release(info)

    # ──────────────────────────────────────────────────────────────────────────
    # History actions
    # ──────────────────────────────────────────────────────────────────────────

    def _on_redownload(self, record: DownloadRecord) -> None:
        """Re-add a history record's source URL to the queue."""
        self._url_bar.set_url(record.url)
        self.switchTo(self._queue_wrapper)
        self._on_fetch(record.url)

    def _on_open_folder(self, record: DownloadRecord) -> None:
        """Open the directory containing the downloaded file."""
        path = Path(record.output_path)
        folder = path.parent if path.exists() else path.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

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
        pass   # options are read live from OptionsBar at download time

    def _update_dl_bar(self) -> None:
        cards    = self._queue_panel.get_all_cards()
        selected = self._queue_panel.get_selected_cards()
        self._dl_bar.set_count(len(selected), len(cards))

    def _on_settings_saved(self) -> None:
        """Apply language and UI changes after settings are saved."""
        # Update translation module and layout direction
        set_language(self._cfg.language)
        if self._cfg.language == "he":
            QApplication.setLayoutDirection(Qt.RightToLeft)
        else:
            QApplication.setLayoutDirection(Qt.LeftToRight)

        # Update visible texts we control here
        try:
            self.setWindowTitle(t("app_name"))
            self.navigationInterface.widget("queuePage").setText(t("queue"))
            self.navigationInterface.widget("searchPage").setText(t("search"))
            self.navigationInterface.widget("historyPage").setText(t("history"))
            self.navigationInterface.widget("settingsPage").setText(t("settings"))
        except Exception:
            pass

        # Refresh some panels and the download bar
        try:
            self._settings_panel.refresh()
        except Exception:
            pass
        self._options_bar.apply_config(self._cfg)
        self._update_dl_bar()

    # ──────────────────────────────────────────────────────────────────────────
    # Settings helpers
    # ──────────────────────────────────────────────────────────────────────────


    def _on_clipboard_setting_change(self, checked: bool) -> None:
        self._cfg.set("clipboard_monitor", checked)
        self._cfg.save()
        if checked:
            self._clipboard_worker.start()
        else:
            self._clipboard_worker.stop()
        self._url_bar.set_clipboard_monitor_active(checked)
        self._options_bar.apply_config(self._cfg)


    # ──────────────────────────────────────────────────────────────────────────
    # Window close
    # ──────────────────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        self._save_state()

        # Stop clipboard monitor
        if hasattr(self, "_clipboard_worker"):
            self._clipboard_worker.stop()

        # Cancel and join workers
        workers = [
            self._fetch_worker,
            self._dl_worker,
            self._search_worker,
            self._scraper_worker,
        ]
        if self._dl_worker and self._dl_worker.isRunning():
            self._engine.cancel()
        for w in workers:
            if w and w.isRunning():
                w.quit()
                w.wait(1500)

        self._db.close()
        super().closeEvent(event)
