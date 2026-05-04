"""
core/scraper.py – Deeply Isolated & Hyper-Optimized Media Scraper
==================================================================
Dedicated extraction functions for every platform and content type.
Optimized for high-speed artist discography scraping using continuous accumulation.
"""
from playwright.sync_api import sync_playwright, Page
from typing import Callable, Optional, Dict, List, Tuple
import logging
import re
import yt_dlp
from utils.yt_dlp_opts import build_parse_ydl_opts as _build_parse_ydl_opts
from utils.logger import SilentLogger as _SilentLogger
logger = logging.getLogger(__name__)
# ── Private Internal Helpers (Shared common logic) ────────────────────────────
# Real Desktop User Agent to avoid bot-detection
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
def _block_heavy_resources(route):
    """
    Aborts requests for heavy media while keeping CSS and XHR/Scripts active.
    This is essential for high-speed reliable scraping in modern SPAs.
    """
    if route.request.resource_type in ["font", "media"]:
        route.abort()
    elif route.request.resource_type == "image":
        # Always allow Spotify images to ensure we get metadata thumbnails
        if "i.scdn.co" in route.request.url:
            route.continue_()
        else:
            route.abort()
    else:
        route.continue_()
def _ensure_high_res_spotify_image(url: str) -> str:
    """
    Ensures Spotify image URLs point to the highest resolution (640x640).
    Spotify uses 00004851 for 64x64, 00001e02 for 300x300, and 0000b273 for 640x640.
    """
    if not url or "i.scdn.co/image" not in url:
        return url
    # Replace size codes with b273 (640x640)
    # Common codes: 4851, 1e02, b273
    url = re.sub(r"/image/ab67616d0000[a-f0-9]{4}", "/image/ab67616d0000b273", url)
    return url
def _scrape_standard_ydl(url: str, platform_label: str, on_item: Optional[Callable[[Dict], None]] = None) -> Tuple[str, List[Dict]]:
    """Generic internal wrapper for yt-dlp based extraction."""
    items = []
    ydl_opts = _build_parse_ydl_opts(logger=_SilentLogger())

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if not info: return "Unknown", []

        # Save playlist/album title BEFORE the loop — the entry loop must not overwrite it
        raw_title = info.get("title") or info.get("playlist_title") or "Unknown"
        # Strip YouTube Music's "Album - " prefix that yt-dlp returns verbatim
        playlist_title = re.sub(r"^Album\s*-\s*", "", raw_title, flags=re.IGNORECASE).strip() if platform_label == "ytmusic" else raw_title
        entries = info.get("entries") or [info]

        for idx, entry in enumerate(entries, 1):
            if not entry: continue
            artist = entry.get("artist") or entry.get("uploader") or entry.get("creator") or ""
            track_title = entry.get("title") or entry.get("fulltitle") or f"Item {idx}"

            # Switch to search query if the platform is ytmusic to avoid bot blocks/crashes
            if platform_label == "ytmusic":
                target_url = f"ytsearch1:{artist} {track_title} audio"
            else:
                target_url = entry.get("webpage_url") or entry.get("url") or f"https://www.youtube.com/watch?v={entry.get('id')}"

            track_dict = {
                "title": track_title,
                "artist": artist,
                "album": playlist_title,
                "url": target_url,
                "thumbnail_url": _scraper_best_thumbnail(entry) or "",
                "duration_sec": entry.get("duration"),
                "platform": platform_label,
                "album_index": entry.get("playlist_index") or idx
            }
            items.append(track_dict)
            if on_item: on_item(track_dict)

    return playlist_title, items
