# YTSpot Downloader

A desktop application for downloading audio and video from **YouTube**, **YouTube Music**, and **Spotify**.  
Built with Python and PySide6 (Qt6), using **yt-dlp** as its download engine, a **Fluent Design** UI powered by **QFluentWidgets**, and **Playwright** for headless browser scraping.

---

## Features at a Glance

| Feature | Details |
|---|---|
| **Platforms** | YouTube, YouTube Music, Spotify (tracks, albums, playlists, artists), generic HLS/DASH streams |
| **Audio formats** | MP3, M4A, FLAC, OPUS |
| **Audio quality** | Best (320k), High (256k), Medium (192k), Low (128k) |
| **Video formats** | MP4 (up to Best / 1080p / 720p / 480p) |
| **Batch downloads** | Up to 6 parallel threads, configurable |
| **GUI + CLI** | Full desktop UI + headless `ytspot-cli` command |
| **Search** | YouTube videos, YouTube Music (songs/albums/artists/playlists), Spotify proxy |
| **History** | SQLite-backed download log with full-text search and CSV export |
| **Post-processing** | Lyrics embed, ReplayGain, MusicBrainz tag enrichment, square thumbnail crop |
| **Anti-ban** | Random delays, rotating yt-dlp clients, SponsorBlock, retry-with-backoff |
| **Themes** | Dark, Light, OLED + custom accent colour |
| **Languages** | English, Hebrew (RTL layout) |
| **Auto-update** | GitHub Releases checker on startup |

---

## Requirements

| Requirement | Version |
|---|---|
| Python | 3.10 or newer |
| FFmpeg | Any recent version (must be on `PATH`) |
| yt-dlp | ≥ 2026.3.13 |
| Playwright | Latest (for Spotify / Channel scraping) |

### Install Dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### Install FFmpeg

**Windows (via Chocolatey):**
```bash
choco install ffmpeg
```

**Windows (manual):** Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to `PATH`.

---

## Running

### GUI (Desktop App)
```bash
python main.py
python main.py --debug    # verbose console logging
```

### CLI (Headless)
```bash
# Single track
python cli.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Playlist (all tracks)
python cli.py "https://www.youtube.com/playlist?list=PLxxxxx"

# Spotify album → YouTube match → download
python cli.py "https://open.spotify.com/album/1DFixLWuPkv3KT3TnV35m3"

# Options
python cli.py URL --format mp4 --quality 1080p --output ~/Music
python cli.py URL --audio-format flac --parallel 4 --cookies cookies.txt

# List tracks without downloading
python cli.py URL --list
```

**CLI Options:**

| Flag | Default | Description |
|---|---|---|
| `-o / --output` | `~/Downloads/YTSpot` | Output directory |
| `-f / --format` | `mp3` | `mp3` or `mp4` |
| `--audio-format` | `mp3` | `mp3`, `m4a`, `flac`, `opus` |
| `--quality` | `Best (320k)` | Audio or video quality label |
| `-j / --parallel` | `3` | Concurrent downloads (1–5) |
| `--cookies` | _(none)_ | Path to Netscape cookies.txt |
| `-l / --list` | — | List tracks; stdout is tab-separated for piping |
| `-q / --quiet` | — | Suppress progress output |
| `--debug` | — | Enable verbose logging |

After `pip install -e .`, the CLI is also available as:
```bash
ytspot-cli URL [options]
```

---

## Supported Platforms & URL Types

### Spotify (Playwright-based, headless Chromium)

| URL type | Action |
|---|---|
| `open.spotify.com/track/…` | Fetch single track metadata |
| `open.spotify.com/album/…` | Fetch all album tracks |
| `open.spotify.com/playlist/…` | Fetch all playlist tracks |
| `open.spotify.com/artist/…` | Fetch full discography (albums + singles/EPs) |

