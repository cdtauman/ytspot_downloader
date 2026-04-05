"""
ui/workers/download_worker.py  –  Parallel download queue worker
================================================================
Downloads a list of (card_key, DownloadRequest) jobs using a
ThreadPoolExecutor so up to 3 tracks are downloaded simultaneously,
dramatically improving batch throughput.

Each job runs on its own pool thread and gets its own threading.Event for
per-track cancellation – cancelling one job does not affect sibling jobs.
All DownloadEngine calls are safe to make from pool threads because:
  * yt-dlp is re-entrant (each call creates its own YoutubeDL context).
  * HistoryDB uses a threading.Lock() for all SQL access.
  * Qt Signals emitted from background threads are automatically queued to
    the main thread via Qt's cross-thread signal mechanism.

Signal summary
--------------
track_progress(str, float)    Per-track progress fraction 0.0 → 1.0.
track_status(str, str)        Per-track status: "downloading"|"done"|"error"|"cancelled".
track_finished(str, str)      (card_key, absolute output_path) on success.
overall_progress(float)       Aggregate fraction across all jobs 0.0 → 1.0.
metrics(str, str)             (speed_str, eta_str) for the status bar.
status_msg(str)               Human-readable status line for the status bar.
job_error(str, object)        (card_key, ErrorInfo) on per-track failure.
all_finished()                Entire batch complete.

Threading model
---------------
One DownloadWorker is created per "Download Selected" click.  It owns a
temporary ThreadPoolExecutor (max 3 workers, or fewer if fewer jobs).
The DownloadEngine instance is shared from AppWindow and handles its own
internal locking.  Cancellation is bi-directional:
  * cancel() on DownloadWorker → sets all per-request events + engine event
  * engine.cancel_all()        → same effect, accessible from AppWindow
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal

from core.history_db import DownloadRecord, HistoryDB
from downloader import (
    DownloadEngine,
    DownloadProgress,
    DownloadRequest,
    MediaType,
)
from error_handler import classify_error, ErrorInfo


class DownloadWorker(QThread):
    """
    Parallel download queue executor.

    Parameters
    ----------
    jobs    : List of (card_key, DownloadRequest) tuples.
    engine  : Shared DownloadEngine instance owned by AppWindow.
    db      : Optional HistoryDB for post-download record insertion.
    max_workers : How many tracks to download in parallel (default 3).
    parent  : Optional Qt parent.
    """

    # ── Signals ───────────────────────────────────────────────────────────────

    track_progress   = Signal(str, float)   # (card_key, fraction 0.0–1.0)
    track_status     = Signal(str, str)      # (card_key, status_str)
    track_finished   = Signal(str, str)      # (card_key, absolute output_path)
    overall_progress = Signal(float)         # batch-level 0.0–1.0
    metrics          = Signal(str, str)      # (speed_str, eta_str)
    status_msg       = Signal(str)
    job_error        = Signal(str, object)   # (card_key, ErrorInfo)
    all_finished     = Signal()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def __init__(
        self,
        jobs:        list[tuple[str, DownloadRequest]],
        engine:      DownloadEngine,
        db:          Optional[HistoryDB] = None,
        max_workers: int                 = 3,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._jobs        = jobs
        self._engine      = engine
        self._db          = db
        self._max_workers = max(1, min(max_workers, 5))
        self._total       = len(jobs)

        # Per-job cancel events so individual tracks can be cancelled
        self._cancel_events: dict[str, threading.Event] = {}

        # Progress accounting (thread-safe via lock)
        self._completed    = 0
        self._progress_lock = threading.Lock()
        self._job_progress: dict[str, float] = {}   # card_key → latest fraction

    # ── Public API ────────────────────────────────────────────────────────────

    def cancel(self) -> None:
        """
        Cancel all in-flight downloads.
        Sets every per-request event and the engine's global cancel event.
        """
        for ev in self._cancel_events.values():
            ev.set()
        self._engine.cancel_all()

    def cancel_track(self, card_key: str) -> None:
        """Cancel a single in-flight download by card key."""
        ev = self._cancel_events.get(card_key)
        if ev:
            ev.set()

    # ── QThread.run ───────────────────────────────────────────────────────────

    def run(self) -> None:
        """Entry point executed on the QThread thread."""
        # Ensure the global cancel event is clear at the start of a new batch
        self._engine._cancel_event.clear()  # noqa: SLF001

        n_workers = min(self._max_workers, self._total)
        futures   = {}

        with ThreadPoolExecutor(
            max_workers=n_workers,
            thread_name_prefix="dl-pool",
        ) as pool:
            for card_key, req in self._jobs:
                # Give each job its own cancel event
                ev = threading.Event()
                req.cancel_event = ev
                self._cancel_events[card_key] = ev
                self._job_progress[card_key]  = 0.0

                future = pool.submit(self._download_one, card_key, req)
                futures[future] = card_key

            # Wait for every job; surface exceptions that escaped _download_one
            for future in as_completed(futures):
                card_key = futures[future]
                try:
                    future.result()
                except Exception as exc:  # noqa: BLE001
                    err = classify_error(exc)
                    self.track_status.emit(card_key, "error")
                    self.job_error.emit(card_key, err)

        # ── Batch finalisation ─────────────────────────────────────────────────
        cancelled = self._engine._cancel_event.is_set()  # noqa: SLF001
        self.overall_progress.emit(1.0)
        self.metrics.emit("", "")
        self.status_msg.emit(
            "🚫  Cancelled."
            if cancelled
            else (
                f"✅  Done — {self._total} track"
                f"{'s' if self._total != 1 else ''} downloaded."
            )
        )
        self.all_finished.emit()

    # ── Per-job runner (called on pool thread) ────────────────────────────────

    def _download_one(self, card_key: str, req: DownloadRequest) -> None:
        """
        Download a single track and emit signals for every progress event.
        Runs on a pool thread; all signal emissions are cross-thread safe.
        """
        cancel_ev = self._cancel_events[card_key]

        # Skip if already cancelled before we even start
        if cancel_ev.is_set() or self._engine._cancel_event.is_set():  # noqa: SLF001
            self.track_status.emit(card_key, "cancelled")
            return

        self.track_status.emit(card_key, "downloading")

        update_counter = [0]

        def on_progress(p: DownloadProgress) -> None:
            update_counter[0] += 1
            # Throttle: only emit every 10th update to avoid Qt signal saturation
            if update_counter[0] % 10 != 0:
                return

            with self._progress_lock:
                self._job_progress[card_key] = p.fraction
                overall = sum(self._job_progress.values()) / self._total
            self.track_progress.emit(card_key, p.fraction)
            self.overall_progress.emit(min(overall, 1.0))

            speed_str = ""
            eta_str   = ""
            if p.speed_bps:
                kb = p.speed_bps / 1024
                speed_str = (
                    f"{kb:.0f} KB/s" if kb < 1024 else f"{kb / 1024:.1f} MB/s"
                )
            if p.eta_seconds:
                s = int(p.eta_seconds)
                eta_str = (
                    f"ETA {s // 60}m{s % 60:02d}s" if s >= 60 else f"ETA {s}s"
                )
            self.metrics.emit(speed_str, eta_str)

        def on_finished(p: DownloadProgress) -> None:
            with self._progress_lock:
                self._job_progress[card_key] = 1.0
                self._completed += 1
                overall = sum(self._job_progress.values()) / self._total
            self.track_status.emit(card_key, "done")
            self.track_progress.emit(card_key, 1.0)
            self.track_finished.emit(card_key, p.output_path or "")
            self.overall_progress.emit(min(overall, 1.0))
            if self._db is not None:
                self._persist_record(req, p)

        def on_error(p: DownloadProgress) -> None:
            err = classify_error(
                Exception(p.error_message or "Unknown download error")
            )
            self.track_status.emit(card_key, "error")
            self.job_error.emit(card_key, err)

        req.on_progress = on_progress
        req.on_finished = on_finished
        req.on_error    = on_error

        self._engine.download(req)

    # ── History persistence ────────────────────────────────────────────────────

    def _persist_record(self, req: DownloadRequest, prog: DownloadProgress) -> None:
        """Insert a DownloadRecord on success.  Never raises."""
        try:
            output_path  = prog.output_path or ""
            file_size_mb: Optional[float] = None

            if output_path:
                p = Path(output_path)
                if p.exists():
                    file_size_mb = round(p.stat().st_size / (1024 * 1024), 2)

            url_lower = req.url.lower()
            if "spotify" in url_lower:
                platform = "spotify"
            elif "music.youtube" in url_lower:
                platform = "ytmusic"
            elif "youtube" in url_lower or "youtu.be" in url_lower:
                platform = "youtube"
            else:
                platform = "unknown"

            record = DownloadRecord(
                title=req.forced_title  or prog.title or "Unknown Title",
                artist=req.forced_artist or "",
                url=req.url,
                output_path=output_path,
                media_type="audio" if req.media_type == MediaType.AUDIO else "video",
                file_size_mb=file_size_mb,
                platform=platform,
                thumbnail_url="",
            )
            self._db.insert(record)
        except Exception:  # noqa: BLE001
            pass
