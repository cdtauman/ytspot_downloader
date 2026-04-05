"""
config.py  –  Persistent user-preferences manager
===================================================
Stores and retrieves settings in  ~/.ytspot/config.json  (cross-platform).

Design decisions
----------------
* Zero GUI imports – pure stdlib only.  Safe to import from any layer.
* Atomic writes: write to a temp file, then os.replace(), so a crash
  mid-write never corrupts the stored config.
* All keys have hard-coded defaults so the app always boots cleanly even
  if config.json is missing, empty, or malformed.
* Type-coercion: values read from JSON are always cast to their expected
  Python types via the typed getter/setter properties.
* Additive-only changes from v1: every existing property is preserved with
  its original name and default so all backend modules remain untouched.

Usage
-----
>>> cfg = AppConfig()
>>> cfg.output_dir
'/home/user/Downloads/YTSpot'
>>> cfg.output_dir = '/mnt/nas/music'
>>> cfg.save()                          # explicit save

Or use the context manager for automatic save-on-exit:

>>> with AppConfig() as cfg:
...     cfg.output_dir     = '/mnt/nas/music'
...     cfg.audio_format   = 'flac'
...     cfg.theme          = 'oled'
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


# ──────────────────────────────────────────────────────────────────────────────
# Defaults
# ──────────────────────────────────────────────────────────────────────────────

_DEFAULTS: dict[str, Any] = {

    # ── Download location ─────────────────────────────────────────────────────
    "output_dir":           str(Path.home() / "Downloads" / "YTSpot"),

    # ── Format & quality ──────────────────────────────────────────────────────
    "media_format":         "mp3",          # "mp3" | "mp4"
    "audio_quality":        "Best (320k)",  # label matching AUDIO_QUALITY_MAP
    "video_quality":        "1080p",        # label matching VIDEO_QUALITY_MAP
    "audio_format":         "mp3",          # codec: "mp3"|"m4a"|"flac"|"opus"

    # ── Metadata embedding ────────────────────────────────────────────────────
    "embed_thumbnail":      True,
    "embed_metadata":       True,

    # ── Cookies file path (empty string = not set) ────────────────────────────
    "cookies_file":         "",

    # ── Appearance ────────────────────────────────────────────────────────────
    # "dark"  → Fluent dark theme   (default)
    # "light" → Fluent light theme
    # "oled"  → Fluent dark + pure-black (#000000) background overrides
    "theme":                "dark",
    # ── Language (UI) ───────────────────────────────────────────────────────
    # "en" → English (default)
    # "he" → Hebrew (Right-to-left)
    "language":             "en",

    # ── Window state ──────────────────────────────────────────────────────────
    # Stored as a hex string of QMainWindow.saveState() bytes.
    # Empty string means "use default layout".
    "window_geometry":      "",             # legacy Tk geometry string (unused by Qt UI)
    "window_state":         "",             # Qt QMainWindow.saveState() → hex string

    # ── Clipboard monitor ─────────────────────────────────────────────────────
    # When True, a background QThread watches the clipboard every 800 ms and
    # auto-populates the URL bar when a supported media URL is detected.
    "clipboard_monitor":    False,

    # ── Update checker ────────────────────────────────────────────────────────
    # When True, a background thread checks the GitHub releases API on launch
    # and shows a dismissible banner if a newer version is available.
    "check_updates":        True,

    # ── Download history database ─────────────────────────────────────────────
    # Absolute path to downloads.db.  Empty string = place it beside config.json
    # in the same ~/.ytspot/ directory.
    "history_db_path":      "",

    # ── Search ────────────────────────────────────────────────────────────────
    # The last query the user typed into the search panel; restored on reopen.
    "last_search_query":    "",

    # The last platform tab selected in the search panel ("youtube" | "spotify").
    "last_search_platform": "youtube",

    # Maximum number of search results to fetch per query.
    "search_max_results":   15,

    # ── Batch import ──────────────────────────────────────────────────────────
    # The last directory the user opened when importing a .txt URL batch file.
    "batch_import_dir":     "",

    # ── Spotify proxy server ──────────────────────────────────────────────────
    # URL to your Spotify proxy server (without trailing slash).
    # The app sends search requests to this server instead of Spotify directly.
    # Example: "http://your-future-server.com" or "http://localhost:5000"
    "proxy_server_url":     "http://localhost:8000",

    # ── Browser cookies source ────────────────────────────────────────────────
    # When set, yt-dlp extracts cookies from the named browser so the app can
    # bypass CAPTCHA-solved sessions and age-verification walls automatically.
    # Valid values: "" (disabled), "chrome", "firefox", "edge", "brave", "safari"
    "cookies_browser":      "",

    # ── Spotify API credentials (v3 – Spotify Web API) ────────────────────────
    # Register a free app at https://developer.spotify.com/dashboard to obtain
    # a Client ID and Client Secret.  When both are set, SpotifyResolver uses
    # the official Web API (client_credentials flow) which gives access to:
    #   - Full track metadata (artist, album, duration, thumbnail)
    #   - Album/playlist pagination with no rate-limit concerns
    #   - Artist discography (all albums + all tracks)
    # When either field is empty, the app falls back to the embed API (no auth)
    # which still works for basic track/album/playlist resolution.
    "spotify_client_id":     "",
    "spotify_client_secret": "",

    # ── Parallel download concurrency ─────────────────────────────────────────
    # Number of tracks downloaded simultaneously (1 = sequential, max = 5).
    # Higher values consume more CPU/bandwidth but complete batches faster.
    "max_parallel_downloads": 3,

}


# ──────────────────────────────────────────────────────────────────────────────
# Config file location
# ──────────────────────────────────────────────────────────────────────────────

def _config_path() -> Path:
    """
    Return the path to config.json, respecting XDG on Linux and
    APPDATA on Windows.

    Platform      Path
    ----------    ---------------------------------------------------
    Windows       %APPDATA%\\YTSpot\\config.json
    macOS/Linux   ~/.ytspot/config.json
    """
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path.home()
    return base / ".ytspot" / "config.json"


def _default_db_path() -> str:
    """
    Return the default absolute path for downloads.db, placed in the
    same directory as config.json so both live under ~/.ytspot/.
    """
    return str(_config_path().parent / "downloads.db")


# ──────────────────────────────────────────────────────────────────────────────
# AppConfig class
# ──────────────────────────────────────────────────────────────────────────────

class AppConfig:
    """
    Read/write wrapper around config.json.

    All public attributes are Python properties backed by self._data.
    Setting a property updates _data in memory; call save() to persist.

    Backward compatibility guarantee
    ---------------------------------
    Every property present in the v1 config.py is preserved verbatim.
    New properties are purely additive – existing callers (downloader.py,
    error_handler.py, playlist_parser.py, spotify_resolver.py) are
    unaffected and require zero changes.
    """

    def __init__(self) -> None:
        self._path: Path          = _config_path()
        self._data: dict[str, Any] = dict(_DEFAULTS)   # start with defaults
        self._load()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load config.json; silently merge over defaults on any error."""
        if not self._path.exists():
            return
        try:
            raw    = self._path.read_text(encoding="utf-8")
            stored = json.loads(raw)
            if isinstance(stored, dict):
                # Accept only known keys; silently drop unknown / stale keys.
                for key in _DEFAULTS:
                    if key in stored:
                        self._data[key] = stored[key]
        except (json.JSONDecodeError, OSError):
            # Corrupted or unreadable config → fall back to defaults silently.
            pass

    def save(self) -> None:
        """
        Atomically write config to disk.
        Creates the parent directory (~/.ytspot/) if it does not yet exist.
        Uses a write-then-rename strategy so a crash mid-write never
        produces a half-written or empty config.json.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(".tmp")
        try:
            tmp_path.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            # os.replace is atomic on POSIX; on Windows it is best-effort.
            tmp_path.replace(self._path)
        except OSError:
            # Write failed (permissions, disk full…) – do not crash the app.
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def reset_to_defaults(self) -> None:
        """Restore all settings to factory defaults and persist immediately."""
        self._data = dict(_DEFAULTS)
        self.save()

    # ── Context manager ────────────────────────────────────────────────────────

    def __enter__(self) -> "AppConfig":
        return self

    def __exit__(self, *_: Any) -> None:
        self.save()

    # ── Low-level get/set (for dynamic access by key name) ────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    # ──────────────────────────────────────────────────────────────────────────
    # Typed properties — v1 (preserved exactly)
    # ──────────────────────────────────────────────────────────────────────────

    @property
    def output_dir(self) -> str:
        v = self._data.get("output_dir", _DEFAULTS["output_dir"])
        return str(v) if v else _DEFAULTS["output_dir"]

    @output_dir.setter
    def output_dir(self, value: str) -> None:
        self._data["output_dir"] = str(value)

    # ──

    @property
    def media_format(self) -> str:
        return str(self._data.get("media_format", _DEFAULTS["media_format"]))

    @media_format.setter
    def media_format(self, value: str) -> None:
        self._data["media_format"] = str(value)

    # ──

    @property
    def audio_quality(self) -> str:
        return str(self._data.get("audio_quality", _DEFAULTS["audio_quality"]))

    @audio_quality.setter
    def audio_quality(self, value: str) -> None:
        self._data["audio_quality"] = str(value)

    # ──

    @property
    def video_quality(self) -> str:
        return str(self._data.get("video_quality", _DEFAULTS["video_quality"]))

    @video_quality.setter
    def video_quality(self, value: str) -> None:
        self._data["video_quality"] = str(value)

    # ──

    @property
    def audio_format(self) -> str:
        return str(self._data.get("audio_format", _DEFAULTS["audio_format"]))

    @audio_format.setter
    def audio_format(self, value: str) -> None:
        self._data["audio_format"] = str(value)

    # ──

    @property
    def embed_thumbnail(self) -> bool:
        return bool(self._data.get("embed_thumbnail", _DEFAULTS["embed_thumbnail"]))

    @embed_thumbnail.setter
    def embed_thumbnail(self, value: bool) -> None:
        self._data["embed_thumbnail"] = bool(value)

    # ──

    @property
    def embed_metadata(self) -> bool:
        return bool(self._data.get("embed_metadata", _DEFAULTS["embed_metadata"]))

    @embed_metadata.setter
    def embed_metadata(self, value: bool) -> None:
        self._data["embed_metadata"] = bool(value)

    # ──

    @property
    def cookies_file(self) -> str:
        return str(self._data.get("cookies_file", ""))

    @cookies_file.setter
    def cookies_file(self, value: str) -> None:
        self._data["cookies_file"] = str(value)

    # ──

    @property
    def window_geometry(self) -> str:
        """Legacy Tk geometry string. Kept for a clean migration period."""
        return str(self._data.get("window_geometry", ""))

    @window_geometry.setter
    def window_geometry(self, value: str) -> None:
        self._data["window_geometry"] = str(value)

    # ──────────────────────────────────────────────────────────────────────────
    # Typed properties — v2 (new keys)
    # ──────────────────────────────────────────────────────────────────────────

    @property
    def theme(self) -> str:
        """
        Active UI theme.  One of: "dark" | "light" | "oled".
        Defaults to "dark".  The ThemeManager reads this on startup and
        whenever the user changes it in Settings.
        """
        val = str(self._data.get("theme", _DEFAULTS["theme"]))
        if val not in ("dark", "light", "oled"):
            return "dark"
        return val

    @theme.setter
    def theme(self, value: str) -> None:
        if value not in ("dark", "light", "oled"):
            raise ValueError(f"Invalid theme '{value}'. Must be 'dark', 'light', or 'oled'.")
        self._data["theme"] = value

    # ──

    @property
    def language(self) -> str:
        """
        UI language code. One of: "en" | "he".
        """
        val = str(self._data.get("language", _DEFAULTS["language"]))
        if val not in ("en", "he"):
            return "en"
        return val

    @language.setter
    def language(self, value: str) -> None:
        if value not in ("en", "he"):
            raise ValueError("Invalid language. Must be 'en' or 'he'.")
        self._data["language"] = value

    # ──

    @property
    def window_state(self) -> str:
        """
        QMainWindow.saveState() bytes serialised as a hex string.
        Empty string means "use default layout" — the Qt window will not
        attempt to restore any state.
        """
        return str(self._data.get("window_state", ""))

    @window_state.setter
    def window_state(self, value: str) -> None:
        self._data["window_state"] = str(value)

    # ──

    @property
    def clipboard_monitor(self) -> bool:
        """
        When True, ClipboardWorker polls the system clipboard every 800 ms
        and auto-populates the URL bar when a supported media URL is detected.
        """
        return bool(self._data.get("clipboard_monitor", _DEFAULTS["clipboard_monitor"]))

    @clipboard_monitor.setter
    def clipboard_monitor(self, value: bool) -> None:
        self._data["clipboard_monitor"] = bool(value)

    # ──

    @property
    def check_updates(self) -> bool:
        """
        When True, UpdateWorker queries the GitHub releases API on launch
        and surfaces a banner if a newer version is available.
        """
        return bool(self._data.get("check_updates", _DEFAULTS["check_updates"]))

    @check_updates.setter
    def check_updates(self, value: bool) -> None:
        self._data["check_updates"] = bool(value)

    # ──

    @property
    def history_db_path(self) -> str:
        """
        Absolute path to downloads.db.
        If empty, HistoryDB will place the file in ~/.ytspot/downloads.db
        (i.e., beside config.json).  The HistoryDB class resolves this
        fallback itself via _default_db_path().
        """
        return str(self._data.get("history_db_path", ""))

    @history_db_path.setter
    def history_db_path(self, value: str) -> None:
        self._data["history_db_path"] = str(value)

    def resolved_history_db_path(self) -> str:
        """
        Returns the effective database path, resolving the empty-string
        default to the canonical ~/.ytspot/downloads.db location.
        Use this in HistoryDB.__init__() rather than history_db_path directly.
        """
        stored = self.history_db_path.strip()
        return stored if stored else _default_db_path()

    # ──

    @property
    def last_search_query(self) -> str:
        """The last query typed into the search panel; restored on reopen."""
        return str(self._data.get("last_search_query", ""))

    @last_search_query.setter
    def last_search_query(self, value: str) -> None:
        self._data["last_search_query"] = str(value)

    # ──

    @property
    def last_search_platform(self) -> str:
        """
        The last platform tab active in the search panel.
        One of: "youtube" | "spotify".  Defaults to "youtube".
        """
        val = str(self._data.get("last_search_platform", _DEFAULTS["last_search_platform"]))
        if val not in ("youtube", "spotify"):
            return "youtube"
        return val

    @last_search_platform.setter
    def last_search_platform(self, value: str) -> None:
        if value not in ("youtube", "spotify", "both"):
            raise ValueError(f"Invalid platform '{value}'. Must be 'youtube', 'spotify', or 'both'.")
        self._data["last_search_platform"] = value

    # ──

    @property
    def search_max_results(self) -> int:
        """
        Maximum number of results to retrieve per search query.
        Clamped to the range [1, 50] to prevent runaway API calls.
        """
        raw = self._data.get("search_max_results", _DEFAULTS["search_max_results"])
        try:
            val = int(raw)
        except (TypeError, ValueError):
            val = _DEFAULTS["search_max_results"]
        return max(1, min(50, val))

    @search_max_results.setter
    def search_max_results(self, value: int) -> None:
        self._data["search_max_results"] = max(1, min(50, int(value)))

    # ──

    @property
    def batch_import_dir(self) -> str:
        """
        Last directory the user opened when importing a .txt URL batch file.
        Empty string means "use the system default open-file dialog location".
        """
        return str(self._data.get("batch_import_dir", ""))

    @batch_import_dir.setter
    def batch_import_dir(self, value: str) -> None:
        self._data["batch_import_dir"] = str(value)

    # ──

    @property
    def proxy_server_url(self) -> str:
        """
        URL to your Spotify proxy server for search requests.
        Empty or placeholder URL means Spotify search is disabled.
        Example: "http://localhost:5000" or "https://your-server.com"
        """
        return str(self._data.get("proxy_server_url", _DEFAULTS["proxy_server_url"]))

    @proxy_server_url.setter
    def proxy_server_url(self, value: str) -> None:
        self._data["proxy_server_url"] = str(value)

    # ──────────────────────────────────────────────────────────────────────────
    # Convenience helpers
    # ──────────────────────────────────────────────────────────────────────────

    def as_dict(self) -> dict[str, Any]:
        """Return a shallow copy of the internal data dict (for debugging)."""
        return dict(self._data)

    @property
    def cookies_browser(self) -> str:
        """
        Browser to extract cookies from for bot bypass and age-gate access.
        Empty string means disabled.  Valid: "chrome", "firefox", "edge", "brave", "safari"
        """
        return str(self._data.get("cookies_browser", ""))

    @cookies_browser.setter
    def cookies_browser(self, value: str) -> None:
        self._data["cookies_browser"] = value.lower().strip()

    # ── Spotify API credentials ────────────────────────────────────────────────

    @property
    def spotify_client_id(self) -> str:
        """
        Spotify Developer App Client ID.
        Register at https://developer.spotify.com/dashboard (free account).
        When non-empty (together with spotify_client_secret), SpotifyResolver
        uses the official Web API instead of the embed API fallback.
        """
        return str(self._data.get("spotify_client_id", ""))

    @spotify_client_id.setter
    def spotify_client_id(self, value: str) -> None:
        self._data["spotify_client_id"] = str(value).strip()

    @property
    def spotify_client_secret(self) -> str:
        """Spotify Developer App Client Secret (paired with spotify_client_id)."""
        return str(self._data.get("spotify_client_secret", ""))

    @spotify_client_secret.setter
    def spotify_client_secret(self, value: str) -> None:
        self._data["spotify_client_secret"] = str(value).strip()

    # ── Parallel download concurrency ─────────────────────────────────────────

    @property
    def max_parallel_downloads(self) -> int:
        """Number of simultaneous downloads (clamped 1–5)."""
        raw = self._data.get("max_parallel_downloads", 3)
        try:
            val = int(raw)
        except (TypeError, ValueError):
            val = 3
        return max(1, min(5, val))

    @max_parallel_downloads.setter
    def max_parallel_downloads(self, value: int) -> None:
        self._data["max_parallel_downloads"] = max(1, min(5, int(value)))

    # ──

    def __repr__(self) -> str:
        return f"AppConfig(path={self._path!r}, theme={self.theme!r}, output_dir={self.output_dir!r})"