"""
downloader.py  –  Backward-compatibility shim
===============================================
The canonical module has moved to ``core/downloader.py``.
This file re-exports every public name so existing imports like::

    from downloader import DownloadEngine, DownloadRequest

continue to work unchanged.  New code should import from ``core.downloader``.
"""

from core.downloader import *          # noqa: F401,F403
from core.downloader import (          # explicit re-exports for type checkers
    DownloadEngine,
    DownloadProgress,
    DownloadRequest,
    DownloadStatus,
    MediaType,
    AudioQuality,
    VideoQuality,
)
