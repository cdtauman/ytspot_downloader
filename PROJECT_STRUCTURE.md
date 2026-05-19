# YTSpot Downloader — Project Structure

## Layer Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        UI Layer (PySide6/Qt6)                    │
│  app_window.py · panels/ · components/                          │
├─────────────────────────────────────────────────────────────────┤
│                    Worker Threads (QThread)                       │
│  ui/workers/ — bridge between UI signals and the core           │
├─────────────────────────────────────────────────────────────────┤
│                       Core Layer (pure Python)                   │
│  downloader.py · playlist_parser.py · core/                     │
├─────────────────────────────────────────────────────────────────┤
│                    Utils & Config (pure Python)                   │
│  utils/ · config.py · error_handler.py                          │
└─────────────────────────────────────────────────────────────────┘
```

**Strict rule:** each layer may only import from the layer(s) below it. No layer imports anything from the UI or Qt. `downloader.py`, `playlist_parser.py`, and all of `core/` have **zero GUI imports** and can be used headlessly.

---

## Annotated File Tree

```
ytspot_downloader/
│
├── main.py                    Entry point. Creates QApplication, loads config,
│                              applies theme, shows AppWindow, starts event loop.
│
├── config.py                  AppConfig — typed, persistent user preferences.
│                              Reads/writes ~/.ytspot/config.json atomically.
│                              23 properties: output dir, format, quality,
│                              theme, language, cookies, proxy URL, etc.
│
├── error_handler.py           Converts raw exceptions into structured ErrorInfo
│                              objects with severity (WARNING / ERROR / CRITICAL)
│                              and user-readable headlines. Also probes network
│                              connectivity for offline detection.
│
├── downloader.py              Core download engine. Accepts a DownloadRequest,
│                              calls yt-dlp, fires granular DownloadProgress
│                              callbacks, and writes ID3/MP4 tags via mutagen.
│                              Supports audio (MP3/M4A/FLAC/Opus) and video (MP4).
│
├── playlist_parser.py         URL classifier and metadata extractor. Resolves
│                              YouTube/YT-Music/Spotify playlist URLs into lists
│                              of TrackMeta without downloading any media.
│                              Emits items incrementally via on_item callbacks.
│
├── requirements.txt           pip dependency list with version constraints.
│
├── test_yt.py                 Smoke test: verifies yt-dlp + JS runtime detection.
├── test_integration.py        Integration tests for key workflows.
│
├── SPOTIFY_PROXY_API.md       API contract for the optional Spotify search proxy.
│
├── core/
│   ├── search_engine.py       SearchEngine — queries YouTube (via yt-dlp's
│   │                          ytsearch extractor) or a Spotify proxy server.
│   │                          PageScraper — fetches any webpage and extracts
│   │                          all recognisable media URLs (3-phase: yt-dlp →
│   │                          BeautifulSoup → same-domain link following).
│   │
│   ├── history_db.py          SQLite-backed download history. FTS5 full-text
│   │                          search, thread-safe WAL journal, CSV export.
│   │                          Stores DownloadRecord objects.
│   │
│   ├── batch_importer.py      Parses a pasted string or text file into a list
│   │                          of validated, deduplicated media URLs.
│   │
│   └── update_checker.py      Checks the GitHub Releases API for a newer
│                              version; emits ReleaseInfo with changelog.
│
├── utils/
│   ├── spotify_resolver.py    Converts a Spotify URL (track/album/playlist)
│   │                          into YouTube search strings via the Spotify Embed
│   │                          API. No OAuth or API key required.
│   │
│   ├── time_format.py         seconds_to_str() — single shared duration
│   │                          formatter used by playlist_parser, history_db,
│   │                          and search_engine.
│   │
│   └── impersonate.py         Shared curl_cffi / ImpersonateTarget detection.
│                              Imported by downloader.py and playlist_parser.py
│                              to avoid duplicating the try/except import block.
│
└── ui/
    ├── app_window.py          Main FluentWindow. Owns all panels, all workers,
    │                          and the shared backend engines. Connects signals
    │                          to slots. Implements closeEvent to cleanly shut
    │                          down all background threads on exit.
    │
    ├── theme_manager.py       Applies dark / light / OLED QSS themes and the
    │                          amber (#F5A623) accent colour via QFluentWidgets.
    │
    ├── i18n.py                Translation dictionary for English and Hebrew.
    │                          t("key") returns the translated string. RTL layout
    │                          is applied at startup for Hebrew.
    │
    ├── panels/
    │   ├── url_bar.py         URL input field with Fetch Info, Paste, Batch
    │   │                      Import, and Scrape Page buttons.
    │   │
    │   ├── queue_panel.py     Scrollable card stack of queued tracks. Supports
    │   │                      select-all, deselect-all, and per-card delete.
    │   │
    │   ├── options_bar.py     Format / quality selectors: media type (audio /
    │   │                      video), audio codec, bitrate, video resolution.
    │   │
    │   ├── search_panel.py    YouTube and Spotify search tabs with auto-complete
    │   │                      input and paginated result list.
    │   │
    │   ├── history_panel.py   Download history viewer. Full-text search,
    │   │                      CSV export, per-row and bulk delete.
    │   │
    │   ├── settings_panel.py  Settings forms: appearance (theme, language),
    │   │                      output folder, cookies, proxy server URL.
    │   │
    │   └── status_bar.py      Bottom status strip: status messages, progress
    │                          bar, Download Selected button, cancel button.
    │
    ├── components/
    │   ├── track_card.py      Visual card for one queued track. Shows title,
    │   │                      duration, thumbnail, per-track progress bar,
    │   │                      download and delete buttons.
    │   │
    │   ├── search_result_card.py  Card for one search result: thumbnail,
    │   │                          title, artist, duration, add-to-queue button.
    │   │
    │   ├── history_row.py     Single row in the history table: title, artist,
    │   │                      file size, date, open-file and delete buttons.
    │   │
    │   ├── update_banner.py   Dismissible banner shown when a newer release is
    │   │                      found. Shows version and release notes preview.
    │   │
    │   └── browser_window.py  Embedded Chromium (QtWebEngine) window for
    │                          solving Cloudflare / Turnstile / sign-in challenges.
    │                          Saves the resulting cookies + HTML so the
    │                          authenticated session is reused on subsequent fetches.
    │
    └── workers/
        ├── fetch_worker.py    QThread — calls PlaylistParser to resolve a URL
        │                      into TrackMeta list; emits item_ready per track.
        │
        ├── download_worker.py QThread — calls DownloadEngine.download();
        │                      marshals DownloadProgress callbacks to Qt signals.
        │
        ├── search_worker.py   QThread — calls SearchEngine; emits result_ready
        │                      per SearchResult for incremental UI population.
        │
        ├── scraper_worker.py  QThread — calls PageScraper; emits url_found
        │                      per discovered media URL.
        │
        ├── thumbnail_worker.py  QThread — fire-and-forget image fetcher;
        │                        loads thumbnail bytes and emits loaded signal.
        │
        ├── clipboard_worker.py  QObject on main thread, driven by QTimer.
        │                        Polls clipboard every 800 ms; emits url_detected
        │                        when a supported media URL is copied.
        │
        └── update_worker.py   QThread — checks GitHub Releases API at startup;
                               emits release_found if a newer version exists.
```

---

## Key Data Types

| Type | Module | Purpose |
|------|--------|---------|
| `AppConfig` | `config.py` | 23-property config object; persists to `~/.ytspot/config.json` |
| `TrackMeta` | `playlist_parser.py` | One track's metadata (title, artist, URL, duration, thumbnail) |
| `ParseResult` | `playlist_parser.py` | Full result of PlaylistParser.parse(): list of TrackMeta + summary |
| `DownloadRequest` | `downloader.py` | Parameters for one download job (URL, format, quality, callbacks) |
| `DownloadProgress` | `downloader.py` | Live progress snapshot (status, bytes, speed, eta, fraction) |
| `SearchResult` | `core/search_engine.py` | One search result (title, artist, URL, duration, views) |
| `DownloadRecord` | `core/history_db.py` | One history entry as stored in SQLite |
| `ErrorInfo` | `error_handler.py` | Structured error with severity, headline, detail, raw message |
| `ReleaseInfo` | `core/update_checker.py` | GitHub release metadata (version, URL, changelog) |

---

## Worker Thread Table

| Worker | Thread model | Signals emitted | Cancellable |
|--------|-------------|-----------------|-------------|
| `FetchWorker` | `QThread` | `item_ready(TrackMeta)`, `finished(ParseResult)`, `error(str)` | Yes — calls `PlaylistParser.cancel()` |
| `DownloadWorker` | `QThread` | `progress(DownloadProgress)`, `finished(DownloadProgress)` | Yes — calls `DownloadEngine.cancel()` |
| `SearchWorker` | `QThread` | `result_ready(SearchResult)`, `finished()`, `error(str)` | Yes — calls `SearchEngine.cancel()` |
| `ScraperWorker` | `QThread` | `url_found(str)`, `finished(list[str])`, `error(str)` | Yes — calls `PageScraper.cancel()` |
| `ThumbnailWorker` | `QThread` | `loaded(bytes)` | No (fire-and-forget) |
| `ClipboardWorker` | `QObject` + `QTimer` | `url_detected(str)` | Yes — call `stop()` |
| `UpdateWorker` | `QThread` | `release_found(ReleaseInfo)` | No (one-shot at startup) |

All workers are created in `AppWindow.__init__()` and their running instances are signalled to stop inside `AppWindow.closeEvent()` before the window closes.

---

## Known Limitations

- **Spotify downloads route through YouTube.** The app searches YouTube for the track title + artist and downloads the best match. Accuracy depends on the search result; there is no direct Spotify audio access.
- **Spotify search requires a proxy server.** The in-app Spotify search tab only works if you deploy your own proxy (see `SPOTIFY_PROXY_API.md`) and configure its URL in Settings.
- **Downloads are sequential.** Only one download runs at a time. Queued items wait for the current one to finish.
- **No pause / resume.** Downloads can be cancelled but not paused; a cancelled download must be restarted from the beginning.
- **No per-track format overrides.** Format and quality settings apply to all downloads in the queue simultaneously.
- **Auto-update is notification-only.** The app notifies you of a newer release but does not download or install it automatically.
