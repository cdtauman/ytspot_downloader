"""
utils/artwork_cleaner.py  –  Thumbnail URL sanitization
=======================================================
Transforms raw platform thumbnail URLs into high-resolution, square (1:1)
versions to ensure consistent UI display and high-quality embedding.
"""

import re
def clean_artwork_url(url: str, platform) -> str:
    """
    Transform a raw thumbnail URL into a high-res square version if possible.
    
    Rules
    -----
    YouTube Music (lh3.googleusercontent / yt3.ggpht):
        Replace size suffixes like =w120-h120-l90-rj with =w1024-h1024-p-rj.
    
    YouTube (i.ytimg.com):
        Prefer maxresdefault.jpg.
        
    Spotify:
        Usually already square, return as-is.
    """
    from core.playlist_parser import SourcePlatform
    if not url:
        return ""

    if platform == SourcePlatform.YOUTUBE_MUSIC:
        # lh3.googleusercontent.com or yt3.ggpht.com URLs often have size params at the end
        # Example: https://lh3.googleusercontent.com/...=w120-h120-l90-rj
        # Examples of matches: =w120-h120, =s120-c, -w120-h120
        pattern = r'(=|-)(w|s)\d+(-b\d+)?(-h\d+)?(-[a-z0-9-]+)?$'
        if re.search(pattern, url):
            # Force 1024x1024 crop
            return re.sub(pattern, r'\1w1024-h1024-p-rj', url)
        
        # If no suffix found but it's a googleusercontent URL, we can try appending it
        if "googleusercontent.com" in url or "ggpht.com" in url:
            if "=" not in url:
                return f"{url}=w1024-h1024-p-rj"
            
    elif platform == SourcePlatform.YOUTUBE:
        # Transform hqdefault.jpg / mqdefault.jpg to maxresdefault.jpg
        # Use a more specific check to avoid double-replacing "default.jpg" in "maxresdefault.jpg"
        if "i.ytimg.com/vi/" in url:
            for quality in ["hqdefault.jpg", "mqdefault.jpg", "sddefault.jpg", "default.jpg"]:
                if quality in url:
                    return url.replace(quality, "maxresdefault.jpg")
            
    return url
