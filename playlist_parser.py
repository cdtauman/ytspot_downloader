"""
playlist_parser.py  –  Playlist & single-URL metadata extractor
================================================================
Responsibilities
----------------
* Detect whether a URL is a single item or a playlist/album.
* Extract structured metadata for every item WITHOUT downloading any media.
* Emit incremental item-ready callbacks so the GUI can populate a list
  progressively (no waiting for 500-track playlists to finish resolving).
* Handle YouTube playlists, YouTube Music playlists, and Spotify
  (tracks, albums, playlists) through yt-dlp's built-in extractors.

Design contract
---------------
* Zero GUI imports – identical rule as downloader.py.
* All I/O is done through callbacks and return values (no global state).
* `ParseResult` and `TrackMeta` are plain dataclasses – safe to pickle,
  copy, or send across a queue to the UI thread.
* The parser can be cancelled mid-flight via `PlaylistParser.cancel()`.

Typical usage
-------------
>>> parser = PlaylistParser()
>>> result = parser.parse(
...     url="https://www.youtube.com/playlist?list=PLxxxxxx",
...     on_item=lambda item, idx, total: print(f"[{idx}/{total}] {item.title}"),
...     on_progress=lambda msg: print(msg),
... )
>>> print(result.summary())
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Iterator, Optional
from urllib.parse import urlparse, parse_qs

import yt_dlp
try:
    import yt_dlp_ejs  # noqa: F401  – loads QuickJS runtime for YouTube PO-token
except ImportError:
    pass

from utils.impersonate import ImpersonateTarget as _ImpersonateTarget, CURL_CFFI_AVAILABLE as _CURL_CFFI_AVAILABLE
from utils.time_format import seconds_to_str as _seconds_to_str


# ──────────────────────────────────────────────────────────────────────────────
# Public data-classes
# ──────────────────────────────────────────────────────────────────────────────

class SourcePlatform(Enum):
    YOUTUBE         = auto()
    YOUTUBE_MUSIC   = auto()
    SPOTIFY         = auto()
    GENERIC         = auto()   # any yt-dlp-supported site that isn't YouTube/Spotify
    UNKNOWN         = auto()   # not a valid http/https URL


class UrlKind(Enum):
    SINGLE_VIDEO    = auto()   # One video / track
    PLAYLIST        = auto()   # YouTube / YT-Music playlist
    ALBUM           = auto()   # Spotify album
    ARTIST          = auto()   # Spotify artist discography (rare)
    UNKNOWN         = auto()


@dataclass
class TrackMeta:
    """
    Normalised metadata for one video/track entry.
    All fields default to safe empty values so the UI can always render
    something even when the extractor returns incomplete data.
    """
    # ── Identity ─────────────────────────────────────────────────────────────
    index:          int   = 0           # 1-based position inside the playlist
    url:            str   = ""          # canonical watch/track URL
    title:          str   = "Unknown Title"
    artist:         str   = ""          # uploader / artist name
    album:          str   = ""          # album / playlist title

    # ── Timing ───────────────────────────────────────────────────────────────
    duration_sec:   Optional[int]   = None   # None = live / unknown
    duration_str:   str             = ""     # human-readable "3:45"

    # ── Visuals ──────────────────────────────────────────────────────────────
    thumbnail_url:  str   = ""          # best-quality thumbnail

    # ── Platform ─────────────────────────────────────────────────────────────
    platform:       SourcePlatform = SourcePlatform.UNKNOWN

    # ── State used by the GUI (not set by the parser) ─────────────────────────
    selected:       bool  = True        # pre-tick all items in the UI

    # ── Helpers ──────────────────────────────────────────────────────────────
    @staticmethod
    def format_duration(seconds: Optional[int]) -> str:
        """Convert raw seconds to MM:SS or HH:MM:SS string."""
        return _seconds_to_str(seconds, live_label="Live")

    def __post_init__(self) -> None:
        # Auto-fill duration_str when duration_sec is provided
        if self.duration_sec is not None and not self.duration_str:
            self.duration_str = self.format_duration(self.duration_sec)


@dataclass
class ParseResult:
    """
    Container returned by `PlaylistParser.parse()` after extraction finishes.
    """
    url:            str
    kind:           UrlKind
    platform:       SourcePlatform
    playlist_title: str             = ""
    playlist_id:    str             = ""
    total_count:    int             = 0     # reported by extractor (may differ from len(tracks))
    tracks:         list[TrackMeta] = field(default_factory=list)
    error:          str             = ""    # non-empty → partial or full failure
    cancelled:      bool            = False

    def success(self) -> bool:
        return not self.error and not self.cancelled and bool(self.tracks)

    def summary(self) -> str:
        if self.cancelled:
            return f"Cancelled after {len(self.tracks)} item(s)."
        if self.error:
            return f"Parse error: {self.error}"
        total_sec = sum(t.duration_sec or 0 for t in self.tracks)
        h, rem    = divmod(total_sec, 3600)
        m, s      = divmod(rem, 60)
        duration  = f"{h}h {m}m" if h else f"{m}m {s}s"
        return (
            f'"{self.playlist_title}" – {len(self.tracks)} tracks, '
            f"~{duration} total"
        )


# ──────────────────────────────────────────────────────────────────────────────
# URL classifier  (pure regex, no network)
# ──────────────────────────────────────────────────────────────────────────────

_YT_PLAYLIST_RE  = re.compile(r"[?&]list=([A-Za-z0-9_-]+)")
_YT_VIDEO_RE     = re.compile(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})")
_YTM_RE          = re.compile(r"music\.youtube\.com")
_SPOTIFY_RE      = re.compile(
    r"open\.spotify\.com/(track|album|playlist|artist)/([A-Za-z0-9]+)"
)


def classify_url(url: str) -> tuple[SourcePlatform, UrlKind]:
    """
    Classify a URL into (platform, kind) without making any network calls.
    Used by the UI to show the right icon / label before parsing starts.
    """
    if _YTM_RE.search(url):
        platform = SourcePlatform.YOUTUBE_MUSIC
        kind     = UrlKind.PLAYLIST if _YT_PLAYLIST_RE.search(url) else UrlKind.SINGLE_VIDEO
        return platform, kind

    if "youtube.com" in url or "youtu.be" in url:
        platform = SourcePlatform.YOUTUBE
        if _YT_PLAYLIST_RE.search(url):
            # Could be a video-in-playlist (v=...&list=...) or pure playlist
            kind = UrlKind.PLAYLIST
        else:
            kind = UrlKind.SINGLE_VIDEO if _YT_VIDEO_RE.search(url) else UrlKind.UNKNOWN
        return platform, kind

    m = _SPOTIFY_RE.search(url)
    if m:
        type_map = {
            "track":    UrlKind.SINGLE_VIDEO,
            "album":    UrlKind.ALBUM,
            "playlist": UrlKind.PLAYLIST,
            "artist":   UrlKind.ARTIST,
        }
        return SourcePlatform.SPOTIFY, type_map.get(m.group(1), UrlKind.UNKNOWN)

    # Any valid http/https URL → let yt-dlp's Generic extractor try
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return SourcePlatform.GENERIC, UrlKind.UNKNOWN

    return SourcePlatform.UNKNOWN, UrlKind.UNKNOWN


# ──────────────────────────────────────────────────────────────────────────────
# Thumbnail selector  (best quality, safe fallback)
# ──────────────────────────────────────────────────────────────────────────────

def _best_thumbnail(info: dict) -> str:
    """
    Pick the highest-resolution thumbnail URL from a yt-dlp info dict.
    Falls back gracefully through multiple possible keys.
    """
    # yt-dlp may provide a ranked list of thumbnails
    thumbnails: list[dict] = info.get("thumbnails") or []
    if thumbnails:
        # Sort by resolution (width * height) descending; prefer HTTPS
        def _score(t: dict) -> int:
            w = t.get("width")  or 0
            h = t.get("height") or 0
            return w * h

        ranked = sorted(
            [t for t in thumbnails if t.get("url")],
            key=_score,
            reverse=True,
        )
        if ranked:
            return ranked[0]["url"]

    # Direct thumbnail key as last resort
    return info.get("thumbnail") or ""


# ──────────────────────────────────────────────────────────────────────────────
# Info-dict → TrackMeta  normaliser
# ──────────────────────────────────────────────────────────────────────────────

def _entry_to_track(
    entry:    dict,
    index:    int,
    platform: SourcePlatform,
    album:    str = "",
) -> TrackMeta:
    """
    Convert one yt-dlp entry dict into a normalised TrackMeta.
    Works for both fully-resolved entries and lightweight flat-playlist entries
    (where only title / id / url are guaranteed to be present).
    """
    # URL: prefer webpage_url, fall back to reconstructed YouTube URL (YouTube only)
    url = (
        entry.get("webpage_url")
        or entry.get("url")
        or (
            f"https://www.youtube.com/watch?v={entry['id']}"
            if entry.get("id") and platform in (
                SourcePlatform.YOUTUBE, SourcePlatform.YOUTUBE_MUSIC
            )
            else ""
        )
    )

    duration_sec: Optional[int] = entry.get("duration")
    if duration_sec is not None:
        try:
            duration_sec = int(duration_sec)
        except (TypeError, ValueError):
            duration_sec = None

    artist = (
        entry.get("artist")
        or entry.get("creator")
        or entry.get("uploader")
        or ""
    )

    return TrackMeta(
        index=index,
        url=url,
        title=entry.get("title") or entry.get("fulltitle") or "Unknown Title",
        artist=artist,
        album=album or entry.get("album") or entry.get("playlist_title") or "",
        duration_sec=duration_sec,
        duration_str=TrackMeta.format_duration(duration_sec),
        thumbnail_url=_best_thumbnail(entry),
        platform=platform,
        selected=True,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Main parser class
# ──────────────────────────────────────────────────────────────────────────────

class PlaylistParser:
    """
    Metadata-only extractor.  Never downloads media.

    Callbacks
    ---------
    on_item(track, index, total)
        Called as soon as each TrackMeta is resolved.
        `total` is the count reported by the extractor; it may be None for
        sources that don't announce total count upfront (e.g. Spotify).

    on_progress(message)
        Called with human-readable status strings, e.g. "Fetching item 3/50".
        Useful for a status-bar label in the GUI.

    on_error(message)
        Called for non-fatal per-item errors (private videos, geo-blocks…).
        The parser continues after calling this; fatal errors are returned
        as ParseResult.error instead.

    Threading
    ---------
    `parse()` is blocking.  Use `parse_async()` for non-blocking use.
    Call `cancel()` from any thread to abort mid-flight.
    """

    def __init__(self) -> None:
        self._cancel = threading.Event()

    # ── Public API ─────────────────────────────────────────────────────────────

    def parse(
        self,
        url:             str,
        *,
        cookies_file:    Optional[str]                               = None,
        on_item:         Optional[Callable[[TrackMeta, int, Optional[int]], None]] = None,
        on_progress:     Optional[Callable[[str], None]]             = None,
        on_error:        Optional[Callable[[str], None]]             = None,
    ) -> ParseResult:
        """
        Blocking metadata extraction.  Returns a fully-populated ParseResult.
        """
        self._cancel.clear()
        platform, kind = classify_url(url)
        result = ParseResult(url=url, kind=kind, platform=platform)

        self._notify(on_progress, f"Analysing URL… ({platform.name})")

        # ── Spotify Fallback ──────────────────────────────────────────────────
        if platform == SourcePlatform.SPOTIFY:
            try:
                from utils.spotify_resolver import SpotifyResolver
                items = SpotifyResolver.resolve(url)
                
                result.total_count = len(items)
                if len(items) > 1:
                    result.playlist_title = f"Spotify Playlist/Album ({len(items)} tracks)"
                elif items:
                    result.playlist_title = items[0]["title"]

                for idx, track_data in enumerate(items, start=1):
                    track = TrackMeta(
                        index=idx,
                        url=track_data["url"],
                        title=track_data["title"],
                        artist=track_data["artist"],
                        duration_sec=track_data.get("duration_sec"),
                        platform=SourcePlatform.SPOTIFY,
                        selected=True
                    )
                    result.tracks.append(track)
                    if on_item:
                        on_item(track, idx, result.total_count)
                
                self._notify(on_progress, f"Resolved {len(items)} tracks from Spotify.")
                return result

            except Exception as exc:
                result.error = f"Failed to resolve Spotify link: {exc}"
                return result

        logger = _SilentLogger()
        ydl_opts = self._build_opts(cookies_file, logger)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

            if info is None:
                # Surface the real yt-dlp error/warning messages
                detail = "; ".join(logger.errors + logger.warnings) or "No details available."
                result.error = f"yt-dlp returned no data for this URL. Detail: {detail}"
                return result

        except yt_dlp.utils.DownloadError as exc:
            result.error = str(exc)
            return result
        except Exception as exc:  # noqa: BLE001
            result.error = f"Unexpected extraction error: {exc}"
            return result

        # ── Detect whether result is a playlist/collection or a single item ──
        is_playlist = info.get("_type") in ("playlist", "multi_video") or \
                      "entries" in info

        if is_playlist:
            self._process_playlist(
                info, result, on_item, on_progress, on_error
            )
        else:
            self._process_single(info, result, on_item, on_progress)

        return result

    def parse_async(
        self,
        url:          str,
        *,
        cookies_file: Optional[str]                               = None,
        on_item:      Optional[Callable[[TrackMeta, int, Optional[int]], None]] = None,
        on_progress:  Optional[Callable[[str], None]]            = None,
        on_error:     Optional[Callable[[str], None]]            = None,
        on_done:      Optional[Callable[[ParseResult], None]]    = None,
        daemon:       bool                                        = True,
    ) -> threading.Thread:
        """
        Non-blocking wrapper.  `on_done` is called with the final ParseResult
        once the thread finishes (or is cancelled).
        """
        def _run() -> None:
            result = self.parse(
                url,
                cookies_file=cookies_file,
                on_item=on_item,
                on_progress=on_progress,
                on_error=on_error,
            )
            if on_done:
                try:
                    on_done(result)
                except Exception:  # noqa: BLE001
                    pass

        t = threading.Thread(target=_run, daemon=daemon, name=f"parse-{id(url)}")
        t.start()
        return t

    def cancel(self) -> None:
        """Signal the running parse to stop after the current item."""
        self._cancel.set()

    # ── yt-dlp options ─────────────────────────────────────────────────────────

    @staticmethod
    def _build_opts(cookies_file: Optional[str], logger: Optional[_SilentLogger] = None) -> dict:
        opts: dict = {
            # ── Runtimes ──────────────────────────────────────────────────────
            # Ensure yt-dlp can find a JS runtime (NodeJS/QuickJS etc.) for bot protection
            "js_runtimes": {
                "node": {},
                "quickjs": {},
                "deno": {},
                "bun": {}
            },

            # ── Never download anything ───────────────────────────────────────
            "skip_download":        True,
            "extract_flat":         "in_playlist",  # lightweight: only fetch
                                                    # full info for single items
            # ── Playlist ─────────────────────────────────────────────────────
            "ignoreerrors":         True,   # skip private/geo-blocked entries
            "playlistend":          None,   # no artificial cap

            # ── Network ───────────────────────────────────────────────────────
            "retries":              5,
            "fragment_retries":     5,
            "nocheckcertificate":   False,

            # ── Output suppression ────────────────────────────────────────────
            "quiet":                True,
            "no_warnings":          False,
            "logger":               logger if logger is not None else _SilentLogger(),

            # ── Cookies ───────────────────────────────────────────────────────
            **({"cookiefile": cookies_file} if cookies_file else {}),
            
            # ── Matching Cloudflare Bypass Headers ────────────────────────────
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },

            # ── Age gate bypass ───────────────────────────────────────────────
            "age_limit": 18,

            # ── TLS browser impersonation (curl_cffi) ─────────────────────────
            **({"impersonate": _ImpersonateTarget("chrome")} if _CURL_CFFI_AVAILABLE else {}),
        }
        return opts

    # ── Processing helpers ─────────────────────────────────────────────────────

    def _process_playlist(
        self,
        info:        dict,
        result:      ParseResult,
        on_item:     Optional[Callable],
        on_progress: Optional[Callable],
        on_error:    Optional[Callable],
    ) -> None:
        entries          = list(info.get("entries") or [])
        result.playlist_title = (
            info.get("title")
            or info.get("playlist_title")
            or info.get("id")
            or "Unknown Playlist"
        )
        result.playlist_id    = info.get("id") or ""
        result.total_count    = info.get("playlist_count") \
                                or info.get("n_entries") \
                                or len(entries)

        album    = result.playlist_title
        platform = result.platform

        self._notify(
            on_progress,
            f'Found playlist "{result.playlist_title}" '
            f"– {result.total_count} item(s)"
        )

        for raw_index, entry in enumerate(entries, start=1):
            if self._cancel.is_set():
                result.cancelled = True
                self._notify(on_progress, "Cancelled by user.")
                return

            if entry is None:
                # yt-dlp inserts None for unavailable entries when ignoreerrors=True
                self._notify(
                    on_error,
                    f"Item {raw_index}: unavailable (private / deleted / geo-blocked)."
                )
                continue

            self._notify(
                on_progress,
                f"Processing item {raw_index} / {result.total_count} …"
            )

            try:
                track = _entry_to_track(entry, raw_index, platform, album)
                result.tracks.append(track)
                if on_item:
                    on_item(track, raw_index, result.total_count)
            except Exception as exc:  # noqa: BLE001
                self._notify(
                    on_error,
                    f"Item {raw_index}: failed to parse metadata – {exc}"
                )

        self._notify(
            on_progress,
            f"Done. Resolved {len(result.tracks)} / {result.total_count} items."
        )

    def _process_single(
        self,
        info:        dict,
        result:      ParseResult,
        on_item:     Optional[Callable],
        on_progress: Optional[Callable],
    ) -> None:
        platform = result.platform
        track    = _entry_to_track(info, 1, platform)

        result.playlist_title = track.title
        result.total_count    = 1
        result.tracks.append(track)

        self._notify(on_progress, f'Single item: "{track.title}"')

        if on_item:
            try:
                on_item(track, 1, 1)
            except Exception:  # noqa: BLE001
                pass

    # ── Utility ────────────────────────────────────────────────────────────────

    @staticmethod
    def _notify(callback: Optional[Callable], message: str) -> None:
        if callback:
            try:
                callback(message)
            except Exception:  # noqa: BLE001
                pass


# ──────────────────────────────────────────────────────────────────────────────
# Silent yt-dlp logger  (suppresses console noise while still storing warnings)
# ──────────────────────────────────────────────────────────────────────────────

class _SilentLogger:
    """Plugs into yt-dlp's `logger` option to suppress stdout/stderr noise."""

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.errors:   list[str] = []

    def debug(self, msg: str)   -> None: pass
    def info(self, msg: str)    -> None: pass

    def warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def error(self, msg: str)   -> None:
        self.errors.append(msg)


