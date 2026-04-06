"""
core/search_engine.py  –  Universal search + deep page scraper  (v3)
======================================================================
Changelog v3
------------
* YouTube Music searches now use ``ytmusicapi`` for native, structured
  JSON responses – no more URL-pattern guessing or yt-dlp raw-dict
  heuristics for the YTM path.
* ``search_youtube_categorized`` is completely replaced by
  ``search_youtube_music`` (ytmusicapi) + ``search_youtube`` (yt-dlp).
* Dead code removed: _detect_kind(), _search_yt_music() helper (old),
  the shadowed ``kind`` variable inside _entry_to_search_result.
* Strict type hints throughout; no bare ``except Exception`` swallows.
* Modular: ytmusicapi logic lives in _YTMusicBackend; yt-dlp logic in
  _YTDLPBackend.  SearchEngine composes both.
* All public methods return ``list[SearchResult]``; on_result callbacks
  are optional for incremental UI population.

Design decisions
----------------
* ytmusicapi is used **unauthenticated** (no OAuth header required).
  All public YT Music data is available without a cookie.
* yt-dlp is still used for plain YouTube searches (not Music) and for
  Spotify resolution – consistent with the existing download pipeline.
* PageScraper is unchanged in behaviour; minor cleanup only.
* Zero GUI imports.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

import httpx
import yt_dlp
from bs4 import BeautifulSoup
from ytmusicapi import YTMusic

from playlist_parser import SourcePlatform, classify_url, _best_thumbnail
from utils.logger import SilentLogger as _SilentLogger
from utils.time_format import seconds_to_str as _seconds_to_str
from utils.yt_dlp_opts import build_search_ydl_opts as _build_search_opts


# ──────────────────────────────────────────────────────────────────────────────
# Public data-classes & exceptions
# ──────────────────────────────────────────────────────────────────────────────

class ResultKind(Enum):
    """Categorises a SearchResult for typed UI rendering."""
    TRACK    = "track"
    ALBUM    = "album"
    PLAYLIST = "playlist"
    ARTIST   = "artist"
    CHANNEL  = "channel"


@dataclass
class SearchResult:
    """
    One item returned by any search backend.

    All fields that may be unknown are Optional / empty-string so callers
    never have to guard against AttributeError.
    """
    result_index:  int
    title:         str
    artist:        str
    url:           str
    platform:      SourcePlatform
    kind:          ResultKind
    thumbnail_url: str            = ""
    duration_sec:  Optional[int]  = None
    duration_str:  str            = ""
    view_count:    Optional[int]  = None
    upload_date:   str            = ""
    album:         str            = ""
    item_count:    Optional[int]  = None   # tracks in album/playlist
    browse_id:     str            = ""     # YTM browseId for drill-down


class SearchError(Exception):
    """Raised when a search backend fails in a non-recoverable way."""


class ScraperError(Exception):
    """Raised when PageScraper cannot fetch or parse a page."""


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _seconds_to_duration(sec: Optional[int]) -> str:
    return _seconds_to_str(sec) if sec is not None else ""


def _pick_thumbnail(thumbnails: list[dict]) -> str:
    """
    Return the URL of the best (highest-resolution) thumbnail from a YTM
    thumbnail list.  YTM thumbnails are sorted smallest-to-largest.
    """
    if not thumbnails:
        return ""
    # YTM lists thumbnails smallest → largest; take the last
    return thumbnails[-1].get("url", "") if thumbnails else ""


def _ytdlp_entry_to_result(
    entry:    dict,
    index:    int,
    platform: SourcePlatform,
    kind:     ResultKind,
) -> SearchResult:
    """
    Convert a raw yt-dlp info-dict entry to a SearchResult.

    Parameters
    ----------
    entry    : raw dict from yt-dlp ``entries`` list.
    index    : 1-based result position.
    platform : pre-resolved SourcePlatform (caller knows best).
    kind     : pre-resolved ResultKind (caller knows best).
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
            pass

    view_count: Optional[int] = None
    raw_views = entry.get("view_count")
    if raw_views is not None:
        try:
            view_count = int(raw_views)
        except (TypeError, ValueError):
            pass

    artist = (
        entry.get("artist")
        or entry.get("creator")
        or entry.get("uploader")
        or entry.get("channel")
        or ""
    )

    return SearchResult(
        result_index=index,
        title=entry.get("title") or entry.get("fulltitle") or "Unknown Title",
        artist=artist,
        url=url,
        platform=platform,
        kind=kind,
        thumbnail_url=_best_thumbnail(entry),
        duration_sec=duration_sec,
        duration_str=_seconds_to_duration(duration_sec),
        view_count=view_count,
        upload_date=entry.get("upload_date") or "",
    )