def _scrape_spotify_grid_on_page(page: Page, url: str, content_type_label: str, on_item: Optional[Callable[[Dict], None]] = None) -> Tuple[str, List[Dict]]:
    """
    CORE LOGIC: Scrape a Spotify grid on a PRE-INITIALIZED page.
    Handles virtualized lists by scrolling.
    """
    items = []
    seen = set()
    page.goto(url, wait_until="load", timeout=30000)
    is_album = content_type_label == "Album"
    try:
        # Wait for grid or track rows
        page.wait_for_selector("main div[role='grid'], main div[data-testid='tracklist-row']", timeout=15000)

        # Get title from entity header
        scraped_title = page.evaluate("() => document.querySelector('h1[data-testid=\"entityTitle\"], main h1')?.innerText") or f"Unknown Spotify {content_type_label}"

        # Get higher-res entity image from header (Album/Playlist cover)
        header_thumb = ""
        try:
            h_img = page.locator("main img[data-testid='entity-image'], main img").first
            if h_img.count():
                header_thumb = _ensure_high_res_spotify_image(h_img.get_attribute("src") or "")
        except: pass
        # Isolate main grid
        main_grid = page.locator("main div[role='grid'], main div[data-testid='track-list']").first
        stagnant_count = 0
        while stagnant_count < 3:
            tracks = main_grid.locator("div[data-testid='tracklist-row']").all()
            if not tracks: break
            added_in_pass = 0
            for track_row in tracks:
                try:
                    row_idx = track_row.get_attribute("aria-rowindex") or track_row.get_attribute("data-testid")
                    title_el = track_row.locator("a[data-testid='internal-track-link'] div").first
                    if not title_el.count(): title_el = track_row.locator("div[dir='auto']").first
                    track_title = title_el.inner_text().strip()
                    uid = f"{row_idx}_{track_title}"
                    if uid in seen: continue
                    seen.add(uid)
                    added_in_pass += 1

                    artist_links = track_row.locator("a[href*='/artist/']").all()
                    artists = ", ".join([a.inner_text().strip() for a in artist_links]) if artist_links else "Unknown Artist"

                    # Extract thumbnail from row
                    track_thumb = ""
                    try:
                        row_img = track_row.locator("img").first
                        if row_img.count():
                            track_thumb = _ensure_high_res_spotify_image(row_img.get_attribute("src") or "")
                    except: pass

                    # For ALBUMS, we ALWAYS prefer the header/album cover over single-track covers
                    final_thumb = track_thumb
                    if is_album and header_thumb:
                        final_thumb = header_thumb
                    elif not final_thumb:
                        final_thumb = header_thumb

                    duration_sec = 0
                    duration_str = ""
                    try:
                        # Find element matching M:SS or HH:MM:SS
                        dur_el = track_row.locator("div, span").filter(has_text=re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")).first
                        if dur_el.count():
                            duration_str = dur_el.inner_text().strip()
                            parts = [int(p) for p in duration_str.split(":")]
                            if len(parts) == 2:
                                duration_sec = parts[0] * 60 + parts[1]
                            elif len(parts) == 3:
                                duration_sec = parts[0] * 3600 + parts[1] * 60 + parts[2]
                    except: pass
                    track_dict = {
                        "title": track_title, "artist": artists, "album": scraped_title,
                        "url": f"ytsearch1:{artists} {track_title} audio",
                        "album_index": len(seen), "thumbnail_url": final_thumb,
                        "duration_sec": duration_sec, "duration_str": duration_str or "??:??",
                        "platform": "spotify", "release_type": content_type_label.lower(),
                    }
                    items.append(track_dict)
                    if on_item: on_item(track_dict)
                except: pass

            if added_in_pass == 0: stagnant_count += 1
            else: stagnant_count = 0
            try:
                tracks[-1].scroll_into_view_if_needed()
                page.wait_for_timeout(500)
            except: break

        # Back-fill total_tracks now that we know the full count (used by EP grouping)
        if items:
            total = len(items)
            for td in items:
                td["total_tracks"] = total
    except Exception as e:
        logger.error(f"Error in _scrape_spotify_grid_on_page for {url}: {e}")
        return "Unknown", []
    return scraped_title, items
# ── Spotify Isolated Functions ────────────────────────────────────────────────
def scrape_spotify_playlist(url: str, on_item: Optional[Callable[[Dict], None]] = None) -> Tuple[str, List[Dict]]:
    """Dedicated entry for Spotify Playlists."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=_USER_AGENT)
        page = context.new_page()
        page.route("**/*", _block_heavy_resources)
        try: return _scrape_spotify_grid_on_page(page, url, "Playlist", on_item)
        finally: browser.close()
def scrape_spotify_album(url: str, on_item: Optional[Callable[[Dict], None]] = None) -> Tuple[str, List[Dict]]:
    """Dedicated entry for Spotify Albums."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=_USER_AGENT)
        page = context.new_page()
        page.route("**/*", _block_heavy_resources)
        try: return _scrape_spotify_grid_on_page(page, url, "Album", on_item)
        finally: browser.close()
def scrape_spotify_track(url: str, on_item: Optional[Callable[[Dict], None]] = None) -> Tuple[str, List[Dict]]:
    """Dedicated entry for single Spotify track."""
    title = "Unknown Track"
    items = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=_USER_AGENT)
        page = context.new_page()
        page.route("**/*", _block_heavy_resources)
        try:
            page.goto(url, wait_until="load")
            page.wait_for_selector("main h1", timeout=12000)
            title = page.locator("main h1").first.inner_text().strip()
            
            # Extract high-res thumbnail
            thumb_url = ""
            try:
                img_el = page.locator("main img[data-testid='entity-image'], main img").first
                if img_el.count():
                    thumb_url = _ensure_high_res_spotify_image(img_el.get_attribute("src") or "")
            except: pass
            artist_links = page.locator("main a[href*='/artist/']").all()
            artist_names = [a.inner_text().strip() for a in artist_links] if artist_links else []
            artists = ", ".join(artist_names) if artist_names else "Unknown Artist"
            parent_artist = artist_names[0] if artist_names else ""
            track_dict = {
                "title": title, "artist": artists, "album": title,
                "parent_artist": parent_artist, "category": "סינגלים ו-EP",
                "url": f"ytsearch1:{artists} {title} audio",
                "thumbnail_url": thumb_url, "platform": "spotify",
                "release_type": "single", "total_tracks": 1,
            }
            items.append(track_dict)
            if on_item: on_item(track_dict)
        finally: browser.close()
    return title, items
