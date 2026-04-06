"""
tests/test_core.py  –  Offline unit tests for YTSpot Downloader core layer
===========================================================================
Run:
    pytest tests/test_core.py -v

Coverage targets: AppConfig, HistoryDB, classify_url, classify_error,
BatchImporter, duplicate_checker, playlist_sync.

All tests are offline (no network) and headless (no Qt/GUI).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# 1. AppConfig
# ──────────────────────────────────────────────────────────────────────────────

class TestAppConfig:
    """Round-trip persistence, default merging, edge cases."""

    def _make_config(self, tmp_path: Path) -> "AppConfig":
        """Create an AppConfig that writes to a temp directory."""
        from config import AppConfig
        cfg = AppConfig.__new__(AppConfig)
        cfg._path = tmp_path / "config.json"
        from config import _DEFAULTS
        cfg._data = dict(_DEFAULTS)
        return cfg

    def test_defaults_applied(self, tmp_path):
        cfg = self._make_config(tmp_path)
        assert cfg.media_format == "mp3"
        assert cfg.embed_thumbnail is True
        assert cfg.output_dir  # non-empty default

    def test_save_and_reload(self, tmp_path):
        cfg = self._make_config(tmp_path)
        cfg.media_format = "mp4"
        cfg.audio_quality = "Low (128k)"
        cfg.save()

        # Reload from same path
        cfg2 = self._make_config(tmp_path)
        cfg2._load()
        assert cfg2.media_format == "mp4"
        assert cfg2.audio_quality == "Low (128k)"

    def test_unknown_keys_preserved(self, tmp_path):
        """Keys not in _DEFAULTS should not crash _load."""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "media_format": "mp4",
            "future_key": "hello",
        }))
        cfg = self._make_config(tmp_path)
        cfg._load()
        assert cfg.media_format == "mp4"
        # future_key is silently ignored (not in _DEFAULTS)

    def test_corrupt_json_falls_back_to_defaults(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text("{{{invalid json")
        cfg = self._make_config(tmp_path)
        cfg._load()
        assert cfg.media_format == "mp3"  # default

    def test_atomic_write_no_partial(self, tmp_path):
        """If save() completes, config.json exists and .tmp does not."""
        cfg = self._make_config(tmp_path)
        cfg.save()
        assert (tmp_path / "config.json").exists()
        assert not (tmp_path / "config.tmp").exists()

    def test_context_manager_saves(self, tmp_path):
        cfg = self._make_config(tmp_path)
        with cfg:
            cfg.media_format = "mp4"
        reloaded = json.loads((tmp_path / "config.json").read_text())
        assert reloaded["media_format"] == "mp4"


# ──────────────────────────────────────────────────────────────────────────────
# 2. HistoryDB
# ──────────────────────────────────────────────────────────────────────────────

class TestHistoryDB:
    """CRUD, FTS, CSV export — all on :memory: DB."""

    @pytest.fixture
    def db(self):
        from core.history_db import HistoryDB
        return HistoryDB(":memory:")

    @pytest.fixture
    def sample_record(self):
        from core.history_db import DownloadRecord
        return DownloadRecord(
            title="Never Gonna Give You Up",
            artist="Rick Astley",
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            output_path="/tmp/rick.mp3",
            media_type="audio",
            platform="youtube",
        )

    def test_insert_and_fetch(self, db, sample_record):
        rec_id = db.insert(sample_record)
        assert rec_id > 0
        records = db.fetch_all(limit=10)
        assert len(records) == 1
        assert records[0].title == "Never Gonna Give You Up"
        assert records[0].artist == "Rick Astley"

    def test_count(self, db, sample_record):
        assert db.count() == 0
        db.insert(sample_record)
        assert db.count() == 1

    def test_delete(self, db, sample_record):
        rec_id = db.insert(sample_record)
        db.delete(rec_id)
        assert db.count() == 0

    def test_delete_nonexistent_silent(self, db):
        db.delete(99999)  # should not raise

    def test_clear_all(self, db, sample_record):
        for _ in range(5):
            db.insert(sample_record)
        assert db.count() == 5
        db.clear_all()
        assert db.count() == 0

    def test_fts_search(self, db, sample_record):
        db.insert(sample_record)
        results = db.search("rick astley")
        assert len(results) == 1
        assert results[0].title == "Never Gonna Give You Up"

    def test_fts_search_no_match(self, db, sample_record):
        db.insert(sample_record)
        results = db.search("beethoven")
        assert len(results) == 0

    def test_export_csv(self, db, sample_record, tmp_path):
        db.insert(sample_record)
        csv_path = str(tmp_path / "export.csv")
        count = db.export_csv(csv_path)
        assert count == 1
        content = Path(csv_path).read_text(encoding="utf-8-sig")
        assert "Rick Astley" in content
        assert "Never Gonna" in content

    def test_downloaded_at_auto_filled(self, db, sample_record):
        assert sample_record.downloaded_at == ""
        db.insert(sample_record)
        records = db.fetch_all()
        assert records[0].downloaded_at  # non-empty after insert


# ──────────────────────────────────────────────────────────────────────────────
# 3. URL Classifier (playlist_parser.classify_url)
# ──────────────────────────────────────────────────────────────────────────────

class TestClassifyUrl:
    """Pure regex, no network."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from playlist_parser import classify_url, SourcePlatform, UrlKind
        self.classify = classify_url
        self.SP = SourcePlatform
        self.UK = UrlKind

    @pytest.mark.parametrize("url, exp_plat, exp_kind", [
        # YouTube
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ",           "YOUTUBE",       "SINGLE_VIDEO"),
        ("https://youtu.be/dQw4w9WgXcQ",                          "YOUTUBE",       "SINGLE_VIDEO"),
        ("https://www.youtube.com/playlist?list=PLxxxxx",          "YOUTUBE",       "PLAYLIST"),
        ("https://www.youtube.com/watch?v=abc&list=PLxxx",         "YOUTUBE",       "PLAYLIST"),
        # YouTube Music
        ("https://music.youtube.com/watch?v=xyz",                  "YOUTUBE_MUSIC", "SINGLE_VIDEO"),
        ("https://music.youtube.com/playlist?list=RDCLAK5uy_k",   "YOUTUBE_MUSIC", "PLAYLIST"),
        # Spotify
        ("https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC", "SPOTIFY",       "SINGLE_VIDEO"),
        ("https://open.spotify.com/album/1DFixLWuPkv3KT3TnV35m3", "SPOTIFY",       "ALBUM"),
        ("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M", "SPOTIFY",     "PLAYLIST"),
        ("https://open.spotify.com/artist/3TVXtAsR1Inumwj472S9r4", "SPOTIFY",       "ARTIST"),
        # Generic
        ("https://example.com/some-video",                         "GENERIC",       "UNKNOWN"),
        # Garbage
        ("not-a-url",                                              "UNKNOWN",       "UNKNOWN"),
    ])
    def test_classify(self, url, exp_plat, exp_kind):
        plat, kind = self.classify(url)
        assert plat.name == exp_plat
        assert kind.name == exp_kind