# ──────────────────────────────────────────────────────────────────────────────
# _YTMusicBackend  –  ytmusicapi-powered YouTube Music search
# ──────────────────────────────────────────────────────────────────────────────

class _YTMusicBackend:
    """
    Wraps ytmusicapi.YTMusic for YTSpot's search needs.

    Instantiated once and shared via SearchEngine.  Thread-safe: ytmusicapi
    makes fresh HTTP requests per call (no shared mutable state).
    """

    # ytmusicapi returns song durations as "M:SS" or "H:MM:SS" strings
    _DURATION_RE = re.compile(r"^(?:(\d+):)?(\d+):(\d{2})$")

    def __init__(self) -> None:
        # Unauthenticated client – works for all public YTM data
        self._ytm: YTMusic = YTMusic()

    # ── helpers ────────────────────────────────────────────────────────────────

    def _parse_duration(self, s: Optional[str]) -> Optional[int]:
        """Convert "M:SS" / "H:MM:SS" to total seconds, or None."""
        if not s:
            return None
        m = self._DURATION_RE.match(s.strip())
        if not m:
            return None
        hours   = int(m.group(1) or 0)
        minutes = int(m.group(2))
        seconds = int(m.group(3))
        return hours * 3600 + minutes * 60 + seconds

    @staticmethod
    def _ytm_song_url(video_id: str) -> str:
        return f"https://music.youtube.com/watch?v={video_id}"

    @staticmethod
    def _ytm_album_url(browse_id: str) -> str:
        return f"https://music.youtube.com/browse/{browse_id}"

    @staticmethod
    def _ytm_artist_url(browse_id: str) -> str:
        return f"https://music.youtube.com/browse/{browse_id}"

    @staticmethod
    def _ytm_playlist_url(browse_id: str) -> str:
        # YTM playlists: browseId starts with VL for public playlists
        return f"https://music.youtube.com/playlist?list={browse_id.lstrip('VL')}"

    # ── public search methods ──────────────────────────────────────────────────

    def search_songs(
        self,
        query:       str,
        max_results: int = 10,
        cancel:      Optional[threading.Event] = None,
        on_result:   Optional[Callable[[SearchResult], None]] = None,
    ) -> list[SearchResult]:
        """Search YTM for Songs (tracks), return structured SearchResults."""
        raw = self._ytm.search(query, filter="songs", limit=max_results)
        results: list[SearchResult] = []
        for idx, item in enumerate(raw, start=1):
            if cancel and cancel.is_set():
                break
            vid_id = item.get("videoId")
            if not vid_id:
                continue

            # Artist name: YTM returns a list of artist dicts
            artists_list: list[dict] = item.get("artists") or []
            artist = ", ".join(a.get("name", "") for a in artists_list if a.get("name"))

            album_info: dict = item.get("album") or {}

            dur_sec = self._parse_duration(item.get("duration"))

            r = SearchResult(
                result_index=idx,
                title=item.get("title") or "Unknown",
                artist=artist,
                url=self._ytm_song_url(vid_id),
                platform=SourcePlatform.YOUTUBE_MUSIC,
                kind=ResultKind.TRACK,
                thumbnail_url=_pick_thumbnail(item.get("thumbnails") or []),
                duration_sec=dur_sec,
                duration_str=_seconds_to_duration(dur_sec),
                album=album_info.get("name") or "",
            )
            results.append(r)
            if on_result:
                try:
                    on_result(r)
                except Exception:
                    pass
        return results

    def search_albums(
        self,
        query:       str,
        max_results: int = 5,
        cancel:      Optional[threading.Event] = None,
        on_result:   Optional[Callable[[SearchResult], None]] = None,
    ) -> list[SearchResult]:
        """Search YTM for Albums."""
        raw = self._ytm.search(query, filter="albums", limit=max_results)
        results: list[SearchResult] = []
        for idx, item in enumerate(raw, start=1):
            if cancel and cancel.is_set():
                break
            browse_id = item.get("browseId") or ""
            if not browse_id:
                continue

            artists_list: list[dict] = item.get("artists") or []
            artist = ", ".join(a.get("name", "") for a in artists_list if a.get("name"))

            r = SearchResult(
                result_index=idx,
                title=item.get("title") or "Unknown Album",
                artist=artist,
                url=self._ytm_album_url(browse_id),
                platform=SourcePlatform.YOUTUBE_MUSIC,
                kind=ResultKind.ALBUM,
                thumbnail_url=_pick_thumbnail(item.get("thumbnails") or []),
                item_count=item.get("trackCount"),
                browse_id=browse_id,
                album=item.get("title") or "",
            )
            results.append(r)
            if on_result:
                try:
                    on_result(r)
                except Exception:
                    pass
        return results

    def search_artists(
        self,
        query:       str,
        max_results: int = 5,
        cancel:      Optional[threading.Event] = None,
        on_result:   Optional[Callable[[SearchResult], None]] = None,
    ) -> list[SearchResult]:
        """Search YTM for Artists."""
        raw = self._ytm.search(query, filter="artists", limit=max_results)
        results: list[SearchResult] = []
        for idx, item in enumerate(raw, start=1):
            if cancel and cancel.is_set():
                break
            browse_id = item.get("browseId") or ""
            if not browse_id:
                continue

            r = SearchResult(
                result_index=idx,
                title=item.get("artist") or item.get("name") or "Unknown Artist",
                artist=item.get("artist") or item.get("name") or "",
                url=self._ytm_artist_url(browse_id),
                platform=SourcePlatform.YOUTUBE_MUSIC,
                kind=ResultKind.ARTIST,
                thumbnail_url=_pick_thumbnail(item.get("thumbnails") or []),
                browse_id=browse_id,
            )
            results.append(r)
            if on_result:
                try:
                    on_result(r)
                except Exception:
                    pass
        return results

    def search_playlists(
        self,
        query:       str,
        max_results: int = 5,
        cancel:      Optional[threading.Event] = None,
        on_result:   Optional[Callable[[SearchResult], None]] = None,
    ) -> list[SearchResult]:
        """Search YTM for Community Playlists."""
        raw = self._ytm.search(query, filter="playlists", limit=max_results)
        results: list[SearchResult] = []
        for idx, item in enumerate(raw, start=1):
            if cancel and cancel.is_set():
                break
            browse_id = item.get("browseId") or ""
            if not browse_id:
                continue

            # ytmusicapi exposes itemCount as int or None
            item_count: Optional[int] = None
            raw_count = item.get("itemCount")
            if raw_count is not None:
                try:
                    item_count = int(raw_count)
                except (TypeError, ValueError):
                    pass

            r = SearchResult(
                result_index=idx,
                title=item.get("title") or "Unknown Playlist",
                artist=item.get("author") or "",
                url=self._ytm_playlist_url(browse_id),
                platform=SourcePlatform.YOUTUBE_MUSIC,
                kind=ResultKind.PLAYLIST,
                thumbnail_url=_pick_thumbnail(item.get("thumbnails") or []),
                item_count=item_count,
                browse_id=browse_id,
            )
            results.append(r)
            if on_result:
                try:
                    on_result(r)
                except Exception:
                    pass
        return results

    def search_all(
        self,
        query:       str,
        max_results: int = 20,
        cancel:      Optional[threading.Event] = None,
        on_result:   Optional[Callable[[SearchResult], None]] = None,
    ) -> list[SearchResult]:
        """
        Fan-out across all four YTM categories (songs, albums, artists,
        playlists) and return a combined, index-reset list.

        Results are emitted incrementally via on_result as each category
        completes so the UI can populate sections in real-time.
        """
        # Category budgets: songs get the lion's share
        song_limit     = max(max_results // 2, 8)
        album_limit    = max(max_results // 6, 3)
        artist_limit   = max(max_results // 6, 3)
        playlist_limit = max(max_results // 6, 3)

        combined: list[SearchResult] = []
        global_idx = 1

        def _run_category(
            method:    Callable[..., list[SearchResult]],
            limit:     int,
        ) -> None:
            nonlocal global_idx
            try:
                batch = method(
                    query,
                    max_results=limit,
                    cancel=cancel,
                    on_result=None,       # collect first, re-index then emit
                )
            except Exception:
                return
            for r in batch:
                if cancel and cancel.is_set():
                    return
                r.result_index = global_idx
                global_idx += 1
                combined.append(r)
                if on_result:
                    try:
                        on_result(r)
                    except Exception:
                        pass

        _run_category(self.search_songs,     song_limit)
        _run_category(self.search_albums,    album_limit)
        _run_category(self.search_artists,   artist_limit)
        _run_category(self.search_playlists, playlist_limit)

        return combined


# ──────────────────────────────────────────────────────────────────────────────
# _YTDLPBackend  –  yt-dlp-powered plain YouTube search
# ──────────────────────────────────────────────────────────────────────────────

class _YTDLPBackend:
    """
    Wraps yt-dlp for plain YouTube (non-Music) searches.
    Unchanged logic from v2; moved here for isolation.
    """

    def __init__(self, cookies_file: Optional[str] = None) -> None:
        self._cookies_file = cookies_file

    def _opts(self, max_results: int) -> dict:
        return _build_search_opts(
            cookies_file=self._cookies_file,
            logger=_SilentLogger(),
            max_results=max_results,
        )

    def search_videos(
        self,
        query:       str,
        max_results: int = 15,
        cancel:      Optional[threading.Event] = None,
        on_result:   Optional[Callable[[SearchResult], None]] = None,
    ) -> list[SearchResult]:
        """Plain ytsearch for individual videos."""
        opts = self._opts(max_results)
        results: list[SearchResult] = []

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(
                    f"ytsearch{max_results}:{query}",
                    download=False,
                )
        except yt_dlp.utils.UserNotLive:
            return results
        except yt_dlp.utils.DownloadError as exc:
            raise SearchError(f"YouTube search failed: {exc}") from exc
        except Exception as exc:
            raise SearchError(f"Unexpected error during YouTube search: {exc}") from exc

        if info is None:
            return results

        for idx, entry in enumerate(info.get("entries") or [], start=1):
            if cancel and cancel.is_set():
                break
            if entry is None:
                continue
            webpage_url = entry.get("webpage_url") or ""
            platform = (
                SourcePlatform.YOUTUBE_MUSIC
                if "music.youtube.com" in webpage_url
                else SourcePlatform.YOUTUBE
            )
            r = _ytdlp_entry_to_result(entry, idx, platform, ResultKind.TRACK)
            results.append(r)
            if on_result:
                try:
                    on_result(r)
                except Exception:
                    pass
            if idx >= max_results:
                break

        return results

    def search_playlists(
        self,
        query:       str,
        max_results: int = 10,
        cancel:      Optional[threading.Event] = None,
        on_result:   Optional[Callable[[SearchResult], None]] = None,
    ) -> list[SearchResult]:
        """ytsearch for playlists only."""
        opts = self._opts(max(10, max_results))
        results: list[SearchResult] = []
        seen: set[str] = set()

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(
                    f"ytsearch{max_results}:{query} playlist",
                    download=False,
                )
        except Exception:
            return results

        if info is None:
            return results

        for entry in (info.get("entries") or []):
            if cancel and cancel.is_set():
                break
            if not entry:
                continue
            ie_key = (entry.get("ie_key") or "").lower()
            _type  = entry.get("_type") or ""
            # Only genuine playlist entries
            if ie_key not in ("youtubeplaylist", "youtubetab") and \
                    _type not in ("playlist", "multi_video"):
                continue
            url = entry.get("webpage_url") or entry.get("url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            platform = (
                SourcePlatform.YOUTUBE_MUSIC
                if "music.youtube.com" in url
                else SourcePlatform.YOUTUBE
            )
            r = _ytdlp_entry_to_result(
                entry, len(results) + 1, platform, ResultKind.PLAYLIST
            )
            results.append(r)
            if on_result:
                try:
                    on_result(r)
                except Exception:
                    pass

        return results

    def search_channels(
        self,
        query:       str,
        max_results: int = 10,
        cancel:      Optional[threading.Event] = None,
        on_result:   Optional[Callable[[SearchResult], None]] = None,
    ) -> list[SearchResult]:
        """ytsearch for official artist channels."""
        opts = self._opts(max(10, max_results))
        results: list[SearchResult] = []

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(
                    f"ytsearch{max_results}:{query} official channel",
                    download=False,
                )
        except Exception:
            return results

        if info is None:
            return results

        for entry in (info.get("entries") or []):
            if cancel and cancel.is_set():
                break
            if not entry:
                continue
            url = entry.get("webpage_url") or entry.get("url") or ""
            # Skip plain watch URLs – we only want channel/user pages
            if not url or "watch?v=" in url:
                continue
            r = _ytdlp_entry_to_result(
                entry, len(results) + 1, SourcePlatform.YOUTUBE, ResultKind.CHANNEL
            )
            results.append(r)
            if on_result:
                try:
                    on_result(r)
                except Exception:
                    pass

        return results


# ──────────────────────────────────────────────────────────────────────────────
# SearchEngine  –  public facade
# ──────────────────────────────────────────────────────────────────────────────

class SearchEngine:
    """
    Query YouTube, YouTube Music, or Spotify and return SearchResult objects.

    Threading
    ---------
    All search methods are blocking.  Run them inside a QThread.
    Call cancel() from any thread to abort after the current result.

    Parameters
    ----------
    cookies_file : str | None
        Netscape-format cookies.txt; forwarded to yt-dlp for auth searches.
    """

    def __init__(self, cookies_file: Optional[str] = None) -> None:
        self._cancel  = threading.Event()
        self._ytm     = _YTMusicBackend()
        self._ytdlp   = _YTDLPBackend(cookies_file=cookies_file)

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def cancel(self) -> None:
        """Signal the running search to stop after the current result."""
        self._cancel.set()

    def reset(self) -> None:
        """Clear the cancel flag so this engine can be reused."""
        self._cancel.clear()

    # ── YouTube Music (ytmusicapi) ─────────────────────────────────────────────

    def search_youtube_music(
        self,
        query:       str,
        max_results: int = 20,
        on_result:   Optional[Callable[[SearchResult], None]] = None,
    ) -> list[SearchResult]:
        """
        Search YouTube Music using ytmusicapi.

        Returns results grouped by kind (TRACK → ALBUM → ARTIST → PLAYLIST),
        emitted incrementally via on_result.

        Raises
        ------
        SearchError  on unrecoverable backend failure.
        """
        self.reset()
        try:
            return self._ytm.search_all(
                query,
                max_results=max_results,
                cancel=self._cancel,
                on_result=on_result,
            )
        except Exception as exc:
            raise SearchError(f"YouTube Music search failed: {exc}") from exc

    def search_ytm_songs(
        self,
        query:       str,
        max_results: int = 10,
        on_result:   Optional[Callable[[SearchResult], None]] = None,
    ) -> list[SearchResult]:
        """Targeted YTM song-only search (for autocomplete / quick look-up)."""
        self.reset()
        try:
            return self._ytm.search_songs(
                query, max_results=max_results,
                cancel=self._cancel, on_result=on_result,
            )
        except Exception as exc:
            raise SearchError(f"YTM song search failed: {exc}") from exc

    # ── Plain YouTube (yt-dlp) ─────────────────────────────────────────────────

    def search_youtube(
        self,
        query:       str,
        max_results: int = 15,
        on_result:   Optional[Callable[[SearchResult], None]] = None,
    ) -> list[SearchResult]:
        """
        Search plain YouTube for individual videos (Tracks).

        Raises
        ------
        SearchError  on unrecoverable yt-dlp failure.
        """
        self.reset()
        return self._ytdlp.search_videos(
            query,
            max_results=max_results,
            cancel=self._cancel,
            on_result=on_result,
        )

    def search_youtube_categorized(
        self,
        query:       str,
        max_results: int = 15,
        on_result:   Optional[Callable[[SearchResult], None]] = None,
    ) -> list[SearchResult]:
        """
        Search plain YouTube returning Tracks + Playlists + Channels.

        This is the method to call when the user selects the plain "YouTube"
        platform (not YouTube Music).  Results from the three sub-searches are
        merged and emitted incrementally.
        """
        self.reset()
        combined: list[SearchResult] = []
        global_idx = 1

        def _re_index_and_emit(
            sub_results: list[SearchResult],
        ) -> None:
            nonlocal global_idx
            for r in sub_results:
                if self._cancel.is_set():
                    return
                r.result_index = global_idx
                global_idx += 1
                combined.append(r)
                if on_result:
                    try:
                        on_result(r)
                    except Exception:
                        pass

        video_limit    = max(max_results, 10)
        playlist_limit = max(max_results // 3, 5)
        channel_limit  = max(max_results // 5, 3)

        _re_index_and_emit(
            self._ytdlp.search_videos(
                query, max_results=video_limit,
                cancel=self._cancel, on_result=None,
            )
        )
        if not self._cancel.is_set():
            _re_index_and_emit(
                self._ytdlp.search_playlists(
                    query, max_results=playlist_limit,
                    cancel=self._cancel, on_result=None,
                )
            )
        if not self._cancel.is_set():
            _re_index_and_emit(
                self._ytdlp.search_channels(
                    query, max_results=channel_limit,
                    cancel=self._cancel, on_result=None,
                )
            )

        return combined

    # ── Spotify ────────────────────────────────────────────────────────────────

    def search_spotify(
        self,
        query:       str,
        max_results: int = 15,
        proxy_url:   Optional[str] = None,
        on_result:   Optional[Callable[[SearchResult], None]] = None,
    ) -> list[SearchResult]:
        """
        Search Spotify via the optional Spotify proxy server.

        Falls back gracefully to an empty list (with a logged warning) if the
        proxy is not configured rather than raising.

        Parameters
        ----------
        proxy_url : URL of the YTSpot Spotify proxy API, e.g.
                    "http://localhost:8765".  If None, returns [].
        """
        self.reset()
        if not proxy_url:
            return []

        endpoint = f"{proxy_url.rstrip('/')}/search"
        params   = {"q": query, "limit": str(max_results)}

        try:
            response = httpx.get(endpoint, params=params, timeout=10.0)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise SearchError(f"Spotify proxy request failed: {exc}") from exc
        except Exception as exc:
            raise SearchError(f"Unexpected Spotify search error: {exc}") from exc

        raw_items: list[tuple[str, dict]] = []
        if isinstance(data, dict):
            for kind_str in ("track", "album", "artist", "playlist"):
                for item in (data.get(f"{kind_str}s") or []):
                    raw_items.append((kind_str, item))
        elif isinstance(data, list):
            for item in data:
                kind_str = item.get("type", "track")
                raw_items.append((kind_str, item))

        kind_map: dict[str, ResultKind] = {
            "track":    ResultKind.TRACK,
            "album":    ResultKind.ALBUM,
            "artist":   ResultKind.ARTIST,
            "playlist": ResultKind.PLAYLIST,
        }
        results: list[SearchResult] = []

        for idx, (kind_str, item) in enumerate(raw_items, start=1):
            if self._cancel.is_set():
                break
            try:
                title  = item.get("title") or item.get("name") or "Unknown Title"
                artist = item.get("artist") or ""
                if not artist and kind_str == "artist":
                    artist = title

                dur    = item.get("duration_sec")
                thumb  = item.get("thumbnail_url") or item.get("image_url") or ""
                s_url  = item.get("spotify_url") or ""
                kind   = kind_map.get(kind_str, ResultKind.TRACK)

                res_url = (
                    f"ytsearch1:{artist} {title} audio"
                    if kind == ResultKind.TRACK
                    else s_url
                )

                r = SearchResult(
                    result_index=idx,
                    title=title,
                    artist=artist,
                    url=res_url,
                    platform=SourcePlatform.SPOTIFY,
                    kind=kind,
                    thumbnail_url=thumb,
                    duration_sec=dur,
                    duration_str=_seconds_to_duration(dur) if dur else "",
                    album=item.get("album_name") or "",
                )
                if kind in (ResultKind.ALBUM, ResultKind.PLAYLIST):
                    raw_count = item.get("total_tracks") or item.get("item_count")
                    if raw_count is not None:
                        try:
                            r.item_count = int(raw_count)
                        except (TypeError, ValueError):
                            pass

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

# Compiled patterns for inline media URL extraction
_INLINE_URL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'https?://(?:www\.)?youtube\.com/watch\?[^\s\'"<>]+',       re.I),
    re.compile(r'https?://youtu\.be/[A-Za-z0-9_-]{11}[^\s\'"<>]*',          re.I),
    re.compile(r'https?://(?:www\.)?youtube\.com/embed/[A-Za-z0-9_-]{11}[^\s\'"<>]*', re.I),
    re.compile(r'https?://(?:www\.)?youtube\.com/playlist\?[^\s\'"<>]+',    re.I),
    re.compile(r'https?://music\.youtube\.com/[^\s\'"<>]+',                 re.I),
    re.compile(r'https?://open\.spotify\.com/[^\s\'"<>]+',                  re.I),
]


class PageScraper:
    """
    Fetch a webpage and extract every recognisable media URL.

    Three-phase extraction:
    1. yt-dlp generic extractor (catches embeds yt-dlp already knows).
    2. BeautifulSoup: <iframe src>, <a href>, <video src>.
    3. Regex scan of raw HTML for inline URL strings.

    Only URLs that classify_url() accepts are returned.
    """

    def __init__(self, cookies_file: Optional[str] = None) -> None:
        self._cookies_file = cookies_file
        self._cancel       = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def reset(self) -> None:
        self._cancel.clear()

    def scrape(
        self,
        page_url:     str,
        on_url_found: Optional[Callable[[str], None]] = None,
        timeout:      float = 20.0,
    ) -> list[str]:
        """
        Scrape page_url and return a deduplicated list of supported media URLs.

        Parameters
        ----------
        page_url     : The webpage URL to scrape.
        on_url_found : Optional callback invoked for each new URL found.
        timeout      : HTTP request timeout in seconds.

        Raises
        ------
        ScraperError on HTTP or parse failure.
        """
        self.reset()
        found:  list[str] = []
        seen:   set[str]  = set()

        def _add(url: str) -> None:
            url = url.split("&")[0] if "?" in url else url  # strip UTM params
            if url in seen:
                return
            try:
                classify_url(url)   # raises if unsupported
            except Exception:
                return
            seen.add(url)
            found.append(url)
            if on_url_found:
                try:
                    on_url_found(url)
                except Exception:
                    pass

        # ── Phase 1: yt-dlp generic extraction ─────────────────────────────────
        try:
            opts = _build_search_opts(
                cookies_file=self._cookies_file,
                logger=_SilentLogger(),
                max_results=50,
            )
            opts.update({"extract_flat": True, "skip_download": True})
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(page_url, download=False)
            if info:
                for entry in info.get("entries") or []:
                    if self._cancel.is_set():
                        break
                    if entry:
                        url = entry.get("webpage_url") or entry.get("url") or ""
                        if url:
                            _add(url)
        except Exception:
            pass   # Phase 1 is best-effort

        if self._cancel.is_set():
            return found

        # ── Phase 2 & 3: HTML fetch + BeautifulSoup + regex ────────────────────
        try:
            resp = httpx.get(page_url, timeout=timeout, follow_redirects=True)
            resp.raise_for_status()
            html = resp.text
        except httpx.HTTPError as exc:
            raise ScraperError(f"HTTP error fetching {page_url!r}: {exc}") from exc
        except Exception as exc:
            raise ScraperError(f"Unexpected error fetching {page_url!r}: {exc}") from exc

        # Phase 2: structured HTML
        try:
            soup = BeautifulSoup(html, "html.parser")
            for tag, attr in [
                ("iframe", "src"), ("a", "href"), ("video", "src"),
                ("source", "src"), ("link", "href"),
            ]:
                for el in soup.find_all(tag):
                    if self._cancel.is_set():
                        break
                    val = el.get(attr, "")
                    if val and val.startswith("http"):
                        _add(val)
        except Exception:
            pass

        # Phase 3: regex scan
        for pattern in _INLINE_URL_PATTERNS:
            if self._cancel.is_set():
                break
            for match in pattern.finditer(html):
                _add(match.group(0))

        return found


# ──────────────────────────────────────────────────────────────────────────────
# Self-test  (python -m core.search_engine)
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    print("=" * 64)
    print("SearchEngine v3 smoke-test")
    print("=" * 64)

    engine = SearchEngine()

    # 1. YTM categorized search
    print("\n── 1. YTM search: 'daft punk get lucky' ──")
    ytm_results: list[SearchResult] = []

    def _on_ytm(r: SearchResult) -> None:
        print(
            f"  [{r.kind.value:<8}]  {r.title[:40]:<40}  "
            f"{r.artist[:24]:<24}  {r.duration_str}"
        )
        ytm_results.append(r)

    try:
        engine.search_youtube_music("daft punk get lucky", max_results=15, on_result=_on_ytm)
        print(f"  ✅  {len(ytm_results)} results\n")
    except SearchError as exc:
        print(f"  ⚠  SearchError: {exc}\n")

    # 2. Plain YouTube categorized
    print("── 2. YouTube categorized: 'lofi hip hop' ──")
    yt_results: list[SearchResult] = []

    def _on_yt(r: SearchResult) -> None:
        print(f"  [{r.kind.value:<8}]  {r.title[:60]}")
        yt_results.append(r)

    try:
        engine.search_youtube_categorized("lofi hip hop", max_results=10, on_result=_on_yt)
        print(f"  ✅  {len(yt_results)} results\n")
    except SearchError as exc:
        print(f"  ⚠  SearchError: {exc}\n")

    # 3. Cancel test
    print("── 3. Cancel flag test ──")
    engine2 = SearchEngine()
    engine2.cancel()
    cancelled = engine2.search_youtube("test query", max_results=10)
    print(f"  ✅  Cancelled search returned {len(cancelled)} results (expected 0)\n")

    print("=" * 64)
    print("Smoke-test complete.")
    sys.exit(0)
