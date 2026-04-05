# YTSpot Downloader – Project Structure

```
ytspot_downloader/
│
├── requirements.txt          ← pip dependencies
│
├── downloader.py             ← ✅ STEP 1: Core engine  (this step)
│
├── gui/                      ← STEP 2: UI layer (coming next)
│   ├── __init__.py
│   ├── app.py                ← Main CustomTkinter / PyQt6 window
│   ├── components/
│   │   ├── url_bar.py        ← URL input + Paste/Add button
│   │   ├── queue_panel.py    ← Download queue list
│   │   ├── settings_panel.py ← Quality, format, output-dir selectors
│   │   └── progress_card.py  ← Per-item progress card with bar
│   └── assets/
│       └── icon.ico
│
├── config/
│   ├── __init__.py
│   └── settings.py           ← STEP 3: Persistent user preferences (JSON)
│
├── utils/
│   ├── __init__.py
│   ├── ffmpeg_checker.py     ← STEP 3: Detect / auto-download FFmpeg
│   └── spotify_resolver.py   ← STEP 4: Spotify URL → YouTube search fallback
│
└── main.py                   ← STEP 2: Entry-point that starts the GUI
```

## Setup (development)

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Ensure FFmpeg is on your PATH
#    Windows:  winget install Gyan.FFmpeg
#    macOS:    brew install ffmpeg
#    Linux:    sudo apt install ffmpeg

# 4. Smoke-test the engine
python downloader.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

## Architecture notes

| Layer         | Module(s)                        | Allowed to import   |
|---------------|----------------------------------|---------------------|
| Core engine   | `downloader.py`                  | stdlib + yt-dlp only |
| Config        | `config/settings.py`             | stdlib only          |
| Utilities     | `utils/*.py`                     | core + config        |
| GUI           | `gui/**`                         | everything           |
| Entry-point   | `main.py`                        | gui + config         |

This strict layering means `downloader.py` can always be used headlessly
(CLI, tests, batch scripts) without pulling in any GUI toolkit.
