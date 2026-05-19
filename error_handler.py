"""
error_handler.py  –  Centralised error classification & user-friendly messages
===============================================================================
Responsibilities
----------------
* Translate raw yt-dlp / network / OS exceptions into structured ErrorInfo
  objects with a clear severity, a short headline, and a full detail string.
* Provide a connectivity probe so the UI can distinguish "no internet" from
  "bad URL" or "private video".
* Expose helper functions the GUI can call directly without importing
  exception types from yt-dlp or requests.

Design decisions
----------------
* Zero GUI imports – this module is UI-agnostic.
* All classification is done via string matching on the exception message;
  yt-dlp does not expose a rich exception hierarchy, so pattern matching is
  the only reliable approach.
* The `probe_connectivity` function checks a known-reliable HTTPS endpoint
  with a short timeout to distinguish network failures from service errors.
"""

from __future__ import annotations

import re
import socket
from typing import Optional

from enum import Enum, auto
from dataclasses import dataclass
from core.retry_policy import is_retriable as _is_retriable


# ──────────────────────────────────────────────────────────────────────────────
# Public data types
# ──────────────────────────────────────────────────────────────────────────────

class ErrorSeverity(Enum):
    WARNING  = auto()   # Non-fatal; operation continues
    ERROR    = auto()   # Operation failed; user should be informed
    CRITICAL = auto()   # Application-level failure (bad config, missing FFmpeg…)


@dataclass
class ErrorInfo:
    """Structured error ready for display."""
    severity:  ErrorSeverity
    headline:  str               # Short title for a dialog / status bar
    detail:    str               # Full explanation shown in dialog body
    raw:       str = ""          # Original exception message (for logging)
    retriable: bool = False

    def is_fatal(self) -> bool:
        return self.severity == ErrorSeverity.CRITICAL

    def status_line(self) -> str:
        icon = {
            ErrorSeverity.WARNING:  "⚠",
            ErrorSeverity.ERROR:    "❌",
            ErrorSeverity.CRITICAL: "🔴",
        }[self.severity]
        return f"{icon}  {self.headline}"


# ──────────────────────────────────────────────────────────────────────────────
# Connectivity probe
# ──────────────────────────────────────────────────────────────────────────────

# Probe targets: try each in order; succeed on the first that responds.
_PROBE_TARGETS = [
    ("dns.google",       443),
    ("8.8.8.8",          53),
    ("one.one.one.one",  443),
]


def probe_connectivity(timeout: float = 3.0) -> bool:
    """
    Return True if at least one probe target is reachable.
    Uses a raw TCP connection (no HTTP), so it works even when
    requests / yt-dlp are not installed.
    """
    for host, port in _PROBE_TARGETS:
        try:
            sock = socket.create_connection((host, port), timeout=timeout)
            sock.close()
            return True
        except OSError:
            continue
    return False


# ──────────────────────────────────────────────────────────────────────────────
# FFmpeg presence check
# ──────────────────────────────────────────────────────────────────────────────

def check_ffmpeg() -> bool:
    """Return True if FFmpeg is available — bundled with the EXE or on PATH.

    Bundled binaries (next to ``ytspot.exe`` for a frozen build, or
    under ``packaging/ffmpeg/`` during development) take priority over
    a system PATH copy so the EXE always uses its known-good LGPL
    build, never a random GPL build the user happens to have.
    """
    from utils.paths import get_ffmpeg_executable
    return get_ffmpeg_executable() is not None


# ──────────────────────────────────────────────────────────────────────────────
# Pattern tables for yt-dlp error messages
# (checked in order; first match wins)
# ──────────────────────────────────────────────────────────────────────────────

