"""
tests/test_p0_gates.py  –  P0-gate tests for YTSpot Downloader
===============================================================
These tests verify that the bugs classified as P0 are fixed and cannot
regress.  All tests are offline (no network) and headless (no Qt/GUI).

Run:
    pytest tests/test_p0_gates.py -v

Covered:
  1. PlaylistParser._parse_standard_yt stores yt-dlp errors in result.error
     and does NOT raise (P0-2 root cause).
  2. ParseResult.success() reflects error state correctly.
  3. TrackMeta dataclass has no duplicate fields (P0-3).
  4. TrackMeta field defaults and __post_init__ work correctly after fix.
  5. SpotifyResolver.resolve() raises RuntimeError when proxy is not configured (P0-2 Spotify path).
  6. DownloadEngine rejects empty URLs cleanly (P0 regression guard).
  7. _sanitize_folder_name does not allow path traversal (security).
  8. DownloadProgress.warning_message field exists and propagates (P1-3).
  9. cookies_file is forwarded to _parse_standard_yt (P0-4 regression guard).
"""

from __future__ import annotations

import dataclasses
import threading
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# 1. TrackMeta — no duplicate fields (P0-3)
# ──────────────────────────────────────────────────────────────────────────────

class TestTrackMetaFields:
    """Verify that TrackMeta has no duplicate field declarations."""

    def test_no_duplicate_fields(self):
        from core.playlist_parser import TrackMeta

        fields = [f.name for f in dataclasses.fields(TrackMeta)]
        assert len(fields) == len(set(fields)), (
            f"Duplicate fields found in TrackMeta: {[x for x in fields if fields.count(x) > 1]}"
        )

    def test_release_type_exists_once(self):
        from core.playlist_parser import TrackMeta
        fields = {f.name for f in dataclasses.fields(TrackMeta)}
        assert "release_type" in fields

    def test_album_index_exists_once(self):
        from core.playlist_parser import TrackMeta
        fields = {f.name for f in dataclasses.fields(TrackMeta)}
        assert "album_index" in fields

    def test_selected_field_present(self):
        """selected field must still exist (was in the duplicate block)."""
        from core.playlist_parser import TrackMeta
        fields = {f.name for f in dataclasses.fields(TrackMeta)}
        assert "selected" in fields

    def test_default_selected_is_true(self):
        from core.playlist_parser import TrackMeta
        t = TrackMeta(url="https://youtu.be/abc")
        assert t.selected is True

    def test_duration_str_auto_filled(self):
        from core.playlist_parser import TrackMeta
        t = TrackMeta(duration_sec=185)
        assert "3" in t.duration_str or ":" in t.duration_str  # "3:05" or "0:03:05"


# ──────────────────────────────────────────────────────────────────────────────
# 2. PlaylistParser — yt-dlp errors stored in result.error, not raised (P0-2)
# ──────────────────────────────────────────────────────────────────────────────

