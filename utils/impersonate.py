"""
utils/impersonate.py  –  curl_cffi / ImpersonateTarget availability check
==========================================================================
Detects whether both curl_cffi (the HTTP impersonation library) and
yt-dlp's impersonation interface are available.

Both conditions must be true for TLS impersonation to work:
  1. ``curl_cffi`` is installed in the environment.
  2. ``yt_dlp.networking.impersonate.ImpersonateTarget`` exists in this
     version of yt-dlp.

Usage
-----
>>> from utils.impersonate import CURL_CFFI_AVAILABLE, ImpersonateTarget
>>> if CURL_CFFI_AVAILABLE:
...     target = ImpersonateTarget("chrome", "137", "windows", None)
"""

from __future__ import annotations

try:
    import curl_cffi  # noqa: F401  — confirm the library is installed
    from yt_dlp.networking.impersonate import ImpersonateTarget
    CURL_CFFI_AVAILABLE: bool = True
except ImportError:
    ImpersonateTarget = None  # type: ignore[assignment,misc]
    CURL_CFFI_AVAILABLE = False
