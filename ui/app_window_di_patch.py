"""
app_window_di_patch.py  –  Dependency injection patch for AppWindow
====================================================================
Apply these changes to ui/app_window.py:

1. Add import:
       from core.services import ServiceContainer

2. Replace the __init__ signature and the first few lines.

The rest of __init__ (panel building, signal wiring, etc.) stays the same.
Only the "where do singletons come from" part changes.
"""

# ──────────────────────────────────────────────────────────────────────────────
# OLD __init__ (first ~15 lines):
# ──────────────────────────────────────────────────────────────────────────────
#
#   def __init__(self, config: AppConfig, db: HistoryDB) -> None:
#       super().__init__()
#       self._cfg    = config
#       self._db     = db
#       self._engine = DownloadEngine()       # ← hard-coded construction
#       self._theme  = ThemeManager(config)
#       ...
#
# ──────────────────────────────────────────────────────────────────────────────
# NEW __init__:
# ──────────────────────────────────────────────────────────────────────────────

def __init__(
    self,
    config: "AppConfig",
    services: "ServiceContainer",
    # Backward compat: accept db= kwarg for existing callers
    db: "Optional[HistoryDB]" = None,
) -> None:
    super().__init__()

    # ── Unpack services ───────────────────────────────────────────────
    self._cfg    = config
    self._svc    = services
    self._db     = services.db if db is None else db
    self._engine = services.engine
    self._theme  = ThemeManager(config)

    # ── Everything below is UNCHANGED from the original __init__ ──────
    # Worker references
    self._fetch_worker:   Optional[FetchWorker]   = None
    self._dl_worker:      Optional[DownloadWorker] = None
    self._search_worker:  Optional[SearchWorker]  = None
    self._scraper_worker: Optional[ScraperWorker] = None

    # Card routing
    self._index_to_card: dict[int,  "TrackCard"] = {}
    self._key_to_card:   dict[str,  "TrackCard"] = {}
    self._card_progress: dict[str,  float]       = {}

    # Pause state
    self._paused_requests: dict[str, DownloadRequest] = {}

    # Last fetch metadata
    self._last_playlist_title: str                = ""
    self._last_url_kind:       Optional[UrlKind]  = None

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


# ──────────────────────────────────────────────────────────────────────────────
# ALSO UPDATE closeEvent — replace self._db.close() with:
#     self._svc.close()
# This closes the DB (and any future closeable services) in one call.
# ──────────────────────────────────────────────────────────────────────────────
