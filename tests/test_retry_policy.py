"""
tests/test_retry_policy.py  –  Retry logic unit tests
======================================================
"""

from __future__ import annotations

import threading

import pytest

from core.retry_policy import (
    RetryPolicy,
    is_retriable,
    retry_download,
)


class TestIsRetriable:

    def test_rate_limit(self):
        assert is_retriable("HTTP Error 429: Too Many Requests") is True

    def test_timeout(self):
        assert is_retriable("Read timed out") is True

    def test_503(self):
        assert is_retriable("503 Service Unavailable") is True

    def test_connection_reset(self):
        assert is_retriable("Connection reset by peer") is True

    def test_private_video_not_retriable(self):
        assert is_retriable("This video is private video") is False

    def test_geo_block_not_retriable(self):
        assert is_retriable("not available in your country") is False

    def test_sign_in_not_retriable(self):
        assert is_retriable("Sign in to confirm your age") is False

    def test_generic_error_not_retriable(self):
        assert is_retriable("Something random happened") is False

    def test_permanent_takes_priority(self):
        # Even if message contains "timeout", "private video" wins
        assert is_retriable("private video timeout") is False


class TestRetryPolicy:

    def test_delay_exponential(self):
        p = RetryPolicy(base_delay_s=1.0, backoff_factor=2.0, max_delay_s=30.0)
        assert p.delay_for_attempt(0) == 1.0
        assert p.delay_for_attempt(1) == 2.0
        assert p.delay_for_attempt(2) == 4.0
        assert p.delay_for_attempt(3) == 8.0

    def test_delay_capped(self):
        p = RetryPolicy(base_delay_s=10.0, backoff_factor=3.0, max_delay_s=30.0)
        assert p.delay_for_attempt(2) == 30.0  # 10*9=90 → capped to 30


class TestRetryDownload:

    def test_success_no_retry(self):
        calls = [0]
        def fn():
            calls[0] += 1
        result = retry_download(fn, RetryPolicy(max_retries=3))
        assert result is None
        assert calls[0] == 1

    def test_permanent_error_no_retry(self):
        def fn():
            raise Exception("This video is private video")
        result = retry_download(fn, RetryPolicy(max_retries=3), job_key="test")
        assert result is not None
        assert "private" in result

    def test_retriable_error_retries(self):
        calls = [0]
        def fn():
            calls[0] += 1
            if calls[0] < 3:
                raise Exception("HTTP Error 429: Too Many Requests")
        policy = RetryPolicy(max_retries=3, base_delay_s=0.01)
        result = retry_download(fn, policy, job_key="test")
        assert result is None  # succeeded on 3rd attempt
        assert calls[0] == 3

    def test_retriable_exhausted(self):
        def fn():
            raise Exception("503 Service Unavailable")
        policy = RetryPolicy(max_retries=2, base_delay_s=0.01)
        result = retry_download(fn, policy, job_key="test")
        assert result is not None
        assert "503" in result

    def test_cancel_during_backoff(self):
        ev = threading.Event()
        ev.set()  # pre-cancel
        def fn():
            raise Exception("429 rate limited")
        policy = RetryPolicy(max_retries=5, base_delay_s=10.0)
        result = retry_download(fn, policy, cancel_event=ev, job_key="test")
        assert result == "Cancelled"
