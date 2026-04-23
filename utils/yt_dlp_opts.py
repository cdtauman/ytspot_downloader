"""
utils/yt_dlp_opts.py  –  Shared yt-dlp configuration builder
=============================================================
Centralises every yt-dlp option that is common across the three backend
modules that call yt-dlp (downloader, playlist_parser, search_engine):

  * Full Chrome 137 browser fingerprint headers (bot-detection bypass)
  * TLS browser impersonation via curl_cffi (when available)
  * Age-gate bypass (age_limit=18)
  * Robust retry counts + extractor retries
  * Cookie injection (file or browser extraction)
  * JavaScript runtime registration (PO-token / n-challenge solving)
  * Optional HTTP proxy for all requests

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
# Kept up-to-date with Chrome/Firefox stable releases (2026-Q2).
_UA_POOL: list[str] = [
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    # Chrome on Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:139.0) Gecko/20100101 Firefox/139.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) Gecko/20100101 Firefox/138.0",
    # Firefox on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.7; rv:139.0) Gecko/20100101 Firefox/139.0",
    # Edge on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 Edg/137.0.0.0",
]


# ── Chrome 137 fingerprint (single source of truth) ──────────────────────────

_CHROME_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/137.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language":           "en-US,en;q=0.9",
    "Accept-Encoding":           "gzip, deflate, br, zstd",
    "Sec-Fetch-Dest":            "document",
    "Sec-Fetch-Mode":            "navigate",
    "Sec-Fetch-Site":            "none",
    "Sec-Fetch-User":            "?1",
    "Sec-CH-UA":                 '"Chromium";v="137", "Google Chrome";v="137", "Not-A.Brand";v="99"',
    "Sec-CH-UA-Mobile":          "?0",
    "Sec-CH-UA-Platform":        '"Windows"',
    "Upgrade-Insecure-Requests": "1",
    "Connection":                "keep-alive",
}

# Expose for callers that need just the UA string (e.g. requests/httpx calls)
CHROME_USER_AGENT: str = _CHROME_HEADERS["User-Agent"]


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
    proxy:                Optional[str]  = None,
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
    randomize_user_agent :
        If True, pick a random UA from the pool for each call.
    proxy :
        Optional HTTP/HTTPS/SOCKS proxy URL (e.g. "http://127.0.0.1:7890").
        Passed directly to yt-dlp's ``proxy`` option.

    Returns
    -------
    dict
        Partial yt-dlp options dict.  Merge caller-specific keys on top.
    """
    opts: dict[str, Any] = {
        # ── Browser fingerprint headers ───────────────────────────────────────
        "http_headers": dict(_CHROME_HEADERS),   # copy, not ref

        # ── Age gate bypass ───────────────────────────────────────────────────
        "age_limit": age_limit,

        # ── Network resilience ────────────────────────────────────────────────
        "retries":                         retries,
        "fragment_retries":                retries,
        "extractor_retries":               5,
        "socket_timeout":                  socket_timeout,
        "nocheckcertificate":              False,
        "abort_on_unavailable_fragment":   False,
        "concurrent_fragment_downloads":   5,

        # ── Performance / format selection ────────────────────────────────────
        "hls_prefer_native":  False,   # ffmpeg handles HLS better than native
        "prefer_free_formats": False,  # prefer quality over open codecs
        "check_formats":      False,   # skip per-format pre-validation (faster)

        # ── JavaScript runtimes (YouTube PO-token / n-challenge solving) ──────
        "js_runtimes": {
            "quickjs": {},
            "node":    {},
            "deno":    {},
            "bun":     {},
        },

        # ── Verbosity ─────────────────────────────────────────────────────────
        "quiet":       quiet,
        "no_warnings": False,
        "no_color":    True,
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

    # ── TLS browser impersonation (curl_cffi ≥ 0.14) ─────────────────────────
    # curl_cffi 0.14+ resolves the Windows/ThreadPoolExecutor deadlock that
    # existed in earlier versions.  The requirements.txt pins curl_cffi>=0.14.
    if CURL_CFFI_AVAILABLE and ImpersonateTarget is not None:
        opts["impersonate"] = ImpersonateTarget("chrome", "137", "windows", None)

    # ── Optional HTTP/HTTPS/SOCKS proxy ──────────────────────────────────────
    if proxy:
        opts["proxy"] = proxy

    return opts


def build_search_ydl_opts(
    *,
    cookies_file:    Optional[str] = None,
    cookies_browser: Optional[str] = None,
    logger:          Any           = None,
    max_results:     int           = 15,
    proxy:           Optional[str] = None,
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
        proxy=proxy,
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
    proxy:           Optional[str] = None,
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
        proxy=proxy,
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
