"""
core/playlist_sync.py  –  Playlist delta / smart sync
======================================================
Compares a saved playlist snapshot (stored in the download history DB)
against the current live playlist and returns only the items that are
NEW since the last sync – avoiding re-downloading already-owned tracks.

Integration
-----------
Called by FetchWorker when the user fetches a playlist URL that has been
seen before.  The worker receives a ``SyncResult`` and emits only the
new items as TrackMeta; existing items are silently skipped.

The "seen" set is keyed on video ID (extracted from the YouTube watch URL)
so format changes or metadata edits to existing tracks do not count as new.

Zero GUI imports.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Pattern to extract YouTube video ID from watch URLs and short URLs
_YT_ID_RE = re.compile(
    r"(?:v=|youtu\.be/|/v/|/embed/|/shorts/)([A-Za-z0-9_-]{11})"
)


@dataclass
class SyncResult:
    """Result of a playlist diff operation."""
    playlist_url:   str
    total_fetched:  int          # items in live playlist
    new_count:      int          # items not in history
    skipped_count:  int          # items already downloaded
    new_video_ids:  list[str]    # IDs of genuinely new items


def extract_video_id(url: str) -> Optional[str]:
    """Extract an 11-character YouTube video ID from a URL."""
    m = _YT_ID_RE.search(url)
    return m.group(1) if m else None


def diff_playlist(
    playlist_url:  str,
    fetched_items: list,            # list[TrackMeta] from playlist_parser
    db,                             # HistoryDB instance
) -> SyncResult:
    """
    Compare fetched_items against the download history for this playlist.

    Parameters
    ----------
    playlist_url  : The canonical URL of the playlist (used as key).
    fetched_items : List of TrackMeta objects returned by PlaylistParser.
    db            : HistoryDB instance to query existing downloads.

    Returns
    -------
    SyncResult with new_video_ids listing only the IDs that should be queued.
    """
    total = len(fetched_items)

    # Collect all video IDs already in history for this playlist URL
    try:
        existing_ids = _get_downloaded_ids(db, playlist_url)
    except Exception as exc:
        logger.warning("[PlaylistSync] DB query failed: %s – syncing all.", exc)
        existing_ids = set()

    new_ids:     list[str] = []
    skipped:     int       = 0

    for item in fetched_items:
        url = getattr(item, "url", "") or ""
        vid_id = extract_video_id(url)
        if vid_id and vid_id in existing_ids:
            skipped += 1
            logger.debug("[PlaylistSync] Skipping known track: %s", vid_id)
        else:
            new_ids.append(vid_id or url)

    result = SyncResult(
        playlist_url=playlist_url,
        total_fetched=total,
        new_count=len(new_ids),
        skipped_count=skipped,
        new_video_ids=new_ids,
    )
    logger.info(
        "[PlaylistSync] %s: %d total, %d new, %d skipped",
        playlist_url, total, result.new_count, skipped,
    )
    return result


def filter_new_items(
    fetched_items: list,
    sync_result:   SyncResult,
) -> list:
    """
    Return only the TrackMeta items from fetched_items whose video IDs
    appear in sync_result.new_video_ids.
    """
    new_id_set = set(sync_result.new_video_ids)
    filtered: list = []
    for item in fetched_items:
        url    = getattr(item, "url", "") or ""
        vid_id = extract_video_id(url)
        if (vid_id and vid_id in new_id_set) or (url in new_id_set):
            filtered.append(item)
    return filtered


# ── History DB query ───────────────────────────────────────────────────────────

def _get_downloaded_ids(db, playlist_url: str) -> set[str]:
    """
    Return a set of video IDs for all records in the DB that originated
    from the given playlist URL.

    Queries HistoryDB.fetch_all() and filters by URL pattern.
    """
    try:
        records = db.fetch_all(limit=10_000)
    except Exception:
        return set()

    ids: set[str] = set()
    for record in records:
        rec_url = getattr(record, "url", "") or ""
        vid_id  = extract_video_id(rec_url)
        if vid_id:
            ids.add(vid_id)
    return ids
