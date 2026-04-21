
import sys
import os
from playwright.sync_api import sync_playwright
def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        # NO RESOURCE BLOCKING THIS TIME
        url = "https://open.spotify.com/artist/28jEBK1RysfSUBHFofFflA/discography/album"
        print(f"Navigating to {url}...")
        page.goto(url, wait_until="networkidle") # Wait for everything
        
        page.screenshot(path="scratch/spotify_debug_full.png")
        print("Screenshot saved to scratch/spotify_debug_full.png")
        
        grid_count = page.locator("div[role='grid']").count()
        print(f"Grid count: {grid_count}")
            
        browser.close()
if __name__ == "__main__":
    run()