# ──────────────────────────────────────────────────────────────────────────────
# 4. Error Handler (classify_error)
# ──────────────────────────────────────────────────────────────────────────────

class TestErrorHandler:

    @pytest.fixture(autouse=True)
    def _import(self):
        from error_handler import classify_error, ErrorInfo, ErrorSeverity
        self.classify = classify_error
        self.Sev = ErrorSeverity

    def test_permission_error(self):
        err = self.classify(PermissionError("access denied"))
        assert err.severity == self.Sev.CRITICAL
        assert "permission" in err.headline.lower()

    def test_os_error(self):
        err = self.classify(OSError("No space left on device"))
        assert err.severity == self.Sev.CRITICAL

    def test_generic_exception_fallback(self):
        err = self.classify(RuntimeError("something weird"))
        assert err.headline == "Download failed"
        assert "something weird" in err.detail

    def test_sign_in_pattern(self):
        err = self.classify(Exception("ERROR: Sign in to confirm your age"))
        assert "sign-in" in err.headline.lower() or "sign" in err.headline.lower()

    def test_private_video_pattern(self):
        err = self.classify(Exception("This video is private video"))
        assert "unavailable" in err.headline.lower()

    def test_rate_limit_pattern(self):
        err = self.classify(Exception("HTTP Error 429: Too Many Requests"))
        assert "rate" in err.headline.lower()

    def test_geo_block_pattern(self):
        err = self.classify(Exception("not available in your country"))
        assert "geo" in err.headline.lower()

    def test_error_info_status_line(self):
        from error_handler import ErrorInfo, ErrorSeverity
        e = ErrorInfo(severity=ErrorSeverity.WARNING, headline="Oops", detail="d")
        assert "⚠" in e.status_line()

    def test_error_info_is_fatal(self):
        from error_handler import ErrorInfo, ErrorSeverity
        assert ErrorInfo(severity=ErrorSeverity.CRITICAL, headline="x", detail="y").is_fatal()
        assert not ErrorInfo(severity=ErrorSeverity.WARNING, headline="x", detail="y").is_fatal()


