"""
core/parallel_enricher.py  –  Concurrent metadata enrichment
==============================================================
Takes a list of lightweight track stubs (from flat playlist extraction or
Spotify resolution) and enriches them in parallel using a thread pool.

Primary use cases
-----------------
1. **Spotify playlists** — Each track needs a YouTube search via the
   match scorer.  Sequential resolution of a 100-track playlist takes
   ~3 minutes; with 4 threads it drops to ~45 seconds.

2. **Flat-extracted YouTube playlists** — yt-dlp's ``extract_flat``
   mode returns entries with only title/ID/URL.  Enrichment fetches
   full metadata (duration, thumbnail, artist) per item.

Design
------
* Pure Python, zero GUI imports.
* Items are emitted incrementally via ``on_item`` callback as soon as
  each resolves — the UI can populate progressively.
* Order is NOT guaranteed (concurrent), but each item carries its
  original index so the UI can insert at the right position.
* Cancellation via threading.Event — checked between items.
* Failed items emit via ``on_error`` and are skipped, not fatal.

Thread safety: yt-dlp is re-entrant (each call creates its own
YoutubeDL context), so parallel extract_info calls are safe.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Generic, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


# ──────────────────────────────────────────────────────────────────────────────
# Generic parallel enricher
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class EnrichResult:
    """Summary of a parallel enrichment run."""
    total:      int
    succeeded:  int
    failed:     int
    cancelled:  bool


def enrich_parallel(
    items:        list,
    enrich_fn:    Callable,
    on_item:      Optional[Callable] = None,
    on_error:     Optional[Callable] = None,
    on_progress:  Optional[Callable] = None,
    cancel_event: Optional[threading.Event] = None,
    max_workers:  int = 4,
) -> tuple[list, EnrichResult]:
    """
    Enrich a list of items in parallel.

    Parameters
    ----------
    items       : Input items (any type).
    enrich_fn   : ``enrich_fn(item) -> enriched_item``.
                  Called on pool threads.  Should raise on failure.
    on_item     : ``on_item(enriched_item, index)`` — called as each
                  item is resolved.  Index is the original list position.
    on_error    : ``on_error(item, index, exception)`` — called on failure.
    on_progress : ``on_progress(completed, total)`` — progress counter.
    cancel_event: If set, stop submitting new work and abandon pending.
    max_workers : Thread pool size (1–8).

    Returns
    -------
    (enriched_items, EnrichResult) where enriched_items is a list the
    same length as ``items``, with None for failed entries.
    """
    total = len(items)
    if total == 0:
        return [], EnrichResult(0, 0, 0, False)

    n_workers = max(1, min(max_workers, 8, total))
    results: list = [None] * total
    succeeded = 0
    failed = 0
    cancelled = False

    pool = ThreadPoolExecutor(max_workers=n_workers, thread_name_prefix="enrich")

    try:
        futures = {}
        for idx, item in enumerate(items):
            if cancel_event and cancel_event.is_set():
                cancelled = True
                break
            future = pool.submit(_safe_enrich, enrich_fn, item, idx)
            futures[future] = idx

        for future in as_completed(futures):
            if cancel_event and cancel_event.is_set():
                cancelled = True
                break

            idx = futures[future]
            try:
                enriched, err = future.result()
                if err is not None:
                    failed += 1
                    if on_error:
                        try:
                            on_error(items[idx], idx, err)
                        except Exception:
                            pass
                else:
                    results[idx] = enriched
                    succeeded += 1
                    if on_item:
                        try:
                            on_item(enriched, idx)
                        except Exception:
                            pass
            except Exception as exc:
                failed += 1
                if on_error:
                    try:
                        on_error(items[idx], idx, exc)
                    except Exception:
                        pass

            if on_progress:
                try:
                    on_progress(succeeded + failed, total)
                except Exception:
                    pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    logger.info(
        "[Enricher] Done: %d/%d succeeded, %d failed, cancelled=%s",
        succeeded, total, failed, cancelled,
    )
    return results, EnrichResult(total, succeeded, failed, cancelled)


def _safe_enrich(fn: Callable, item, idx: int) -> tuple:
    """Wrapper that catches exceptions and returns (result, error)."""
    try:
        return fn(item), None
    except Exception as exc:
        logger.debug("[Enricher] Item %d failed: %s", idx, exc)
        return None, exc


# ──────────────────────────────────────────────────────────────────────────────
# Spotify-specific enricher (resolves YouTube matches in parallel)
# ──────────────────────────────────────────────────────────────────────────────

def enrich_spotify_tracks(
    tracks:       list[dict],
    on_item:      Optional[Callable] = None,
    on_error:     Optional[Callable] = None,
    on_progress:  Optional[Callable] = None,
    cancel_event: Optional[threading.Event] = None,
    max_workers:  int = 4,
    cookies_file: Optional[str] = None,
) -> tuple[list[dict], EnrichResult]:
    """
    Take a list of Spotify track dicts (from SpotifyResolver) and resolve
    each to a concrete YouTube URL using the match scorer.

    Each dict is expected to have: title, artist, duration_sec, url
    (currently a ytsearch1: string).

    Returns the same list with ``url`` replaced by real YouTube watch URLs
    for tracks that matched, or unchanged for those that didn't.
    """
    def _resolve_one(track: dict) -> dict:
        from core.spotify_match_scorer import find_best_youtube_match

        title    = track.get("title", "")
        artist   = track.get("artist", "")
        duration = track.get("duration_sec")

        match = find_best_youtube_match(
            title=title,
            artist=artist,
            duration_sec=duration,
            max_candidates=5,
            cookies_file=cookies_file,
            min_confidence=0.35,
        )

        if match:
            enriched = dict(track)
            enriched["url"] = match.url
            enriched["_match_confidence"] = match.confidence
            enriched["_match_yt_title"] = match.youtube_title
            return enriched
        else:
            # Keep original ytsearch1: URL as fallback
            return track

    return enrich_parallel(
        items=tracks,
        enrich_fn=_resolve_one,
        on_item=on_item,
        on_error=on_error,
        on_progress=on_progress,
        cancel_event=cancel_event,
        max_workers=max_workers,
    )