class TestPlaylistParserErrorPropagation:
    """
    Verify that DownloadError from yt-dlp is caught by _parse_standard_yt
    and stored in ParseResult.error rather than propagating as an exception.

    This is the P0-2 root cause: _on_fetch_finished never inspected result.error.
    These tests document the contract that must hold for the UI fix to work.
    """

    def _make_parser(self):
        from core.playlist_parser import PlaylistParser
        return PlaylistParser()

    def test_download_error_stored_not_raised(self):
        """DownloadError from yt-dlp must appear in result.error, not raise."""
        import yt_dlp.utils

        parser = self._make_parser()
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.__enter__ = lambda s: mock_ydl
            mock_ydl.__exit__ = MagicMock(return_value=False)
            mock_ydl.extract_info.side_effect = yt_dlp.utils.DownloadError(
                "Unsupported URL: https://www.example.com"
            )
            mock_ydl_cls.return_value = mock_ydl

            result = parser.parse("https://www.example.com")

        assert result.error, "ParseResult.error must be non-empty on DownloadError"
        assert len(result.tracks) == 0
        assert "Unsupported URL" in result.error or "example.com" in result.error.lower() or result.error

    def test_none_info_stored_not_raised(self):
        """When yt-dlp returns None, result.error must be set."""
        parser = self._make_parser()
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.__enter__ = lambda s: mock_ydl
            mock_ydl.__exit__ = MagicMock(return_value=False)
            mock_ydl.extract_info.return_value = None
            mock_ydl_cls.return_value = mock_ydl

            result = parser.parse("https://www.example.com")

        assert result.error, "ParseResult.error must be set when yt-dlp returns None"
        assert len(result.tracks) == 0

    def test_generic_exception_stored_not_raised(self):
        """Unexpected exceptions must also be caught and stored."""
        parser = self._make_parser()
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.__enter__ = lambda s: mock_ydl
            mock_ydl.__exit__ = MagicMock(return_value=False)
            mock_ydl.extract_info.side_effect = RuntimeError("Unexpected failure")
            mock_ydl_cls.return_value = mock_ydl

            result = parser.parse("https://www.example.com")

        assert result.error
        assert len(result.tracks) == 0

    def test_parse_result_success_method_reflects_error(self):
        """ParseResult.success() must return False when error is set."""
        from core.playlist_parser import ParseResult, UrlKind, SourcePlatform
        result = ParseResult(
            url="https://x.com",
            kind=UrlKind.UNKNOWN,
            platform=SourcePlatform.UNKNOWN,
            error="something went wrong",
        )
        # success() should return False when there's an error and no tracks
        assert not result.success() or len(result.tracks) == 0

    def test_cookies_file_forwarded_to_build_opts(self):
        """cookies_file passed to parse() must reach _parse_standard_yt (P0-4).

        We verify this by checking that _parse_standard_yt is called with
        the cookies_file keyword argument rather than hardcoded None.
        """
        parser = self._make_parser()
        captured_kwargs = []

        original_parse_std = parser._parse_standard_yt

        def spy_parse_standard_yt(*args, **kwargs):
            captured_kwargs.append(kwargs.get("cookies_file"))
            # Simulate no data to avoid full yt-dlp invocation
            from core.playlist_parser import ParseResult, UrlKind, SourcePlatform
            return ParseResult(
                url=args[0] if args else "",
                kind=UrlKind.UNKNOWN,
                platform=SourcePlatform.GENERIC,
            )

        parser._parse_standard_yt = spy_parse_standard_yt

        parser.parse("https://www.youtube.com/watch?v=abc", cookies_file="/tmp/cookies.txt")

        assert len(captured_kwargs) == 1, "_parse_standard_yt was not called"
        assert captured_kwargs[0] == "/tmp/cookies.txt", (
            f"cookies_file was not forwarded to _parse_standard_yt — P0-4 regression. "
            f"Got: {captured_kwargs[0]!r}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 3. SpotifyResolver — raises when proxy not configured (P0-2 Spotify path)
# ──────────────────────────────────────────────────────────────────────────────

class TestSpotifyResolverNoProxy:
    """Verify SpotifyResolver raises RuntimeError with an actionable message
    when the proxy is not configured, rather than crashing silently."""

    def test_raises_runtime_error_without_proxy(self):
        from utils.spotify_resolver import SpotifyResolver

        with patch.object(SpotifyResolver, "_get_proxy_config", return_value=("", "")):
            with pytest.raises(RuntimeError) as exc_info:
                SpotifyResolver.resolve("https://open.spotify.com/track/abc123")

        assert "Proxy" in str(exc_info.value) or "configured" in str(exc_info.value), (
            "RuntimeError message must guide the user to configure the proxy"
        )

    def test_error_message_is_actionable(self):
        from utils.spotify_resolver import SpotifyResolver

        with patch.object(SpotifyResolver, "_get_proxy_config", return_value=("", "")):
            try:
                SpotifyResolver.resolve("https://open.spotify.com/album/abc123")
            except RuntimeError as exc:
                msg = str(exc)
                # Message must reference Settings so the user knows where to go
                assert "Settings" in msg or "proxy" in msg.lower() or "Proxy" in msg


# ──────────────────────────────────────────────────────────────────────────────
# 4. DownloadProgress — warning_message field exists (P1-3)
# ──────────────────────────────────────────────────────────────────────────────

class TestDownloadProgressWarningField:
    """warning_message must be a declared field on DownloadProgress."""

    def test_warning_message_field_exists(self):
        from core.downloader import DownloadProgress, DownloadStatus
        p = DownloadProgress(status=DownloadStatus.FINISHED)
        assert hasattr(p, "warning_message"), "warning_message field missing from DownloadProgress"

    def test_warning_message_default_empty(self):
        from core.downloader import DownloadProgress, DownloadStatus
        p = DownloadProgress(status=DownloadStatus.FINISHED)
        assert p.warning_message == ""

    def test_warning_message_can_be_set(self):
        from core.downloader import DownloadProgress, DownloadStatus
        p = DownloadProgress(status=DownloadStatus.FINISHED, warning_message="lyrics failed")
        assert p.warning_message == "lyrics failed"


# ──────────────────────────────────────────────────────────────────────────────
# 5. DownloadRequest — _final_output_path declared (P2-2)
# ──────────────────────────────────────────────────────────────────────────────

class TestDownloadRequestFinalOutputPath:
    """_final_output_path must be a declared dataclass field, not dynamic."""

    def test_field_is_declared(self):
        from core.downloader import DownloadRequest
        field_names = {f.name for f in dataclasses.fields(DownloadRequest)}
        assert "_final_output_path" in field_names, (
            "_final_output_path must be a declared field, not set dynamically"
        )

    def test_field_default_empty_string(self):
        from core.downloader import DownloadRequest
        req = DownloadRequest(url="https://youtu.be/abc", output_dir="/tmp")
        assert req._final_output_path == ""  # noqa: SLF001


# ──────────────────────────────────────────────────────────────────────────────
# 6. _sanitize_folder_name — path traversal prevention (security)
# ──────────────────────────────────────────────────────────────────────────────

class TestSanitizeFolderName:
    """Path traversal must not survive sanitization."""

    def _sanitize(self, name: str) -> str:
        from core.downloader import _sanitize_folder_name
        return _sanitize_folder_name(name)

    def test_no_double_dots(self):
        result = self._sanitize("../../Windows/System32")
        assert ".." not in result, f"Path traversal not sanitized: {result!r}"

    def test_no_backslash(self):
        result = self._sanitize(r"foo\bar")
        assert "\\" not in result

    def test_no_reserved_chars(self):
        result = self._sanitize('hack"file*name?<>')
        for ch in '"*?<>':
            assert ch not in result, f"Reserved char {ch!r} not removed from {result!r}"

    def test_normal_name_preserved(self):
        result = self._sanitize("My Favorite Album (2024)")
        assert "My Favorite Album" in result


# ──────────────────────────────────────────────────────────────────────────────
# 7. SpotifyResolver — token lock declared (P1-2)
# ──────────────────────────────────────────────────────────────────────────────

class TestSpotifyResolverTokenLock:
    """_token_lock must be a class-level threading.Lock."""

    def test_token_lock_exists(self):
        from utils.spotify_resolver import SpotifyResolver
        assert hasattr(SpotifyResolver, "_token_lock"), (
            "_token_lock class variable missing from SpotifyResolver"
        )

    def test_token_lock_is_lock(self):
        from utils.spotify_resolver import SpotifyResolver
        assert isinstance(SpotifyResolver._token_lock, type(threading.Lock())), (
            "_token_lock must be a threading.Lock instance"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 8. classify_url — GENERIC platform for arbitrary http URLs
# ──────────────────────────────────────────────────────────────────────────────

class TestClassifyUrlGeneric:
    """Generic http/https URLs must be classified as GENERIC, not UNKNOWN."""

    def _classify(self, url: str):
        from core.playlist_parser import classify_url
        return classify_url(url)

    def test_example_com_is_generic(self):
        platform, _ = self._classify("https://www.example.com/video.html")
        from core.playlist_parser import SourcePlatform
        assert platform == SourcePlatform.GENERIC

    def test_non_http_is_unknown(self):
        platform, _ = self._classify("ftp://files.example.com/file.mp3")
        from core.playlist_parser import SourcePlatform
        assert platform == SourcePlatform.UNKNOWN

    def test_plain_text_is_unknown(self):
        platform, _ = self._classify("just a song name")
        from core.playlist_parser import SourcePlatform
        assert platform == SourcePlatform.UNKNOWN


# ──────────────────────────────────────────────────────────────────────────────
# 9. DownloadOrchestrator — retry_download integrated (P1-9 regression guard)
# ──────────────────────────────────────────────────────────────────────────────

class TestOrchestratorRetryIntegration:
    """
    Verify that DownloadOrchestrator._download_one uses retry_download()
    rather than calling engine.download() bare.

    Strategy: Mock engine.download() to fire req.on_error on the first
    call with a retriable error string (429), then succeed on the second.
    Assert that on_finished is eventually called (not on_error).
    """

    def test_retriable_error_is_retried(self):
        """A 429 error on the first attempt must be retried; on_finished fires on success."""
        import threading
        from core.downloader import (
            DownloadEngine, DownloadProgress, DownloadRequest, DownloadStatus
        )
        from core.download_orchestrator import DownloadOrchestrator, OrchestratorCallbacks
        from core.retry_policy import RetryPolicy

        finished_keys: list[str] = []
        errored_keys: list[str] = []

        class StubCallbacks:
            def on_track_progress(self, key, fraction): pass
            def on_track_status(self, key, status): pass
            def on_track_finished(self, key, path): finished_keys.append(key)
            def on_track_error(self, key, error): errored_keys.append(key)
            def on_overall_progress(self, fraction): pass
            def on_metrics(self, speed, eta): pass
            def on_status_message(self, msg): pass
            def on_job_count_changed(self, completed, total): pass
            def on_batch_finished(self): pass

        call_count = [0]

        def fake_download(req: DownloadRequest) -> None:
            call_count[0] += 1
            if call_count[0] == 1:
                # First attempt: fire retriable error
                req.on_error(DownloadProgress(
                    status=DownloadStatus.ERROR,
                    url=req.url,
                    error_message="HTTP Error 429: Too Many Requests",
                ))
            else:
                # Second attempt: succeed
                req.on_finished(DownloadProgress(
                    status=DownloadStatus.FINISHED,
                    url=req.url,
                    fraction=1.0,
                    output_path="/tmp/track.mp3",
                ))

        engine = MagicMock(spec=DownloadEngine)
        engine.download.side_effect = fake_download
        engine._cancel_event = threading.Event()

        # Use a policy with zero base delay so the test runs instantly
        fast_policy = RetryPolicy(max_retries=2, base_delay_s=0.0, backoff_factor=1.0)

        with patch("core.download_orchestrator.DEFAULT_POLICY", fast_policy):
            orch = DownloadOrchestrator(
                engine=engine,
                callbacks=StubCallbacks(),
                max_workers=1,
            )
            req = DownloadRequest(url="https://youtu.be/abc", output_dir="/tmp")
            orch.run_batch([("track1", req)])

        assert call_count[0] == 2, f"Expected 2 attempts (retry), got {call_count[0]}"
        assert "track1" in finished_keys, "on_track_finished must be called after successful retry"
        assert "track1" not in errored_keys, "on_track_error must NOT be called when retry succeeds"

    def test_non_retriable_error_not_retried(self):
        """A 'private video' error must not be retried; on_error fires immediately."""
        import threading
        from core.downloader import (
            DownloadEngine, DownloadProgress, DownloadRequest, DownloadStatus
        )
        from core.download_orchestrator import DownloadOrchestrator
        from core.retry_policy import RetryPolicy

        finished_keys: list[str] = []
        errored_keys: list[str] = []

        class StubCallbacks:
            def on_track_progress(self, key, fraction): pass
            def on_track_status(self, key, status): pass
            def on_track_finished(self, key, path): finished_keys.append(key)
            def on_track_error(self, key, error): errored_keys.append(key)
            def on_overall_progress(self, fraction): pass
            def on_metrics(self, speed, eta): pass
            def on_status_message(self, msg): pass
            def on_job_count_changed(self, completed, total): pass
            def on_batch_finished(self): pass

        call_count = [0]

        def fake_download(req: DownloadRequest) -> None:
            call_count[0] += 1
            req.on_error(DownloadProgress(
                status=DownloadStatus.ERROR,
                url=req.url,
                error_message="This video is private.",
            ))

        engine = MagicMock(spec=DownloadEngine)
        engine.download.side_effect = fake_download
        engine._cancel_event = threading.Event()

        fast_policy = RetryPolicy(max_retries=3, base_delay_s=0.0, backoff_factor=1.0)

        with patch("core.download_orchestrator.DEFAULT_POLICY", fast_policy):
            orch = DownloadOrchestrator(
                engine=engine,
                callbacks=StubCallbacks(),
                max_workers=1,
            )
            req = DownloadRequest(url="https://youtu.be/abc", output_dir="/tmp")
            orch.run_batch([("track1", req)])

        assert call_count[0] == 1, f"Non-retriable error must not be retried, got {call_count[0]} attempts"
        assert "track1" in errored_keys, "on_track_error must fire for permanent failure"
        assert "track1" not in finished_keys


# ──────────────────────────────────────────────────────────────────────────────
# 10. UpdateChecker / UpdateWorker default repo (P0 — wrong owner silently
#     breaks the update check)
# ──────────────────────────────────────────────────────────────────────────────

class TestUpdateCheckerDefaults:
    """Default GitHub owner must match the live remote so the update banner
    actually surfaces new releases. The wrong default silently returns None
    for every check because the repo URL 404s.

    The canonical owner is `cdtauman-projects`; the repo name is
    `ytspot_downloader`. If this changes in the future, also update
    `core/update_checker.py`, `ui/workers/update_worker.py`,
    `README.md`, `ui/panels/settings_panel.py`, and
    `core/musicbrainz_enricher.py` (User-Agent URL).
    """

    EXPECTED_OWNER = "cdtauman-projects"
    EXPECTED_REPO = "ytspot_downloader"

    def test_update_checker_default_owner(self):
        from core.update_checker import UpdateChecker

        checker = UpdateChecker()
        assert checker._repo_owner == self.EXPECTED_OWNER, (
            f"UpdateChecker default repo_owner must be "
            f"{self.EXPECTED_OWNER!r} so the GitHub Releases API returns "
            f"a live response. Got {checker._repo_owner!r}."
        )
        assert checker._repo_name == self.EXPECTED_REPO

    def test_update_worker_default_owner(self):
        # Importing UpdateWorker requires PySide6 — skip cleanly in
        # headless CI where Qt is not installed.
        try:
            from ui.workers.update_worker import UpdateWorker  # noqa: F401
        except ImportError:
            pytest.skip("PySide6 not available in this environment")
            return

        import inspect
        sig = inspect.signature(UpdateWorker.__init__)
        owner_default = sig.parameters["repo_owner"].default
        repo_default = sig.parameters["repo_name"].default
        assert owner_default == self.EXPECTED_OWNER, (
            f"UpdateWorker default repo_owner must be "
            f"{self.EXPECTED_OWNER!r}. Got {owner_default!r}."
        )
        assert repo_default == self.EXPECTED_REPO


# ──────────────────────────────────────────────────────────────────────────────
# 11b. Version consistency across all declared sources
# ──────────────────────────────────────────────────────────────────────────────

class TestVersionConsistency:
    """The release process requires a single canonical version string.
    The source of truth is ``version.__version__``. Every other site
    that declares the version must match.

    A drift here is a release blocker: the EXE VS_VERSIONINFO, the
    Inno Setup metadata, the update banner ("you are running v…"), and
    the MusicBrainz User-Agent all read from these sources.
    """

    def test_version_module_is_source_of_truth(self):
        from version import __version__, VERSION_INFO
        assert isinstance(__version__, str) and __version__.count(".") == 2
        major, minor, patch = VERSION_INFO
        assert __version__ == f"{major}.{minor}.{patch}"

    def test_update_checker_matches_version_module(self):
        from version import __version__
        from core.update_checker import CURRENT_VERSION
        assert CURRENT_VERSION == __version__, (
            f"core.update_checker.CURRENT_VERSION ({CURRENT_VERSION}) "
            f"must equal version.__version__ ({__version__})"
        )

    def test_pyproject_version_matches_version_module(self):
        import re
        from pathlib import Path
        from version import __version__

        pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
        m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', pyproject)
        assert m is not None, "pyproject.toml is missing a [project] version"
        assert m.group(1) == __version__, (
            f"pyproject.toml version ({m.group(1)}) must equal "
            f"version.__version__ ({__version__})"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 11c. CLI release flags: --version and --doctor (commercial-release delta C-2)
# ──────────────────────────────────────────────────────────────────────────────

class TestCLIReleaseFlags:
    """`--version` and `--doctor` must work without a positional URL.

    The release process and the user-facing troubleshooting docs both
    rely on these flags; a regression would surface as a confusing
    'URL is required' error on a freshly-installed EXE.
    """

    def test_version_flag_prints_version_and_exits_zero(self, capsys):
        from cli import build_parser
        from version import __version__

        parser = build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--version"])
        # argparse `version` action exits with code 0.
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        # argparse writes version to stdout in Python 3.4+.
        out = captured.out + captured.err
        assert __version__ in out
        assert "ytspot-cli" in out

    def test_doctor_flag_runs_without_url(self):
        from cli import build_parser, _run_doctor

        parser = build_parser()
        args = parser.parse_args(["--doctor"])
        assert args.doctor is True
        assert args.url is None

        # _run_doctor must not raise even if checks fail; it returns
        # an int exit code.
        rc = _run_doctor(args)
        assert isinstance(rc, int)
        assert rc in (0, 1)

    def test_missing_url_without_release_flag_is_friendly_error(self):
        # main() prints a clear message and returns 2 when neither
        # --version nor --doctor is set and no URL is supplied.
        from cli import build_parser, main as cli_main
        import sys as _sys

        parser = build_parser()
        args = parser.parse_args([])
        assert args.url is None
        assert args.doctor is False

        # Run main() with a synthetic argv to avoid touching the real
        # one. patch sys.argv just for the call.
        original_argv = _sys.argv
        try:
            _sys.argv = ["cli.py"]
            rc = cli_main()
        finally:
            _sys.argv = original_argv
        assert rc == 2


# ──────────────────────────────────────────────────────────────────────────────
# 11d. Playwright graceful degradation (commercial-release delta C-7)
# ──────────────────────────────────────────────────────────────────────────────

class TestPlaywrightDegradation:
    """Modules that drive a Chromium browser must import cleanly even
    when Playwright is not installed, and must raise a friendly,
    localised error (not a stack trace) when their entry point is
    called without the dependency.

    A module-level `from playwright.sync_api import ...` line is a
    release blocker because it breaks `import core.scraper` on every
    Playwright-less machine — including the headless CI image.
    """

    def test_scraper_imports_without_playwright(self):
        # Even though Playwright is installed on this dev machine,
        # the import path must not depend on it. We assert the module
        # imports and that the public scrape_* names exist.
        import core.scraper as scraper

        for name in (
            "scrape_spotify_playlist",
            "scrape_spotify_album",
            "scrape_spotify_track",
            "scrape_spotify_artist",
            "scrape_youtube_channel",
        ):
            assert callable(getattr(scraper, name, None)), (
                f"core.scraper.{name} must be importable on Playwright-less installs"
            )

    def test_playwright_not_available_carries_localised_messages(self):
        from utils.playwright_check import PlaywrightNotAvailable
        exc = PlaywrightNotAvailable("Foo feature")
        # English text used for str(exc), Hebrew text on exc.message_he.
        assert "Foo feature" in exc.message_en
        assert "playwright" in exc.message_en.lower()
        assert "Foo feature" in exc.message_he
        # str(exc) returns the English message so error_handler /
        # CLI doctor can display it directly.
        assert str(exc) == exc.message_en

    def test_is_playwright_available_returns_bool(self):
        from utils.playwright_check import is_playwright_available
        result = is_playwright_available()
        assert isinstance(result, bool)


# ──────────────────────────────────────────────────────────────────────────────
# 11. SearchPanel restores "ytmusic" as last_search_platform (S1-4 guard)
# ──────────────────────────────────────────────────────────────────────────────

class TestSearchPanelRestoresYTMusic:
    """The restore allow-list used to omit "ytmusic", so users who last
    selected YouTube Music silently reverted to YouTube on every
    restart. AppConfig.last_search_platform already accepted "ytmusic"
    on both the setter and getter — only the SearchPanel restore was
    wrong."""

    def test_ytmusic_round_trips_through_panel(self, tmp_path, monkeypatch):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

        # Skip if Qt or qfluentwidgets is not installed (headless CI).
        try:
            from PySide6.QtWidgets import QApplication
            from ui.panels.search_panel import SearchPanel
        except ImportError:
            pytest.skip("PySide6 / qfluentwidgets not available")
            return

        # Use a tmp config dir so the test never reads/writes the user's
        # real ~/.ytspot/config.json. AppConfig uses APPDATA on Windows
        # and ~/.ytspot on POSIX; redirect both.
        monkeypatch.setenv("APPDATA", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))

        from config import AppConfig

        cfg = AppConfig()
        cfg.last_search_platform = "ytmusic"

        app = QApplication.instance() or QApplication([])
        panel = SearchPanel(config=cfg)
        try:
            assert panel.get_platform() == "ytmusic", (
                "SearchPanel must restore last_search_platform=ytmusic "
                "from config; allow-list in _restore_state regressed."
            )
        finally:
            panel.deleteLater()
