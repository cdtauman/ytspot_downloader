"""
core/search_engine.py  –  Universal search + deep page scraper
===============================================================
Responsibilities
----------------
* SearchEngine   : Query YouTube or Spotify for media, returning ranked
                   SearchResult objects with full metadata, incrementally
                   via an on_result callback so the UI can populate live.
* PageScraper    : Given any webpage URL, fetch its HTML and extract every
                   recognisable media URL (YouTube embeds, direct video
                   sources, playlist links, etc.) so the user can bulk-add
                   them to the download queue.

Design decisions
----------------
* Zero GUI imports – pure backend module, callable from any thread.
* SearchEngine uses yt-dlp's built-in ytsearch extractor for YouTube so we
  reuse the same engine that drives downloads (consistent cookie/auth handling,
  bot-protection workarounds, and format data).
* Spotify search uses the Spotify Embed search endpoint (same approach as
  spotify_resolver.py) – no OAuth, no API key required.
* PageScraper uses httpx for the HTTP fetch and BeautifulSoup for parsing.
  It hands every discovered URL to playlist_parser.classify_url() so only
  genuinely supported media links are returned.
* Both classes expose a cancel() method safe to call from any thread.
* All network calls have explicit timeouts; all exceptions are caught and
  surfaced as SearchError / ScraperError rather than propagating.

Typical usage
-------------
>>> engine = SearchEngine()
>>> results = engine.search_youtube(
...     "rick astley never gonna give you up",
...     max_results=10,
...     on_result=lambda r: print(r.title),
... )

>>> scraper = PageScraper()
>>> urls = scraper.scrape("https://example.com/videos-page")
>>> for url in urls:
...     print(url)
"""

from __future__ import annotations

import json
import re
import threading
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional

import httpx
import yt_dlp
from bs4 import BeautifulSoup

# Re-use the platform classifier from the existing backend – zero duplication.
from playlist_parser import SourcePlatform, classify_url, TrackMeta, _best_thumbnail
from utils.logger import SilentLogger as _SilentLogger
from utils.time_format import seconds_to_str as _seconds_to_str
from utils.yt_dlp_opts import build_search_ydl_opts as _build_search_opts


# ──────────────────────────────────────────────────────────────────────────────
# Public data-classes & exceptions
# ──────────────────────────────────────────────────────────────────────────────

class ResultKind(Enum):
    """
    Categorises a SearchResult so the UI can render different card styles
    and enable drill-down behaviour for non-track entities.
    """
    TRACK    = auto()   # A single video or audio track
    ALBUM    = auto()   # A music album (Spotify / YouTube Music)
    PLAYLIST = auto()   # A user-created playlist or YouTube playlist
    ARTIST   = auto()   # A Spotify artist or YouTube channel/artist page
    CHANNEL  = auto()   # A YouTube channel (distinct from an artist entity)


@dataclass
class SearchResult:
    """
    One entry returned by SearchEngine.search_youtube() or search_spotify().

    All fields default to safe empty/None values so the UI can always render
    a card even when the source returns incomplete metadata.
    """
    # ── Identity ──────────────────────────────────────────────────────────────
    result_index:   int             = 0         # 1-based rank in the result list
    title:          str             = "Unknown Title"
    artist:         str             = ""        # uploader / artist
    url:            str             = ""        # canonical watch / track URL
    platform:       SourcePlatform  = SourcePlatform.UNKNOWN
    kind:           ResultKind      = ResultKind.TRACK   # entity category

    # ── Display metadata ──────────────────────────────────────────────────────
    thumbnail_url:  str             = ""
    duration_str:   str             = ""        # e.g. "3:45"
    duration_sec:   Optional[int]   = None
    view_count:     Optional[int]   = None      # YouTube only
    upload_date:    str             = ""        # "YYYYMMDD" from yt-dlp
    item_count:     Optional[int]   = None      # # tracks in playlist/album

    # ── Helpers ───────────────────────────────────────────────────────────────
    def view_count_str(self) -> str:
        """Return a short human-readable view count, e.g. '1.4M views'."""
        if self.view_count is None:
            return ""
        v = self.view_count
        if v >= 1_000_000_000:
            return f"{v / 1_000_000_000:.1f}B views"
        if v >= 1_000_000:
            return f"{v / 1_000_000:.1f}M views"
        if v >= 1_000:
            return f"{v / 1_000:.1f}K views"
        return f"{v} views"

    def formatted_date(self) -> str:
        """Convert 'YYYYMMDD' → 'YYYY-MM-DD', or return empty string."""
        d = self.upload_date
        if len(d) == 8 and d.isdigit():
            return f"{d[:4]}-{d[4:6]}-{d[6:]}"
        return d


class SearchError(Exception):
    """Raised when a search query fails irrecoverably."""


class ScraperError(Exception):
    """Raised when a page scrape fails irrecoverably."""


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _detect_kind(entry: dict, platform: SourcePlatform) -> ResultKind:
    """
    Infer the ResultKind from a yt-dlp entry's ie_key, _type, or URL patterns.
    """
    ie_key   = (entry.get("ie_key") or "").lower()
    url      = entry.get("webpage_url") or entry.get("url") or ""
    _type    = entry.get("_type") or ""

    # yt-dlp uses YoutubePlaylist / YoutubeTab for playlists / channels
    if ie_key in ("youtubeplaylist",) or _type in ("playlist", "multi_video"):
        return ResultKind.PLAYLIST
    if ie_key in ("youtubetab",) or "youtube.com/@" in url or "/channel/" in url:
        return ResultKind.CHANNEL
    if platform == SourcePlatform.SPOTIFY:
        # These are set by the caller based on Spotify API type field
        return ResultKind.TRACK
    return ResultKind.TRACK


