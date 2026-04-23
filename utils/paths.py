"""
utils/paths.py  –  Shared app-directory path helpers
=====================================================
Single source of truth for all paths under the YTSpot app-data directory.
Zero GUI imports — pure stdlib only.
"""

from __future__ import annotations

import os
from pathlib import Path


def get_app_data_dir() -> Path:
    """
    Return the platform-specific YTSpot app-data directory.

    Windows : %APPDATA%\\.ytspot   (falls back to home/.ytspot)
    Other   : ~/.ytspot
    """
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path.home()
    return base / ".ytspot"


def get_app_cookies_path() -> Path:
    """Return the path where the cookie wizard saves Netscape-format cookies."""
    return get_app_data_dir() / "app_cookies.txt"


def get_log_dir() -> Path:
    """Return the directory used for rotating log files."""
    return get_app_data_dir() / "logs"


def get_history_db_path() -> Path:
    """Return the default SQLite history database path."""
    return get_app_data_dir() / "history.db"