Spotify downloads work by scraping the track list headlessly, then running a `ytsearch1:Artist Title audio` YouTube query for each track via **yt-dlp**. **No Spotify API key is required.**

### YouTube Music (yt-dlp + ytmusicapi)

| URL type | Action |
|---|---|
| `music.youtube.com/watch?v=…` | Single track |
| `music.youtube.com/playlist?list=…` | Playlist |
| `music.youtube.com/browse/MPRE…` or `MPSP…` | Album |
| `music.youtube.com/browse/UC…` | Artist discography |

### YouTube (yt-dlp + Playwright for channels)

| URL type | Action |
|---|---|
| `youtube.com/watch?v=…` or `youtu.be/…` | Single video |
| `youtube.com/playlist?list=…` | Playlist |
| `youtube.com/@channel` or `/c/channel` | Full channel (Videos / Shorts / Releases / Playlists) |

### Generic / Other Sites

Any `http/https` URL is first attempted via yt-dlp's Generic extractor. If that finds nothing, the app falls back to a **Playwright page-interception** pass that captures live HLS/DASH/MP4 streams from the page's network traffic.

---

## File Organization — Output Folder Hierarchy

All files are saved under your configured **Output Directory** (default: `~/Downloads/YTSpot`).

### Solo Download (exactly 1 song/video)
```
[Output Directory]/
    Song Name.mp3
```
No subfolder. No track-number prefix. No artist in filename.

### Playlist or Album (multi-track)
```
[Output Directory]/
    [Playlist or Album Name]/
        01 - Artist Name - Song Name.mp3
        02 - Artist Name - Song Name.mp3
```

### Spotify Artist Discography
```
[Output Directory]/
    [Artist Name]/
        אלבומים/
            [Album Name]/
                01 - Song.mp3
        סינגלים ו-EP/
            Single Name.mp3
            [EP Name]/          ← only if EP has >1 track
                01 - Song.mp3
```

### YouTube Music Artist Discography
```
[Output Directory]/
    [Artist Name]/
        אלבומים/
            [Album Name]/
                01 - Song.mp3
        סינגלים וגרסאות EP/
            Single Name.mp3
        הופעות חיות/
            [Live Album]/
                01 - Song.mp3
```

### YouTube Channel
```
[Output Directory]/
    [Channel Name]/
        סרטונים/
            Video Title.mp4
        קצרים/
            Short Title.mp4
        פריטי תוכן/
            Release.mp3
        פלייליסטים/
            (playlist entries)
```

---

## Filename Convention

| Scenario | Format |
|---|---|
| Solo download | `Song Name.mp3` |
| Multi-artist playlist | `Song Name.mp3` (title only) |
| Album / Artist discography | `01 - Artist Name - Song Name.mp3` |
| Video | `Artist Name - Title.mp4` |

**Automatic filename cleaning** is applied to all titles:
- Removes parenthetical noise: `(Official Video)`, `(Lyrics)`, `(4K)`, `(Prod. by …)`
- Strips promotional suffixes: `- Official`, `- Club Edit`, `- Original Mix`
- **Preserves** meaningful variants: `(Remix)`, `(Acoustic)`, `(Live)`, `(feat. …)`

---

## Search

The built-in Search panel supports three platforms:

### YouTube Music (`ytmusicapi`)
- Songs, Albums, Artists, Playlists — all in one combined results view
- Results arrive incrementally (section by section) while searching
- No authentication or API key needed

### YouTube (yt-dlp)
- Videos, Playlists, Channels
- Uses direct YouTube search-results page with type-filter tokens for accurate playlist/channel results

### Spotify
- Requires a self-hosted Spotify search proxy (see `SPOTIFY_PROXY_API.md`) **or** Spotify API credentials in Settings

Results show thumbnail, duration, view count, artist, and platform badge. Click to load directly into the download queue.

---

## Batch Import

Paste multiple URLs directly into the URL bar, or load a `.txt` file:

