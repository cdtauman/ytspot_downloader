import sys
import os
import re
# Add project root to path
sys.path.append(os.getcwd())
from core.scraper import scrape_spotify_artist
url = sys.argv[1] if len(sys.argv) > 1 else "https://open.spotify.com/artist/28jEBK1RysfSUBHFofFflA"
def on_item(item):
    cat = item.get('category', 'unknown')
    kind = item.get('release_type', 'unknown')
    count = item.get('total_tracks', 0)
    alb = item.get('album', 'Unknown')
    title = item.get('title', 'Unknown')
    # Print a summary to verify
    print(f"[{cat}] ({kind}/{count}) {alb} -> {title}")
print(f"Starting Categorical Scrape for {url}...")
artist_name, tracks = scrape_spotify_artist(url, on_item=on_item)
print(f"\nTotal Tracks: {len(tracks)}")
# Verify specific releases
albums = [t for t in tracks if t['category'] == "אלבומים"]
singles = [t for t in tracks if t['category'] == "סינגלים ו-EP"]
print(f"Albums Found: {len(set(t['album'] for t in albums))}")
print(f"Singles/EPs Found: {len(set(t['album'] for t in singles))}")
