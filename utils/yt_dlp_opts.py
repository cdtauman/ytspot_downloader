"""
utils/yt_dlp_opts.py  –  Shared yt-dlp configuration builder
=============================================================
Centralises every yt-dlp option that is common across the three backend
modules that call yt-dlp (downloader, playlist_parser, search_engine):

  * Full Chrome 136 browser fingerprint headers (bot-detection bypass)
  * TLS browser impersonation via curl_cffi (when available)
  * Age-gate bypass (age_limit=18)
  * Robust retry counts
  * Cookie injection (file or browser extraction)
  * QuickJS / Node.js runtime registration

Previously these were duplicated in every module that used yt-dlp.  Any
future change to the fingerprint (e.g. Chrome 137) is now a single edit.

Design
------
* Zero GUI imports – pure stdlib + yt-dlp.
* Returns a plain dict so callers can merge or override individual keys.
* Caller is responsible for adding module-specific keys (format, outtmpl,
  progress_hooks, postprocessors, skip_download, extract_flat, etc.).

Usage
-----
>>> from utils.yt_dlp_opts import build_base_ydl_opts
>>> opts = build_base_ydl_opts(cookies_file="/path/to/cookies.txt")
>>> opts.update({"skip_download": True, "extract_flat": True})
>>> with yt_dlp.YoutubeDL(opts) as ydl:
...     info = ydl.extract_info(url, download=False)
"""

from __future__ import annotations

import random
from typing import Any, Optional

from utils.impersonate import ImpersonateTarget, CURL_CFFI_AVAILABLE


# ── Browser UA pool for randomization ────────────────────────────────────────
# Kept realistic and up-to-date.  All entries pass YouTube's bot checks.
_UA_POOL: list[str] = [
    # Chrome on Windows (various recent versions)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) Gecko/20100101 Firefox/138.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:137.0) Gecko/20100101 Firefox/137.0",
    # Firefox on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.7; rv:138.0) Gecko/20100101 Firefox/138.0",
    # Edge on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0",
]


# ── Chrome 136 fingerprint (single source of truth) ───────────────────────────

_CHROME_136_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language":           "en-US,en;q=0.9",
    "Accept-Encoding":           "gzip, deflate, br",
    "Sec-Fetch-Dest":            "document",
    "Sec-Fetch-Mode":            "navigate",
    "Sec-Fetch-Site":            "none",
    "Sec-Fetch-User":            "?1",
    "Sec-CH-UA":                 '"Chromium";v="136", "Google Chrome";v="136", "Not-A.Brand";v="99"',
    "Sec-CH-UA-Mobile":          "?0",
    "Sec-CH-UA-Platform":        '"Windows"',
    "Upgrade-Insecure-Requests": "1",
    "Connection":                "keep-alive",
}

# Expose for callers that need just the UA string (e.g. requests/httpx calls)
CHROME_USER_AGENT: str = _CHROME_136_HEADERS["User-Agent"]


# ──────────────────────────────────────────────────────────────────────────────
# Main builder
# ──────────────────────────────────────────────────────────────────────────────