**Text file format:**
```
# My download batch – 2025-06-01
https://www.youtube.com/watch?v=dQw4w9WgXcQ
https://open.spotify.com/album/1DFixLWuPkv3KT3TnV35m3
https://music.youtube.com/playlist?list=RDCLAK5uy_k
```

- Lines starting with `#` are comments
- URLs can be mixed (YouTube + Spotify + YouTube Music) in any order
- Duplicates are automatically removed

The **Clipboard Monitor** (optional) watches your clipboard continuously and auto-adds any recognised URL it detects.

---

## Post-Processing Pipeline

Each step runs sequentially after yt-dlp finishes. All steps are individually guarded by a config flag and are **non-fatal** — a failure in one step is logged as a warning without cancelling the batch.

| Step | Config Flag | Default | Module |
|---|---|---|---|
| Custom thumbnail embed (Spotify hi-res art) | `embed_thumbnail` | **on** | `core/thumbnail_cropper.py` |
| Square thumbnail crop (1:1) | `square_thumbnails` | **on** | `core/thumbnail_cropper.py` |
| Metadata embedding (ID3/MP4 tags) | `embed_metadata` | **on** | yt-dlp FFmpegMetadata |
| MusicBrainz tag enrichment | `musicbrainz_enabled` | **on** | `core/musicbrainz_enricher.py` |
| Lyrics embedding | `lyrics_enabled` | off | `core/lyrics_embedder.py` |
| ReplayGain loudness analysis | `replay_gain_enabled` | off | `core/replay_gain.py` |
| SponsorBlock segment removal | `sponsorblock_enabled` | off | yt-dlp SponsorBlock PP |

---

## Authentication — YouTube Cookie Wizard

To bypass YouTube age-gates and bot-protection:

1. Go to **Settings → Authentication → Open Login Wizard**.
2. A browser window opens. Log into YouTube normally.
3. Close the browser. Cookies are saved to `%APPDATA%\.ytspot\app_cookies.txt`.
4. The app picks up cookies automatically on the next download — no restart required.

> **Note:** Cookies expire after browser session rotation. If downloads fail with "Sign in" errors, re-run the wizard.

**Alternative:** Use the **Get cookies.txt LOCALLY** Chrome extension to export a `cookies.txt` file manually, then set it in Settings → Authentication.

---

## Download Engine & Anti-Ban Strategy

### yt-dlp Client Strategy
- **Primary clients**: `android_vr`, `web_safari`, `tv_downgraded`
- **Avoided clients**: `mweb`, `web` (require GVS PO Tokens / JavaScript challenge solvers)
- **Retry policy**: Up to 3 automatic retries with exponential backoff (1s → 2s → 4s) for transient errors (HTTP 429, 503, timeouts, DNS failures)
- **Permanent errors** (private video, geo-block, DMCA) are never retried

### Anti-Ban Measures
| Measure | Default |
|---|---|
| Random delay between downloads | 1.5–4.0 seconds (configurable) |
| Staggered batch start | Yes (prevents burst detection) |
| User-agent rotation | Enabled |
| Max parallel downloads | 3 (configurable 1–6) |

### Filtered Log Noise
Terminal warnings like `Signature solving failed` and `n challenge solving failed` are **suppressed by design** — they are internal yt-dlp retry messages that do not indicate actual failures. Only genuine errors (access denied, video unavailable) are shown to the user.

---

## Settings

All settings are stored in:
- **Windows**: `%APPDATA%\.ytspot\config.json`
- **macOS/Linux**: `~/.ytspot/config.json`

### General Settings