# ──────────────────────────────────────────────────────────────────────────────
# 5. BatchImporter
# ──────────────────────────────────────────────────────────────────────────────

class TestBatchImporter:

    @pytest.fixture(autouse=True)
    def _import(self):
        from core.batch_importer import BatchImporter
        self.BI = BatchImporter

    def test_from_raw_text_extracts_urls(self):
        text = """
        Check out https://www.youtube.com/watch?v=dQw4w9WgXcQ
        and also https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC
        some garbage text here
        """
        result = self.BI.from_raw_text(text)
        assert result.found_count == 2

    def test_from_raw_text_empty(self):
        result = self.BI.from_raw_text("")
        assert result.found_count == 0

    def test_from_raw_text_deduplicates(self):
        text = (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ\n"
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ\n"
        )
        result = self.BI.from_raw_text(text)
        assert result.found_count == 1

    def test_from_clipboard_text(self):
        urls = self.BI.from_clipboard_text(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ random stuff"
        )
        assert urls == ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]

    def test_from_clipboard_text_empty(self):
        assert self.BI.from_clipboard_text("") == []

    def test_from_text_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            self.BI.from_text_file(str(tmp_path / "nope.txt"))

    def test_from_text_file_with_comments(self, tmp_path):
        f = tmp_path / "batch.txt"
        f.write_text(
            "# My batch\n"
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ\n"
            "# skip this\n"
            "https://youtu.be/abc123def45\n"
        )
        result = self.BI.from_text_file(str(f))
        # At least the first URL should be found
        assert result.found_count >= 1


# ──────────────────────────────────────────────────────────────────────────────
# 6. Duplicate Checker
# ──────────────────────────────────────────────────────────────────────────────

class TestDuplicateChecker:

    def test_expected_stem_basic(self):
        from core.duplicate_checker import expected_stem
        assert expected_stem("My Song", "Artist") == "Artist - My Song"

    def test_expected_stem_with_index(self):
        from core.duplicate_checker import expected_stem
        assert expected_stem("My Song", "Artist", index=3) == "03 Artist - My Song"

    def test_expected_stem_no_index(self):
        from core.duplicate_checker import expected_stem
        assert expected_stem("My Song", "Artist", index=3, include_index=False) == "Artist - My Song"

    def test_find_duplicate_no_dir(self, tmp_path):
        from core.duplicate_checker import find_duplicate
        result = find_duplicate(
            str(tmp_path / "nonexistent"),
            "Song", "Artist",
        )
        assert result is None

    def test_find_duplicate_match(self, tmp_path):
        from core.duplicate_checker import find_duplicate, expected_stem
        stem = expected_stem("My Song", "Daft Punk")
        (tmp_path / f"{stem}.mp3").write_bytes(b"\x00" * 100)
        result = find_duplicate(str(tmp_path), "My Song", "Daft Punk")
        assert result is not None
        assert result.name == f"{stem}.mp3"

    def test_find_duplicate_no_match(self, tmp_path):
        from core.duplicate_checker import find_duplicate
        (tmp_path / "unrelated.mp3").write_bytes(b"\x00")
        result = find_duplicate(str(tmp_path), "My Song", "Artist")
        assert result is None


# ──────────────────────────────────────────────────────────────────────────────
# 7. Playlist Sync (extract_video_id)
# ──────────────────────────────────────────────────────────────────────────────

class TestPlaylistSync:

    def test_extract_video_id_watch(self):
        from core.playlist_sync import extract_video_id
        assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_extract_video_id_short(self):
        from core.playlist_sync import extract_video_id
        assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_extract_video_id_none(self):
        from core.playlist_sync import extract_video_id
        assert extract_video_id("https://example.com") is None

    def test_extract_video_id_embed(self):
        from core.playlist_sync import extract_video_id
        assert extract_video_id("https://youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


# ──────────────────────────────────────────────────────────────────────────────
# 8. Connectivity probe (error_handler)
# ──────────────────────────────────────────────────────────────────────────────

class TestProbeConnectivity:

    def test_probe_returns_bool(self):
        from error_handler import probe_connectivity
        result = probe_connectivity(timeout=2.0)
        assert isinstance(result, bool)

    def test_check_ffmpeg_returns_bool(self):
        from error_handler import check_ffmpeg
        assert isinstance(check_ffmpeg(), bool)
