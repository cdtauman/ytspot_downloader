"""
ui/workers/download_worker.py  –  Sequential download queue worker
==================================================================
Iterates a list of (card_key, DownloadRequest) jobs, runs each through the
shared DownloadEngine, and emits granular Qt signals so the UI can update
individual track cards, the overall progress bar, and the status bar in
real-time without any polling.

Also persists a DownloadRecord to HistoryDB after each successful download.

Signal summary
--------------
track_progress(int, float)   Per-track progress fraction 0.0 → 1.0.
track_status(int, str)       Per-track status: "downloading"|"done"|"error"|"cancelled".
track_finished(int, str)     Emitted on success with (card_key, output_path).
overall_progress(float)      Aggregate fraction across all jobs in this batch.
metrics(str, str)            (speed_str, eta_str) for the status bar.
status_msg(str)              Human-readable status line for the status bar.
job_error(int, ErrorInfo)    Per-track error with structured info.
all_finished()               Emitted once when the entire batch is done.

Threading model
---------------
One DownloadWorker is created per "Download Selected" click.  The same
DownloadEngine instance is shared across workers (one engine per app).
Cancellation is via engine.cancel() which sets a threading.Event that both
the engine's inner loop and this worker's outer loop check.
"""

from __future__ import annotations

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
    Sequentially downloads a list of tracks and emits Qt signals for each
    progress event, status change, and completion.

    Parameters
    ----------
    jobs   : List of (card_key, DownloadRequest) tuples.
             card_key is a unique string identifier for each TrackCard – used to
             route signals back to the correct card widget without holding a reference.
    engine : Shared DownloadEngine instance owned by AppWindow.
    db     : Optional HistoryDB instance.  When provided, a DownloadRecord
             is inserted after each successful download.
    parent : Optional Qt parent object.
    """

    # ── Signals ───────────────────────────────────────────────────────────────

    track_progress   = Signal(str, float)   # (card_key, fraction 0.0–1.0)
    track_status     = Signal(str, str)      # (card_key, status_str)
    track_finished   = Signal(str, str)      # (card_key, absolute output_path)
    overall_progress = Signal(float)         # batch-level fraction 0.0–1.0
    metrics          = Signal(str, str)      # (speed_str, eta_str)
    status_msg       = Signal(str)           # status bar text
    job_error        = Signal(str, object)   # (card_key, ErrorInfo)
    all_finished     = Signal()              # entire batch complete

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def __init__(
        self,
        jobs:   list[tuple[str, DownloadRequest]],
        engine: DownloadEngine,
        db:     Optional[HistoryDB] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._jobs   = jobs
        self._engine = engine
        self._db     = db
        self._total  = len(jobs)

    # ── QThread.run ───────────────────────────────────────────────────────────

    def run(self) -> None:
        """Entry point executed on the worker thread."""

        for job_num, (card_key, req) in enumerate(self._jobs, start=1):

            # Respect a cancel that was set before this job started
            if self._engine._cancel_event.is_set():  # noqa: SLF001
                self.track_status.emit(card_key, "cancelled")
                continue

            # ── Status update ─────────────────────────────────────────────────
            short = (
                req.url.split("v=")[-1] if "v=" in req.url
                else req.url[-20:]
            )
            self.status_msg.emit(
                f"⬇  Downloading  {job_num} / {self._total}  ·  {short}"
            )
            self.track_status.emit(card_key, "downloading")

            # ── Closure factories (capture loop vars) ─────────────────────────

            def make_on_progress(ck: str = card_key, jn: int = job_num):
                update_counter = [0]  # Throttle to every Nth update
                
                def _cb(p: DownloadProgress) -> None:
                    # Throttle emissions: only emit every 10th callback to reduce
                    # signal spam that can saturate the Qt main thread
                    update_counter[0] += 1
                    if update_counter[0] % 10 != 0:
                        return

                    self.track_progress.emit(ck, p.fraction)

                    overall = (jn - 1 + p.fraction) / self._total
                    self.overall_progress.emit(min(overall, 1.0))

                    speed_str = ""
                    eta_str   = ""
                    if p.speed_bps:
                        kb = p.speed_bps / 1024
                        speed_str = (
                            f"{kb:.0f} KB/s"
                            if kb < 1024
                            else f"{kb / 1024:.1f} MB/s"
                        )
                    if p.eta_seconds:
                        s = int(p.eta_seconds)
                        eta_str = (
                            f"ETA {s // 60}m{s % 60:02d}s"
                            if s >= 60
                            else f"ETA {s}s"
                        )
                    self.metrics.emit(speed_str, eta_str)

                return _cb

            def make_on_finished(ck: str = card_key, r: DownloadRequest = req):
                def _cb(p: DownloadProgress) -> None:
                    self.track_status.emit(ck, "done")
                    self.track_progress.emit(ck, 1.0)
                    self.track_finished.emit(ck, p.output_path or "")
                    # Persist to history (best-effort; never raises)
                    if self._db is not None:
                        self._persist_record(r, p)

                return _cb

            def make_on_error(ck: str = card_key):
                def _cb(p: DownloadProgress) -> None:
                    err: ErrorInfo = classify_error(
                        Exception(p.error_message or "Unknown download error")
                    )
                    self.track_status.emit(ck, "error")
                    self.job_error.emit(ck, err)

                return _cb

            # Inject callbacks into the request (safe – request is not shared)
            req.on_progress = make_on_progress()
            req.on_finished = make_on_finished()
            req.on_error    = make_on_error()

            # Blocking download – returns when the track is done (or errors)
            self._engine.download(req)

        # ── Batch complete ────────────────────────────────────────────────────
        cancelled = self._engine._cancel_event.is_set()  # noqa: SLF001
        self.status_msg.emit(
            "🚫  Cancelled." if cancelled
            else (
                f"✅  Done — {self._total} track"
                f"{'s' if self._total != 1 else ''} downloaded."
            )
        )
        self.overall_progress.emit(1.0)
        self.metrics.emit("", "")
        self.all_finished.emit()

    # ── History persistence ────────────────────────────────────────────────────

    def _persist_record(
        self,
        req:  DownloadRequest,
        prog: DownloadProgress,
    ) -> None:
        """
        Build a DownloadRecord from the completed request + progress snapshot
        and insert it into HistoryDB.  Catches all exceptions internally so a
        DB write failure can never crash the download thread.
        """
        try:
            output_path  = prog.output_path or ""
            file_size_mb: Optional[float] = None

            if output_path:
                p = Path(output_path)
                if p.exists():
                    file_size_mb = round(p.stat().st_size / (1024 * 1024), 2)

            # Derive platform label from URL
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
                media_type=(
                    "audio" if req.media_type == MediaType.AUDIO else "video"
                ),
                file_size_mb=file_size_mb,
                platform=platform,
                thumbnail_url="",   # not available at this stage; set by UI if needed
            )
            self._db.insert(record)

        except Exception:  # noqa: BLE001
            pass