# ──────────────────────────────────────────────────────────────────────────────
# Convenience one-shot function  (for callers that don't need an instance)
# ──────────────────────────────────────────────────────────────────────────────

def fetch_playlist_metadata(
    url:          str,
    *,
    cookies_file: Optional[str]  = None,
    on_item:      Optional[Callable[[TrackMeta, int, Optional[int]], None]] = None,
    on_progress:  Optional[Callable[[str], None]]  = None,
    on_error:     Optional[Callable[[str], None]]  = None,
) -> ParseResult:
    """
    Module-level convenience wrapper.  Creates a parser, runs it, returns
    the result.  No way to cancel – use PlaylistParser directly for that.

    Returns
    -------
    ParseResult
        .tracks  → list[TrackMeta]  each item has:
                   .index           int          1-based position
                   .title           str
                   .artist          str
                   .album           str          playlist / album name
                   .duration_sec    int | None   raw seconds
                   .duration_str    str          "3:45" or "1:02:30"
                   .url             str          watch / track URL
                   .thumbnail_url   str          best thumbnail URL
                   .platform        SourcePlatform
                   .selected        bool         True (UI default)
    """
    return PlaylistParser().parse(
        url,
        cookies_file=cookies_file,
        on_item=on_item,
        on_progress=on_progress,
        on_error=on_error,
    )


