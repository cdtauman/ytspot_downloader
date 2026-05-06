"""
core/lyrics_embedder.py  –  Lyrics fetch + embed (Advanced Setting)
====================================================================
Fetches plain-text lyrics for a track using the syncedlyrics library
(which queries multiple lyrics sources in order) and embeds them into
the file's metadata tags.

Supported containers
--------------------
  MP3  → ID3  USLT (Unsynchronised Lyrics) tag
  M4A  → iTunes ©lyr atom via mutagen.mp4
  FLAC → LYRICS Vorbis comment via mutagen.flac
  OPUS → LYRICS Vorbis comment via mutagen.oggvorbis

This module is **disabled by default** and is only called from
downloader.py when AppConfig.lyrics_enabled is True.

Zero GUI imports.  Raises LyricsError on unrecoverable failure.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class LyricsError(Exception):
    """Raised when lyrics cannot be fetched or embedded."""


def _fetch_lyrics(title: str, artist: str) -> Optional[str]:
    """
    Try to fetch plain-text lyrics using syncedlyrics.

    Returns the lyrics string, or None if not found.
    Falls back gracefully if syncedlyrics is not installed.
    """
    try:
        import syncedlyrics  # type: ignore[import]
    except ImportError:
        logger.warning("[LyricsEmbedder] syncedlyrics not installed. "
                       "Run: pip install syncedlyrics")
        return None

    query = f"{artist} {title}".strip()
    try:
        # syncedlyrics.search returns synced LRC text or falls back to plain
        lyrics = syncedlyrics.search(query, plain_only=True)
        if lyrics:
            return lyrics
        # Try without artist if first search failed
        lyrics = syncedlyrics.search(title, plain_only=True)
        return lyrics
    except Exception as exc:
        logger.debug("[LyricsEmbedder] syncedlyrics search error: %s", exc)
        return None


def embed_lyrics(
    file_path: str,
    title:     str,
    artist:    str,
) -> bool:
    """
    Fetch lyrics for the given track and embed them into file_path.

    Parameters
    ----------
    file_path : Absolute path to the downloaded audio file.
    title     : Track title (used for lyrics query).
    artist    : Artist name (used for lyrics query).

    Returns
    -------
    True if lyrics were embedded, False if not found or embedding failed.

    Raises
    ------
    LyricsError if mutagen is not available.
    """
    try:
        import mutagen  # noqa: F401
    except ImportError as exc:
        raise LyricsError("mutagen not installed. Run: pip install mutagen") from exc

    lyrics = _fetch_lyrics(title, artist)
    if not lyrics:
        logger.info("[LyricsEmbedder] No lyrics found for '%s – %s'", artist, title)
        return False

    path = Path(file_path)
    suffix = path.suffix.lower()

    try:
        if suffix == ".mp3":
            _embed_mp3(path, lyrics, title, artist)
        elif suffix in (".m4a", ".mp4", ".aac"):
            _embed_m4a(path, lyrics)
        elif suffix == ".flac":
            _embed_flac(path, lyrics)
        elif suffix in (".ogg", ".opus"):
            _embed_ogg(path, lyrics)
        else:
            logger.warning(
                "[LyricsEmbedder] Unsupported format '%s' for lyrics embedding.", suffix
            )
            return False
    except Exception as exc:
        logger.error("[LyricsEmbedder] Failed to embed lyrics in %s: %s", file_path, exc)
        return False

    logger.info("[LyricsEmbedder] Lyrics embedded in %s", path.name)
    return True


# ── Format-specific writers ────────────────────────────────────────────────────

def _embed_mp3(path: Path, lyrics: str, title: str, artist: str) -> None:
    from mutagen.id3 import ID3, USLT, ID3NoHeaderError

    try:
        tags = ID3(str(path))
    except ID3NoHeaderError:
        tags = ID3()

    # Remove any existing lyrics tags first
    tags.delall("USLT")
    tags.add(
        USLT(
            encoding=3,       # UTF-8
            lang="eng",
            desc="Lyrics",
            text=lyrics,
        )
    )
    tags.save(str(path))


def _embed_m4a(path: Path, lyrics: str) -> None:
    from mutagen.mp4 import MP4

    audio = MP4(str(path))
    if audio.tags is None:
        audio.add_tags()
    audio.tags["\xa9lyr"] = [lyrics]
    audio.save()


def _embed_flac(path: Path, lyrics: str) -> None:
    from mutagen.flac import FLAC

    audio = FLAC(str(path))
    audio["LYRICS"] = lyrics
    audio.save()


def _embed_ogg(path: Path, lyrics: str) -> None:
    try:
        from mutagen.oggopus import OggOpus
        audio = OggOpus(str(path))
    except Exception:
        from mutagen.oggvorbis import OggVorbis
        audio = OggVorbis(str(path))
    audio["LYRICS"] = [lyrics]
    audio.save()