def scrape_spotify_artist(url: str, on_item: Optional[Callable[[Dict], None]] = None) -> Tuple[str, List[Dict]]:
    """
    Dedicated entry for Spotify Artist discographies.
    Iterates over /album and /single URLs for categorical accuracy.
    """
    items = []
    artist_name = ""
    seen_track_uids = set()
    # Normalize URL: strip trailing slashes and common sub-paths to get the base artist URL
    artist_url = re.sub(r"/discography/.*$", "", url.rstrip("/"))
    artist_url = re.sub(r"/all/?$", "", artist_url)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            viewport={"width": 1280, "height": 1000},
            user_agent=_USER_AGENT,
            locale="he-IL",
            extra_http_headers={"Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7"}
        )
        page = context.new_page()
        page.route("**/*", _block_heavy_resources)
        
        urls = [
            (artist_url.rstrip("/") + "/discography/album", "אלבומים"),
            (artist_url.rstrip("/") + "/discography/single", "סינגלים ו-EP")
        ]
        
        for target_url, cat_name in urls:
            try:
                page.goto(target_url, wait_until="load", timeout=30000)
                
                # 1. Fetch Artist Name (only once)
                if not artist_name:
                    try:
                        header_selector = "main h1, [data-testid='artist-page-header-name'], [data-testid='artist-name']"
                        page.wait_for_selector(header_selector, timeout=8000)
                        artist_name = page.locator(header_selector).first.inner_text().strip()
                    except:
                        artist_name = page.title().split("|")[0].strip()
                    
                    artist_name = re.sub(r"^Spotify\s*[-–]\s*", "", artist_name, flags=re.IGNORECASE)
                    artist_name = re.sub(r"\s*[-–]\s*(דיסקוגraphic|Discography)\s*$", "", artist_name, flags=re.IGNORECASE)
                    artist_name = re.sub(r"\s*[-–]\s*Discography.*$", "", artist_name, flags=re.IGNORECASE)
                    artist_name = re.sub(r"\s*\(Discography\).*$", "", artist_name, flags=re.IGNORECASE)
                    artist_name = artist_name.strip()
                # 2. Toggle to List View
                try:
                    view_toggle = page.locator("[aria-controls='sort-and-view-picker']").first
                    if view_toggle.count():
                        view_toggle.click()
                        list_option = page.locator("button[role='menuitemradio'] >> text=/List|רשימה/").first
                        if list_option.count():
                            list_option.click()
                            page.wait_for_timeout(800)
                except: pass
                # 3. Targeted Accumulation Loop for this URL
                stagnant_count = 0
                try: page.wait_for_selector("main div[data-testid='track-list']", timeout=12000)
                except: pass
                
                while stagnant_count < 10:
                    grids = page.locator("main div[data-testid='track-list']").all()
                    if not grids: break
                    added_any = False
                    last_track = None
                    for grid in grids:
                        release_title = grid.get_attribute("aria-label") or ""
                        if not release_title or release_title == artist_name:
                             release_title = grid.evaluate("el => el.previousElementSibling?.innerText") or release_title
                        if not release_title: release_title = "Unknown Release"
                        visible_tracks = grid.locator("div[data-testid='tracklist-row']").all()
                        if not visible_tracks: continue
                        
                        # Metadata for this grid
                        try:
                            rel_container = grid.evaluate_handle("el => el.closest('div:has(h1), div:has(h2), div:has(img), [class*=\"contentSpacing\"]') || el.parentElement")
                            thumb_url = rel_container.evaluate("el => el.querySelector('img')?.src") or ""
                            # Release label and track count (e.g. "אלבום • 2023 • 16 שירים")
                            # We collect all text from the header container to ensure we find the song count
                            meta_str = rel_container.evaluate("el => el.innerText || ''")
                            m_low = meta_str.lower()
                            
                            # Extract REAL track count from metadata string (e.g. "16 שירים" or "3 songs")
                            track_count_match = re.search(r"(\d+)\s*(שיר|שירים|song|track)", m_low)
                            total_tracks_stable = int(track_count_match.group(1)) if track_count_match else len(visible_tracks)
                            # Final site_label logic
                            site_label = "album" if "album" in target_url else \
                                         "ep" if ("ep" in m_low or total_tracks_stable > 1) else \
                                         "single" if ("single" in m_low or "single" in target_url) else "release"
                        except:
                            site_label = "album" if "album" in target_url else "release"
                            thumb_url = ""
                            total_tracks_stable = len(visible_tracks)
                        for t_idx, track_row in enumerate(visible_tracks, 1):
                            last_track = track_row
                            try:
                                title_el = track_row.locator("a[data-testid='internal-track-link'] div").first
                                if not title_el.count(): title_el = track_row.locator("div[dir='auto']").first
                                track_title = title_el.inner_text().strip()
                                
                                uid = f"{cat_name}_{release_title}_{track_title}"
                                if uid in seen_track_uids: continue
                                seen_track_uids.add(uid)
                                added_any = True
                                
                                artist_links = track_row.locator("a[href*='/artist/']").all()
                                artists = ", ".join([a.inner_text().strip() for a in artist_links]) if artist_links else artist_name
                                duration_sec, duration_str = 0, ""
                                try:
                                    dur_el = track_row.locator("[data-testid='track-duration']").first
                                    if not dur_el.count():
                                        dur_el = track_row.locator("div, span").filter(has_text=re.compile(r"^\d{1,2}:\d{2}$")).first
                                    if dur_el.count():
                                        duration_str = dur_el.inner_text().strip()
                                        if ":" in duration_str:
                                            parts = [int(p) for p in duration_str.split(":")]
                                            duration_sec = parts[0]*60 + parts[1] if len(parts)==2 else parts[0]*3600 + parts[1]*60 + parts[2]
                                except: pass
                                try:
                                    row_img = track_row.locator("img").first
                                    final_thumb = _ensure_high_res_spotify_image(row_img.get_attribute("src")) if row_img.count() else thumb_url
                                except: final_thumb = thumb_url
                                
                                # Final sweep for safety
                                final_thumb = _ensure_high_res_spotify_image(final_thumb)
                                track_dict = {
                                    "title": track_title, "artist": artists, "album": release_title,
                                    "parent_artist": artist_name, "category": cat_name,
                                    "release_type": site_label, "album_index": t_idx,
                                    "total_tracks": total_tracks_stable,
                                    "url": f"ytsearch1:{artists} {track_title} audio",
                                    "platform": "spotify", "thumbnail_url": final_thumb,
                                    "duration_sec": duration_sec, "duration_str": duration_str or "??:??"
                                }
                                items.append(track_dict)
                                if on_item: on_item(track_dict)
                            except: pass
                    if added_any: stagnant_count = 0
                    else: stagnant_count += 1
                    
                    if last_track:
                        last_track.scroll_into_view_if_needed()
                        page.wait_for_timeout(600)
            except Exception as e:
                logger.error(f"Error scraping {target_url}: {e}")
        
        browser.close()
            
    return artist_name or "Unknown Artist", items
