"""
core/duplicate_checker.py  –  Smart duplicate detection
========================================================
Before a download starts, this module checks whether an output file that
would match the given request already exists on disk.

Logic
-----
1. Reconstruct the expected output filename using the same rules as
   downloader.py (artist – title.ext, with optional index prefix and
   playlist subfolder).
2. Search for any file whose stem matches the expected stem (ignoring
   extension, to catch format conversions) in the output directory.
3. Optionally verify the match by comparing the file duration (within
   ±5 seconds) using mutagen – avoids false positives from coincidental
   filename collisions.

The caller decides what to do with the result; this module only detects.

Zero GUI imports.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Audio extensions we scan for when checking duplicates
_AUDIO_EXTS: frozenset[str] = frozenset(
    {".mp3", ".m4a", ".flac", ".opus", ".ogg", ".wav", ".aac"}
)


def _sanitize(name: str) -> str:
    """Mirror downloader._sanitize_filename exactly."""
    if not name: return "Unknown"
    name = name.replace('"', "''").replace(":", " - ").replace("/", "-").replace("\\", "-").replace("|", "-")
    name = re.sub(r'[*?<> ]', " ", name)
    name = re.sub(r'\s+', " ", name)
    name = re.sub(r'[\x00-\x1f]', "", name)
    return name.strip(". ")[:200]


def expected_stem(
    title:             str,
    artist:            str,
    index:             Optional[int] = None,
    include_index:     bool          = True,
) -> str:
    """
    Return the expected filename stem (no extension) for the given track,
    mirroring the naming logic in downloader.py.
    """
    a = _sanitize(artist or "Unknown Artist")
    t = _sanitize(title  or "Unknown Title")
    prefix = f"{index:02d} " if (index is not None and include_index) else ""
    return f"{prefix}{a} - {t}"


def find_duplicate(
    output_dir:    str,
    title:         str,
    artist:        str,
    index:         Optional[int] = None,
    include_index: bool          = True,
    duration_s:    Optional[int] = None,
    playlist_name: str           = "",
) -> Optional[Path]:
    """
    Search for an existing file that matches the expected output.

    Parameters
    ----------
    output_dir    : Base download directory.
    title         : Track title.
    artist        : Artist name.
    index         : 1-based track index (for playlists).
    include_index : Whether to include the index prefix in the stem.
    duration_s    : Expected duration in seconds for verification.
    playlist_name : Sub-folder name when playlist_subfolders is enabled.

    Returns
    -------
    Path of the duplicate file if found, else None.
    """
    base = Path(output_dir).expanduser().resolve()
    search_dir = base / playlist_name if playlist_name else base

    if not search_dir.exists():
        return None

    stem = expected_stem(title, artist, index, include_index)
    stem_lower = stem.lower()

    for candidate in search_dir.iterdir():
        if candidate.suffix.lower() not in _AUDIO_EXTS:
            continue
        if candidate.stem.lower() != stem_lower:
            continue
        # Stem match found – optionally verify duration
        if duration_s is not None:
            file_dur = _get_duration(candidate)
            if file_dur is not None and abs(file_dur - duration_s) > 5:
                continue   # same name but different track length
        logger.info(
            "[DuplicateChecker] Duplicate found: %s", candidate.name
        )
        return candidate

    return None


def _get_duration(path: Path) -> Optional[int]:
    """
    Return the audio duration of a file in seconds using mutagen, or None.
    """
    try:
        import mutagen
        audio = mutagen.File(str(path))
        if audio and audio.info:
            return int(audio.info.length)
    except Exception as exc:
        logger.debug("[DuplicateChecker] mutagen error on %s: %s", path.name, exc)
    return None
