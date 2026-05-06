"""
tests/test_spotify_match_scorer.py  –  Offline scoring tests
==============================================================
Tests only the pure scoring functions — no yt-dlp or network.
"""

from __future__ import annotations

import pytest

from core.spotify_match_scorer import (
    MatchResult,
    _artist_score,
    _channel_score,
    _duration_score,
    _normalize,
    _title_score,
    score_candidate,
)


class TestNormalize:
    def test_strips_official_audio(self):
        assert "sample song" in _normalize("Sample Song (Official Audio)")

    def test_strips_lyrics(self):
        assert "song" in _normalize("Song [Lyrics]")

    def test_strips_feat(self):
        assert "feat" not in _normalize("Song (feat. Someone)")

    def test_collapses_whitespace(self):
        assert "  " not in _normalize("hello   world")


class TestTitleScore:
    def test_exact_match(self):
        s = _title_score("Sample Song", "Sample Song")
        assert s == 40.0

    def test_with_noise(self):
        s = _title_score("Sample Song", "Sample Song (Official Audio)")
        assert s >= 35.0  # after normalization, nearly identical

    def test_totally_different(self):
        s = _title_score("Sample Song", "Unrelated Track Title")
        assert s < 15.0


class TestDurationScore:
    def test_exact_match(self):
        assert _duration_score(369, 369) == 30.0

    def test_within_tolerance(self):
        assert _duration_score(369, 371) == 30.0  # ±3s

    def test_moderate_diff(self):
        s = _duration_score(369, 379)  # 10s off
        assert 0 < s < 30

    def test_large_diff(self):
        assert _duration_score(369, 400) == 0.0  # >15s

    def test_unknown_duration(self):
        s = _duration_score(369, None)
        assert s == 30.0 * 0.3  # partial credit

    def test_both_unknown(self):
        s = _duration_score(None, None)
        assert s == 30.0 * 0.3


class TestArtistScore:
    def test_in_both(self):
        s = _artist_score("Sample Artist", "Sample Artist - Sample Song", "Sample Artist")
        assert s == 20.0

    def test_in_title_only(self):
        s = _artist_score("Sample Artist", "Sample Artist - Sample Song", "SomeChannel")
        assert s == 16.0  # 80% (in title but not channel)

    def test_not_present(self):
        s = _artist_score("Sample Artist", "Sample Song", "SomeChannel")
        assert s < 10.0

    def test_empty_artist(self):
        assert _artist_score("", "Sample Song", "Channel") == 0.0


class TestChannelScore:
    def test_branded_channel(self):
        s = _channel_score("SampleArtistOfficial", "Sample Artist")
        assert s > 0

    def test_topic(self):
        s = _channel_score("Sample Artist - Topic", "Sample Artist")
        assert s > 0

    def test_official(self):
        s = _channel_score("Sample Artist Official", "Sample Artist")
        assert s > 0

    def test_generic_channel(self):
        s = _channel_score("RandomUploader", "Sample Artist")
        assert s == 0.0


class TestScoreCandidate:
    def test_perfect_match(self):
        total, bd = score_candidate(
            "Sample Song", "Sample Artist", 369,
            "Sample Artist - Sample Song (Official Audio)", "SampleArtistOfficial", 369,
        )
        assert total >= 80.0
        assert bd["title"] > 30
        assert bd["duration"] == 30.0

    def test_wrong_track(self):
        total, bd = score_candidate(
            "Sample Song", "Sample Artist", 369,
            "Completely Different Title", "OtherArtistChannel", 354,
        )
        assert total < 30.0

    def test_right_track_wrong_duration(self):
        total, _ = score_candidate(
            "Sample Song", "Sample Artist", 369,
            "Sample Artist - Sample Song (Extended Mix)", "SampleArtistOfficial", 480,
        )
        # Good title/artist but duration kills it
        assert total < 70.0
