import sys
import os
import re
sys.path.append(os.getcwd())
from core.scraper import scrape_spotify_artist
url = "https://open.spotify.com/artist/28jEBK1RysfSUBHFofFflA"
def on_item(item):
    pass
print(f"Scraping {url}...")
# Note: scrape_spotify_artist now handles the list view and scrolling internally
artist_name, tracks = scrape_spotify_artist(url, on_item=on_item)
# Check specifically for the requested singles
shir_mamad_thumb = None
rocky_thumb = None
for t in tracks:
    alb = t['album']
    thumb = t['thumbnail_url']
    if "שיר לממ" in alb:
        shir_mamad_thumb = thumb
        print(f"FOUND 'שיר לממ''ד': {thumb}")
    if "רוקי" in alb:
        rocky_thumb = thumb
        print(f"FOUND 'רוקי': {thumb}")
if shir_mamad_thumb and rocky_thumb:
    if shir_mamad_thumb != rocky_thumb:
        print("\n✅ SUCCESS: 'שיר לממ''ד' and 'רוקי' have DIFFERENT thumbnails!")
    else:
        print("\n❌ FAILURE: 'שיר לממ''ד' and 'רוקי' share the SAME thumbnail!")
else:
    print(f"\n⚠️ WARNING: Found Shir: {bool(shir_mamad_thumb)}, Found Rocky: {bool(rocky_thumb)}")
    # Print first few releases found to see what's happening
    unique_rels = list(set([t['album'] for t in tracks]))
    print(f"Total Unique Releases: {len(unique_rels)}")
    print(f"First 10: {unique_rels[:10]}")

