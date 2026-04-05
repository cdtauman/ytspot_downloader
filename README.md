# YTSpot Downloader

A desktop application for downloading audio and video from YouTube, Spotify, and other supported sites. Built with Python and PySide6 (Qt6), it uses **yt-dlp** as its download engine and a Fluent Design UI powered by **QFluentWidgets**.

---

## Features

- **Download audio** — MP3, M4A, FLAC, or Opus at selectable bitrates (128 k – 320 k)
- **Download video** — MP4/MKV at up to 1080p (or best available)
- **Playlist support** — resolves full YouTube and YouTube Music playlists incrementally; select individual tracks before downloading
- **Spotify support** — paste any Spotify track, album, or playlist URL; tracks are matched on YouTube automatically (no Spotify API key required)
- **Built-in search** — search YouTube directly from the app; Spotify search requires a self-hosted proxy server (see Settings)
- **Page scraper** — paste any webpage URL and the app extracts all embeddable media links from it
- **Batch import** — paste or load a plain-text file of URLs to queue them all at once
- **Download history** — full-text searchable SQLite log of every completed download; exportable to CSV
- **Metadata embedding** — ID3/MP4 tags (title, artist, thumbnail) written automatically via mutagen
- **Clipboard monitor** — optionally watches the clipboard and auto-fills the URL bar when a supported link is copied
- **Auto-update check** — notifies you at startup when a newer release is available on GitHub
- **Themes** — Dark, Light, and OLED modes; amber accent colour; Hebrew (RTL) and English UI
- **Cookie support** — pass a `cookies.txt` file (Netscape format) or extract from a browser for age-gated or member-only content
- **Bot-bypass browser** — built-in Chromium window for solving Cloudflare/Turnstile challenges

---

## Requirements

| Requirement | Version |
|-------------|---------|
| Python | 3.10 or newer |
| FFmpeg | Any recent version (must be on `PATH`) |
| yt-dlp | ≥ 2026.3.13 (installed via pip) |

Install FFmpeg:

```bash
# Windows (via Chocolatey)
choco install ffmpeg

# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt install ffmpeg
```

---

## Installation

```bash
git clone https://github.com/cdtauman/ytspot_downloader.git
cd ytspot_downloader
pip install -r requirements.txt
```

---

## Running

```bash
python main.py
```

---

## Options & Settings

All settings are persisted to `~/.ytspot/config.json` and can be changed from the **Settings** panel inside the app.

### Download

| Setting | Values | Default | Description |
|---------|--------|---------|-------------|
| Output directory | Any writable path | `~/Downloads/YTSpot` | Where downloaded files are saved |
| Media format | `mp3`, `mp4` | `mp3` | Whether to download audio or video |
| Audio format | `mp3`, `m4a`, `flac`, `opus` | `mp3` | Audio codec (audio-only downloads) |
| Audio quality | Best (320k), High (256k), Medium (192k), Low (128k) | Best | Target bitrate |
| Video quality | Best, 1080p, 720p, 480p, Worst | 1080p | Maximum video resolution |
| Embed thumbnail | on / off | on | Embed cover art into the file metadata |
| Embed metadata | on / off | on | Embed title, artist, and other tags |

### Appearance

| Setting | Values | Default | Description |
|---------|--------|---------|-------------|
| Theme | `dark`, `light`, `oled` | `dark` | UI colour scheme |
| Language | `en`, `he` | `en` | UI language (Hebrew switches to RTL layout) |

### Authentication & Network

| Setting | Values | Default | Description |
|---------|--------|---------|-------------|
| Cookies file | Path to `cookies.txt` | _(empty)_ | Netscape-format cookies for authenticated or age-gated downloads |
| Cookies browser | `chrome`, `firefox`, `edge`, `brave`, `safari`, or empty | _(empty)_ | Extract cookies live from an installed browser |
| Spotify proxy URL | HTTP URL | _(empty)_ | URL of your self-hosted Spotify search proxy server (see `SPOTIFY_PROXY_API.md`) |

### Other

| Setting | Description |
|---------|-------------|
| Clipboard monitor | Automatically paste supported URLs when they are copied to the clipboard |
| Output directory | Opens a folder picker to choose where files are saved |

---

## Supported Platforms

| Platform | Single track | Playlist / Album | Search |
|----------|-------------|-----------------|--------|
| YouTube | Yes | Yes | Yes (built-in) |
| YouTube Music | Yes | Yes | Via YouTube search |
| Spotify | Via YouTube match | Via YouTube match | Requires proxy server |
| Generic URLs | Yes (yt-dlp) | Partial | No |

Spotify downloads work by converting the track metadata to a YouTube search query (`artist title audio`) and downloading the best YouTube match. This requires no Spotify account or API key.

---

## Architecture Overview

The app is split into four layers with strict separation:

1. **Core** (`downloader.py`, `playlist_parser.py`, `core/`) — pure Python, zero GUI imports; can be used headlessly
2. **Utils** (`utils/`) — shared helpers: duration formatting, curl_cffi detection, Spotify URL resolution
3. **Workers** (`ui/workers/`) — thin `QThread` wrappers that call the core layer and emit Qt signals
4. **UI** (`ui/panels/`, `ui/components/`, `ui/app_window.py`) — PySide6/QFluentWidgets panels and cards

Data flows strictly downward: UI → Workers → Core → Utils. No layer imports anything above it.

---

## Troubleshooting

**FFmpeg not found** — Install FFmpeg and make sure it is on your system `PATH`. The app will show a warning dialog on startup if it cannot find FFmpeg.

**YouTube bot protection** — If downloads fail with "Sign in" or "bot" errors, try providing a `cookies.txt` file exported from your browser, or use the browser cookie extraction option in Settings.

**Spotify not downloading** — Spotify downloads route through YouTube. If a track cannot be found, the search query may not match. Try searching manually and pasting the YouTube URL instead.

**Spotify search not working** — Spotify search in the app requires a self-hosted proxy server. See `SPOTIFY_PROXY_API.md` for the API contract and how to deploy one.
