"""
playlist_parser.py  –  Backward-compatibility shim
====================================================
The canonical module has moved to ``core/playlist_parser.py``.
This file re-exports every public name so existing imports like::

    from playlist_parser import classify_url, PlaylistParser

continue to work unchanged.  New code should import from ``core.playlist_parser``.
"""

from core.playlist_parser import *          # noqa: F401,F403
from core.playlist_parser import (          # explicit re-exports for type checkers
    PlaylistParser,
    TrackMeta,
    ParseResult,
    SourcePlatform,
    UrlKind,
    classify_url,
)
