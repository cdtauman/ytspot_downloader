# YTSpot Downloader

A desktop application for downloading audio and video from YouTube, Spotify, and YouTube Music. Built with Python and PySide6 (Qt6), using **yt-dlp** as its download engine and a Fluent Design UI powered by **QFluentWidgets**.

---

## Requirements

| Requirement | Version |
|---|---|
| Python | 3.10 or newer |
| FFmpeg | Any recent version (must be on `PATH`) |
| yt-dlp | ≥ 2026.3.13 |
| Playwright | Latest (for Spotify/Channel scraping) |

Install dependencies:

```bash
pip install -r requirements.txt
playwright install chromium
```

Install FFmpeg (Windows via Chocolatey):
```bash
choco install ffmpeg
```

---

## Running

```bash
python main.py
```

---

## Project Structure

```
ytspot_downloader-main/
│
├── main.py                        # Entry point — bootstraps Qt app and AppWindow
├── config.py                      # AppConfig dataclass + JSON persistence
├── config_migrate.py              # Migrates old config.json versions to latest schema
│
├── core/
│   ├── downloader.py              # Core yt-dlp download engine (DownloadRequest/Progress)
│   ├── scraper.py                 # Platform-isolated headless Playwright scraper (main)
│   ├── cookie_wizard.py           # Playwright browser login wizard (runs in QThread)
│   ├── duplicate_checker.py       # Detects already-downloaded files before queueing
│   ├── lyrics_embedder.py         # Fetches and embeds lyrics into audio files
│   ├── musicbrainz_enricher.py    # Tag enrichment via MusicBrainz API
│   ├── offline_monitor.py         # Background thread that monitors network availability
│   ├── replay_gain.py             # ReplayGain loudness analysis and embedding
│   └── thumbnail_cropper.py       # Crops embedded art to 1:1 square (Pillow)
│
├── ui/
│   ├── app_window.py              # Main AppWindow — routing, error dialogs, wizard launch
│   ├── panels/
│   │   ├── download_panel.py      # Main download view (URL bar, queue cards)
│   │   ├── settings_panel.py      # All user-configurable settings
│   │   ├── history_panel.py       # SQLite download history viewer
│   │   └── about_panel.py         # Version info, changelog
│   ├── components/
│   │   ├── download_card.py       # One card per track in the queue (thumbnail, progress)
│   │   └── options_bar.py         # Format/quality picker above the queue
│   └── controllers/
│       └── download_controller.py # Orchestrates batch dispatch, folder logic, error routing
│
├── utils/
│   ├── yt_dlp_opts.py             # Shared yt-dlp option builders (base, parse, download)
│   ├── ytm_scraper.py             # YouTube Music artist release fetcher
│   ├── impersonate.py             # curl-cffi impersonation target detection
│   └── logger.py                  # Shared SilentLogger for yt-dlp
│
├── ui/workers/
│   └── download_worker.py         # QThread worker — calls downloader.py, emits Qt signals
│
├── requirements.txt               # Python dependencies
├── README.md                      # This file
├── PROJECT_STRUCTURE.md           # Legacy auto-generated architecture snapshot
├── SPOTIFY_PROXY_API.md           # API contract for self-hosted Spotify search proxy
└── user_guide_hebrew.md           # Hebrew user guide
```

---

## Supported Platforms & Entry Functions

Each platform has its own **isolated** set of functions in `core/scraper.py`. Do NOT mix platform logic across these boundaries.

### Spotify (Playwright-based, headless Chromium)
| URL type | Function |
|---|---|
| `open.spotify.com/track/...` | `scrape_spotify_track()` |
| `open.spotify.com/album/...` | `scrape_spotify_album()` |
| `open.spotify.com/playlist/...` | `scrape_spotify_playlist()` |
| `open.spotify.com/artist/...` | `scrape_spotify_artist()` |

Spotify downloads work by scraping the track list in a headless browser, then constructing a `ytsearch1:Artist Title audio` YouTube query for each track, which is resolved and downloaded via **yt-dlp**. No Spotify API key or account is required.

**Spotify-specific helpers (do not use for other platforms):**
- `_ensure_high_res_spotify_image(url)` — upgrades `i.scdn.co` image URLs to 640×640 resolution.
- `_scrape_spotify_grid_on_page()` — internal scrolling grid scraper used by album/playlist/artist functions. For albums, it always applies the album header cover to every track instead of individual track thumbnails.

### YouTube Music (yt-dlp based)
| URL type | Function |
|---|---|
| Single track | `scrape_ytm_track()` |
| Album | `scrape_ytm_album()` |
| Playlist | `scrape_ytm_playlist()` |
| Artist discography | `scrape_ytm_artist()` → calls `utils/ytm_scraper.py` |

### YouTube (yt-dlp + Playwright for channels)
| URL type | Function |
|---|---|
| Single video | `scrape_youtube_track()` |
| Playlist | `scrape_youtube_playlist()` |
| Channel (Videos/Shorts/Releases/Playlists) | `scrape_youtube_channel()` |

---

## File Organization — Output Folder Hierarchy

All files are saved under your configured **Output Directory** (default: `~/Downloads/YTSpot`).

### Solo Download (exactly 1 song selected)
```
[Output Directory]/
    Song Name.mp3
```
- No subfolders created.
- No track number prefix (`01 -`).
- No artist name in filename.
- Just: `Song Name.mp3`

