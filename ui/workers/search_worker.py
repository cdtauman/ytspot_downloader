"""
ui/workers/search_worker.py  –  Universal search worker
========================================================
Runs a SearchEngine query on a background thread and emits each result
individually as it arrives so the search panel populates incrementally,
exactly like a streaming search UI – no waiting for all results before
the first card appears.

For YouTube, `search_youtube_categorized()` runs 3 parallel sub-queries
(tracks, playlists, channels) internally so all ResultKind variants are
populated without extra round-trips from this worker.

For Spotify, `search_spotify_categorized()` uses the Web API when
credentials are configured, otherwise falls back to the proxy endpoint.
Both return TRACK / ALBUM / PLAYLIST / ARTIST results.

Signal summary
--------------
result_ready(SearchResult)   One result; emitted as soon as it is resolved.
status_msg(str)              Status bar text ("Searching YouTube for …").
finished(int)                Total results returned (emitted once at the end).
error(str)                   Human-readable error message on failure.

Threading model
---------------
One SearchWorker is created per query submission.  If the user types a new
query before the previous one finishes, the caller should call
previous_worker.cancel() before starting the new worker.
cancel() sets a threading.Event inside SearchEngine that is checked between
results so the thread exits cleanly after the current network call.
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QThread, Signal

from core.search_engine import SearchEngine, SearchError, SearchResult

logger = logging.getLogger(__name__)


class SearchWorker(QThread):
    """
    Background search thread.

    Parameters
    ----------
    query            : The search string typed by the user.
    platform         : "youtube" | "spotify" | "both" – which engine to query.
    max_results      : Maximum number of results to fetch (1–50).
    cookies_file     : Optional cookies.txt path forwarded to SearchEngine.
    spotify_client_id     : Spotify Web API client ID (empty → proxy fallback).
    spotify_client_secret : Spotify Web API client secret.
    parent           : Optional Qt parent object.
    """

    # ── Signals ───────────────────────────────────────────────────────────────

    result_ready = Signal(object)   # SearchResult – one per emission
    status_msg   = Signal(str)      # Status bar text
    finished     = Signal(int)      # Total results returned
    error        = Signal(str)      # Human-readable failure message

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def __init__(
        self,
        query:                str,
        platform:             str           = "youtube",
        max_results:          int           = 15,
        cookies_file:         Optional[str] = None,
        spotify_client_id:    str           = "",
        spotify_client_secret: str          = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._query                 = query.strip()
        self._platform              = platform
        self._max_results           = max(1, min(50, max_results))
        self._spotify_client_id     = spotify_client_id
        self._spotify_client_secret = spotify_client_secret
        self._engine                = SearchEngine(cookies_file=cookies_file)
        logger.debug(
            "[SearchWorker] Init: query=%r  platform=%s  max_results=%d",
            self._query, self._platform, self._max_results,
        )

    def cancel(self) -> None:
        """Thread-safe cancellation.  Delegates to SearchEngine.cancel()."""
        logger.debug("[SearchWorker] Cancel requested.")
        self._engine.cancel()

    # ── QThread.run ───────────────────────────────────────────────────────────

    def run(self) -> None:
        logger.debug(
            "[SearchWorker] Starting run: query=%r  platform=%s",
            self._query, self._platform,
        )
        if not self._query:
            self.error.emit("Search query is empty.")
            return

        collected: list[SearchResult] = []

        def on_result(r: SearchResult) -> None:
            collected.append(r)
            self.result_ready.emit(r)

        try:
            if self._platform == "both":
                self._run_youtube(on_result)
                self._run_spotify(on_result)
                platform_label = "YouTube + Spotify"

            elif self._platform == "spotify":
                self._run_spotify(on_result)
                platform_label = "Spotify"

            else:  # youtube (default)
                self._run_youtube(on_result)
                platform_label = "YouTube"

            count = len(collected)
            logger.debug("[SearchWorker] Done: %d results.", count)
            if count == 0:
                self.status_msg.emit(
                    f"⚠  No results found for \"{self._query}\" on {platform_label}."
                )
            else:
                self.status_msg.emit(
                    f"✅  {count} result{'s' if count != 1 else ''} found "
                    f"for \"{self._query}\" on {platform_label}."
                )

            self.finished.emit(count)

        except SearchError as exc:
            logger.debug("[SearchWorker] SearchError: %s", exc)
            self.error.emit(str(exc))

        except Exception as exc:  # noqa: BLE001
            logger.debug("[SearchWorker] Unexpected error: %s", exc, exc_info=True)
            self.error.emit(f"Unexpected search error: {exc}")

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _run_youtube(self, on_result) -> None:
        """Run YouTube categorized search (tracks + playlists + channels)."""
        self.status_msg.emit(f"🔍  Searching YouTube for \"{self._query}\" …")
        try:
            if hasattr(self._engine, "search_youtube_categorized"):
                self._engine.search_youtube_categorized(
                    self._query,
                    max_results=self._max_results,
                    on_result=on_result,
                )
            else:
                # Fallback for older engine versions
                self._engine.search_youtube(
                    self._query,
                    max_results=self._max_results,
                    on_result=on_result,
                )
        except Exception as exc:
            logger.debug("[SearchWorker] YouTube search error: %s", exc, exc_info=True)

    def _run_spotify(self, on_result) -> None:
        """Run Spotify categorized search."""
        self.status_msg.emit(f"🔍  Searching Spotify for \"{self._query}\" …")
        try:
            if hasattr(self._engine, "search_spotify_categorized"):
                self._engine.search_spotify_categorized(
                    self._query,
                    max_results=self._max_results,
                    on_result=on_result,
                    client_id=self._spotify_client_id,
                    client_secret=self._spotify_client_secret,
                )
            else:
                # Fallback for older engine versions
                self._engine.search_spotify(
                    self._query,
                    max_results=self._max_results,
                    on_result=on_result,
                )
        except Exception as exc:
            logger.debug("[SearchWorker] Spotify search error: %s", exc, exc_info=True)
