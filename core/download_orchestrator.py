"""
core/download_orchestrator.py  –  Framework-agnostic batch download manager
============================================================================
Owns the job queue, thread pool, per-job cancellation, progress aggregation,
and history persistence.  Communicates exclusively via a callback protocol —
zero Qt / GUI imports.

This is the single source of truth for "run N downloads in parallel".
The UI layer (DownloadWorker QThread, or a future CLI) only needs to:
  1. Create an Orchestrator with an OrchestratorCallbacks implementation.
  2. Call run_batch() — blocking, meant to be called from a background thread.
  3. Optionally call cancel() / cancel_track() from any thread.

Thread safety
-------------
* The ThreadPoolExecutor handles scheduling.
* _progress_lock guards the shared progress dict.
* cancel events are threading.Event — safe to set from any thread.
* All callback invocations are wrapped in try/except so a crashing
  callback never kills a pool thread.

Zero GUI imports.
"""

from __future__ import annotations

import time
import random
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Optional, Protocol, Tuple

from core.history_db import DownloadRecord, HistoryDB
from core.downloader import (
    DownloadEngine,
    DownloadProgress,
    DownloadRequest,
    DownloadStatus,
    MediaType,
)
from core.playlist_parser import SourcePlatform
from core.retry_policy import DEFAULT_POLICY, retry_download
from error_handler import classify_error, ErrorInfo

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Callback protocol (the "port" that the UI adapter implements)
# ──────────────────────────────────────────────────────────────────────────────

class OrchestratorCallbacks(Protocol):
    """
    Interface that any consumer (Qt worker, CLI, tests) must implement.
    All methods are called from background threads — the implementer is
    responsible for marshalling to the correct thread (e.g. via Qt signals).
    """

    def on_track_progress(self, key: str, fraction: float) -> None: ...
    def on_track_speed(self, key: str, speed_bps: float, eta_seconds: float) -> None: ...
    def on_track_status(self, key: str, status: str) -> None: ...
    def on_track_finished(self, key: str, output_path: str) -> None: ...
    def on_track_error(self, key: str, error: ErrorInfo) -> None: ...
    def on_overall_progress(self, fraction: float) -> None: ...
    def on_metrics(self, speed: str, eta: str) -> None: ...
    def on_status_message(self, msg: str) -> None: ...
    def on_job_count_changed(self, completed: int, total: int) -> None: ...
    def on_batch_finished(self) -> None: ...
    def on_track_thumbnail(self, key: str, thumbnail_url: str) -> None: ...


# ──────────────────────────────────────────────────────────────────────────────
# Batch result
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class BatchResult:
    """Summary returned by run_batch()."""
    total:      int
    completed:  int
    failed:     int
    cancelled:  bool


# ──────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ──────────────────────────────────────────────────────────────────────────────