| Setting | Default | Description |
|---|---|---|
| `output_dir` | `~/Downloads/YTSpot` | Root save directory |
| `media_format` | `mp3` | Default format (`mp3` / `mp4`) |
| `audio_quality` | `Best (320k)` | Audio bitrate target |
| `video_quality` | `1080p` | Video resolution cap |
| `audio_format` | `mp3` | Audio codec (`mp3`, `m4a`, `flac`, `opus`) |
| `embed_thumbnail` | `true` | Embed cover art into audio/video file |
| `embed_metadata` | `true` | Embed ID3/MP4 metadata tags |
| `playlist_subfolders` | `true` | Organise playlist downloads into named subfolders |
| `playlist_index_prefix` | `true` | Prefix filenames with `01 -`, `02 -`, etc. |
| `duplicate_action` | `warn` | On duplicate file: `skip`, `warn`, or `overwrite` |
| `language` | `en` | UI language: `en` (English) or `he` (Hebrew / RTL) |
| `theme` | `dark` | UI theme: `dark`, `light`, or `oled` |
| `accent_color` | `#F5A623` | Custom accent hex colour |

### Authentication Settings

| Setting | Default | Description |
|---|---|---|
| `cookies_file` | _(empty)_ | Path to a Netscape-format `cookies.txt` |
| `cookies_browser` | _(empty)_ | Live browser to extract cookies from (e.g. `chrome`) |

### Advanced / Post-Processing Settings

| Setting | Default | Description |
|---|---|---|
| `square_thumbnails` | `true` | Crop embedded art to 1:1 square |
| `musicbrainz_enabled` | `true` | Enrich tags via MusicBrainz API |
| `lyrics_enabled` | `false` | Auto-fetch and embed lyrics after download |
| `replay_gain_enabled` | `false` | Run ReplayGain loudness normalisation |
| `sponsorblock_enabled` | `false` | Remove non-music YouTube segments |
| `sponsorblock_categories` | _(see below)_ | Categories to remove |

Default SponsorBlock categories: `music_offtopic`, `sponsor`, `intro`, `outro`, `selfpromo`.

### Network & Performance Settings

| Setting | Default | Description |
|---|---|---|
| `max_parallel_downloads` | `3` | Concurrent download threads (1–6) |
| `download_delay_range` | `[1.5, 4.0]` | Random sleep range between downloads (seconds) |
| `randomize_user_agent` | `true` | Rotate browser headers |
| `youtube_proxy_url` | _(empty)_ | HTTP/SOCKS proxy for yt-dlp |
| `proxy_server_url` | `http://localhost:8000` | Self-hosted Spotify search proxy |
| `check_updates` | `true` | Check GitHub for new releases on startup |

### Clipboard & System Tray Settings

| Setting | Default | Description |
|---|---|---|
| `clipboard_monitor` | `false` | Watch clipboard and auto-add recognised URLs |
| `tray_on_close` | `false` | Minimise to system tray instead of quitting |
| `global_hotkeys_enabled` | `false` | Register OS-level keyboard shortcuts |

---

## Download History

Every completed download is recorded in `%APPDATA%\.ytspot\downloads.db` (SQLite).

**History Panel features:**
- View the last 500 downloads (newest first)
- **Full-text search** by title or artist (FTS5 index)
- Delete individual records
- **Export to CSV** (UTF-8 with BOM for Excel compatibility)
- Open the output file directly from the history row

The database includes automatic integrity checking on startup. If corruption is detected, the file is renamed with a timestamp backup and a fresh database is created.

---

## Auto-Update Checker

On startup, the app queries the GitHub Releases API (`api.github.com/repos/cdtauman/ytspot_downloader/releases/latest`) and compares the remote version against the installed version using **semantic versioning** (SemVer).

- An **update banner** appears at the top of the window when a newer version is found
- Pre-releases are skipped by default
- Network failures are silently absorbed — a failed update check never crashes or shows an error
- The check runs in a background thread and does not block startup

---

## Architecture

### Layer Diagram

```
UI (app_window.py, panels/, components/)
    ↓  Qt Signals
Workers (ui/workers/)
    ↓  Python calls
Controllers (ui/controllers/)
    ↓  Python calls
Core (downloader.py, scraper.py, search_engine.py, …)
    ↓  imports
Utils (yt_dlp_opts.py, spotify_resolver.py, logger.py, …)
```

