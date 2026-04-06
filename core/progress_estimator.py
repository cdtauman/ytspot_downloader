"""
core/progress_estimator.py  –  Rolling-average speed & ETA calculator
======================================================================
Replaces the raw instantaneous speed/ETA from yt-dlp's progress hooks
with a smoothed rolling average over a configurable time window.

Problem
-------
yt-dlp reports speed_bps that fluctuates wildly between progress ticks
(e.g. 2 MB/s → 500 KB/s → 4 MB/s in consecutive callbacks).  The
DownloadWorker throttles to every 10th update, which helps but still
produces jittery ETA display.

Solution
--------
``ProgressEstimator`` maintains a deque of (timestamp, bytes_downloaded)
samples.  On each update it computes:
  * **Speed** — total bytes in the window ÷ window duration (rolling avg)
  * **ETA** — remaining bytes ÷ rolling speed
  * **Per-track and batch-level** aggregation

The estimator is lightweight (no threads, no locks needed if called from
a single thread per track) and has zero GUI imports.

Usage
-----
    est = ProgressEstimator(window_seconds=5.0)

    # In progress hook:
    est.update(downloaded_bytes=p.downloaded_bytes, total_bytes=p.total_bytes)
    smooth_speed = est.speed_bps       # rolling average
    smooth_eta   = est.eta_seconds     # based on rolling speed
    speed_str    = est.speed_str       # "1.2 MB/s"
    eta_str      = est.eta_str         # "ETA 2m34s"
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class _Sample:
    """One progress measurement."""
    timestamp: float        # time.monotonic()
    bytes_dl:  int          # cumulative bytes downloaded


class ProgressEstimator:
    """
    Rolling-window speed and ETA estimator for a single download track.

    Parameters
    ----------
    window_seconds : How many seconds of history to keep for averaging.
                     Shorter = more responsive, longer = smoother.
    """

    def __init__(self, window_seconds: float = 5.0) -> None:
        self._window = max(1.0, window_seconds)
        self._samples: deque[_Sample] = deque()
        self._total_bytes: Optional[int] = None
        self._speed: float = 0.0          # bytes/sec (rolling avg)
        self._eta: Optional[float] = None # seconds remaining

    # ── Public API ────────────────────────────────────────────────────────────

    def update(
        self,
        downloaded_bytes: int,
        total_bytes: Optional[int] = None,
    ) -> None:
        """
        Feed a new progress sample.  Call this from every progress hook
        tick (before throttling — the estimator does its own smoothing).
        """
        now = time.monotonic()
        self._samples.append(_Sample(timestamp=now, bytes_dl=downloaded_bytes))

        if total_bytes is not None and total_bytes > 0:
            self._total_bytes = total_bytes

        # Evict samples older than the window
        cutoff = now - self._window
        while self._samples and self._samples[0].timestamp < cutoff:
            self._samples.popleft()

        # Compute rolling speed
        if len(self._samples) >= 2:
            oldest = self._samples[0]
            newest = self._samples[-1]
            dt = newest.timestamp - oldest.timestamp
            db = newest.bytes_dl - oldest.bytes_dl
            if dt > 0.01:
                self._speed = max(0.0, db / dt)
            # else keep previous speed
        # else not enough samples yet

        # Compute ETA
        if self._total_bytes and self._speed > 0:
            remaining = self._total_bytes - downloaded_bytes
            if remaining > 0:
                self._eta = remaining / self._speed
            else:
                self._eta = 0.0
        else:
            self._eta = None

    def reset(self) -> None:
        """Clear all state — call when starting a new track."""
        self._samples.clear()
        self._total_bytes = None
        self._speed = 0.0
        self._eta = None

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def speed_bps(self) -> float:
        """Rolling average speed in bytes per second."""
        return self._speed

    @property
    def eta_seconds(self) -> Optional[float]:
        """Estimated seconds remaining, or None if unknown."""
        return self._eta

    @property
    def speed_str(self) -> str:
        """Human-readable speed string."""
        return format_speed(self._speed)

    @property
    def eta_str(self) -> str:
        """Human-readable ETA string."""
        return format_eta(self._eta)


# ──────────────────────────────────────────────────────────────────────────────
# Batch-level aggregator
# ──────────────────────────────────────────────────────────────────────────────

class BatchEstimator:
    """
    Aggregates per-track estimators into a single batch-level view.

    Tracks are identified by string keys.  Call ``update()`` with the
    track key and the estimator auto-creates/reuses per-key state.
    """

    def __init__(self, total_tracks: int, window_seconds: float = 5.0) -> None:
        self._total_tracks = total_tracks
        self._window = window_seconds
        self._estimators: dict[str, ProgressEstimator] = {}
        self._completed: set[str] = set()

    def update(
        self,
        key: str,
        downloaded_bytes: int,
        total_bytes: Optional[int] = None,
    ) -> None:
        """Feed a progress sample for a specific track."""
        if key not in self._estimators:
            self._estimators[key] = ProgressEstimator(self._window)
        self._estimators[key].update(downloaded_bytes, total_bytes)

    def mark_completed(self, key: str) -> None:
        self._completed.add(key)

    @property
    def aggregate_speed_bps(self) -> float:
        """Sum of all active (non-completed) track speeds."""
        return sum(
            est.speed_bps
            for key, est in self._estimators.items()
            if key not in self._completed
        )

    @property
    def aggregate_speed_str(self) -> str:
        return format_speed(self.aggregate_speed_bps)

    @property
    def completed_count(self) -> int:
        return len(self._completed)

    @property
    def fraction(self) -> float:
        if self._total_tracks == 0:
            return 1.0
        return len(self._completed) / self._total_tracks

    def reset(self) -> None:
        self._estimators.clear()
        self._completed.clear()


# ──────────────────────────────────────────────────────────────────────────────
# Formatting helpers
# ──────────────────────────────────────────────────────────────────────────────

def format_speed(bps: float) -> str:
    """Format bytes/sec as a human-readable string."""
    if bps <= 0:
        return ""
    kb = bps / 1024
    if kb < 1024:
        return f"{kb:.0f} KB/s"
    return f"{kb / 1024:.1f} MB/s"


def format_eta(seconds: Optional[float]) -> str:
    """Format seconds remaining as a human-readable string."""
    if seconds is None or seconds < 0:
        return ""
    s = int(seconds)
    if s < 60:
        return f"ETA {s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"ETA {m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"ETA {h}h{m:02d}m"
