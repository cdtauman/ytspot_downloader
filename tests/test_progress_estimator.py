"""
tests/test_progress_estimator.py  –  Rolling average estimator tests
=====================================================================
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from core.progress_estimator import (
    BatchEstimator,
    ProgressEstimator,
    format_eta,
    format_speed,
)


class TestFormatSpeed:
    def test_zero(self):
        assert format_speed(0) == ""

    def test_kilobytes(self):
        assert "KB/s" in format_speed(500 * 1024)

    def test_megabytes(self):
        assert "MB/s" in format_speed(2 * 1024 * 1024)


class TestFormatEta:
    def test_none(self):
        assert format_eta(None) == ""

    def test_seconds(self):
        assert format_eta(45) == "ETA 45s"

    def test_minutes(self):
        assert format_eta(125) == "ETA 2m05s"

    def test_hours(self):
        assert format_eta(3661) == "ETA 1h01m"


class TestProgressEstimator:

    def test_initial_state(self):
        est = ProgressEstimator()
        assert est.speed_bps == 0.0
        assert est.eta_seconds is None
        assert est.speed_str == ""

    def test_speed_after_updates(self):
        est = ProgressEstimator(window_seconds=10.0)
        # Simulate: 0 bytes at t=0, 1MB at t=1
        t0 = time.monotonic()
        with patch("time.monotonic", return_value=t0):
            est.update(0, total_bytes=2_000_000)
        with patch("time.monotonic", return_value=t0 + 1.0):
            est.update(1_000_000, total_bytes=2_000_000)

        assert est.speed_bps == pytest.approx(1_000_000, rel=0.01)
        assert est.eta_seconds == pytest.approx(1.0, rel=0.1)

    def test_window_eviction(self):
        est = ProgressEstimator(window_seconds=2.0)
        t0 = time.monotonic()
        # Old sample at t=0
        with patch("time.monotonic", return_value=t0):
            est.update(0, total_bytes=10_000_000)
        # Sample at t=1
        with patch("time.monotonic", return_value=t0 + 1.0):
            est.update(1_000_000)
        # Sample at t=3 (t=0 sample should be evicted)
        with patch("time.monotonic", return_value=t0 + 3.0):
            est.update(2_000_000)

        # Speed should be based on t=1→t=3 window: 1MB in 2s = 500KB/s
        assert est.speed_bps == pytest.approx(500_000, rel=0.05)

    def test_reset(self):
        est = ProgressEstimator()
        est.update(1000, 2000)
        est.reset()
        assert est.speed_bps == 0.0
        assert est.eta_seconds is None

    def test_eta_zero_when_done(self):
        est = ProgressEstimator()
        t0 = time.monotonic()
        with patch("time.monotonic", return_value=t0):
            est.update(0, total_bytes=1000)
        with patch("time.monotonic", return_value=t0 + 1.0):
            est.update(1000, total_bytes=1000)
        assert est.eta_seconds == 0.0


class TestBatchEstimator:

    def test_aggregate_speed(self):
        b = BatchEstimator(total_tracks=3, window_seconds=10.0)
        t0 = time.monotonic()
        with patch("time.monotonic", return_value=t0):
            b.update("a", 0)
            b.update("b", 0)
        with patch("time.monotonic", return_value=t0 + 1.0):
            b.update("a", 500_000)
            b.update("b", 300_000)

        # ~500KB/s + ~300KB/s
        assert b.aggregate_speed_bps == pytest.approx(800_000, rel=0.1)

    def test_completed_excluded_from_speed(self):
        b = BatchEstimator(total_tracks=2, window_seconds=10.0)
        t0 = time.monotonic()
        with patch("time.monotonic", return_value=t0):
            b.update("a", 0)
            b.update("b", 0)
        with patch("time.monotonic", return_value=t0 + 1.0):
            b.update("a", 500_000)
            b.update("b", 300_000)

        b.mark_completed("a")
        # Only "b" contributes
        assert b.aggregate_speed_bps == pytest.approx(300_000, rel=0.1)

    def test_fraction(self):
        b = BatchEstimator(total_tracks=4)
        b.mark_completed("a")
        b.mark_completed("b")
        assert b.fraction == 0.5

    def test_reset(self):
        b = BatchEstimator(total_tracks=2)
        b.update("a", 100)
        b.mark_completed("a")
        b.reset()
        assert b.completed_count == 0
        assert b.aggregate_speed_bps == 0.0