**Strict rule:** No layer imports anything above it. `core/` and `utils/` have **zero GUI imports**.

### Core Modules

| Module | Responsibility |
|---|---|
| `core/downloader.py` | yt-dlp download engine — `DownloadRequest` / `DownloadProgress` / `DownloadEngine` |
| `core/playlist_parser.py` | URL classifier + metadata extractor (no download) → `TrackMeta` / `ParseResult` |
| `core/scraper.py` | Platform-isolated Playwright scrapers for Spotify, YTM, YouTube channels |
| `core/download_orchestrator.py` | Thread-pool batch manager — parallelism, cancellation, progress aggregation |
| `core/search_engine.py` | Unified search: YTM (ytmusicapi), YouTube (yt-dlp), Spotify proxy |
| `core/history_db.py` | SQLite download history — insert, search (FTS5), export CSV |
| `core/batch_importer.py` | Parse URLs from text files or pasted multi-line text |
| `core/retry_policy.py` | Exponential-backoff retry wrapper for transient download failures |
| `core/update_checker.py` | GitHub Releases API version checker (SemVer comparison) |
| `core/lyrics_embedder.py` | Fetch and embed lyrics using `syncedlyrics` |
| `core/musicbrainz_enricher.py` | Enrich ID3/MP4 tags via MusicBrainz API |
| `core/replay_gain.py` | ReplayGain loudness analysis and embedding |
| `core/thumbnail_cropper.py` | Download hi-res cover art, optionally crop to 1:1 square (Pillow) |
| `core/hls_downloader.py` | FFmpeg-based downloader for HLS/DASH/direct-stream URLs |
| `core/universal_extractor.py` | Playwright network-interception fallback for generic sites |
| `core/duplicate_checker.py` | Check for already-downloaded files before queueing |
| `core/queue_persistence.py` | Serialise/restore the download queue across restarts |
| `core/progress_estimator.py` | ETA and speed smoothing for the progress bar |
| `core/parallel_enricher.py` | Run post-processing enrichers concurrently per-track |
| `core/playlist_sync.py` | Sync a watched playlist/album (re-check for new tracks) |
| `core/offline_monitor.py` | Background thread that watches network availability |
| `core/cookie_wizard.py` | Playwright browser login wizard (runs in QThread) |
| `core/services.py` | `ServiceContainer` — DI container for shared backend singletons |

### UI Modules

| Module | Responsibility |
|---|---|
| `ui/app_window.py` | Main `AppWindow` — navigation, error dialogs, wizard launch |
| `ui/theme_manager.py` | Dark/Light/OLED themes + custom accent colour |
| `ui/i18n.py` | Translations (English / Hebrew) + RTL layout switching |
| `ui/panels/url_bar.py` | URL input bar with batch-paste detection |
| `ui/panels/options_bar.py` | Format / quality selector above the queue |
| `ui/panels/queue_panel.py` | Download queue with progress cards |
| `ui/panels/search_panel.py` | Multi-platform search UI |
| `ui/panels/history_panel.py` | SQLite download history viewer |
| `ui/panels/settings_panel.py` | All user-configurable settings |
| `ui/panels/converter_panel.py` | Local audio file format converter |
| `ui/panels/status_bar.py` | Bottom status bar (speed, ETA, messages) |
| `ui/components/track_card.py` | One card per queued track (thumbnail, progress bar, controls) |
| `ui/components/search_result_card.py` | One card per search result |
| `ui/components/history_row.py` | One row per history record |
| `ui/components/update_banner.py` | Top-of-window update notification |
| `ui/components/offline_banner.py` | Network-offline warning banner |
| `ui/controllers/download_controller.py` | Orchestrates batch dispatch, folder routing, error handling |
| `ui/controllers/fetch_controller.py` | Controls URL fetching / playlist parsing |
| `ui/controllers/search_controller.py` | Controls search lifecycle and result delivery |
| `ui/workers/download_worker.py` | QThread wrapper — calls orchestrator, emits Qt signals |
| `ui/workers/fetch_worker.py` | QThread wrapper for playlist parsing |
| `ui/workers/search_worker.py` | QThread wrapper for search engine |
| `ui/workers/clipboard_worker.py` | Background clipboard monitor |
| `ui/workers/thumbnail_worker.py` | Async thumbnail loader for cards |
| `ui/workers/update_worker.py` | Background update checker |
| `ui/workers/scraper_worker.py` | QThread wrapper for Playwright scraping |
| `ui/workers/offline_monitor.py` | QThread wrapper for network monitor |