# ── YouTube Music Isolated Functions ──────────────────────────────────────────
def scrape_ytm_playlist(url: str, on_item: Optional[Callable[[Dict], None]] = None) -> Tuple[str, List[Dict]]:
    """Dedicated entry for YouTube Music Playlists."""
    return _scrape_standard_ydl(url, "ytmusic", on_item)
def scrape_ytm_album(url: str, on_item: Optional[Callable[[Dict], None]] = None) -> Tuple[str, List[Dict]]:
    """Dedicated entry for YouTube Music Albums."""
    return _scrape_standard_ydl(url, "ytmusic", on_item)
def scrape_ytm_track(url: str, on_item: Optional[Callable[[Dict], None]] = None) -> Tuple[str, List[Dict]]:
    """Dedicated entry for YTM single tracks."""
    return _scrape_standard_ydl(url, "ytmusic", on_item)
def scrape_ytm_artist(url: str, on_item: Optional[Callable[[Dict], None]] = None) -> Tuple[str, List[Dict]]:
    """Dedicated entry for YTM Artist discographies."""
    from utils.ytm_scraper import fetch_ytm_artist_releases
    releases = fetch_ytm_artist_releases(url)
    if not releases: return "Unknown Artist", []
    artist_name = releases[0].get("parent_artist", "Unknown Artist")
    items = []
    ydl_opts = _build_parse_ydl_opts(logger=_SilentLogger())
    for r_idx, release in enumerate(releases, 1):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(release["url"], download=False)
                if not info: continue
                raw_title = info.get("title") or release["title"]
                # Strip YouTube Music's "Album - " prefix (yt-dlp returns it verbatim)
                album_title = re.sub(r"^Album\s*-\s*", "", raw_title, flags=re.IGNORECASE).strip()
                entries = info.get("entries") or [info]
                total_tracks = len(entries)
                for t_idx, entry in enumerate(entries, 1):
                    if not entry: continue
                    artist = entry.get("artist") or artist_name
                    title = entry.get("title") or "Unknown Title"
                    track_dict = {
                        "title": title,
                        "artist": artist,
                        "album": album_title, "parent_artist": artist_name,
                        "url": f"ytsearch1:{artist} {title} audio",
                        "thumbnail_url": _scraper_best_thumbnail(entry) or "",
                        "duration_sec": entry.get("duration"), "platform": "ytmusic",
                        "release_type": release.get("type", "album"),
                        "category": release.get("category_name", ""), "album_index": t_idx,
                        "total_tracks": total_tracks,
                    }
                    items.append(track_dict)
                    if on_item: on_item(track_dict)
        except Exception as e:
            logger.error(f"[Scraper] YTM artist release extraction failed for {release.get('url', 'N/A')}: {e}", exc_info=True)
    return artist_name, items
