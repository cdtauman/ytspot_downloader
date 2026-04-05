import re
import json
import urllib.request

class SpotifyResolver:
    @classmethod
    def resolve(cls, url: str) -> list[dict]:
        """
        Takes a Spotify URL (track, album, playlist) and uses the Spotify Embed API
        to resolve all items into YouTube search strings. 
        This avoids the 403 blocks on the main site & token endpoint.
        Returns a list of dicts: {'title', 'artist', 'url', 'duration_sec'}.
        """
        # Convert standard URL to an embed URL
        path_match = re.search(r'open\.spotify\.com/(track|album|playlist)/([^?]+)', url)
        if not path_match:
            raise ValueError("Invalid or unsupported Spotify URL format.")
            
        entity_type = path_match.group(1)
        entity_id = path_match.group(2)
        
        embed_url = f"https://open.spotify.com/embed/{entity_type}/{entity_id}"
        
        req = urllib.request.Request(
            embed_url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        
        try:
            with urllib.request.urlopen(req) as resp:
                html = resp.read().decode('utf-8')
        except Exception as e:
            raise RuntimeError(f"Failed to fetch Spotify embed page: {e}")
            
        # Extract the NEXT_DATA json payload
        json_match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
        if not json_match:
            raise RuntimeError("Could not find internal playlist data in Spotify embed page.")
            
        try:
            data = json.loads(json_match.group(1))
            entity = data["props"]["pageProps"]["state"]["data"]["entity"]
        except Exception as e:
            raise RuntimeError(f"Error parsing Spotify JSON data: {e}")

        items = []

        def _extract_duration_ms(track_obj: dict) -> int:
            """Safely extract duration in milliseconds from a track object."""
            if not isinstance(track_obj, dict):
                return 0
            
            # Case 1: {"duration": {"totalMilliseconds": 123}}
            duration_field = track_obj.get("duration")
            if isinstance(duration_field, dict):
                return duration_field.get("totalMilliseconds", 0)
            
            # Case 2: {"duration_ms": 123} (common in other Spotify APIs)
            if "duration_ms" in track_obj:
                return track_obj.get("duration_ms", 0)

            # Case 3 (based on error): {"duration": 123}
            if isinstance(duration_field, (int, float)):
                return int(duration_field)

            return 0

        if entity_type == "track":
            title = entity.get("name") or "Unknown Title"
            artist = entity.get("subtitle") or "Unknown Artist"
            duration_ms = _extract_duration_ms(entity)
            items.append({
                "title": title,
                "artist": artist,
                "url": f"ytsearch1:{artist} {title} audio",
                "duration_sec": duration_ms / 1000 if duration_ms else None
            })
            
        elif entity_type in ("playlist", "album"):
            track_list = entity.get("trackList", [])
            for track in track_list:
                title = track.get("title") or "Unknown Title"
                artist = track.get("subtitle") or "Unknown Artist"
                duration_ms = _extract_duration_ms(track)
                items.append({
                    "title": title,
                    "artist": artist,
                    "url": f"ytsearch1:{artist} {title} audio",
                    "duration_sec": duration_ms / 1000 if duration_ms else None
                })
        
        if not items:
            raise RuntimeError("No actionable tracks found in this Spotify link.")
            
        return items