### Utils Modules

| Module | Responsibility |
|---|---|
| `utils/yt_dlp_opts.py` | Shared yt-dlp option builders (base, parse, download, search) |
| `utils/spotify_resolver.py` | Resolve Spotify track URLs → YouTube search matches |
| `utils/ytm_scraper.py` | YouTube Music artist discography fetcher (ytmusicapi) |
| `utils/logging_config.py` | Structured logging setup (file + console handlers) |
| `utils/logger.py` | `SilentLogger` class for yt-dlp (suppresses noise) |
| `utils/cookie_validator.py` | Detect expired or malformed cookies.txt files |
| `utils/artwork_cleaner.py` | Normalise and upgrade thumbnail/cover URLs per platform |
| `utils/paths.py` | App data directory helpers (`~/.ytspot/`) |
| `utils/time_format.py` | `seconds_to_str()` — convert raw seconds to `"M:SS"` / `"H:MM:SS"` |
| `utils/network_probe.py` | Lightweight connectivity check |
| `utils/impersonate.py` | curl-cffi impersonation target detection |

---

## Project File Layout

```
ytspot_downloader-main/
├── main.py                         # GUI entry point
├── cli.py                          # Headless CLI entry point
├── config.py                       # AppConfig dataclass + JSON persistence (v3.1)
├── config_migrate.py               # Schema migration for older config.json versions
├── error_handler.py                # Error classification and ErrorInfo dataclass
├── pyproject.toml                  # Package metadata + entry points (ytspot / ytspot-cli)
├── requirements.txt                # Python dependencies
│
├── core/                           # Backend — zero GUI imports
│   ├── downloader.py               # yt-dlp download engine
│   ├── playlist_parser.py          # URL classifier + metadata extractor
│   ├── scraper.py                  # Playwright scrapers (Spotify, YTM, YouTube)
│   ├── download_orchestrator.py    # Thread-pool batch manager
│   ├── search_engine.py            # Multi-platform search engine
│   ├── history_db.py               # SQLite download history
│   ├── batch_importer.py           # Multi-URL text/file importer
│   ├── retry_policy.py             # Retry-with-backoff logic
│   ├── update_checker.py           # GitHub Releases version checker
│   ├── lyrics_embedder.py          # Lyrics fetch + embed
│   ├── musicbrainz_enricher.py     # MusicBrainz tag enrichment
│   ├── replay_gain.py              # ReplayGain analysis + embedding
│   ├── thumbnail_cropper.py        # Cover art download + 1:1 crop
│   ├── hls_downloader.py           # HLS/DASH/direct-stream via FFmpeg
│   ├── universal_extractor.py      # Playwright network-interception fallback
│   ├── duplicate_checker.py        # Pre-queue duplicate detection
│   ├── queue_persistence.py        # Queue save/restore across restarts
│   ├── progress_estimator.py       # ETA + speed smoothing
│   ├── parallel_enricher.py        # Concurrent post-processing runner
│   ├── playlist_sync.py            # Playlist/album sync (new track detection)
│   ├── offline_monitor.py          # Network availability monitor
│   ├── cookie_wizard.py            # Playwright login wizard
│   └── services.py                 # ServiceContainer (DI)
│
├── ui/                             # Frontend — Qt/PySide6
│   ├── app_window.py               # Main AppWindow
│   ├── theme_manager.py            # Dark/Light/OLED + accent colour
│   ├── i18n.py                     # Translations + RTL support
│   ├── panels/                     # Full-screen panels
│   │   ├── url_bar.py
│   │   ├── options_bar.py
│   │   ├── queue_panel.py
│   │   ├── search_panel.py
│   │   ├── history_panel.py
│   │   ├── settings_panel.py
│   │   ├── converter_panel.py
│   │   └── status_bar.py
│   ├── components/                 # Reusable widgets
│   │   ├── track_card.py
│   │   ├── search_result_card.py
│   │   ├── history_row.py
│   │   ├── update_banner.py
│   │   └── offline_banner.py
│   ├── controllers/                # Business-logic layer between UI and core
│   │   ├── download_controller.py
│   │   ├── fetch_controller.py
│   │   └── search_controller.py
│   └── workers/                    # QThread background workers
│       ├── download_worker.py
│       ├── fetch_worker.py
│       ├── search_worker.py
│       ├── clipboard_worker.py
│       ├── thumbnail_worker.py
│       ├── update_worker.py
│       ├── scraper_worker.py
│       └── offline_monitor.py
│
├── utils/                          # Shared helpers — zero GUI imports
│   ├── yt_dlp_opts.py
│   ├── spotify_resolver.py
│   ├── ytm_scraper.py
│   ├── logging_config.py
│   ├── logger.py
│   ├── cookie_validator.py
│   ├── artwork_cleaner.py
│   ├── paths.py
│   ├── time_format.py
│   ├── network_probe.py
│   └── impersonate.py
│
└── tests/                          # Pytest test suite
    ├── test_core.py
    ├── test_p0_gates.py
    ├── test_orchestrator.py
    ├── test_history_db_resilience.py
    ├── test_parallel_enricher.py
    ├── test_progress_estimator.py
    ├── test_queue_persistence.py
    ├── test_retry_policy.py
    └── test_spotify_match_scorer.py
```

