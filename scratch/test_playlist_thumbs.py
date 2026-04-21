import sys
import os
import asyncio
from typing import Dict
# Add project root to path
sys.path.append(os.getcwd())
from core.scraper import scrape_spotify_playlist
# A popular public playlist
url = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM3M" # Today's Top Hits
def on_item(item: Dict):
    title = item.get('title', 'Unknown')
    thumb = item.get('thumbnail_url', '')
    print(f"Track: {title} | Thumbnail: {'Found' if thumb else 'Missing'}")
    if thumb:
        print(f"  URL: {thumb[:60]}...")
print(f"Scraping Playlist: {url}")
title, items = scrape_spotify_playlist(url, on_item=on_item)
print(f"\nTotal tracks scraped: {len(items)}")
missing = [i for i in items if not i.get('thumbnail_url')]
print(f"Tracks missing thumbnails: {len(missing)}")
if len(items) > 0 and len(missing) < len(items):
    print("\nSUCCESS: Thumbnails are being extracted for playlist tracks.")
else:
    print("\nFAILURE: Thumbnails are missing.")
