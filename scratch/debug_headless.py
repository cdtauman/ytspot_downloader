
import sys
import os
from playwright.sync_api import sync_playwright
def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Use a real user agent
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        # Block images/fonts
        def block(route):
            if route.request.resource_type in ["image", "font", "media", "other"]:
                route.abort()
            else:
                route.continue_()
        page.route("**/*", block)
        
        url = "https://open.spotify.com/artist/28jEBK1RysfSUBHFofFflA/discography/album"
        print(f"Navigating to {url}...")
        page.goto(url, wait_until="load")
        
        # Take screenshot to see what's happening
        page.screenshot(path="scratch/spotify_debug.png")
        print("Screenshot saved to scratch/spotify_debug.png")
        
        # Check for grid
        grid_count = page.locator("div[role='grid']").count()
        print(f"Grid count: {grid_count}")
        
        content = page.content()
        with open("scratch/spotify_debug.html", "w", encoding="utf-8") as f:
            f.write(content)
            
        browser.close()
if __name__ == "__main__":
    run()