class DownloadOrchestrator:
    """
    Pure-Python batch download manager.

    Parameters
    ----------
    engine      : Shared DownloadEngine instance.
    db          : Optional HistoryDB for post-download persistence.
    callbacks   : Implementation of OrchestratorCallbacks.
    max_workers : Concurrent download limit (1–5).
    """

    def __init__(
        self,
        engine:      DownloadEngine,
        callbacks:   OrchestratorCallbacks,
        db:          Optional[HistoryDB] = None,
        max_workers: int = 3,
    ) -> None:
        self._engine      = engine
        self._cb          = callbacks
        self._db          = db
        self._max_workers = max(1, min(max_workers, 6))

        # Cancel infrastructure
        self._cancel_events: dict[str, threading.Event] = {}
        self._pool: Optional[ThreadPoolExecutor] = None
        self._pool_lock = threading.Lock()

        # Progress accounting
        self._progress_lock = threading.Lock()
        self._job_progress: dict[str, float] = {}
        self._completed = 0
        self._failed    = 0
        self._total     = 0

    # ── Public API (call from any thread) ─────────────────────────────────────

    def cancel(self) -> None:
        """Cancel all in-flight and pending downloads."""
        logger.info("[Orchestrator] cancel() — stopping all jobs")
        for ev in self._cancel_events.values():
            ev.set()
        self._engine.cancel_all()
        with self._pool_lock:
            if self._pool is not None:
                try:
                    self._pool.shutdown(wait=False, cancel_futures=True)
                except TypeError:
                    self._pool.shutdown(wait=False)

    def cancel_track(self, key: str) -> None:
        """Cancel a single track by its key."""
        ev = self._cancel_events.get(key)
        if ev:
            ev.set()
            logger.debug("[Orchestrator] Cancelled track %s", key)

    # ── Main entry point (blocking — call from background thread) ─────────────

    def run_batch(
        self, 
        jobs: list[tuple[str, DownloadRequest]],
        delay_range: Optional[Tuple[float, float]] = None
    ) -> BatchResult:
        """
        Execute a batch of downloads with bounded parallelism and optional staggered start.
        """
        if not jobs:
            logger.debug("[Orchestrator] Empty batch — skipping")
            self._safe_cb("on_overall_progress", 1.0)
            self._safe_cb("on_batch_finished")
            return BatchResult(total=0, completed=0, failed=0, cancelled=False)

        # Check for pre-cancellation
        if self._engine._cancel_event.is_set():
            logger.info("[Orchestrator] run_batch() — started in cancelled state")
            # Mark all as cancelled
            for key, _ in jobs:
                self._safe_cb("on_track_status", key, "cancelled")
            self._safe_cb("on_batch_finished")
            return BatchResult(total=len(jobs), completed=0, failed=0, cancelled=True)

        self._total     = len(jobs)
        self._completed = 0
        self._failed    = 0
        self._job_progress.clear()
        self._cancel_events.clear()
        # We DON'T clear engine._cancel_event here anymore to respect pre-cancellation.
        # The UI/Worker should clear it when starting a FRESH download session.

        n_workers = min(self._max_workers, self._total)
        futures: dict = {}

        pool = ThreadPoolExecutor(
            max_workers=n_workers,
            thread_name_prefix="dl-pool",
        )
        with self._pool_lock:
            self._pool = pool

        try:
            for i, (key, req) in enumerate(jobs):
                if self._engine._cancel_event.is_set():
                    break
                    
                # Stagger the starts to avoid "Burst" detection (Anti-Ban)
                if i > 0 and delay_range:
                    sleep_time = random.uniform(*delay_range)
                    logger.debug(f"[Orchestrator] Staggering start: sleeping {sleep_time:.2f}s")
                    sleep_start = time.time()
                    while time.time() - sleep_start < sleep_time:
                        if self._engine._cancel_event.is_set():
                            break
                        time.sleep(0.2)

                if self._engine._cancel_event.is_set():
                    break

                ev = threading.Event()
                req.cancel_event = ev
                self._cancel_events[key] = ev
                self._job_progress[key]  = 0.0

                future = pool.submit(self._download_one, key, req)
                futures[future] = key

            for future in as_completed(futures):
                key = futures[future]
                try:
                    future.result()
                except Exception as exc:  # noqa: BLE001
                    err = classify_error(exc)
                    self._failed += 1
                    self._safe_cb("on_track_status", key, "error")
                    self._safe_cb("on_track_error", key, err)
                    logger.error(
                        "[Orchestrator] Unhandled exception for %s: %s",
                        key, exc, exc_info=True,
                    )
        finally:
            pool.shutdown(wait=False)
            with self._pool_lock:
                self._pool = None

        # ── Finalisation ──────────────────────────────────────────────────────
        was_cancelled = self._engine._cancel_event.is_set()  # noqa: SLF001

        self._safe_cb("on_overall_progress", 1.0)
        self._safe_cb("on_metrics", "", "")

        if was_cancelled:
            self._safe_cb("on_status_message", "🚫  Cancelled.")
        else:
            s = "s" if self._total != 1 else ""
            self._safe_cb(
                "on_status_message",
                f"✅  Done — {self._total} track{s} downloaded.",
            )

        self._safe_cb("on_batch_finished")

        logger.info(
            "[Orchestrator] Batch finished: total=%d completed=%d failed=%d cancelled=%s",
            self._total, self._completed, self._failed, was_cancelled,
        )

        return BatchResult(
            total=self._total,
            completed=self._completed,
            failed=self._failed,
            cancelled=was_cancelled,
        )

    # ── Per-job runner (pool thread) ──────────────────────────────────────────

    def _download_one(self, key: str, req: DownloadRequest) -> None:
        cancel_ev = self._cancel_events[key]

        if cancel_ev.is_set() or self._engine._cancel_event.is_set():  # noqa: SLF001
            self._safe_cb("on_track_status", key, "cancelled")
            return

        self._safe_cb("on_track_status", key, "downloading")
        logger.debug("[Orchestrator] Starting %s", key)

        update_counter = [0]

        def on_progress(p: DownloadProgress) -> None:
            if p.thumbnail_url and not getattr(req, "_thumb_sent", False):
                # Prefer the original thumbnail (e.g. Spotify) if we had one
                thumb_to_send = req.thumbnail_url if req.thumbnail_url else p.thumbnail_url
                self._safe_cb("on_track_thumbnail", key, thumb_to_send)
                req._thumb_sent = True

            update_counter[0] += 1
            if update_counter[0] % 10 != 0:
                return
            with self._progress_lock:
                self._job_progress[key] = p.fraction
                overall = sum(self._job_progress.values()) / self._total
            self._safe_cb("on_track_progress", key, p.fraction)
            self._safe_cb("on_track_speed", key, p.speed_bps or 0.0, p.eta_seconds or 0.0)
            self._safe_cb("on_overall_progress", min(overall, 1.0))

            speed_str = ""
            eta_str   = ""
            if p.speed_bps:
                kb = p.speed_bps / 1024
                speed_str = f"{kb:.0f} KB/s" if kb < 1024 else f"{kb / 1024:.1f} MB/s"
            if p.eta_seconds:
                s = int(p.eta_seconds)
                eta_str = f"ETA {s // 60}m{s % 60:02d}s" if s >= 60 else f"ETA {s}s"
            self._safe_cb("on_metrics", speed_str, eta_str)

        def on_finished(p: DownloadProgress) -> None:
            with self._progress_lock:
                self._job_progress[key] = 1.0
                self._completed += 1
                overall = sum(self._job_progress.values()) / self._total
            self._safe_cb("on_track_status", key, "done")
            self._safe_cb("on_track_progress", key, 1.0)
            self._safe_cb("on_track_finished", key, p.output_path or "")
            self._safe_cb("on_overall_progress", min(overall, 1.0))
            self._safe_cb("on_job_count_changed", self._completed, self._total)
            if p.warning_message:
                self._safe_cb("on_status_message", f"⚠ {p.warning_message}")
            logger.info("[Orchestrator] Track done: %s → %s", key, p.output_path)
            self._persist_record(req, p)

        def on_error(p: DownloadProgress) -> None:
            with self._progress_lock:
                self._failed += 1
            err = classify_error(
                Exception(p.error_message or "Unknown download error")
            )
            self._safe_cb("on_track_status", key, "error")
            self._safe_cb("on_track_error", key, err)
            self._safe_cb("on_job_count_changed", self._completed + self._failed, self._total) # treat failed as 'done' for progress count
            logger.warning("[Orchestrator] Track error: %s — %s", key, p.error_message)

        req.on_progress = on_progress
        req.on_finished = on_finished

        # ── Retry wrapper ─────────────────────────────────────────────────────
        # engine.download() signals failure via req.on_error callback (not
        # by raising).  We intercept it to raise a catchable exception so
        # retry_download() can apply retriable-error detection and backoff.
        _err: list[str] = []

        def _capture_error(p: DownloadProgress) -> None:
            _err.append(p.error_message or "Unknown download error")

        def _attempt() -> None:
            _err.clear()
            req.on_error = _capture_error
            self._engine.download(req)
            if _err:
                raise RuntimeError(_err[0])

        final_error = retry_download(_attempt, cancel_event=cancel_ev, job_key=key)

        if final_error and final_error != "Cancelled":
            on_error(DownloadProgress(
                status=DownloadStatus.ERROR,
                url=req.url,
                error_message=final_error,
            ))

    # ── History persistence ───────────────────────────────────────────────────

    def _persist_record(self, req: DownloadRequest, prog: DownloadProgress) -> None:
        if self._db is None:
            return
        try:
            # Derive history platform from the request. HistoryDB recognises
            # "youtube" | "ytmusic" | "spotify" | "unknown" (see history_db.py).
            # SourcePlatform.value already produces the right string for each
            # known platform; GENERIC and missing platform fall through to
            # "unknown" so per-platform stats stay honest.
            if isinstance(req.platform, SourcePlatform) and req.platform in (
                SourcePlatform.YOUTUBE,
                SourcePlatform.YOUTUBE_MUSIC,
                SourcePlatform.SPOTIFY,
            ):
                platform_str = req.platform.value
            else:
                platform_str = "unknown"

            record = DownloadRecord(
                title=prog.title or req.forced_title or "",
                artist=req.forced_artist or "",
                url=req.url,
                output_path=prog.output_path or "",
                media_type="audio" if req.media_type == MediaType.AUDIO else "video",
                file_size_mb=None,
                duration_sec=req.forced_duration,
                thumbnail_url="",
                platform=platform_str,
            )
            self._db.insert(record)
        except Exception as exc:  # noqa: BLE001
            logger.error("[Orchestrator] History insert failed: %s", exc)

    # ── Safe callback dispatch ────────────────────────────────────────────────

    def _safe_cb(self, method: str, *args) -> None:
        """Call a callback method, swallowing any exception it raises."""
        fn = getattr(self._cb, method, None)
        if fn is None:
            return
        try:
            fn(*args)
        except Exception:  # noqa: BLE001
            logger.warning("[Orchestrator] Callback %s raised unexpectedly", method, exc_info=True)
