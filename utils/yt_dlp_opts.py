"""
utils/yt_dlp_opts.py  –  Shared yt-dlp configuration builder
=============================================================
Centralises every yt-dlp option that is common across the three backend
modules that call yt-dlp (downloader, playlist_parser, search_engine):

  * Native Cookie injection (file or automatic browser extraction)
  * Robust retry counts + extractor retries
  * Optional HTTP proxy for all requests
  
Design
------
* Zero GUI imports – pure stdlib + yt-dlp.
* Returns a plain dict so callers can merge or override individual keys.
* Caller is responsible for adding module-specific keys (format, outtmpl,
  progress_hooks, postprocessors, skip_download, extract_flat, etc.).
"""

from __future__ import annotations

import shutil
from typing import Any, Optional

CHROME_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"

_JS_RUNTIMES_PREFERENCE = ("node", "bun", "deno")

def _detect_js_runtimes() -> dict[str, dict]:
    """Find available JS runtimes on PATH and return a js_runtimes dict for yt-dlp."""
    runtimes: dict[str, dict] = {}
    for name in _JS_RUNTIMES_PREFERENCE:
        path = shutil.which(name)
        if path:
            runtimes[name] = {"path": path}
            break  # one is enough
    return runtimes or {"node": {}}  # fallback: let yt-dlp try to find node itself

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
    socket_timeout:       int            = 20,
    randomize_user_agent: bool           = False, # Kept for signature compatibility, but unused
    proxy:                Optional[str]  = None,
) -> dict[str, Any]:
    """
    Return a base yt-dlp options dict with YTSpot's standard network,
    cookie, and retry settings applied. Lets yt-dlp handle impersonation natively.
    """
    opts: dict[str, Any] = {
        # ── Network resilience ────────────────────────────────────────────────
        "nocheckcertificate":              True,
        "retries":                         retries,
        "fragment_retries":                retries,
        "extractor_retries":               5,
        "socket_timeout":                  socket_timeout,
        "abort_on_unavailable_fragment":   False,
        "concurrent_fragment_downloads":   5,

        # ── Verbosity ─────────────────────────────────────────────────────────
        "quiet":       quiet,
        "no_warnings": False,
        "color":       "no_color",

        # ── JS runtime for YouTube player decryption ──────────────────────────
        "js_runtimes": _detect_js_runtimes(),
    }

    # ── Logger (optional) ─────────────────────────────────────────────────────
    if logger is not None:
        opts["logger"] = logger

    # ── Cookie injection ──────────────────────────────────────────────────────
    if cookies_file:
        opts["cookiefile"] = cookies_file
    elif cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser, None, None, None)

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
    })
    return opts