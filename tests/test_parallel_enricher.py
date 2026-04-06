"""
tests/test_parallel_enricher.py  –  Concurrent enrichment tests
=================================================================
"""

from __future__ import annotations

import threading
import time

import pytest

from core.parallel_enricher import EnrichResult, enrich_parallel


class TestEnrichParallel:

    def test_all_succeed(self):
        items = [1, 2, 3, 4, 5]
        results, summary = enrich_parallel(
            items=items,
            enrich_fn=lambda x: x * 10,
            max_workers=2,
        )
        assert results == [10, 20, 30, 40, 50]
        assert summary.succeeded == 5
        assert summary.failed == 0

    def test_partial_failure(self):
        def fn(x):
            if x == 3:
                raise ValueError("bad item")
            return x * 10

        errors = []
        results, summary = enrich_parallel(
            items=[1, 2, 3, 4],
            enrich_fn=fn,
            on_error=lambda item, idx, exc: errors.append((item, idx)),
            max_workers=2,
        )
        assert summary.succeeded == 3
        assert summary.failed == 1
        assert results[2] is None  # item 3 failed
        assert results[0] == 10
        assert len(errors) == 1
        assert errors[0] == (3, 2)

    def test_on_item_called(self):
        received = []
        enrich_parallel(
            items=["a", "b", "c"],
            enrich_fn=lambda x: x.upper(),
            on_item=lambda enriched, idx: received.append((enriched, idx)),
            max_workers=2,
        )
        assert len(received) == 3
        assert set(e for e, _ in received) == {"A", "B", "C"}

    def test_on_progress_called(self):
        progress = []
        enrich_parallel(
            items=[1, 2, 3],
            enrich_fn=lambda x: x,
            on_progress=lambda done, total: progress.append((done, total)),
            max_workers=1,
        )
        assert len(progress) == 3
        assert progress[-1] == (3, 3)

    def test_cancel_stops_early(self):
        cancel = threading.Event()
        call_count = [0]

        def slow_fn(x):
            call_count[0] += 1
            if call_count[0] >= 2:
                cancel.set()
            time.sleep(0.01)
            return x

        results, summary = enrich_parallel(
            items=list(range(20)),
            enrich_fn=slow_fn,
            cancel_event=cancel,
            max_workers=1,
        )
        assert summary.cancelled is True
        # Not all 20 should have been processed
        completed = sum(1 for r in results if r is not None)
        assert completed < 20

    def test_empty_input(self):
        results, summary = enrich_parallel(
            items=[],
            enrich_fn=lambda x: x,
        )
        assert results == []
        assert summary.total == 0
        assert summary.succeeded == 0

    def test_preserves_order(self):
        """Even though enrichment is concurrent, results list has correct indices."""
        import random

        def slow_fn(x):
            time.sleep(random.uniform(0.001, 0.01))
            return x * 2

        items = list(range(10))
        results, _ = enrich_parallel(items, slow_fn, max_workers=4)
        assert results == [x * 2 for x in items]
