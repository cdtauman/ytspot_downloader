"""
core/channel_tab_discoverer.py  –  YouTube channel tab discovery via Playwright
================================================================================
Opens the channel page once and reads the tab navigation DOM to find which
tabs actually exist (Videos, Shorts, Live, Playlists, Releases, Podcasts).
Returns a list of TabInfo objects — no yt-dlp calls, no downloading.

Runs in ~2-3 seconds for a typical channel.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ── Tab catalogue ──────────────────────────────────────────────────────────────
# Maps YouTube's English tab titles (what the DOM contains) to our Hebrew labels
# and canonical URL path suffixes.

_TAB_MAP: dict[str, dict] = {
    "videos":    {"name": "סרטונים",      "path": "/videos",    "icon": "🎬", "type": "videos"},
    "shorts":    {"name": "קצרים",         "path": "/shorts",    "icon": "⚡", "type": "shorts"},
    "live":      {"name": "שידורים חיים", "path": "/streams",   "icon": "🔴", "type": "streams"},
    "streams":   {"name": "שידורים חיים", "path": "/streams",   "icon": "🔴", "type": "streams"},
    "playlists": {"name": "פלייליסטים",   "path": "/playlists", "icon": "📋", "type": "playlists"},
    "releases":  {"name": "פריטי תוכן",   "path": "/releases",  "icon": "🎵", "type": "releases"},
    "podcasts":  {"name": "פודקאסטים",    "path": "/podcasts",  "icon": "🎙", "type": "podcasts"},
}

# Tabs we don't care about (community posts, store, members, about, etc.)
_IGNORE_TABS = {"community", "about", "channels", "membership", "store", "featured", "home"}


@dataclass
class TabInfo:
    name:     str   # Hebrew display name, e.g. "סרטונים"
    url:      str   # Full tab URL, e.g. "https://youtube.com/@handle/videos"
    icon:     str   # Emoji icon for the Card Grid dialog
    tab_type: str   # Canonical type: "videos" | "shorts" | "streams" | "playlists" | "releases" | "podcasts"
    count:    int   = -1   # -1 = unknown; will be populated after scraping


@dataclass
class DiscoveryResult:
    channel_name: str
    channel_url:  str
    tabs:         list[TabInfo] = field(default_factory=list)
    error:        Optional[str] = None

    def success(self) -> bool:
        return not self.error and bool(self.tabs)


# ── Main entry point ───────────────────────────────────────────────────────────

def discover_tabs(url: str) -> DiscoveryResult:
    """
    Blocking call.  Opens the channel page with Playwright, reads the tab
    navigation bar, and returns a DiscoveryResult with all available tabs.

    Parameters
    ----------
    url : Any YouTube channel URL format:
          https://www.youtube.com/@handle
          https://www.youtube.com/channel/UCxxx
          https://www.youtube.com/user/xxx
          https://www.youtube.com/c/xxx

    Returns
    -------
    DiscoveryResult — always returned; check .error for failures.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return DiscoveryResult(
            channel_name="",
            channel_url=url,
            error="Playwright is not installed. Run: playwright install chromium",
        )

    # Strip any trailing tab suffix so we always land on the channel home
    base_url = _strip_tab_suffix(url)

    try:
        from core.scraper import _USER_AGENT, _block_heavy_resources  # reuse existing helpers
    except ImportError:
        _USER_AGENT = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        _block_heavy_resources = None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=_USER_AGENT,
            )
            page = ctx.new_page()
            if _block_heavy_resources:
                page.route("**/*", _block_heavy_resources)

            logger.debug("[TabDiscoverer] Navigating to %s", base_url)
            page.goto(base_url, wait_until="domcontentloaded", timeout=30_000)

            # Give JS a moment to render the tab bar
            page.wait_for_timeout(2_000)

            # ── Channel name ────────────────────────────────────────────────────
            channel_name = _extract_channel_name(page)

            # ── Tab navigation ─────────────────────────────────────────────────
            tabs = _extract_tabs(page, base_url)

            browser.close()

        if not tabs:
            # Fallback: assume basic tabs exist
            tabs = _default_tabs(base_url)
            logger.warning("[TabDiscoverer] No tabs found via DOM — using defaults")

        return DiscoveryResult(
            channel_name=channel_name,
            channel_url=base_url,
            tabs=tabs,
        )

    except Exception as exc:  # noqa: BLE001
        logger.error("[TabDiscoverer] Discovery failed: %s", exc)
        return DiscoveryResult(
            channel_name="",
            channel_url=base_url,
            tabs=_default_tabs(base_url),
            error=str(exc),
        )


