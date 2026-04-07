import sys
import os
import requests
import re
import html
import json
from typing import List, Dict, Set, Optional
from utils.yt_dlp_opts import CHROME_USER_AGENT

# API Constants
_API_URL = "https://music.youtube.com/youtubei/v1/browse?key=AIzaSyC9XL3ZjWddXya6X74dJoCTL-WEYFDNX30&prettyPrint=false"
_CLIENT_CONTEXT = {
    "client": {
        "hl": "iw", "gl": "IL", "clientName": "WEB_REMIX",
        "clientVersion": "1.20260331.01.00", "osName": "Windows",
        "osVersion": "10.0", "platform": "DESKTOP"
    }
}

def _clean_name(name: str) -> str:
    """Strip 'Official Channel' suffixes and Album prefixes for clean folder paths."""
    if not name: return ""
    # Strip YTM official markers
    name = re.sub(r" - הערוץ הרשמי$", "", name)
    name = re.sub(r" - Official Channel$", "", name, flags=re.I)
    name = re.sub(r" - Official$", "", name, flags=re.I)
    name = re.sub(r" - Topic$", "", name, flags=re.I)
    name = re.sub(r"^Album - ", "", name, flags=re.I)
    return name.strip()

def _call_ytm_api(browse_id: str, params: Optional[str] = None) -> Optional[dict]:
    headers = {"Content-Type": "application/json", "User-Agent": CHROME_USER_AGENT}
    payload = {"context": _CLIENT_CONTEXT, "browseId": browse_id}
    if params: payload["params"] = params
    try:
        r = requests.post(_API_URL, json=payload, headers=headers, timeout=15)
        return r.json()
    except Exception: return None

def _extract_from_shelf(shelf_data: dict, artist_name: str, artist_id: str, rel_type: str) -> List[Dict[str, str]]:
    items = []
    def _walk(obj):
        if isinstance(obj, dict):
            if "musicTwoRowItemRenderer" in obj:
                renderer = obj["musicTwoRowItemRenderer"]
                raw_title = "".join(r.get("text", "") for r in renderer.get("title", {}).get("runs", []))
                title = _clean_name(raw_title)
                
                nav = renderer.get("navigationEndpoint", {})
                v_id = nav.get("watchEndpoint", {}).get("videoId")
                b_id = nav.get("browseEndpoint", {}).get("browseId")
                
                if b_id or v_id:
                    final_id = b_id or v_id
                    items.append({
                        "id": final_id,
                        "url": f"https://music.youtube.com/browse/{final_id}" if b_id else f"https://music.youtube.com/watch?v={final_id}",
                        "title": title,
                        "type": rel_type,
                        "parent_artist": artist_name,
                        "artist": artist_name,
                        "album": title if rel_type == "album" else ""
                    })
            for v in obj.values(): _walk(v)
        elif isinstance(obj, list):
            for i in obj: _walk(i)
    _walk(shelf_data)
    return items

def fetch_ytm_artist_releases(artist_url: str) -> List[Dict[str, str]]:
    artist_id = None
    if "/channel/" in artist_url: artist_id = artist_url.split("/channel/")[1].split("?")[0]
    elif "/browse/" in artist_url: artist_id = artist_url.split("/browse/")[1].split("?")[0]
    if not artist_id: return []

    main_data = _call_ytm_api(artist_id)
    if not main_data: return []
    
    header = main_data.get("header", {})
    r_renderer = header.get("musicVisualHeaderRenderer") or header.get("musicImmersiveHeaderRenderer")
    artist_name = "אודיה"
    if r_renderer:
        raw_name = r_renderer.get("title", {}).get("runs", [{}])[0].get("text", artist_name)
        artist_name = _clean_name(raw_name)

    all_releases = []
    seen_ids = set()

    def fetch_full_tab(renderer, shelf_type):
        button = renderer.get("header", {}).get("musicCarouselShelfBasicHeaderRenderer", {}).get("moreContentButton", {})
        eb = button.get("buttonRenderer", {}).get("navigationEndpoint", {}).get("browseEndpoint", {})
        if eb and eb.get("browseId"):
            full_data = _call_ytm_api(eb["browseId"], params=eb.get("params"))
            if full_data: return _extract_from_shelf(full_data, artist_name, artist_id, shelf_type)
        return _extract_from_shelf(renderer, artist_name, artist_id, shelf_type)

    def scan_for_shelves(obj):
        if isinstance(obj, dict):
            if "musicCarouselShelfRenderer" in obj:
                renderer = obj["musicCarouselShelfRenderer"]
                title_runs = renderer.get("header", {}).get("musicCarouselShelfBasicHeaderRenderer", {}).get("title", {}).get("runs", [])
                header_text = "".join(r.get("text", "") for r in title_runs).strip()
                
                s_type = None
                if "אלבומים" in header_text: s_type = "album"
                elif "סינגלים" in header_text: s_type = "single"
                elif "הופעות" in header_text or "Live" in header_text: s_type = "performance"
                
                if s_type:
                    results = fetch_full_tab(renderer, s_type)
                    for item in results:
                        if item["id"] not in seen_ids:
                            seen_ids.add(item["id"])
                            all_releases.append(item)
            for v in obj.values(): scan_for_shelves(v)
        elif isinstance(obj, list):
            for i in obj: scan_for_shelves(i)

    scan_for_shelves(main_data)
    return all_releases