### Playlist or Album (multi-track selection)
```
[Output Directory]/
    [Playlist or Album Name]/
        01 - Song Name.mp3
        02 - Song Name.mp3
        ...
```

### Spotify Artist Discography
Strict category separation using Hebrew category names:
```
[Output Directory]/
    [Artist Name]/
        אלבומים/
            [Album Name]/
                01 - Song.mp3
                02 - Song.mp3
        סינגלים ו-EP/
            Single Name.mp3
            [EP Name]/           ← only if EP has >1 track
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

| Scenario | Filename Format |
|---|---|
| Solo download (1 song) | `Song Name.mp3` |
| Multi-artist batch (playlist from multiple artists) | `Song Name.mp3` (Title only) |
| Album / Artist discography | `01 - Artist Name - Song Name.mp3` |
| Video | `Artist Name - Title.mp4` |

Filename cleaning is applied automatically:
- Removes parenthetical tags like `(Official Video)`, `(Lyrics)`, `(4K)`, `(Prod. by ...)`.
- Strips trailing promotional suffixes like `- Official`, `- Club Edit`.
- Preserves meaningful variants like `(Remix)`, `(Acoustic)`, `(Live)`.

---

## Authentication — YouTube Cookie Wizard

To bypass YouTube age gates and bot protection:

1. Go to **Settings** → **Authentication** → **Open Login Wizard**.
2. A browser window will open. Log into YouTube normally.
3. Close the browser. Cookies are saved automatically to `%APPDATA%/.ytspot/app_cookies.txt`.
4. The app picks up these cookies automatically on the next download — no restart required.

> **Note:** Cookies may expire after browser session rotation. If downloads start failing with "Sign in" errors, re-run the wizard.

---

## yt-dlp Client Strategy

The app uses a specific set of YouTube clients for maximum compatibility without requiring advanced JavaScript challenge solvers:

- **Primary clients**: `android_vr`, `web_safari`, `tv_downgraded`
- **Avoided clients**: `mweb`, `web` (require GVS PO Tokens / EJS solver)
- **Rate limiting**: 2–5 second sleeps between downloads to reduce bot-detection risk.

Terminal warnings like `Signature solving failed` and `n challenge solving failed` are **filtered out** — they are internal yt-dlp retry messages that do not indicate a real failure. Only genuine errors (access denied, video unavailable) are shown.

---

## Architecture Layers

```
UI (app_window.py, panels/, components/)
    ↓  Qt Signals
Workers (ui/workers/download_worker.py)
    ↓  Python calls
Core (downloader.py, scraper.py, ...)
    ↓  imports
Utils (yt_dlp_opts.py, impersonate.py, logger.py)
```

**Strict rule:** No layer imports anything above it. Core and Utils have zero GUI imports.

---

## Post-Processing Pipeline (per track, after download)

Each step is individually guarded by a config flag. All steps are non-fatal — partial failures are reported as warnings without cancelling the batch.

| Step | Config Flag | Module |
|---|---|---|
| Custom Thumbnail Embed (Spotify hi-res art) | `embed_thumbnail` | `core/thumbnail_cropper.py` |
| Square thumbnail crop (1:1) | `square_thumbnails` | `core/thumbnail_cropper.py` |
| Lyrics embedding | `lyrics_enabled` | `core/lyrics_embedder.py` |
| MusicBrainz tag enrichment | `musicbrainz_enabled` | `core/musicbrainz_enricher.py` |
| ReplayGain analysis | `replay_gain_enabled` | `core/replay_gain.py` |

---

## Settings Persistence

All settings are saved to `%APPDATA%/.ytspot/config.json` (Windows) or `~/.ytspot/config.json` (macOS/Linux).

Key settings:

| Setting | Default | Description |
|---|---|---|
| `output_dir` | `~/Downloads/YTSpot` | Root save directory |
| `audio_format` | `mp3` | Audio codec |
| `audio_quality` | `Best` | Target bitrate |
| `embed_thumbnail` | `true` | Embed cover art |
| `embed_metadata` | `true` | Embed ID3/MP4 tags |
| `playlist_subfolders` | `true` | Organize into subfolders |
| `playlist_index_prefix` | `true` | Add track numbers to filenames |
| `square_thumbnails` | `false` | Crop art to 1:1 square |
| `cookies_browser` | _(empty)_ | Live browser cookie source |
| `sponsorblock_enabled` | `false` | Cut non-music YouTube segments |
| `lyrics_enabled` | `false` | Embed lyrics post-download |
| `replay_gain_enabled` | `false` | ReplayGain loudness normalization |

---

## Troubleshooting

**FFmpeg not found** — Install FFmpeg and ensure it is on your system `PATH`. The app shows a warning on startup.

**YouTube "Sign in" errors** — Run the Cookie Wizard (Settings → Authentication). Cookies may have expired.

**Spotify not downloading** — Spotify routes through YouTube search. If a song title or artist name is uncommon, the YouTube match may fail. Try downloading the YouTube URL directly.

**Download cancels after 1-2 tracks** — Usually a YouTube rate-limit response. The app has built-in retries and sleep intervals. If persistent, run the Cookie Wizard to authenticate.

**All warnings in terminal** — Only genuine errors are shown. `Signature solving failed` messages are suppressed by design — they are internal yt-dlp retry noise.