---

## Running Tests

```bash
pip install -e ".[dev]"
pytest
```

---

## Troubleshooting

**FFmpeg not found**  
Install FFmpeg and ensure it is on `PATH`. The app shows a warning on startup.

**YouTube "Sign in" errors**  
Run the Cookie Wizard: Settings → Authentication → Open Login Wizard. Cookies may have expired after a browser session rotation.

**Spotify not downloading**  
Spotify downloads route through YouTube search. If a song title or artist name is uncommon, the match may fail. Download the YouTube URL directly for guaranteed results.

**Download stops after 1–2 tracks**  
Usually a YouTube rate-limit (HTTP 429). The app has built-in retries and configurable sleep delays. Re-running the Cookie Wizard often resolves persistent cases.

**Signature / n-challenge errors in terminal**  
These are suppressed internal yt-dlp retry messages — not real failures. They appear only with `--debug`. Install `pip install quickjs` if they appear as actual errors.

**Chrome cookie lock error**  
Close Chrome completely before extracting cookies. If the problem persists, use the Cookie Wizard (which bypasses Chrome's DPAPI encryption entirely).

**Generic / external site not downloading**  
The app will automatically fall back to Playwright network interception. If that also fails, the site may use DRM or require authentication the app cannot bypass.

---

## Additional Documentation

| File | Description |
|---|---|
| `SPOTIFY_PROXY_API.md` | API contract for the self-hosted Spotify search proxy server |
| `PROJECT_STRUCTURE.md` | Auto-generated architecture snapshot (may be slightly stale) |
| `user_guide_hebrew.md` | Full Hebrew user guide (מדריך משתמש בעברית) |
