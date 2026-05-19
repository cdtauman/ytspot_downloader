"""
core/musicbrainz_enricher.py  –  MusicBrainz metadata enrichment
=================================================================
Queries the MusicBrainz API (JSON, no auth required) to find the
canonical release for a track and enrich the file's ID3/MP4/FLAC tags
with: label, genre, ISRC, release year, and country.

Uses musicbrainzngs when available; falls back to a direct httpx call
to the MB JSON API when the library is absent.

Rate limiting: MusicBrainz asks for max 1 request/second.  We honour
this with a simple per-call sleep(1.0).

Zero GUI imports.  All errors are logged; returns False on any failure.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import httpx

from core.update_checker import CURRENT_VERSION

logger = logging.getLogger(__name__)

# MusicBrainz JSON API base
_MB_BASE = "https://musicbrainz.org/ws/2"
_MB_HEADERS = {
    "User-Agent": (
        f"YTSpotDownloader/{CURRENT_VERSION} "
        f"(https://github.com/cdtauman-projects/ytspot_downloader)"
    ),
    "Accept": "application/json",
}


# ── Public entry point ────────────────────────────────────────────────────────

def enrich_file(
    file_path:  str,
    title:      str,
    artist:     str,
    album:      str = "",
    duration_s: Optional[int] = None,
) -> bool:
    """
    Query MusicBrainz for the given track and embed enriched tags.

    Returns True if at least one tag was added, False otherwise.
    """
    recording = _find_recording(title, artist, album, duration_s)
    if not recording:
        logger.debug(
            "[MusicBrainz] No recording found for '%s – %s'", artist, title
        )
        return False

    tags_to_write = _extract_tags(recording)
    if not tags_to_write:
        return False

    return _write_enriched_tags(file_path, tags_to_write)


# ── MusicBrainz query ─────────────────────────────────────────────────────────

def _find_recording(
    title:      str,
    artist:     str,
    album:      str,
    duration_s: Optional[int],
) -> Optional[dict]:
    """
    Search the MusicBrainz recordings endpoint and return the best match.
    """
    # Build Lucene-style query
    parts = [f'recording:"{title}"']
    if artist:
        parts.append(f'artist:"{artist}"')
    if album:
        parts.append(f'release:"{album}"')
    query = " AND ".join(parts)

    try:
        time.sleep(1.0)   # MB rate limit
        resp = httpx.get(
            f"{_MB_BASE}/recording",
            params={
                "query":  query,
                "fmt":    "json",
                "limit":  5,
                "inc":    "releases+isrcs+artist-credits+genres",
            },
            headers=_MB_HEADERS,
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.debug("[MusicBrainz] API error: %s", exc)
        return None

    recordings = data.get("recordings") or []
    if not recordings:
        return None

    # If we have a duration, prefer the closest match (within 5 s)
    if duration_s is not None:
        def _dur_diff(rec: dict) -> int:
            mb_ms = rec.get("length")
            if mb_ms:
                return abs(int(mb_ms) // 1000 - duration_s)
            return 9999

        recordings_sorted = sorted(recordings, key=_dur_diff)
        if _dur_diff(recordings_sorted[0]) <= 5:
            return recordings_sorted[0]

    return recordings[0]


def _extract_tags(recording: dict) -> dict[str, str]:
    """
    Pull useful fields out of a MusicBrainz recording dict.

    Returns a flat {tag_name: value} dict; only non-empty values included.
    """
    tags: dict[str, str] = {}

    # ISRCs
    isrcs: list[str] = recording.get("isrcs") or []
    if isrcs:
        tags["ISRC"] = isrcs[0]

    # Genres (MB returns a list of {name, count} dicts, sorted by vote count)
    genres: list[dict] = recording.get("genres") or []
    if genres:
        top_genre = max(genres, key=lambda g: g.get("count", 0))
        if top_genre.get("name"):
            tags["GENRE"] = top_genre["name"].title()

    # Release info (first release in the list)
    releases: list[dict] = recording.get("releases") or []
    if releases:
        rel = releases[0]

        # Release date → year
        date_str: str = rel.get("date") or ""
        if date_str and len(date_str) >= 4:
            tags["YEAR"] = date_str[:4]

        # Label
        label_info: list[dict] = rel.get("label-info") or []
        if label_info and label_info[0].get("label"):
            label_name = label_info[0]["label"].get("name") or ""
            if label_name:
                tags["LABEL"] = label_name

        # Country
        country = rel.get("country") or ""
        if country:
            tags["RELEASECOUNTRY"] = country

    return tags


# ── Tag writers ────────────────────────────────────────────────────────────────

def _write_enriched_tags(file_path: str, tags: dict[str, str]) -> bool:
    """
    Write the enriched tag dict into the audio file.

    Supports MP3 (ID3), FLAC, M4A, OGG/Opus.
    """
    try:
        import mutagen  # noqa: F401
    except ImportError:
        logger.warning("[MusicBrainz] mutagen not installed; cannot write tags.")
        return False

    from pathlib import Path
    suffix = Path(file_path).suffix.lower()

    try:
        if suffix == ".mp3":
            _write_mp3(file_path, tags)
        elif suffix == ".flac":
            _write_flac(file_path, tags)
        elif suffix in (".m4a", ".mp4", ".aac"):
            _write_m4a(file_path, tags)
        elif suffix in (".ogg", ".opus"):
            _write_ogg(file_path, tags)
        else:
            logger.debug("[MusicBrainz] Unsupported format: %s", suffix)
            return False
    except Exception as exc:
        logger.error("[MusicBrainz] Tag write error on %s: %s", file_path, exc)
        return False

    logger.info("[MusicBrainz] Enriched %s with: %s", Path(file_path).name, tags)
    return True


def _write_mp3(file_path: str, tags: dict[str, str]) -> None:
    from mutagen.id3 import ID3, TXXX, TCON, TDRC, ID3NoHeaderError

    try:
        id3 = ID3(file_path)
    except ID3NoHeaderError:
        id3 = ID3()

    if "GENRE" in tags:
        id3.delall("TCON")
        id3.add(TCON(encoding=3, text=tags["GENRE"]))
    if "YEAR" in tags:
        id3.delall("TDRC")
        id3.add(TDRC(encoding=3, text=tags["YEAR"]))
    for key in ("ISRC", "LABEL", "RELEASECOUNTRY"):
        if key in tags:
            id3.delall(f"TXXX:{key}")
            id3.add(TXXX(encoding=3, desc=key, text=tags[key]))
    id3.save(file_path)


def _write_flac(file_path: str, tags: dict[str, str]) -> None:
    from mutagen.flac import FLAC

    audio = FLAC(file_path)
    _MAP = {"GENRE": "genre", "YEAR": "date", "ISRC": "isrc",
            "LABEL": "label", "RELEASECOUNTRY": "releasecountry"}
    for src_key, flac_key in _MAP.items():
        if src_key in tags:
            audio[flac_key] = tags[src_key]
    audio.save()


def _write_m4a(file_path: str, tags: dict[str, str]) -> None:
    from mutagen.mp4 import MP4, MP4FreeForm

    audio = MP4(file_path)
    if audio.tags is None:
        audio.add_tags()
    if "GENRE" in tags:
        audio.tags["\xa9gen"] = [tags["GENRE"]]
    if "YEAR" in tags:
        audio.tags["\xa9day"] = [tags["YEAR"]]
    for key in ("ISRC", "LABEL", "RELEASECOUNTRY"):
        if key in tags:
            audio.tags[f"----:com.apple.iTunes:{key}"] = [
                MP4FreeForm(tags[key].encode())
            ]
    audio.save()


def _write_ogg(file_path: str, tags: dict[str, str]) -> None:
    try:
        from mutagen.oggopus import OggOpus
        audio = OggOpus(file_path)
    except Exception:
        from mutagen.oggvorbis import OggVorbis
        audio = OggVorbis(file_path)

    _MAP = {"GENRE": "genre", "YEAR": "date", "ISRC": "isrc",
            "LABEL": "label", "RELEASECOUNTRY": "releasecountry"}
    for src_key, vorbis_key in _MAP.items():
        if src_key in tags:
            audio[vorbis_key] = [tags[src_key]]
    audio.save()