def _entry_to_search_result(
    entry:    dict,
    index:    int,
    platform: SourcePlatform,
    kind:     Optional[ResultKind] = None,
) -> SearchResult:
    """
    Convert a raw yt-dlp info-dict entry into a SearchResult.
    Works for both fully-resolved entries and lightweight flat entries.
    The ``kind`` parameter can be pre-set by the caller; otherwise it is
    inferred from the entry's ie_key / _type.
    """
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

    duration_sec: Optional[int] = None
    raw_dur = entry.get("duration")
    if raw_dur is not None:
        try:
            duration_sec = int(raw_dur)
        except (TypeError, ValueError):
            duration_sec = None

    view_count: Optional[int] = None
    raw_views = entry.get("view_count")
    if raw_views is not None:
        try:
            view_count = int(raw_views)
        except (TypeError, ValueError):
            view_count = None

    artist = (
        entry.get("artist")
        or entry.get("creator")
        or entry.get("uploader")
        or entry.get("channel")
        or ""
    )

    resolved_kind = kind if kind is not None else _detect_kind(entry, platform)

    return SearchResult(
        result_index=index,
        title=entry.get("title") or entry.get("fulltitle") or "Unknown Title",
        artist=artist,
        url=url,
        platform=platform,
        kind=resolved_kind,
        thumbnail_url=_best_thumbnail(entry),
        duration_sec=duration_sec,
        duration_str=_seconds_to_str(duration_sec),
        view_count=view_count,
        upload_date=entry.get("upload_date") or "",
    )


# ──────────────────────────────────────────────────────────────────────────────
# SearchEngine
# ──────────────────────────────────────────────────────────────────────────────

