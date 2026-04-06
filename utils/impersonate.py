"""
utils/impersonate.py  –  Shared curl_cffi / ImpersonateTarget detection
=========================================================================
Both downloader.py and playlist_parser.py need to detect whether
curl_cffi is available and optionally build an ImpersonateTarget for
yt-dlp's impersonation API.  This module centralises that detection so
there is a single place to update if yt-dlp's internal API changes.

Usage
-----
>>> from utils.impersonate import CURL_CFFI_AVAILABLE, ImpersonateTarget
>>> if CURL_CFFI_AVAILABLE:
...     target = ImpersonateTarget("chrome", None, "windows", None)
"""

from __future__ import annotations

try:
    from yt_dlp.networking.impersonate import ImpersonateTarget
    CURL_CFFI_AVAILABLE: bool = True
except ImportError:
    ImpersonateTarget = None  # type: ignore[assignment,misc]
    CURL_CFFI_AVAILABLE = False
