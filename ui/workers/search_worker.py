"""
ui/workers/search_worker.py  –  Universal search worker
========================================================
Runs a SearchEngine query on a background thread and emits each result
individually as it arrives so the search panel populates incrementally,
exactly like a streaming search UI – no waiting for all results before
the first card appears.

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
    query        : The search string typed by the user.
    platform     : "youtube" | "spotify"  – which engine to query.
    max_results  : Maximum number of results to fetch (1–50).
    cookies_file : Optional cookies.txt path forwarded to SearchEngine.
    parent       : Optional Qt parent object.
    """

    # ── Signals ───────────────────────────────────────────────────────────────

    result_ready = Signal(object)   # SearchResult – one per emission
    status_msg   = Signal(str)      # Status bar text
    finished     = Signal(int)      # Total results returned
    error        = Signal(str)      # Human-readable failure message

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def __init__(
        self,
        query:        str,
        platform:     str            = "youtube",
        max_results:  int            = 15,
        cookies_file: Optional[str]  = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._query       = query.strip()
        self._platform    = platform
        self._max_results = max(1, min(50, max_results))
        self._engine      = SearchEngine(cookies_file=cookies_file)
        logger.debug("[SearchWorker] Initialized with query=%r, platform=%s, max_results=%d", self._query, self._platform, self._max_results)

    def cancel(self) -> None:
        """
        Thread-safe cancellation.
        Delegates to SearchEngine.cancel() which sets a threading.Event
        checked between results in the search loop.
        """
        logger.debug("[SearchWorker] Cancel requested.")
        self._engine.cancel()

    # ── QThread.run ───────────────────────────────────────────────────────────

    def run(self) -> None:
        """Entry point executed on the worker thread."""
        logger.debug("[SearchWorker] Starting run for query=%r, platform=%s", self._query, self._platform)
        if not self._query:
            logger.debug("[SearchWorker] Query is empty, aborting.")
            self.error.emit("Search query is empty.")
            return

        collected: list[SearchResult] = []

        def on_result(r: SearchResult) -> None:
            """Called by SearchEngine for each result as it resolves."""
            collected.append(r)
            self.result_ready.emit(r)

        try:
            # Handle all three platforms: youtube, spotify, or both
            if self._platform == "both":
                # Search both platforms
                logger.debug("[SearchWorker] Platform is 'both'. Starting YouTube search...")
                self.status_msg.emit(f"🔍  Searching YouTube for \"{self._query}\" …")
                try:
                    self._engine.search_youtube(
                        self._query,
                        max_results=self._max_results,
                        on_result=on_result,
                    )
                except Exception as e:
                    logger.debug("[SearchWorker] YouTube search error: %s", e, exc_info=True)
                
                logger.debug("[SearchWorker] Platform is 'both'. Starting Spotify search...")
                self.status_msg.emit(f"🔍  Searching Spotify for \"{self._query}\" …")
                try:
                    self._engine.search_spotify(
                        self._query,
                        max_results=self._max_results,
                        on_result=on_result,
                    )
                except Exception as e:
                    logger.debug("[SearchWorker] Spotify search error: %s", e, exc_info=True)
                platform_label = "YouTube + Spotify"
                
            elif self._platform == "spotify":
                logger.debug("[SearchWorker] Platform is 'spotify'. Starting Spotify search...")
                self.status_msg.emit(f"🔍  Searching Spotify for \"{self._query}\" …")
                self._engine.search_spotify(
                    self._query,
                    max_results=self._max_results,
                    on_result=on_result,
                )
                platform_label = "Spotify"
            else:  # youtube
                logger.debug("[SearchWorker] Platform is 'youtube'. Starting YouTube search...")
                self.status_msg.emit(f"🔍  Searching YouTube for \"{self._query}\" …")
                self._engine.search_youtube(
                    self._query,
                    max_results=self._max_results,
                    on_result=on_result,
                )
                platform_label = "YouTube"

            # Emit a meaningful completion message
            count = len(collected)
            logger.debug("[SearchWorker] Search completed. Collected %d results.", count)
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
            logger.debug("[SearchWorker] SearchError caught: %s", exc)
            self.error.emit(str(exc))

        except Exception as exc:  # noqa: BLE001
            logger.debug("[SearchWorker] Unexpected error: %s", exc, exc_info=True)
            self.error.emit(f"Unexpected search error: {exc}")