def build_base_ydl_opts(
    *,
    cookies_file:         Optional[str]  = None,
    cookies_browser:      Optional[str]  = None,
    logger:               Any            = None,
    quiet:                bool           = True,
    retries:              int            = 10,
    age_limit:            int            = 18,
    socket_timeout:       int            = 20,
    randomize_user_agent: bool           = False,
) -> dict[str, Any]:
    """
    Return a base yt-dlp options dict with YTSpot's standard bot-bypass,
    cookie, and impersonation settings applied.

    Parameters
    ----------
    cookies_file :
        Absolute path to a Netscape-format cookies.txt file.  Takes priority
        over ``cookies_browser`` when both are supplied.
    cookies_browser :
        Browser name to extract cookies from at runtime.
        Valid values: "chrome" | "firefox" | "edge" | "brave" | "safari".
    logger :
        yt-dlp logger object (must implement debug/info/warning/error).
        Pass a ``SilentLogger`` instance to suppress all console output.
    quiet :
        Pass ``quiet=True`` to yt-dlp.  Set False for debug builds.
    retries :
        Number of download retries on transient network errors.
    age_limit :
        Maximum content age rating to allow (18 bypasses most gates).
    socket_timeout :
        TCP socket timeout in seconds.

    Returns
    -------
    dict
        Partial yt-dlp options dict.  Merge caller-specific keys on top.
    """
    opts: dict[str, Any] = {
        # ── Browser fingerprint headers ───────────────────────────────────────
        "http_headers": dict(_CHROME_136_HEADERS),   # copy, not ref

        # ── Age gate bypass ───────────────────────────────────────────────────
        "age_limit": age_limit,

        # ── Network resilience ────────────────────────────────────────────────
        "retries":          retries,
        "fragment_retries": retries,
        "socket_timeout":   socket_timeout,
        "nocheckcertificate": False,
        "abort_on_unavailable_fragment": False,
        "concurrent_fragment_downloads": 5,

        # ── JavaScript runtimes (YouTube PO-token) ────────────────────────────
        "js_runtimes": {
            "quickjs": {},
            "node":    {},
            "deno":    {},
            "bun":     {},
        },

        # ── Verbosity ─────────────────────────────────────────────────────────
        "quiet":       quiet,
        "no_warnings": False,
    }

    # ── User-Agent rotation (anti-ban) ───────────────────────────────────────
    if randomize_user_agent:
        opts["http_headers"]["User-Agent"] = random.choice(_UA_POOL)

    # ── Logger (optional) ─────────────────────────────────────────────────────
    if logger is not None:
        opts["logger"] = logger

    # ── Cookie injection: file takes priority over browser extraction ─────────
    if cookies_file:
        opts["cookiefile"] = cookies_file
    elif cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser, None, None, None)

    # ── TLS browser impersonation (curl_cffi) ─────────────────────────────────
    if CURL_CFFI_AVAILABLE and ImpersonateTarget is not None:
        opts["impersonate"] = ImpersonateTarget("chrome")

    return opts


def build_search_ydl_opts(
    *,
    cookies_file:    Optional[str] = None,
    cookies_browser: Optional[str] = None,
    logger:          Any           = None,
    max_results:     int           = 15,
) -> dict[str, Any]:
    """
    Variant for metadata-only search operations (no download).

    Adds ``extract_flat``, ``skip_download``, and ``ignoreerrors`` on top of
    the base options, and caps ``playlistend`` at ``max_results``.
    """
    opts = build_base_ydl_opts(
        cookies_file=cookies_file,
        cookies_browser=cookies_browser,
        logger=logger,
        quiet=True,
        retries=3,
        socket_timeout=10,
    )
    opts.update({
        "extract_flat":  True,
        "skip_download": True,
        # ignoreerrors intentionally omitted: we want real errors to propagate
        # so the caller (SearchEngine) can surface them to the user instead of
        # silently returning empty results.
        "playlistend":   max_results,
    })
    return opts


def build_parse_ydl_opts(
    *,
    cookies_file:    Optional[str] = None,
    cookies_browser: Optional[str] = None,
    logger:          Any           = None,
) -> dict[str, Any]:
    """
    Variant for playlist/URL metadata extraction (PlaylistParser).

    Uses ``extract_flat="in_playlist"`` for lightweight lookups, removes
    the ``playlistend`` cap so full playlists are resolved.
    """
    opts = build_base_ydl_opts(
        cookies_file=cookies_file,
        cookies_browser=cookies_browser,
        logger=logger,
        quiet=True,
        retries=5,
    )
    opts.update({
        "extract_flat":  "in_playlist",
        "skip_download": True,
        "ignoreerrors":  True,
        # ── YouTube-specific extractor args ───────────────────────────────────
        "extractor_args": {
            "youtube": {
                "skip": ["webpage"],
            }
        },
    })
    return opts