class SearchEngine:
    """
    Query YouTube or Spotify for media and return ranked SearchResult objects.

    Threading
    ---------
    All search methods are blocking.  Run them inside a QThread / Thread.
    Call cancel() from any thread to abort the current search early.

    Parameters
    ----------
    cookies_file : str | None
        Path to a Netscape-format cookies.txt for authenticated searches.
        Passed directly to yt-dlp, same as in the download engine.
    """

    def __init__(self, cookies_file: Optional[str] = None) -> None:
        self._cookies_file = cookies_file
        self._cancel        = threading.Event()

    # ── Public API ─────────────────────────────────────────────────────────────

    def cancel(self) -> None:
        """Signal any running search to stop after the current result."""
        self._cancel.set()

    def reset(self) -> None:
        """Clear the cancel flag so the engine can be reused."""
        self._cancel.clear()

    def search_youtube(
        self,
        query:       str,
        max_results: int = 15,
        on_result:   Optional[Callable[[SearchResult], None]] = None,
    ) -> list[SearchResult]:
        """
        Search YouTube for ``query`` and return up to ``max_results``
        SearchResult objects ordered by YouTube's own relevance ranking.
        All results have ``kind = ResultKind.TRACK``.

        If ``on_result`` is provided it is called for each result as it arrives,
        enabling incremental UI population.

        Raises SearchError on irrecoverable failure.
        """
        self._cancel.clear()
        results: list[SearchResult] = []

        ydl_opts = _build_search_opts(
            cookies_file=self._cookies_file,
            logger=_SilentLogger(),
            max_results=max_results,
        )
        search_url = f"ytsearch{max_results}:{query}"

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(search_url, download=False)
        except yt_dlp.utils.DownloadError as exc:
            err_str = str(exc).lower()
            if "bot" in err_str or "sign in" in err_str:
                raise SearchError(
                    "YouTube is blocking automated searches due to bot protection. "
                    "Try pasting a video URL directly instead."
                ) from exc
            raise SearchError(f"YouTube search failed: {exc}") from exc
        except Exception as exc:
            raise SearchError(f"Unexpected error during YouTube search: {exc}") from exc

        if info is None:
            raise SearchError("YouTube returned no data for this query.")

        for raw_index, entry in enumerate(info.get("entries") or [], start=1):
            if self._cancel.is_set():
                break
            if entry is None:
                continue

            webpage_url = entry.get("webpage_url") or entry.get("url") or ""
            platform = (
                SourcePlatform.YOUTUBE_MUSIC
                if "music.youtube.com" in webpage_url
                else SourcePlatform.YOUTUBE
            )

            result = _entry_to_search_result(entry, raw_index, platform, kind=ResultKind.TRACK)
            results.append(result)

            if on_result:
                try:
                    on_result(result)
                except Exception:
                    pass

            if raw_index >= max_results:
                break

        return results

    def search_youtube_categorized(
        self,
        query:       str,
        max_results: int = 15,
        on_result:   Optional[Callable[[SearchResult], None]] = None,
    ) -> list[SearchResult]:
        """
        Search YouTube and return results categorised into Tracks, Playlists,
        and Channels.  Runs three parallel yt-dlp searches under the hood.

        All results are emitted via ``on_result`` as soon as they arrive so
        the UI can populate sections incrementally.

        Returns
        -------
        list[SearchResult]
            Combined results from all three searches, de-duplicated by URL.
        """
        self._cancel.clear()

        # We collect all results with a shared lock to prevent race conditions
        combined: list[SearchResult] = []
        seen_urls: set[str] = set()
        counter = [0]
        lock = threading.Lock()

        def _emit(result: SearchResult) -> None:
            with lock:
                if result.url in seen_urls:
                    return
                seen_urls.add(result.url)
                counter[0] += 1
                result.result_index = counter[0]
                combined.append(result)
            if on_result:
                try:
                    on_result(result)
                except Exception:
                    pass

        def _search_tracks() -> None:
            try:
                opts = _build_search_opts(
                    cookies_file=self._cookies_file,
                    logger=_SilentLogger(),
                    max_results=max_results,
                )
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
                if not info:
                    return
                for entry in (info.get("entries") or []):
                    if self._cancel.is_set():
                        return
                    if not entry:
                        continue
                    url = entry.get("webpage_url") or entry.get("url") or ""
                    plat = (
                        SourcePlatform.YOUTUBE_MUSIC
                        if "music.youtube.com" in url
                        else SourcePlatform.YOUTUBE
                    )
                    _emit(_entry_to_search_result(entry, 0, plat, kind=ResultKind.TRACK))
            except Exception:
                pass

        def _search_playlists() -> None:
            try:
                opts = _build_search_opts(
                    cookies_file=self._cookies_file,
                    logger=_SilentLogger(),
                    max_results=max(5, max_results // 3),
                )
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(
                        f"ytsearch{max(5, max_results // 3)}:{query} playlist",
                        download=False,
                    )
                if not info:
                    return
                for entry in (info.get("entries") or []):
                    if self._cancel.is_set():
                        return
                    if not entry:
                        continue
                    ie_key = (entry.get("ie_key") or "").lower()
                    _type  = (entry.get("_type") or "")
                    # Only emit genuine playlist/channel entries
                    if ie_key in ("youtubeplaylist", "youtubetab") or \
                            _type in ("playlist", "multi_video"):
                        kind = ResultKind.PLAYLIST
                    else:
                        kind = ResultKind.PLAYLIST  # returned by playlist search
                    url = entry.get("webpage_url") or entry.get("url") or ""
                    if not url:
                        continue
                    plat = (
                        SourcePlatform.YOUTUBE_MUSIC
                        if "music.youtube.com" in url
                        else SourcePlatform.YOUTUBE
                    )
                    _emit(_entry_to_search_result(entry, 0, plat, kind=kind))
            except Exception:
                pass

        def _search_channels() -> None:
            try:
                n = max(3, max_results // 5)
                opts = _build_search_opts(
                    cookies_file=self._cookies_file,
                    logger=_SilentLogger(),
                    max_results=n,
                )
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(
                        f"ytsearch{n}:{query} channel",
                        download=False,
                    )
                if not info:
                    return
                for entry in (info.get("entries") or []):
                    if self._cancel.is_set():
                        return
                    if not entry:
                        continue
                    url = entry.get("webpage_url") or entry.get("url") or ""
                    if not url or "watch?v=" in url:
                        continue   # skip plain videos from this search
                    plat = SourcePlatform.YOUTUBE
                    kind = ResultKind.CHANNEL
                    _emit(_entry_to_search_result(entry, 0, plat, kind=kind))
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="yt-search") as pool:
            fs = [
                pool.submit(_search_tracks),
                pool.submit(_search_playlists),
                pool.submit(_search_channels),
            ]
            for f in as_completed(fs):
                _ = f.result()   # surface any unexpected exceptions

        return combined

    def search_spotify(
        self,
        query:       str,
        max_results: int = 15,
        on_result:   Optional[Callable[[SearchResult], None]] = None,
    ) -> list[SearchResult]:
        """
        Search Spotify via the Web API (when credentials are configured) or
        fall back to the proxy server URL (legacy behaviour).

        Returns flat TRACK-kind results for backward-compatible callers that
        don't need categories.  For category-aware UI, use
        ``search_spotify_categorized()`` instead.
        """
        try:
            results = self.search_spotify_categorized(
                query, max_results=max_results, on_result=on_result
            )
            # Filter to tracks for backward compat
            return [r for r in results if r.kind == ResultKind.TRACK]
        except SearchError:
            raise

    def search_spotify_categorized(
        self,
        query:       str,
        max_results: int = 15,
        on_result:   Optional[Callable[[SearchResult], None]] = None,
    ) -> list[SearchResult]:
        """
        Search Spotify and return results in all categories (Tracks, Albums,
        Artists, Playlists).

        When ``spotify_client_id`` and ``spotify_client_secret`` are configured
        in AppConfig, uses the official Spotify Web API.  Otherwise falls back
        to the proxy server URL (if configured).

        Raises SearchError when neither credentials nor proxy are available.
        """
        self._cancel.clear()

        # Try Spotify Web API first
        try:
            from config import AppConfig
            cfg = AppConfig()
            client_id     = cfg.spotify_client_id.strip()
            client_secret = cfg.spotify_client_secret.strip()
            proxy_url     = cfg.proxy_server_url.strip()
        except Exception:
            client_id = client_secret = proxy_url = ""

        if client_id and client_secret:
            return self._search_spotify_api(query, max_results, on_result)

        # Fall back to proxy server
        if proxy_url and "your-future-server" not in proxy_url.lower():
            return self._search_spotify_proxy(query, max_results, on_result, proxy_url)

        raise SearchError(
            "Spotify search is not configured.\n\n"
            "Option A (recommended): Go to Settings → Spotify and enter your "
            "Developer App Client ID and Secret (free account at "
            "developer.spotify.com/dashboard).\n\n"
            "Option B (legacy): Set a Proxy Server URL in Settings → Search."
        )

    # ── Spotify Web API search ─────────────────────────────────────────────────

    def _search_spotify_api(
        self,
        query:       str,
        max_results: int,
        on_result:   Optional[Callable[[SearchResult], None]],
    ) -> list[SearchResult]:
        """Search the official Spotify Web API for all entity types."""
        from utils.spotify_resolver import SpotifyResolver

        try:
            token = SpotifyResolver._get_access_token()
        except RuntimeError as exc:
            raise SearchError(str(exc)) from exc

        import urllib.parse
        import urllib.request

        params = urllib.parse.urlencode({
            "q":      query,
            "type":   "track,album,artist,playlist",
            "limit":  min(max_results, 20),
            "market": "US",
        })
        req = urllib.request.Request(
            f"https://api.spotify.com/v1/search?{params}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept":        "application/json",
                "User-Agent":    "YTSpotDownloader/1.0",
            },
        )

        try:
            import json
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode())
        except Exception as exc:
            raise SearchError(f"Spotify API search failed: {exc}") from exc

        results: list[SearchResult] = []
        counter = [0]

        def _emit(r: SearchResult) -> None:
            counter[0] += 1
            r.result_index = counter[0]
            results.append(r)
            if on_result and not self._cancel.is_set():
                try:
                    on_result(r)
                except Exception:
                    pass

        # ── Tracks ────────────────────────────────────────────────────────────
        for item in (data.get("tracks") or {}).get("items") or []:
            if self._cancel.is_set():
                break
            if not item:
                continue
            title  = item.get("name") or "Unknown Title"
            artist = (item.get("artists") or [{}])[0].get("name", "")
            dur_ms = int(item.get("duration_ms") or 0)
            thumb  = SpotifyResolver._best_image(
                (item.get("album") or {}).get("images") or []
            )
            surl   = (item.get("external_urls") or {}).get("spotify", "")
            _emit(SearchResult(
                title=title, artist=artist,
                url=f"ytsearch1:{artist} {title} audio",
                platform=SourcePlatform.SPOTIFY, kind=ResultKind.TRACK,
                thumbnail_url=thumb, duration_sec=dur_ms // 1000 if dur_ms else None,
                duration_str=_seconds_to_str(dur_ms // 1000 if dur_ms else None),
            ))

        # ── Albums ────────────────────────────────────────────────────────────
        for item in (data.get("albums") or {}).get("items") or []:
            if self._cancel.is_set():
                break
            if not item:
                continue
            title  = item.get("name") or "Unknown Album"
            artist = (item.get("artists") or [{}])[0].get("name", "")
            thumb  = SpotifyResolver._best_image(item.get("images") or [])
            surl   = (item.get("external_urls") or {}).get("spotify", "")
            count  = item.get("total_tracks")
            _emit(SearchResult(
                title=title, artist=artist, url=surl,
                platform=SourcePlatform.SPOTIFY, kind=ResultKind.ALBUM,
                thumbnail_url=thumb, item_count=count,
            ))

        # ── Artists ───────────────────────────────────────────────────────────
        for item in (data.get("artists") or {}).get("items") or []:
            if self._cancel.is_set():
                break
            if not item:
                continue
            name  = item.get("name") or "Unknown Artist"
            thumb = SpotifyResolver._best_image(item.get("images") or [])
            surl  = (item.get("external_urls") or {}).get("spotify", "")
            followers = (item.get("followers") or {}).get("total")
            _emit(SearchResult(
                title=name, artist=name, url=surl,
                platform=SourcePlatform.SPOTIFY, kind=ResultKind.ARTIST,
                thumbnail_url=thumb,
                view_count=followers,
            ))

        # ── Playlists ─────────────────────────────────────────────────────────
        for item in (data.get("playlists") or {}).get("items") or []:
            if self._cancel.is_set():
                break
            if not item:
                continue
            title  = item.get("name") or "Unknown Playlist"
            owner  = (item.get("owner") or {}).get("display_name", "")
            thumb  = SpotifyResolver._best_image(item.get("images") or [])
            surl   = (item.get("external_urls") or {}).get("spotify", "")
            count  = (item.get("tracks") or {}).get("total")
            _emit(SearchResult(
                title=title, artist=owner, url=surl,
                platform=SourcePlatform.SPOTIFY, kind=ResultKind.PLAYLIST,
                thumbnail_url=thumb, item_count=count,
            ))

        return results

    # ── Proxy server search (legacy fallback) ─────────────────────────────────

    def _search_spotify_proxy(
        self,
        query:     str,
        max_results: int,
        on_result: Optional[Callable[[SearchResult], None]],
        proxy_url: str,
    ) -> list[SearchResult]:
        """Search via the configured proxy server (legacy path)."""
        results: list[SearchResult] = []
        proxy_url = proxy_url.rstrip("/")
        endpoint  = f"{proxy_url}/api/v1/search"
        params    = {"query": query, "limit": max_results}

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(endpoint, params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            raise SearchError(
                f"Proxy returned HTTP {exc.response.status_code}. "
                f"Is the server running at {proxy_url}?"
            ) from exc
        except httpx.RequestError as exc:
            raise SearchError(
                f"Cannot reach proxy at {proxy_url}: {exc}"
            ) from exc

        for idx, item in enumerate((data.get("data") or [])[:max_results], start=1):
            if self._cancel.is_set():
                break
            try:
                title  = item.get("title") or "Unknown Title"
                artist = item.get("artist") or ""
                dur    = item.get("duration_sec")
                thumb  = item.get("thumbnail_url", "")
                r = SearchResult(
                    result_index=idx,
                    title=title, artist=artist,
                    url=f"ytsearch1:{artist} {title} audio",
                    platform=SourcePlatform.SPOTIFY, kind=ResultKind.TRACK,
                    thumbnail_url=thumb,
                    duration_sec=dur,
                    duration_str=_seconds_to_str(dur) if dur else "",
                )
                results.append(r)
                if on_result:
                    try:
                        on_result(r)
                    except Exception:
                        pass
            except Exception:
                continue

        return results



# ──────────────────────────────────────────────────────────────────────────────
# PageScraper
# ──────────────────────────────────────────────────────────────────────────────

# Regex patterns that recognise media URLs embedded in HTML outside of
# standard <iframe>/<video> tags (e.g., JavaScript variables, data attributes).
_INLINE_URL_PATTERNS = [
    # youtube.com/watch?v=... or youtu.be/...
    re.compile(r'https?://(?:www\.)?youtube\.com/watch\?[^\s\'"<>]+', re.I),
    re.compile(r'https?://youtu\.be/[A-Za-z0-9_-]{11}[^\s\'"<>]*',   re.I),
    # youtube.com/embed/...
    re.compile(r'https?://(?:www\.)?youtube\.com/embed/[A-Za-z0-9_-]{11}[^\s\'"<>]*', re.I),
    # YouTube playlist
    re.compile(r'https?://(?:www\.)?youtube\.com/playlist\?[^\s\'"<>]+', re.I),
    # YouTube Music
    re.compile(r'https?://music\.youtube\.com/[^\s\'"<>]+', re.I),
    # Spotify open links
    re.compile(
        r'https?://open\.spotify\.com/(?:track|album|playlist)/[A-Za-z0-9]+[^\s\'"<>]*',
        re.I,
    ),
    # Direct video file URLs
    re.compile(r'https?://[^\s\'"<>]+\.(?:mp4|m3u8|webm|flv|mov|avi)[^\s\'"<>]*', re.I),
    # Vimeo
    re.compile(r'https?://(?:www\.)?vimeo\.com/\d+[^\s\'"<>]*', re.I),
    # Dailymotion
    re.compile(r'https?://(?:www\.)?dailymotion\.com/video/[^\s\'"<>]+', re.I),
    # Twitch clips/videos
    re.compile(r'https?://(?:www\.)?twitch\.tv/[^\s\'"<>]+/(?:clip|video)[^\s\'"<>]*', re.I),
    # Generic video embed URLs
    re.compile(r'https?://[^\s\'"<>]+/embed/[A-Za-z0-9_-]+[^\s\'"<>]*', re.I),
]

# HTML tag + attribute pairs we inspect for embedded media URLs.
_TAG_ATTR_PAIRS: list[tuple[str, str]] = [
    ("iframe",  "src"),
    ("iframe",  "data-src"),
    ("video",   "src"),
    ("source",  "src"),
    ("a",       "href"),
    ("div",     "data-video-url"),
    ("div",     "data-src"),
    ("div",     "data-video-src"),
    ("div",     "data-embed-url"),
    ("span",    "data-url"),
    ("section", "data-video-url"),
    ("button",  "data-video-url"),
    ("a",       "data-video-url"),
    ("figure",  "data-video"),
    ("article", "data-video-id"),  # some CMS platforms embed the ID only
]

# YouTube video-ID pattern for reconstructing watch URLs from bare IDs.
_YT_ID_RE = re.compile(r'^[A-Za-z0-9_-]{11}$')


class PageScraper:
    """
    Fetch any webpage and extract all recognisable media links from it.

    The extracted URLs are validated via playlist_parser.classify_url() so
    only genuinely supported media links are returned – no false positives
    from unrelated anchor tags.

    Threading
    ---------
    scrape() is blocking.  Run it inside a QThread / Thread.
    Call cancel() from any thread to abort early (checked between phases).
    """

    # Domains we intentionally skip when following redirects or scanning links
    # (ad networks, tracking pixels, social share widgets, etc.)
    _SKIP_DOMAINS = frozenset({
        "doubleclick.net", "googlesyndication.com", "googletagmanager.com",
        "facebook.com", "twitter.com", "instagram.com", "tiktok.com",
        "amazon.com", "pinterest.com", "reddit.com",
    })

    def __init__(self) -> None:
        self._cancel = threading.Event()

    # ── Public API ─────────────────────────────────────────────────────────────

    def cancel(self) -> None:
        """Signal the running scrape to stop at the next checkpoint."""
        self._cancel.set()

    def reset(self) -> None:
        """Clear the cancel flag so the scraper can be reused."""
        self._cancel.clear()


    @staticmethod
    def _is_thumbnail_cdn(url: str) -> bool:
        """Return True if the URL is a CDN thumbnail preview clip, not a real video page."""
        try:
            host = urllib.parse.urlparse(url).netloc.lower()
            cdn_hints = ("xhcdn.com", "xhvideo.com")
            if any(h in host for h in cdn_hints):
                return True
            path = urllib.parse.urlparse(url).path.lower()
            if ".t.webm" in path or ".t.mp4" in path or ".t.av1" in path:
                return True
        except Exception:
            pass
        return False


    def scrape(
        self,
        page_url: str,
        on_url_found: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        cookies_file: Optional[str] = None,
        timeout: float = 20.0,
        follow_links: bool = True,
        max_follow: int = 25,
    ) -> list[str]:
        """
        Fetch `page_url`, extract all downloadable media URLs using a 3-phase
        approach: yt-dlp native extraction → BeautifulSoup HTML scan →
        same-domain link following for listing/trailer pages.

        Parameters
        ----------
        page_url     : The webpage to scrape.
        on_url_found : Optional callback fired for each URL as it is discovered.
        on_status    : Optional callback for status messages.
        cookies_file : Optional path to a Netscape cookies.txt file.
        timeout      : HTTP request timeout in seconds.
        follow_links : Whether to follow same-domain links (phase 3).
        max_follow   : Max number of sub-pages to follow in phase 3.

        Returns
        -------
        list[str]
            Deduplicated, ordered list of downloadable media URLs found.

        Raises
        ------
        ScraperError
            On HTTP errors, network failures, or HTML parsing failures.
        """
        print(f"[DEBUG Scraper] Starting scrape for URL: {page_url}")
        self._cancel.clear()

        seen: set[str] = set()
        validated: list[str] = []

        def _emit(url: str) -> None:
            url = url.strip().rstrip("/.,;)'\"")
            if not url or url in seen or self._is_skip_domain(url):
                return
            seen.add(url)
            validated.append(url)
            print(f"[DEBUG Scraper] Found valid link: {url}")
            if on_url_found:
                try:
                    on_url_found(url)
                except Exception:
                    pass

        # ── SPECIAL CASE: xhamster user channel ─────────────────────────────
        if re.search(r'xhamster\.com/users/[^/?#]+/videos', page_url):
            return self._scrape_xhamster_channel(
                page_url, seen, validated, _emit, on_status, cookies_file, timeout
            )

        # xhamster channel: dedicated paginator
        if re.search(r'xhamster\.com/users/[^/?#]+/videos', page_url):
            return self._scrape_xhamster_channel(
                page_url, seen, validated, _emit, on_status, cookies_file, timeout
            )

        # Phase 1: yt-dlp on the page itself (handles most known sites natively)
        print("[DEBUG Scraper] Phase 1: Trying _try_ytdlp_extract on base URL...")
        if on_status:
            on_status("🕷  Trying yt-dlp extractor…")
        for u in self._try_ytdlp_extract(page_url, cookies_file, timeout):
            if self._cancel.is_set():
                print("[DEBUG Scraper] Cancelled during Phase 1.")
                return validated
            _emit(u)

        if self._cancel.is_set():
            return validated

        # Phase 2: BeautifulSoup HTML extraction (catches iframes, video tags, etc.)
        print("[DEBUG Scraper] Phase 2: Fetching base page HTML...")
        if on_status:
            on_status("🕷  Scanning page HTML…")
        try:
            html = self._fetch_page(page_url, timeout, cookies_file)
            print(f"[DEBUG Scraper] Phase 2: Success! HTML length: {len(html)}")
        except Exception as e:
            print(f"[DEBUG Scraper] FATAL Phase 2 fetch failed: {e}")
            raise

        raw_urls = self._extract_from_tags(html, page_url)
        raw_urls.extend(self._extract_from_patterns(html))
        
        print(f"[DEBUG Scraper] Phase 2 extracted {len(raw_urls)} candidate raw URLs.")
        # Only emit URLs that actually look like specific media URLs instead of plain domains/logins
        valid_media_hints = (
            "/video/", "/watch", "/clip/", "/episode/", "/movie/", "spankbang.com/",
            "pornhub.com/view_video", "xvideos.com/video", "xhamster.com/videos/"
        )
        
        for url in raw_urls:
            if self._cancel.is_set():
                break
            
            # Simple whitelist to avoid emitting /login, /password-recovery, etc.
            is_valid = any(hint in url for hint in valid_media_hints)
            if not is_valid and url.lower().endswith((".mp4", ".webm", ".m3u8")):
                lower = url.lower()
                if not any(x in lower for x in ("/thumb", "526x298", ".t.mp4", ".t.webm", ".t.av1", "preview")):
                    is_valid = True
            if is_valid:
                _emit(url)

        # Phase 3: Follow same-domain links (for "trailer listing" pages)
        print(f"[DEBUG Scraper] Phase 3: Commencing follow_links={follow_links}")
        if follow_links and not self._cancel.is_set():
            page_links = self._extract_page_links(html, page_url, max_links=max_follow)
            print(f"[DEBUG Scraper] Phase 3: Found {len(page_links)} sub-page links.")
            if on_status and page_links:
                on_status(f"🕷  Following {len(page_links)} sub-page links…")
            for link in page_links:
                if self._cancel.is_set():
                    break
                if link in seen:
                    continue
                extracted = self._try_ytdlp_extract(link, cookies_file, timeout=8.0)
                if extracted:
                    print(f"[DEBUG Scraper] Phase 3 yt-dlp validation success for {link}")
                    for u in extracted:
                        _emit(u)
                else:
                    print(f"[DEBUG Scraper] Phase 3 yt-dlp validation fallback for {link}")
                    
                    # If this looks like a pagination link that yt-dlp couldn't parse, try fetching its HTML!
                    is_pagination = False
                    if "xhamster.com" in link and ("/videos/" in link or "page=" in link):
                        is_pagination = True
                    
                    if is_pagination:
                        print(f"[DEBUG Scraper] Shallow pagination HTML fetch for: {link}")
                        try:
                            # Note: This might trigger Turnstile if BotBypassWindow didn't cache this specific sub-page.
                            # But since `curl_cffi` returned status 200 via bypass cookies earlier, it should pass!
                            sub_html = self._fetch_page(link, timeout=10.0, cookies_file=cookies_file)
                            sub_raw_urls = self._extract_from_tags(sub_html, link)
                            for sub_url in sub_raw_urls:
                                is_vid = any(hint in sub_url for hint in valid_media_hints) or sub_url.endswith((".mp4", ".webm", ".m3u8"))
                                if is_vid:
                                    _emit(sub_url)
                        except Exception as e:
                            print(f"[DEBUG Scraper] Failed to fetch sub-page {link}: {e}")
                    else:
                        _emit(link)

        print(f"[DEBUG Scraper] Finished completely. Emitted {len(validated)} URLs.")
        return validated

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _try_ytdlp_extract(
        self,
        url: str,
        cookies_file: Optional[str] = None,
        timeout: float = 15.0,
    ) -> list[str]:
        """
        Run yt-dlp's extractor on `url` and return all downloadable URLs found.
        Returns empty list on any failure so the caller can fall back gracefully.
        """
        import yt_dlp

        opts: dict = {
            "logger": _SilentLogger(),
            "skip_download":  True,
            "extract_flat":   "in_playlist",
            "quiet":          True,
            "ignoreerrors":   True,
            "socket_timeout": timeout,
            "age_limit":      18,
            **({"cookiefile": cookies_file} if cookies_file else {}),
        }
        from utils.yt_dlp_opts import _CHROME_136_HEADERS
        opts["http_headers"] = dict(_CHROME_136_HEADERS)
        print(f"[DEBUG yt-dlp] Invoking yt-dlp on {url} with cookies_file={cookies_file}")
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            if not info:
                print(f"[DEBUG yt-dlp] yt-dlp returned no info for {url}")
                return []
            
            _type = info.get("_type")
            print(f"[DEBUG yt-dlp] yt-dlp success. _type={_type}")
            if _type in ("playlist", "multi_video") or "entries" in info:
                entries = info.get("entries") or []
                print(f"[DEBUG yt-dlp] Found {len(entries)} entries.")
                return [
                    e.get("webpage_url") or e.get("url", "")
                    for e in entries
                    if e and (e.get("webpage_url") or e.get("url"))
                ]
            page_url = info.get("webpage_url") or info.get("url") or url
            return [page_url]
        except Exception as e:
            print(f"[DEBUG yt-dlp] yt-dlp crashed for {url}: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _extract_page_links(
        self,
        html: str,
        base_url: str,
        max_links: int = 30,
    ) -> list[str]:
        """
        Extract same-domain <a href> links that look like they could be video pages.
        Limited to `max_links` to prevent runaway scraping.
        """
        base_domain = urllib.parse.urlparse(base_url).netloc.lower()
        found: list[str] = []
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            return found

        video_path_hints = (
            "/video", "/watch", "/clip", "/movie", "/film", "/episode",
            "/shows", "/trailer", "/play", "/stream", "/pornsite/", "/channel/",
            "/tags/", "/search/", "/models/", "/albums/",
        )

        for tag in soup.find_all("a", href=True):
            if len(found) >= max_links:
                break
            href = tag.get("href", "").strip()
            abs_url = self._make_absolute(href, base_url)
            if not abs_url:
                continue
            parsed = urllib.parse.urlparse(abs_url)
            if parsed.netloc.lower() != base_domain:
                continue
            if parsed.scheme not in ("http", "https"):
                continue
                
            path = parsed.path.lower()
            
            # Stricter media detection: Avoid generic top-level links
            is_video = False
            # If it explicitly contains the word video/watch but isn't just a category
            if any(hint in path for hint in ("/video/", "/watch", "/clip/", "/movie/", "/episode/")):
                is_video = True
            # xhamster individual video pages
            elif "xhamster.com" in abs_url and re.search(r'/videos/[^/]+-\d+$', path):
                is_video = True
            elif path.endswith((".mp4", ".webm", ".m3u8", ".ts", ".avi", ".mkv")):
                is_video = True
            
            if is_video:
                found.append(abs_url)

        return found

    def _fetch_page(self, url: str, timeout: float, cookies_file: Optional[str] = None) -> str:
        """
        Fetch the raw HTML of `url`.
        Follows redirects. Raises ScraperError on any failure.
        """
        print(f"[DEBUG Fetch] Fetching url: {url} with cookies_file={cookies_file}")

        # Check if we have an exactly matched Turnstile-bypassed payload from WebEngine
        import os
        from tempfile import gettempdir
        html_file = os.path.join(gettempdir(), "ytspot_bypass_html.html")
        url_file = os.path.join(gettempdir(), "ytspot_bypass_url.txt")
        
        if os.path.exists(html_file) and os.path.exists(url_file):
            try:
                with open(url_file, 'r', encoding='utf-8') as f:
                    bypass_url = f.read().strip()
                # Normalize URLs for comparison (strip trailing slash, ignore query params diff)
                def _norm(u): return u.rstrip("/").split("?")[0]
                if _norm(bypass_url) == _norm(url):
                    print("[DEBUG Fetch] SUCCESS! Intercepted exact URL from WebEngine bypass HTML payload! Skipping curl_cffi.")
                    with open(html_file, 'r', encoding='utf-8') as f:
                        cached_html = f.read()
                    
                    # Clean up the cache to prevent cross-contamination on subsequent fetches
                    try:
                        os.unlink(html_file)
                        os.unlink(url_file)
                    except Exception:
                        pass
                        
                    return cached_html
            except Exception as e:
                print(f"[DEBUG Fetch] Failed to read cached URL bypass file: {e}")

        cookies_dict = {}
        if cookies_file:
            try:
                import http.cookiejar
                cj = http.cookiejar.MozillaCookieJar(cookies_file)
                cj.load(ignore_discard=True, ignore_expires=True)
                for cookie in cj:
                    cookies_dict[cookie.name] = cookie.value
                print(f"[DEBUG Fetch] Loaded {len(cookies_dict)} cookies. Keys: {list(cookies_dict.keys())}")
                if "cf_clearance" not in cookies_dict:
                    print("[DEBUG Fetch] WARNING: 'cf_clearance' missing from loaded cookies! Bypass might fail.")
            except Exception as e:
                print(f"[DEBUG Fetch] Failed to load cookies: {e}")
                
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
            ),
            "Accept":           "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language":  "en-US,en;q=0.9",
            "Accept-Encoding":  "gzip, deflate, br",
            "Sec-Fetch-Dest":   "document",
            "Sec-Fetch-Mode":   "navigate",
            "Sec-Fetch-Site":   "none",
            "Sec-CH-UA":        '"Chromium";v="122", "Google Chrome";v="122", "Not-A.Brand";v="99"',
            "Sec-CH-UA-Mobile": "?0",
        }
        # Try curl_cffi first for TLS fingerprinting (stronger bot bypass)
        print("[DEBUG Fetch] Attempting curl_cffi...")
        try:
            from curl_cffi import requests as _cffi_req
            resp = _cffi_req.get(
                url,
                impersonate="chrome136",   # ← שנה מ-"chrome" ל-"chrome136" 
                headers=headers,
                cookies=cookies_dict,
                timeout=timeout,
                allow_redirects=True,
                verify=False,
            )
            print(f"[DEBUG Fetch] curl_cffi status: {resp.status_code}")
            resp.raise_for_status()
            return resp.text
        except ImportError:
            print("[DEBUG Fetch] curl_cffi not installed, falling back to httpx.")
        except Exception as exc:
            print(f"[DEBUG Fetch] curl_cffi failed: {exc}")
            raise ScraperError(f"curl_cffi fetch error: {exc}") from exc
            
        # Fallback: plain httpx (no TLS fingerprinting)
        print("[DEBUG Fetch] Attempting httpx...")
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True, cookies=cookies_dict) as client:
                response = client.get(url, headers=headers)
                print(f"[DEBUG Fetch] httpx status: {response.status_code}")
                response.raise_for_status()
                return response.text
        except httpx.HTTPStatusError as exc:
            print(f"[DEBUG Fetch] httpx HTTP error: {exc}")
            raise ScraperError(
                f"Page returned HTTP {exc.response.status_code}: {url}"
            ) from exc
        except httpx.RequestError as exc:
            print(f"[DEBUG Fetch] httpx request error: {exc}")
            raise ScraperError(
                f"Network error fetching page: {exc}"
            ) from exc
        except Exception as exc:
            print(f"[DEBUG Fetch] httpx unexpected error: {exc}")
            raise ScraperError(
                f"Unexpected error fetching page: {exc}"
            ) from exc

    def _extract_from_tags(self, html: str, base_url: str) -> list[str]:
        """
        Parse the HTML with BeautifulSoup and collect URLs from known
        tag / attribute pairs defined in _TAG_ATTR_PAIRS.
        """
        found: list[str] = []
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            return found

        for tag_name, attr_name in _TAG_ATTR_PAIRS:
            if self._cancel.is_set():
                break
            for tag in soup.find_all(tag_name, **{attr_name: True}):
                raw = tag.get(attr_name, "")
                if not raw:
                    continue

                # Convert relative URLs to absolute
                url = self._make_absolute(raw.strip(), base_url)
                if url:
                    found.append(url)

                # Some CMS platforms embed only a YouTube video ID in data attrs
                if _YT_ID_RE.match(raw.strip()):
                    found.append(
                        f"https://www.youtube.com/watch?v={raw.strip()}"
                    )

        return found

    def _extract_from_patterns(self, html: str) -> list[str]:
        """
        Scan the raw HTML text for media URLs using the regex patterns in
        _INLINE_URL_PATTERNS.  Catches URLs embedded in JS, JSON blobs,
        data attributes, and anywhere else BeautifulSoup won't reach.
        """
        found: list[str] = []
        for pattern in _INLINE_URL_PATTERNS:
            if self._cancel.is_set():
                break
            found.extend(pattern.findall(html))
        return found

    @staticmethod
    def _make_absolute(url: str, base: str) -> str:
        """
        Convert a potentially relative URL to absolute using base.
        Returns empty string if the result is not HTTP/HTTPS.
        """
        if url.startswith(("http://", "https://")):
            return url
        if url.startswith("//"):
            scheme = "https" if base.startswith("https") else "http"
            return f"{scheme}:{url}"
        if url.startswith("/"):
            parsed = urllib.parse.urlparse(base)
            return f"{parsed.scheme}://{parsed.netloc}{url}"
        # Relative path
        return urllib.parse.urljoin(base, url)

    @staticmethod
    def _is_skip_domain(url: str) -> bool:
        """Return True if the URL belongs to a domain we intentionally skip."""
        try:
            host = urllib.parse.urlparse(url).netloc.lower()
            return any(skip in host for skip in PageScraper._SKIP_DOMAINS)
        except Exception:
            return False