# ──────────────────────────────────────────────────────────────────────────────
# CLI smoke-test  (python playlist_parser.py <url>)
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    _url = (
        sys.argv[1] if len(sys.argv) > 1
        else "https://www.youtube.com/playlist?list=PLbZIPy20-1pM5OX8RMwO6DvYkKfFf2dOq"
    )

    _platform, _kind = classify_url(_url)
    print(f"URL classified as → platform={_platform.name}  kind={_kind.name}\n")

    _col_w = (4, 42, 22, 8, 10)   # column widths

    def _header() -> None:
        print(
            f"{'#':<{_col_w[0]}}  "
            f"{'Title':<{_col_w[1]}}  "
            f"{'Artist':<{_col_w[2]}}  "
            f"{'Duration':<{_col_w[3]}}  "
            f"{'Thumbnail?':<{_col_w[4]}}"
        )
        print("─" * sum(_col_w + (2,) * len(_col_w)))

    _header_printed = False

    def _on_item(track: TrackMeta, idx: int, total: Optional[int]) -> None:
        global _header_printed
        if not _header_printed:
            _header()
            _header_printed = True
        has_thumb = "✓" if track.thumbnail_url else "✗"
        total_str = str(total) if total else "?"
        print(
            f"{idx:<{_col_w[0]}}  "
            f"{track.title[:_col_w[1]]:<{_col_w[1]}}  "
            f"{track.artist[:_col_w[2]]:<{_col_w[2]}}  "
            f"{track.duration_str:<{_col_w[3]}}  "
            f"{has_thumb:<{_col_w[4]}}"
        )

    def _on_progress(msg: str) -> None:
        print(f"  ℹ  {msg}")

    def _on_error(msg: str) -> None:
        print(f"  ⚠  {msg}", file=sys.stderr)

    _result = fetch_playlist_metadata(
        _url,
        on_item=_on_item,
        on_progress=_on_progress,
        on_error=_on_error,
    )

    print()
    print("=" * 60)
    print(_result.summary())

    if _result.error:
        print(f"Error detail: {_result.error}", file=sys.stderr)
        sys.exit(1)
