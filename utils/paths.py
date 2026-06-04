"""
utils/paths.py  –  Shared app-directory path helpers
=====================================================
Single source of truth for all paths under the YTSpot app-data directory.
Also handles the frozen-EXE FFmpeg discovery used by core.downloader.
Zero GUI imports — pure stdlib only.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional


def get_app_data_dir() -> Path:
    """
    Return the platform-specific YTSpot app-data directory.

    This is the single source of truth for the app-data location.
    ``config.py`` and ``utils.logging_config`` delegate here so all
    three never drift.

    Windows : %APPDATA%\\.ytspot              (falls back to ~/.ytspot)
    macOS   : ~/Library/Application Support/YTSpot
    Linux   : $XDG_CONFIG_HOME/ytspot         (falls back to ~/.ytspot)
    """
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
        return base / ".ytspot"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "YTSpot"
    # Linux / other POSIX: honour XDG when set, else hidden home dir.
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "ytspot"
    return Path.home() / ".ytspot"


def get_app_cookies_path() -> Path:
    """Return the path where the cookie wizard saves Netscape-format cookies."""
    return get_app_data_dir() / "app_cookies.txt"


def get_log_dir() -> Path:
    """Return the directory used for rotating log files."""
    return get_app_data_dir() / "logs"


def get_history_db_path() -> Path:
    """Return the default SQLite history database path."""
    return get_app_data_dir() / "history.db"


def get_install_dir() -> Path:
    """Return the directory the app is installed in.

    When running from a PyInstaller-frozen EXE, this is the folder
    containing ``ytspot.exe``. When running from source, this is the
    repo root (the parent of the ``utils`` package).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_bundled_ffmpeg_dir() -> Optional[Path]:
    """Return the folder containing bundled ffmpeg.exe / ffprobe.exe, or None.

    The Windows EXE build script may copy LGPL FFmpeg binaries into
    ``packaging/ffmpeg/`` and PyInstaller relocates them to sit next
    to ``ytspot.exe``. Source checkouts use the same convention if the
    developer dropped binaries there.

    Returns the directory path when both ``ffmpeg.exe`` and
    ``ffprobe.exe`` are present, otherwise ``None`` so yt-dlp falls
    back to PATH.
    """
    install = get_install_dir()
    candidates = [
        install,                  # next to ytspot.exe (frozen install)
        install / "ffmpeg",       # nested folder (alternative layout)
        install / "packaging" / "ffmpeg",  # source checkout dev layout
    ]
    # macOS .app bundle: PyInstaller may place binaries under
    # Contents/MacOS (== install), Contents/Frameworks, or
    # Contents/Resources, with symlinks between them. Add all three so
    # discovery succeeds regardless of where PyInstaller dropped them.
    if sys.platform == "darwin" and install.name == "MacOS":
        contents = install.parent
        candidates += [
            contents / "Frameworks",
            contents / "Resources",
        ]
    suffix = ".exe" if os.name == "nt" else ""
    for d in candidates:
        ff = d / f"ffmpeg{suffix}"
        fp = d / f"ffprobe{suffix}"
        if ff.exists() and fp.exists():
            return d
    return None


def get_ffmpeg_executable() -> Optional[str]:
    """Return the path to ffmpeg, preferring the bundled binary.

    Used by ``error_handler.check_ffmpeg`` and the doctor diagnostic
    so the "FFmpeg: OK" report reflects what yt-dlp will actually
    invoke at runtime, not just whatever happens to be on PATH.
    """
    bundled = get_bundled_ffmpeg_dir()
    if bundled is not None:
        suffix = ".exe" if os.name == "nt" else ""
        ff = bundled / f"ffmpeg{suffix}"
        if ff.exists():
            return str(ff)
    return shutil.which("ffmpeg")
