"""
core/metadata_processor.py  –  Tag reading, writing, and filename utilities
============================================================================
Pure Python — zero Qt imports.  Uses mutagen (already in requirements).

Format support
--------------
  MP3   → mutagen.id3  (ID3 v2.3/2.4 frames)
  FLAC  → mutagen.flac (Vorbis comments)
  M4A   → mutagen.mp4  (iTunes atoms)

Follows the same dispatch pattern as core/replay_gain.py.
All public functions log errors and never raise to the caller.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Generator, Optional

from core.metadata_models import (
    AudioTrackItem,
    OriginalTags,
    ProposedTags,
    ScanResult,
    TrackStatus,
)

logger = logging.getLogger(__name__)

_SUPPORTED_EXTS: frozenset[str] = frozenset({".mp3", ".flac", ".m4a"})

# Matches a leading track number like "01 -", "1.", "002_", "03) ", "04 "
_TRACK_NUM_RE = re.compile(r"^\s*(\d{1,3})\s*[-–.)_\s]")
# Used to strip the leading number+separator from a filename stem
_STRIP_NUM_RE = re.compile(r"^\s*\d{1,3}\s*[-–.)_\s]\s*")


# ──────────────────────────────────────────────────────────────────────────────
# Public helpers
# ──────────────────────────────────────────────────────────────────────────────

def clean_filename_to_title(filename: str) -> str:
    """
    Convert a filename (with or without extension) to a clean song title.

    Examples:
      "01 - אור.mp3"   → "אור"
      "02. Track.flac" → "Track"
      "03_Song.m4a"    → "Song"
      "No Number.mp3"  → "No Number"
    """
    stem = Path(filename).stem
    cleaned = _STRIP_NUM_RE.sub("", stem).strip()
    return cleaned if cleaned else stem


def extract_track_number(filename: str) -> Optional[int]:
    """
    Extract the leading track number from a filename.

    "01 - Song.mp3" → 1
    "15 Track.flac" → 15
    "No Num.mp3"    → None
    """
    m = _TRACK_NUM_RE.match(Path(filename).name)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Scanning
# ──────────────────────────────────────────────────────────────────────────────

def scan_folder(
    root: Path,
    recursive: bool = True,
) -> Generator[AudioTrackItem, None, None]:
    """
    Yield AudioTrackItem objects for every audio file found under root.

    Unsupported extensions are yielded with status=UNSUPPORTED and no tag read.
    Errors during tag reading yield the item with status=ERROR.
    """
    pattern = "**/*" if recursive else "*"
    skipped = 0

    for file_path in sorted(root.glob(pattern)):
        if not file_path.is_file():
            continue

        ext = file_path.suffix.lower()

        if ext not in _SUPPORTED_EXTS:
            # Only surface audio-looking files as unsupported; skip non-audio silently
            _AUDIO_EXTS = {
                ".wav", ".wma", ".aac", ".ogg", ".opus", ".ape", ".m4b",
                ".mp4", ".aif", ".aiff", ".alac",
            }
            if ext in _AUDIO_EXTS:
                item = AudioTrackItem(
                    path=file_path,
                    folder=file_path.parent,
                    ext=ext,
                    status=TrackStatus.UNSUPPORTED,
                    error_msg="פורמט לא נתמך",
                )
                yield item
            else:
                skipped += 1
            continue

        try:
            tags = read_tags(file_path)
            item = AudioTrackItem(
                path=file_path,
                folder=file_path.parent,
                ext=ext,
                original=tags,
            )
        except Exception as exc:
            logger.error("[MetadataProcessor] Error reading %s: %s", file_path.name, exc)
            item = AudioTrackItem(
                path=file_path,
                folder=file_path.parent,
                ext=ext,
                status=TrackStatus.ERROR,
                error_msg=str(exc),
            )

        yield item


def build_scan_result(root: Path, tracks: list[AudioTrackItem], skipped: int) -> ScanResult:
    folder_set = {t.folder for t in tracks}
    result = ScanResult(root=root, tracks=tracks, skipped_count=skipped, folder_set=folder_set)
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Tag reading
# ──────────────────────────────────────────────────────────────────────────────

def read_tags(path: Path) -> OriginalTags:
    """Read ID3 / Vorbis / M4A tags from a file. Returns empty OriginalTags on failure."""
    ext = path.suffix.lower()
    try:
        if ext == ".mp3":
            return _read_mp3(path)
        elif ext == ".flac":
            return _read_flac(path)
        elif ext == ".m4a":
            return _read_m4a(path)
    except Exception as exc:
        logger.warning("[MetadataProcessor] read_tags failed on %s: %s", path.name, exc)
    return OriginalTags()


def _read_mp3(path: Path) -> OriginalTags:
    from mutagen.id3 import ID3, ID3NoHeaderError

    try:
        tags = ID3(str(path))
    except ID3NoHeaderError:
        return OriginalTags()

    def _text(frame_id: str) -> str:
        frame = tags.get(frame_id)
        if frame and frame.text:
            return str(frame.text[0]).strip()
        return ""

    track_num = None
    track_total = None
    trck = _text("TRCK")
    if trck:
        parts = trck.split("/")
        try:
            track_num = int(parts[0])
        except ValueError:
            pass
        if len(parts) > 1:
            try:
                track_total = int(parts[1])
            except ValueError:
                pass

    # Comments: prefer COMM::xxx, fall back to any COMM frame
    comment = ""
    for key in tags:
        if key.startswith("COMM"):
            frame = tags[key]
            if hasattr(frame, "text") and frame.text:
                comment = str(frame.text[0]).strip()
                break

    return OriginalTags(
        title        = _text("TIT2"),
        artist       = _text("TPE1"),
        album        = _text("TALB"),
        album_artist = _text("TPE2"),
        track_num    = track_num,
        track_total  = track_total,
        comment      = comment,
        year         = _text("TDRC"),
    )


def _read_flac(path: Path) -> OriginalTags:
    from mutagen.flac import FLAC

    audio = FLAC(str(path))

    def _get(key: str) -> str:
        vals = audio.get(key.lower(), [])
        return vals[0].strip() if vals else ""

    track_num = None
    track_total = None
    trackno_raw = _get("tracknumber")
    if trackno_raw:
        parts = trackno_raw.split("/")
        try:
            track_num = int(parts[0])
        except ValueError:
            pass
        if len(parts) > 1:
            try:
                track_total = int(parts[1])
            except ValueError:
                pass

    totaltracks_raw = _get("totaltracks") or _get("tracktotal")
    if totaltracks_raw and track_total is None:
        try:
            track_total = int(totaltracks_raw)
        except ValueError:
            pass

    return OriginalTags(
        title        = _get("title"),
        artist       = _get("artist"),
        album        = _get("album"),
        album_artist = _get("albumartist"),
        track_num    = track_num,
        track_total  = track_total,
        comment      = _get("comment"),
        year         = _get("date"),
    )


def _read_m4a(path: Path) -> OriginalTags:
    from mutagen.mp4 import MP4

    audio = MP4(str(path))
    tags = audio.tags or {}

    def _get_str(key: str) -> str:
        val = tags.get(key, [])
        return str(val[0]).strip() if val else ""

    track_num = None
    track_total = None
    trkn = tags.get("trkn")
    if trkn:
        pair = trkn[0]  # (track, total) tuple
        try:
            track_num = int(pair[0]) if pair[0] else None
        except (TypeError, ValueError, IndexError):
            pass
        try:
            track_total = int(pair[1]) if len(pair) > 1 and pair[1] else None
        except (TypeError, ValueError, IndexError):
            pass

    return OriginalTags(
        title        = _get_str("\xa9nam"),
        artist       = _get_str("\xa9ART"),
        album        = _get_str("\xa9alb"),
        album_artist = _get_str("aART"),
        track_num    = track_num,
        track_total  = track_total,
        comment      = _get_str("\xa9cmt"),
        year         = _get_str("\xa9day"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Tag writing
# ──────────────────────────────────────────────────────────────────────────────

def write_tags(path: Path, proposed: ProposedTags, original: OriginalTags) -> bool:
    """
    Write proposed tags to file.  Only fields that differ from original are written.
    Returns True on success, False on any error (error is logged).
    """
    if not proposed.has_changes(original):
        return True  # nothing to do

    effective = proposed.effective_tags(original)
    ext = path.suffix.lower()

    try:
        if ext == ".mp3":
            _write_mp3(path, effective)
        elif ext == ".flac":
            _write_flac(path, effective)
        elif ext == ".m4a":
            _write_m4a(path, effective)
        else:
            logger.warning("[MetadataProcessor] Unsupported format for writing: %s", ext)
            return False

        logger.info("[MetadataProcessor] Tagged: %s", path.name)
        return True

    except PermissionError:
        logger.error("[MetadataProcessor] Permission denied writing %s", path)
        return False
    except Exception as exc:
        logger.error("[MetadataProcessor] Write error on %s: %s", path.name, exc)
        return False


def _write_mp3(path: Path, tags: OriginalTags) -> None:
    from mutagen.id3 import (
        ID3, ID3NoHeaderError,
        TIT2, TPE1, TALB, TPE2, TRCK, COMM, TDRC,
        Encoding,
    )

    try:
        audio = ID3(str(path))
    except ID3NoHeaderError:
        audio = ID3()

    def _set(frame_id: str, frame_cls, **kwargs):
        audio.delall(frame_id)
        audio.add(frame_cls(encoding=Encoding.UTF8, **kwargs))

    def _del(frame_id: str):
        audio.delall(frame_id)

    if tags.title:
        _set("TIT2", TIT2, text=tags.title)
    else:
        _del("TIT2")

    if tags.artist:
        _set("TPE1", TPE1, text=tags.artist)
    else:
        _del("TPE1")

    if tags.album:
        _set("TALB", TALB, text=tags.album)
    else:
        _del("TALB")

    if tags.album_artist:
        _set("TPE2", TPE2, text=tags.album_artist)
    else:
        _del("TPE2")

    if tags.track_num is not None:
        trck_val = (
            f"{tags.track_num}/{tags.track_total}"
            if tags.track_total
            else str(tags.track_num)
        )
        _set("TRCK", TRCK, text=trck_val)
    else:
        _del("TRCK")

    if tags.comment:
        audio.delall("COMM")
        audio.add(COMM(encoding=Encoding.UTF8, lang="xxx", desc="", text=tags.comment))
    else:
        audio.delall("COMM")

    if tags.year:
        _set("TDRC", TDRC, text=tags.year)

    audio.save(str(path))


def _write_flac(path: Path, tags: OriginalTags) -> None:
    from mutagen.flac import FLAC

    audio = FLAC(str(path))

    def _set(key: str, value: str):
        if value:
            audio[key] = value
        elif key in audio:
            del audio[key]

    _set("title",       tags.title)
    _set("artist",      tags.artist)
    _set("album",       tags.album)
    _set("albumartist", tags.album_artist)
    _set("comment",     tags.comment)

    if tags.track_num is not None:
        audio["tracknumber"] = str(tags.track_num)
        if tags.track_total:
            audio["totaltracks"] = str(tags.track_total)
    elif "tracknumber" in audio:
        del audio["tracknumber"]

    audio.save()


def _write_m4a(path: Path, tags: OriginalTags) -> None:
    from mutagen.mp4 import MP4

    audio = MP4(str(path))
    if audio.tags is None:
        audio.add_tags()
    t = audio.tags

    def _set(key: str, value: str):
        if value:
            t[key] = [value]
        elif key in t:
            del t[key]

    _set("\xa9nam", tags.title)
    _set("\xa9ART", tags.artist)
    _set("\xa9alb", tags.album)
    _set("aART",    tags.album_artist)
    _set("\xa9cmt", tags.comment)

    if tags.track_num is not None:
        total = tags.track_total or 0
        t["trkn"] = [(tags.track_num, total)]
    elif "trkn" in t:
        del t["trkn"]

    audio.save()


# ──────────────────────────────────────────────────────────────────────────────
# Backup
# ──────────────────────────────────────────────────────────────────────────────

def backup_tags(tracks: list[AudioTrackItem], backup_path: Path) -> None:
    """
    Write a JSON backup of all original tags to backup_path.
    Creates parent directories if needed.
    """
    backup_path.parent.mkdir(parents=True, exist_ok=True)

    records = []
    for item in tracks:
        records.append({
            "path":     str(item.path),
            "original": item.original.to_dict(),
        })

    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    logger.info("[MetadataProcessor] Backup saved: %s (%d tracks)", backup_path.name, len(records))
