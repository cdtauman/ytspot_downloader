"""
ui/workers/download_worker.py  –  Qt adapter for DownloadOrchestrator
======================================================================
This is now a thin QThread shell.  All download logic, concurrency,
progress aggregation, and history persistence live in
core.download_orchestrator.DownloadOrchestrator (pure Python, zero Qt).

DownloadWorker's only job is:
  1. Implement OrchestratorCallbacks by forwarding each call to a Qt Signal.
  2. Call orchestrator.run_batch() inside QThread.run().
  3. Expose cancel() / cancel_track() / shutdown() for the UI.

Signal summary  (unchanged from v3)
------------------------------------
track_progress(str, float)    Per-track progress fraction.
track_status(str, str)        Per-track status string.
track_finished(str, str)      (key, output_path) on success.
overall_progress(float)       Batch-level 0.0–1.0.
metrics(str, str)             (speed_str, eta_str).
status_msg(str)               Human-readable status line.
job_error(str, object)        (key, ErrorInfo) on failure.
all_finished()                Entire batch complete.
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QThread, Signal

from core.download_orchestrator import (
    BatchResult,
    DownloadOrchestrator,
    OrchestratorCallbacks,
)
from core.history_db import HistoryDB
from downloader import DownloadEngine, DownloadRequest
from error_handler import ErrorInfo

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Signal-based callback adapter
# ──────────────────────────────────────────────────────────────────────────────

class _SignalAdapter:
    """
    Bridges OrchestratorCallbacks → Qt Signals.

    Each method simply emits the corresponding signal.  Qt's cross-thread
    signal mechanism automatically queues them to the main thread.
    """

    def __init__(self, worker: "DownloadWorker") -> None:
        self._w = worker

    def on_track_progress(self, key: str, fraction: float) -> None:
        self._w.track_progress.emit(key, fraction)

    def on_track_status(self, key: str, status: str) -> None:
        self._w.track_status.emit(key, status)

    def on_track_finished(self, key: str, output_path: str) -> None:
        self._w.track_finished.emit(key, output_path)

    def on_track_error(self, key: str, error: ErrorInfo) -> None:
        self._w.job_error.emit(key, error)

    def on_overall_progress(self, fraction: float) -> None:
        self._w.overall_progress.emit(fraction)

    def on_metrics(self, speed: str, eta: str) -> None:
        self._w.metrics.emit(speed, eta)

    def on_status_message(self, msg: str) -> None:
        self._w.status_msg.emit(msg)

    def on_batch_finished(self) -> None:
        self._w.all_finished.emit()


# ──────────────────────────────────────────────────────────────────────────────
# DownloadWorker (QThread shell)
# ──────────────────────────────────────────────────────────────────────────────

class DownloadWorker(QThread):
    """
    Thin Qt wrapper around DownloadOrchestrator.

    Parameters
    ----------
    jobs        : List of (key, DownloadRequest) tuples.
    engine      : Shared DownloadEngine.
    db          : Optional HistoryDB.
    max_workers : Concurrent download limit (1–5).
    parent      : Optional Qt parent.
    """

    # ── Signals (public API unchanged) ────────────────────────────────────────

    track_progress   = Signal(str, float)
    track_status     = Signal(str, str)
    track_finished   = Signal(str, str)
    overall_progress = Signal(float)
    metrics          = Signal(str, str)
    status_msg       = Signal(str)
    job_error        = Signal(str, object)
    all_finished     = Signal()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def __init__(
        self,
        jobs:        list[tuple[str, DownloadRequest]],
        engine:      DownloadEngine,
        db:          Optional[HistoryDB] = None,
        max_workers: int = 3,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._jobs   = jobs
        self._orch   = DownloadOrchestrator(
            engine=engine,
            callbacks=_SignalAdapter(self),
            db=db,
            max_workers=max_workers,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def cancel(self) -> None:
        """Cancel all in-flight downloads."""
        self._orch.cancel()

    def cancel_track(self, card_key: str) -> None:
        """Cancel a single track by key."""
        self._orch.cancel_track(card_key)

    def shutdown(self, timeout_ms: int = 3000) -> None:
        """
        Graceful shutdown for application quit.
        Cancels everything, then waits for the QThread to finish.
        """
        logger.info("[DownloadWorker] shutdown(timeout=%dms)", timeout_ms)
        self.cancel()
        if self.isRunning():
            finished = self.wait(timeout_ms)
            if not finished:
                logger.warning(
                    "[DownloadWorker] Thread did not finish within %dms", timeout_ms,
                )

    # ── QThread.run ───────────────────────────────────────────────────────────

    def run(self) -> None:
        """Blocking call on the QThread — delegates entirely to orchestrator."""
        self._orch.run_batch(self._jobs)
