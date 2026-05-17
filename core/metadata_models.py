"""
core/metadata_models.py  –  Data classes for the Tag Editor feature
====================================================================
Pure Python — zero Qt imports. All classes are mutable dataclasses
that can be serialised to / from plain dicts for JSON backup.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ──────────────────────────────────────────────────────────────────────────────
# Tag state
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class OriginalTags:
    """Tags as they currently exist on disk."""
    title:        str = ""
    artist:       str = ""
    album:        str = ""
    album_artist: str = ""
    track_num:    Optional[int] = None
    track_total:  Optional[int] = None
    comment:      str = ""
    year:         str = ""
    genre:        str = ""

    def to_dict(self) -> dict:
        return {
            "title":        self.title,
            "artist":       self.artist,
            "album":        self.album,
            "album_artist": self.album_artist,
            "track_num":    self.track_num,
            "track_total":  self.track_total,
            "comment":      self.comment,
            "year":         self.year,
            "genre":        self.genre,
        }


@dataclass
class ProposedTags:
    """
    Proposed changes — overlaid on OriginalTags at apply time.

    Convention:
      None  = "leave unchanged"
      ""    = "clear this field"
      value = "set to this value"
    """
    title:        Optional[str] = None
    artist:       Optional[str] = None
    album:        Optional[str] = None
    album_artist: Optional[str] = None
    track_num:    Optional[int] = None   # -1 means "clear"
    comment:      Optional[str] = None
    year:         Optional[str] = None
    genre:        Optional[str] = None

    def has_changes(self, original: OriginalTags) -> bool:
        """True if any proposed field would actually change the original."""
        checks = [
            (self.title,        original.title),
            (self.artist,       original.artist),
            (self.album,        original.album),
            (self.album_artist, original.album_artist),
            (self.comment,      original.comment),
            (self.year,         original.year),
            (self.genre,        original.genre),
        ]
        for proposed, orig in checks:
            if proposed is not None and proposed != orig:
                return True
        if self.track_num is not None and self.track_num != original.track_num:
            return True
        return False

    def effective_tags(self, original: OriginalTags) -> OriginalTags:
        """Merge proposed values over original, returning the final result."""
        def pick(proposed, orig):
            return orig if proposed is None else proposed

        track = original.track_num
        if self.track_num is not None:
            track = None if self.track_num == -1 else self.track_num

        return OriginalTags(
            title        = pick(self.title,        original.title),
            artist       = pick(self.artist,       original.artist),
            album        = pick(self.album,        original.album),
            album_artist = pick(self.album_artist, original.album_artist),
            track_num    = track,
            track_total  = original.track_total,
            comment      = pick(self.comment,      original.comment),
            year         = pick(self.year,         original.year),
            genre        = pick(self.genre,        original.genre),
        )

    def clear(self) -> None:
        """Reset all proposed fields to None (revert state)."""
        self.title        = None
        self.artist       = None
        self.album        = None
        self.album_artist = None
        self.track_num    = None
        self.comment      = None
        self.year         = None
        self.genre        = None


# ──────────────────────────────────────────────────────────────────────────────
# Track item
# ──────────────────────────────────────────────────────────────────────────────

class TrackStatus:
    PENDING     = "pending"
    CHANGED     = "changed"
    DONE        = "done"
    ERROR       = "error"
    UNSUPPORTED = "unsupported"


@dataclass
class AudioTrackItem:
    """Represents one audio file in the tag-editor session."""
    path:      Path
    folder:    Path       # = path.parent, pre-computed for fast filtering
    ext:       str        # ".mp3" | ".flac" | ".m4a"
    original:  OriginalTags = field(default_factory=OriginalTags)
    proposed:  ProposedTags = field(default_factory=ProposedTags)
    proposed_filename: Optional[str] = None   # rename target (None = no rename)
    status:    str = TrackStatus.PENDING
    error_msg: str = ""

    @property
    def display_name(self) -> str:
        return self.path.name

    @property
    def has_changes(self) -> bool:
        return (
            self.proposed.has_changes(self.original)
            or self.proposed_filename is not None
        )


# ──────────────────────────────────────────────────────────────────────────────
# Scan result + session
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ScanResult:
    root:          Path
    tracks:        list[AudioTrackItem] = field(default_factory=list)
    skipped_count: int = 0
    folder_set:    set[Path] = field(default_factory=set)

    @property
    def files_count(self) -> int:
        return len(self.tracks)

    @property
    def folders_count(self) -> int:
        return len(self.folder_set)


@dataclass
class TagEditSession:
    scan_result:   Optional[ScanResult] = None
    backup_path:   Optional[Path] = None
    apply_done:    int = 0
    apply_failed:  int = 0
    apply_skipped: int = 0
