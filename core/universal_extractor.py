"""
core/universal_extractor.py  –  Playwright-based universal media interceptor
=============================================================================
Intercepts HLS (.m3u8), DASH (.mpd), and direct media URLs (.mp4, .webm, .ts)
that a page loads, exactly like the HLS Downloader browser extension.

Used as a fallback when yt-dlp cannot extract media from a URL.

Zero Qt imports.  Async core with a sync wrapper for non-async callers.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Patterns that identify a URL as a media stream
_HLS_RE   = re.compile(r'\.m3u8(\?|$|#)', re.I)
_DASH_RE  = re.compile(r'\.mpd(\?|$|#)', re.I)
_MEDIA_RE = re.compile(r'\.(mp4|webm|ts|m4s|mkv|mov|avi|m4v|flv|f4v)(\?|$|#)', re.I)

# Content-Types that indicate a media resource
_MEDIA_CONTENT_TYPES = frozenset({
    "video/mp4", "video/webm", "video/mpeg", "video/ogg",
    "video/x-flv", "video/x-m4v", "video/quicktime",
    "audio/mpeg", "audio/mp4", "audio/webm", "audio/ogg",
    "audio/x-m4a", "audio/aac",
    "application/x-mpegurl",          # HLS
    "application/vnd.apple.mpegurl",  # HLS (Apple)
    "application/dash+xml",           # DASH
    "application/octet-stream",       # generic binary (many video CDNs)
})


@dataclass
class InterceptedStream:
    url:          str
    stream_type:  Literal["hls", "dash", "mp4", "webm", "ts", "unknown"]
    content_type: str   = ""
    size_hint:    int   = 0   # bytes from Content-Length header; 0 = unknown
    page_title:   str   = ""


def _classify_url(url: str) -> Literal["hls", "dash", "mp4", "webm", "ts", "unknown"]:
    if _HLS_RE.search(url):
        return "hls"
    if _DASH_RE.search(url):
        return "dash"
    m = _MEDIA_RE.search(url)
    if m:
        ext = m.group(1).lower()
        if ext == "mp4":    return "mp4"
        if ext == "webm":   return "webm"
        if ext in ("ts", "m4s"): return "ts"
    return "unknown"


def _classify_content_type(ct: str) -> Literal["hls", "dash", "mp4", "webm", "ts", "unknown"] | None:
    ct = ct.lower().split(";")[0].strip()
    if ct in ("application/x-mpegurl", "application/vnd.apple.mpegurl"):
        return "hls"
    if ct == "application/dash+xml":
        return "dash"
    if ct.startswith("video/mp4"):  return "mp4"
    if ct.startswith("video/webm"): return "webm"
    if any(ct.startswith(m) for m in ("video/", "audio/")):
        return "ts"
    return None


def _url_base(url: str) -> str:
    """Strip query string for deduplication (segment URLs share a base path)."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


async def intercept_page(
    page_url:   str,
    timeout_ms: int = 20_000,
) -> list[InterceptedStream]:
    """
    Launch a headless Chromium page, intercept all media-related network
    requests, and return the deduplicated list of streams found.

    Sorted largest-first (by size_hint) so callers can pick the best stream.
    """
    try:
        from playwright.async_api import async_playwright, TimeoutError as PWTimeout
    except ImportError:
        logger.warning("playwright not installed — universal extractor unavailable")
        return []

    found: dict[str, InterceptedStream] = {}   # base_url → stream (dedup)
    page_title = ""

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/137.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 720},
        )
        page = await ctx.new_page()

        # ── Request listener (fires before fetch) ─────────────────────────────
        async def _on_request(request) -> None:
            url = request.url
            st = _classify_url(url)
            if st != "unknown":
                base = _url_base(url)
                if base not in found:
                    found[base] = InterceptedStream(
                        url=url,
                        stream_type=st,
                    )

        # ── Response listener (fires after headers arrive) ────────────────────
        async def _on_response(response) -> None:
            ct = response.headers.get("content-type", "")
            ct_base = ct.lower().split(";")[0].strip()
            if ct_base not in _MEDIA_CONTENT_TYPES:
                return
            url = response.url
            st = _classify_content_type(ct_base) or _classify_url(url)
            if st != "unknown":
                base = _url_base(url)
                size = int(response.headers.get("content-length", 0) or 0)
                if base not in found:
                    found[base] = InterceptedStream(
                        url=url,
                        stream_type=st,
                        content_type=ct_base,
                        size_hint=size,
                    )
                else:
                    # Upgrade existing entry with real content-type/size
                    s = found[base]
                    s.content_type = ct_base
                    if size:
                        s.size_hint = size
                    if s.stream_type == "unknown":
                        s.stream_type = st

        page.on("request",  _on_request)
        page.on("response", _on_response)

        try:
            await page.goto(page_url, wait_until="networkidle", timeout=timeout_ms)
        except PWTimeout:
            logger.debug("universal_extractor: networkidle timeout, using partial results")
        except Exception as exc:
            logger.warning("universal_extractor: page.goto failed: %s", exc)
        finally:
            try:
                page_title = await page.title()
            except Exception:
                pass
            await browser.close()

    streams = list(found.values())
    for s in streams:
        s.page_title = page_title

    # Sort: HLS/DASH first (most useful), then by size descending
    def _sort_key(s: InterceptedStream):
        priority = {"hls": 0, "dash": 1, "mp4": 2, "webm": 3, "ts": 4, "unknown": 5}
        return (priority.get(s.stream_type, 5), -(s.size_hint or 0))

    streams.sort(key=_sort_key)
    return streams


def find_streams(
    page_url:   str,
    timeout_ms: int = 20_000,
) -> list[InterceptedStream]:
    """
    Synchronous wrapper around intercept_page().
    Safe to call from any thread (creates its own event loop).
    Returns [] if Playwright is not installed.
    """
    try:
        return asyncio.run(intercept_page(page_url, timeout_ms=timeout_ms))
    except Exception as exc:
        logger.warning("universal_extractor.find_streams failed: %s", exc)
        return []