# Each entry: (compiled regex, headline, detail template, severity)
_YTDLP_PATTERNS: list[tuple[re.Pattern, str, str, ErrorSeverity]] = [
    # Age-gated / sign-in required
    (
        re.compile(r"sign in|age.?gated|account|login", re.I),
        "Sign-in required",
        "This video is age-restricted or requires a YouTube account.\n\n"
        "Solution: Export your browser cookies to a cookies.txt file and set the path "
        "in Settings → Cookies File.",
        ErrorSeverity.ERROR,
    ),
    # Private / deleted video
    (
        re.compile(r"private video|video unavailable|has been removed|no longer available", re.I),
        "Video unavailable",
        "This video is private, deleted, or not available in your region.",
        ErrorSeverity.WARNING,
    ),
    # Geo-blocked
    (
        re.compile(r"not available in your country|geo.?block|geo.?restrict", re.I),
        "Geo-restricted content",
        "This content is not available in your country.\n\n"
        "Consider using a VPN or a region-specific cookies file.",
        ErrorSeverity.ERROR,
    ),
    # Rate-limited / throttled
    (
        re.compile(r"429|too many requests|rate.?limit|throttl", re.I),
        "Rate limited by YouTube",
        "YouTube is temporarily blocking requests from your IP.\n\n"
        "Wait a few minutes and try again, or use a cookies file to authenticate.",
        ErrorSeverity.ERROR,
    ),
    # HTTP 403
    (
        re.compile(r"\b403\b|forbidden", re.I),
        "Access denied (403)",
        "The server refused the request.\n\n"
        "This usually means the video requires authentication. "
        "Try adding a cookies file in Settings.",
        ErrorSeverity.ERROR,
    ),
    # Copyright / DMCA takedown
    (
        re.compile(r"copyright|dmca|blocked in some countries on copyright", re.I),
        "Content blocked due to copyright",
        "This video has been restricted due to a copyright claim and cannot be downloaded.",
        ErrorSeverity.ERROR,
    ),
    # Invalid / unsupported URL
    (
        re.compile(r"unsupported url|no video formats|ie_key|extractor", re.I),
        "Unsupported URL",
        "yt-dlp could not find a supported extractor for this URL.\n\n"
        "Check that the URL is a direct video, playlist, or album link.",
        ErrorSeverity.ERROR,
    ),
    # Network-level errors surfaced inside yt-dlp
    (
        re.compile(r"connection reset|connection refused|timed? ?out|name or service not known|"
                   r"temporary failure in name resolution|network is unreachable", re.I),
        "Network error",
        "A network error occurred while communicating with the server.\n\n"
        "Check your internet connection and try again.",
        ErrorSeverity.ERROR,
    ),
    # SSL
    (
        re.compile(r"ssl|certificate", re.I),
        "SSL / Certificate error",
        "A secure connection could not be established.\n\n"
        "Your system clock may be wrong, or a firewall is intercepting HTTPS traffic.",
        ErrorSeverity.ERROR,
    ),
    # FFmpeg missing (detected inside yt-dlp)
    (
        re.compile(r"ffmpeg|ffprobe|postprocessor", re.I),
        "FFmpeg not found",
        "yt-dlp requires FFmpeg to merge or convert audio/video.\n\n"
        "Install FFmpeg and make sure it is on your system PATH.\n\n"
        "  Windows : winget install Gyan.FFmpeg\n"
        "  macOS   : brew install ffmpeg\n"
        "  Linux   : sudo apt install ffmpeg",
        ErrorSeverity.CRITICAL,
    ),
    # Disk full / permissions
    (
        re.compile(r"no space left|permission denied|read.?only", re.I),
        "Disk / permissions error",
        "Could not write the downloaded file.\n\n"
        "Either the disk is full or you do not have write permission "
        "to the output folder. Choose a different folder in Settings.",
        ErrorSeverity.CRITICAL,
    ),
]


# ──────────────────────────────────────────────────────────────────────────────
# Main classifier
# ──────────────────────────────────────────────────────────────────────────────

def classify_error(exc: Exception) -> ErrorInfo:
    """
    Convert any exception raised during fetch/download into an ErrorInfo.

    Handles:
    - yt-dlp.utils.DownloadError  (most common)
    - requests.exceptions.*
    - OSError / PermissionError
    - Any other Exception (generic fallback)
    """
    raw_msg = str(exc)

    # ── yt-dlp DownloadError ──────────────────────────────────────────────────
    # yt-dlp wraps its errors in DownloadError with a verbose message string.
    # We pattern-match on the string because yt-dlp doesn't expose sub-types.
    try:
        import yt_dlp.utils as _ydl_utils
        if isinstance(exc, _ydl_utils.DownloadError):
            return _match_patterns(raw_msg)
    except ImportError:
        pass

    # ── requests exceptions ───────────────────────────────────────────────────
    try:
        import requests.exceptions as _req_exc
        if isinstance(exc, _req_exc.ConnectionError):
            if not probe_connectivity():
                return ErrorInfo(
                    severity=ErrorSeverity.ERROR,
                    headline="No internet connection",
                    detail="Could not reach the internet.\n\n"
                           "Please check your network connection and try again.",
                    raw=raw_msg,
                )
            return ErrorInfo(
                severity=ErrorSeverity.ERROR,
                headline="Connection failed",
                detail="Could not connect to the server.\n\n"
                       "The service may be temporarily unavailable.",
                raw=raw_msg,
            )
        if isinstance(exc, _req_exc.Timeout):
            return ErrorInfo(
                severity=ErrorSeverity.ERROR,
                headline="Request timed out",
                detail="The server did not respond in time.\n\nTry again in a moment.",
                raw=raw_msg,
            )
        if isinstance(exc, _req_exc.HTTPError):
            return _match_patterns(raw_msg)
    except ImportError:
        pass

    # ── OS / file system ──────────────────────────────────────────────────────
    if isinstance(exc, PermissionError):
        return ErrorInfo(
            severity=ErrorSeverity.CRITICAL,
            headline="Permission denied",
            detail="Cannot write to the output folder.\n\n"
                   "Choose a different folder in Settings.",
            raw=raw_msg,
        )
    if isinstance(exc, OSError):
        return _match_patterns(raw_msg, default_severity=ErrorSeverity.CRITICAL)

    # ── Catch-all: still try pattern matching on the message ──────────────────
    return _match_patterns(raw_msg)