# ── YouTube Isolated Functions ───────────────────────────────────────────────
def scrape_youtube_playlist(url: str, on_item: Optional[Callable[[Dict], None]] = None) -> Tuple[str, List[Dict]]:
    """Dedicated entry for standard YouTube Playlists."""
    return _scrape_standard_ydl(url, "youtube", on_item)
def scrape_youtube_track(url: str, on_item: Optional[Callable[[Dict], None]] = None) -> Tuple[str, List[Dict]]:
    """Dedicated entry for single YouTube videos."""
    return _scrape_standard_ydl(url, "youtube", on_item)
def scrape_youtube_channel(url: str, required_tabs: List[str], on_item: Optional[Callable[[Dict], None]] = None) -> Tuple[str, List[Dict]]:
    """Dedicated entry for YouTube channel browsing."""
    items = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800}, user_agent=_USER_AGENT)
        page = context.new_page()
        page.route("**/*", _block_heavy_resources)
        base_url = url.split("/videos")[0].split("/shorts")[0].split("/releases")[0].split("/playlists")[0]
        tab_map = {"סרטונים": "/videos", "קצרים": "/shorts", "פריטי תוכן": "/releases", "פלייליסטים": "/playlists"}
        page.goto(base_url, wait_until="load")
        try: channel_name = page.locator("yt-page-header-renderer h1").first.inner_text().strip()
        except: channel_name = "Unknown Channel"
        for tab_name in required_tabs:
            if tab_name not in tab_map: continue
            tab_url = base_url.rstrip("/") + tab_map[tab_name]
            page.goto(tab_url, wait_until="load")
            for _ in range(5):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1000)
            if tab_name == "פלייליסטים":
                links = page.locator("main a.yt-simple-endpoint.ytd-playlist-thumbnail").evaluate_all("els => els.map(el => el.href)")
                for pl in links:
                    td = {"url": pl, "parent_artist": channel_name, "category": tab_name, "release_type": "playlist", "platform": "youtube"}
                    items.append(td); 
                    if on_item: on_item(td)
            else:
                vids = page.locator("main a#video-title, a#video-title-link").all()
                for v in vids:
                    title = v.inner_text().strip()
                    href = v.get_attribute("href")
                    if href:
                        td = {"title": title, "url": "https://www.youtube.com" + href.split("&")[0], "parent_artist": channel_name, "category": tab_name, "release_type": "video", "platform": "youtube"}
                        items.append(td); 
                        if on_item: on_item(td)
        browser.close()
    return channel_name, items

def _scraper_best_thumbnail(info: dict) -> str:
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