# ── DOM helpers ────────────────────────────────────────────────────────────────

def _extract_channel_name(page) -> str:
    selectors = [
        "yt-page-header-renderer h1",
        "ytd-channel-name yt-formatted-string",
        "meta[property='og:title']",
    ]
    for sel in selectors:
        try:
            if sel.startswith("meta"):
                val = page.get_attribute(sel, "content")
            else:
                el = page.locator(sel).first
                val = el.inner_text(timeout=2_000).strip() if el.count() else None
            if val:
                return val
        except Exception:
            continue
    return "Unknown Channel"


def _extract_tabs(page, base_url: str) -> list[TabInfo]:
    """
    Try multiple selector strategies to find the tab navigation bar.
    YouTube has changed this structure several times; we try all known variants.
    """
    found_tabs: list[TabInfo] = []

    # Modern yt-tab-group-component or yt-tab-shape
    try:
        tab_els = page.locator("yt-tab-group-component yt-tab-renderer, yt-tab-shape").all()
        if tab_els:
            for el in tab_els:
                tab = _tab_from_element(el, base_url, strategy="tab-shape")
                if tab:
                    found_tabs.append(tab)
            if found_tabs:
                # deduplicate just in case
                return list({t.tab_type: t for t in found_tabs}.values())
    except Exception:
        pass

    return found_tabs


def _tab_from_element(el, base_url: str, strategy: str) -> Optional[TabInfo]:
    """Parse a single tab DOM element into a TabInfo, or None if not a content tab."""
    try:
        text = el.inner_text(timeout=1_500).strip().lower()
        if not text:
            return None

        # Match against known tab keywords (English or Hebrew)
        for key, info in _TAB_MAP.items():
            hebrew = info["name"].lower()
            if key in text or hebrew in text:
                return TabInfo(
                    name=info["name"],
                    url=base_url.rstrip("/") + info["path"],
                    icon=info["icon"],
                    tab_type=info["type"],
                )

        # Check if it's a tab we should ignore
        for ignore in _IGNORE_TABS:
            if ignore in text:
                return None

        # Unknown tab — skip it
        logger.debug("[TabDiscoverer] Unknown tab text: %r (strategy=%s)", text, strategy)
        return None

    except Exception:
        return None


# ── Fallback defaults ──────────────────────────────────────────────────────────

def _default_tabs(base_url: str) -> list[TabInfo]:
    """Return the three most common tabs as a safe fallback."""
    return [
        TabInfo(name="סרטונים",    url=base_url.rstrip("/") + "/videos",    icon="🎬", tab_type="videos"),
        TabInfo(name="קצרים",      url=base_url.rstrip("/") + "/shorts",    icon="⚡", tab_type="shorts"),
        TabInfo(name="פלייליסטים", url=base_url.rstrip("/") + "/playlists", icon="📋", tab_type="playlists"),
    ]


def _strip_tab_suffix(url: str) -> str:
    """Remove trailing /videos, /shorts, etc. to get the channel home URL."""
    for suffix in ("/videos", "/shorts", "/streams", "/playlists", "/releases", "/podcasts",
                   "/community", "/about", "/channels", "/membership", "/featured"):
        if url.rstrip("/").endswith(suffix):
            return url.rstrip("/")[: -len(suffix)]
    return url.rstrip("/")