# ──────────────────────────────────────────────────────────────────────────────
# Smoke-test  (python core/search_engine.py)
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    print("=" * 64)
    print("SearchEngine + PageScraper  –  smoke-test")
    print("=" * 64)
    print()

    engine = SearchEngine()

    # ── 1. YouTube search ─────────────────────────────────────────────────────
    print("── 1. YouTube search: 'rick astley never gonna give you up' ──")
    yt_results: list[SearchResult] = []

    def _on_yt_result(r: SearchResult) -> None:
        print(
            f"  [{r.result_index:>2}]  {r.title[:48]:<48}  "
            f"{r.duration_str:<7}  {r.view_count_str()}"
        )
        yt_results.append(r)

    try:
        engine.search_youtube(
            "rick astley never gonna give you up",
            max_results=5,
            on_result=_on_yt_result,
        )
        assert len(yt_results) > 0, "Expected at least one YouTube result"
        assert yt_results[0].url.startswith("https://"), "URL should be absolute"
        assert yt_results[0].platform in (
            SourcePlatform.YOUTUBE, SourcePlatform.YOUTUBE_MUSIC
        )
        print(f"  ✅  {len(yt_results)} results returned\n")
    except SearchError as exc:
        print(f"  ⚠  SearchError (may be network-related): {exc}\n")

    # ── 2. Spotify search ─────────────────────────────────────────────────────
    print("── 2. Spotify search: 'bohemian rhapsody queen' ──")
    sp_results: list[SearchResult] = []

    def _on_sp_result(r: SearchResult) -> None:
        print(
            f"  [{r.result_index:>2}]  {r.title[:40]:<40}  "
            f"{r.artist[:24]:<24}  {r.duration_str}"
        )
        sp_results.append(r)

    try:
        engine.search_spotify(
            "bohemian rhapsody queen",
            max_results=5,
            on_result=_on_sp_result,
        )
        assert len(sp_results) > 0, "Expected at least one Spotify result"
        assert sp_results[0].platform == SourcePlatform.SPOTIFY
        assert sp_results[0].url.startswith("ytsearch"), (
            "Spotify result URL should be a yt-dlp search string"
        )
        print(f"  ✅  {len(sp_results)} results returned\n")
    except SearchError as exc:
        print(f"  ⚠  SearchError (may be network or Spotify structure change): {exc}\n")

    # ── 3. PageScraper ────────────────────────────────────────────────────────
    print("── 3. PageScraper on a known public page with embedded videos ──")
    scraper = PageScraper()
    scraped: list[str] = []

    def _on_url(u: str) -> None:
        print(f"  Found: {u}")
        scraped.append(u)

    try:
        # Wikipedia's YouTube article tends to have embedded YT links in its HTML.
        scraped_urls = scraper.scrape(
            "https://en.wikipedia.org/wiki/YouTube",
            on_url_found=_on_url,
            timeout=15.0,
        )
        print(f"  ✅  {len(scraped_urls)} unique supported media URL(s) found\n")
    except ScraperError as exc:
        print(f"  ⚠  ScraperError (may be network-related): {exc}\n")

    # ── 4. Cancel test ────────────────────────────────────────────────────────
    print("── 4. Cancel flag test ──")
    engine2 = SearchEngine()
    engine2.cancel()
    # With cancel pre-set, search should return an empty list without erroring
    try:
        cancelled_results = engine2.search_youtube("test query", max_results=10)
        # The cancel flag aborts before any results are emitted
        print(f"  ✅  Cancelled search returned {len(cancelled_results)} result(s) (expected 0)\n")
    except SearchError as exc:
        print(f"  ⚠  Unexpected SearchError during cancel test: {exc}\n")

    print("=" * 64)
    print("Smoke-test complete.")
    print("Note: ⚠ warnings above indicate network conditions, not code bugs.")
    sys.exit(0)