def _match_patterns(
    raw_msg: str,
    default_severity: ErrorSeverity = ErrorSeverity.ERROR,
) -> ErrorInfo:
    """Apply the pattern table; return a generic ErrorInfo if nothing matches."""
    for pattern, headline, detail, severity in _YTDLP_PATTERNS:
        if pattern.search(raw_msg):
            return ErrorInfo(
                severity=severity,
                headline=headline,
                detail=detail,
                raw=raw_msg,
                retriable=_is_retriable(raw_msg),
            )
    # Generic fallback
    short = raw_msg[:200]
    return ErrorInfo(
        severity=default_severity,
        headline="Download failed",
        detail=f"An unexpected error occurred:\n\n{short}\n\n"
               "If this persists, check your internet connection and try again.",
        raw=raw_msg,
        retriable=_is_retriable(raw_msg),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Pre-flight checks  (called once at startup from main.py and by `cli --doctor`)
# ──────────────────────────────────────────────────────────────────────────────


def check_playwright() -> bool:
    """Return True if the playwright Chromium browser is installed.

    Playwright is an optional runtime dependency used by the channel
    scraper, cookie wizard, and universal stream extractor. The browser
    binaries are not bundled with the EXE because they add ~300 MB; the
    user runs ``playwright install chromium`` once after first install.

    A missing browser is a warning, not a fatal error: most download
    flows do not need Playwright.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False

    try:
        with sync_playwright() as p:
            exe = p.chromium.executable_path
            from pathlib import Path
            return bool(exe) and Path(exe).exists()
    except Exception:
        return False


def check_output_dir_writable(path: str) -> tuple[bool, str]:
    """Return ``(ok, detail)`` for the configured download directory.

    Used by both the GUI preflight and the CLI ``--doctor`` so the
    user sees the same diagnostic on both paths. Creates the
    directory if it does not exist (matches DownloadController
    behaviour); the failure mode is permission denied.
    """
    from pathlib import Path
    try:
        p = Path(path).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        # Round-trip a small file to confirm write permission.
        probe = p / ".ytspot_write_probe"
        probe.write_bytes(b"ok")
        probe.unlink(missing_ok=True)
        return True, str(p)
    except (OSError, PermissionError) as exc:
        return False, f"{path!r}: {exc}"


def check_cookies_file_valid(path: str) -> tuple[bool, str]:
    """Return ``(ok, detail)`` for the configured cookies.txt.

    Empty path = nothing configured = treated as OK (None is a valid
    user choice). Returns False only when the file is set but
    unreadable or malformed.
    """
    if not path:
        return True, "no cookies file configured"
    try:
        from utils.cookie_validator import check_cookies_valid
        ok, msg = check_cookies_valid(path)
        return bool(ok), msg or ("OK" if ok else "cookies file invalid")
    except Exception as exc:
        return False, f"cookies validator raised: {exc}"


@dataclass
class PreflightResult:
    ffmpeg_ok:      bool
    network_ok:     bool
    output_dir_ok:  bool
    cookies_ok:     bool
    playwright_ok:  bool
    warnings:       list[str]
    # Per-check detail lines for the --doctor CLI output. The GUI uses
    # ``warnings`` for the MessageBox; --doctor prints details too.
    details:        list[str]

    def all_ok(self) -> bool:
        # Playwright is optional; not having it is a warning, not a
        # blocker. Cookies validity is informational unless the user
        # explicitly configured a file (handled in run_preflight).
        return self.ffmpeg_ok and self.network_ok and self.output_dir_ok

    def warning_text(self) -> str:
        return "\n\n".join(self.warnings)

    def detail_text(self) -> str:
        return "\n".join(self.details)


def run_preflight(
    output_dir: str = "",
    cookies_file: str = "",
) -> PreflightResult:
    """
    Run startup checks. Returns a PreflightResult the GUI can inspect.
    Does NOT raise – all failures are captured into the result.

    Parameters
    ----------
    output_dir   : Optional path to the configured download folder. When
                   provided, writability is checked. Empty string skips
                   the check (used by the CLI before any download).
    cookies_file : Optional path to a cookies.txt. When non-empty, the
                   file is validated (existence + minimal Netscape
                   header). Empty string skips the check.
    """
    warnings: list[str] = []
    details: list[str] = []

    from utils.paths import get_bundled_ffmpeg_dir, get_ffmpeg_executable

    ffmpeg_exe = get_ffmpeg_executable()
    bundled_ffmpeg_dir = get_bundled_ffmpeg_dir()
    ffmpeg_ok = ffmpeg_exe is not None
    if ffmpeg_ok and bundled_ffmpeg_dir is not None:
        details.append(f"FFmpeg          : OK (bundled: {ffmpeg_exe})")
    elif ffmpeg_ok:
        details.append(f"FFmpeg          : OK (PATH: {ffmpeg_exe})")
    else:
        details.append("FFmpeg          : MISSING")
    if not ffmpeg_ok:
        warnings.append(
            "⚠  FFmpeg was not found on your PATH.\n\n"
            "Audio/video conversion and thumbnail embedding will not work.\n\n"
            "If you installed YTSpot via the official EXE, FFmpeg should be\n"
            "bundled in the app folder. If you are running from source:\n"
            "  Windows : winget install Gyan.FFmpeg\n"
            "  macOS   : brew install ffmpeg\n"
            "  Linux   : sudo apt install ffmpeg\n\n"
            "Then restart YTSpot Downloader."
        )

    network_ok = probe_connectivity()
    details.append(f"Network         : {'OK' if network_ok else 'OFFLINE'}")
    if not network_ok:
        warnings.append(
            "⚠  No internet connection detected.\n\n"
            "Fetching metadata and downloading will fail until the connection is restored."
        )

    output_dir_ok = True
    if output_dir:
        output_dir_ok, output_detail = check_output_dir_writable(output_dir)
        details.append(
            f"Output directory: {'OK' if output_dir_ok else 'NOT WRITABLE'}  ({output_detail})"
        )
        if not output_dir_ok:
            warnings.append(
                f"⚠  The configured download folder is not writable:\n{output_detail}\n\n"
                "Choose a different folder in Settings or check permissions."
            )

    cookies_ok = True
    if cookies_file:
        cookies_ok, cookies_detail = check_cookies_file_valid(cookies_file)
        details.append(
            f"Cookies file    : {'OK' if cookies_ok else 'INVALID'}  ({cookies_detail})"
        )
        if not cookies_ok:
            warnings.append(
                f"⚠  The configured cookies.txt is invalid or unreadable:\n{cookies_detail}\n\n"
                "Re-export cookies or clear the cookies file in Settings."
            )
    else:
        details.append("Cookies file    : not configured (optional)")

    playwright_ok = check_playwright()
    details.append(
        f"Playwright      : {'OK' if playwright_ok else 'NOT INSTALLED'} "
        "(needed for channel scraping, cookie wizard, universal extractor)"
    )
    if not playwright_ok:
        warnings.append(
            "ℹ  Playwright Chromium is not installed.\n\n"
            "Most downloads work without it, but these features are disabled:\n"
            "  • Channel and artist discography scraping\n"
            "  • Cookie sign-in wizard\n"
            "  • Universal stream extractor (generic video sites)\n\n"
            "Run `python -m playwright install chromium` from the install folder\n"
            "(or use the bundled `scripts/install_playwright.ps1`) to enable them."
        )

    return PreflightResult(
        ffmpeg_ok=ffmpeg_ok,
        network_ok=network_ok,
        output_dir_ok=output_dir_ok,
        cookies_ok=cookies_ok,
        playwright_ok=playwright_ok,
        warnings=warnings,
        details=details,
    )
