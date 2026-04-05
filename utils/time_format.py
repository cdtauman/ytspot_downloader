"""
utils/time_format.py  –  Shared duration formatting helper
===========================================================
Single source of truth for converting a raw number of seconds into the
human-readable "M:SS" / "H:MM:SS" strings displayed throughout the app.

Previously there were three separate copies of this logic spread across
playlist_parser.py, core/search_engine.py, and core/history_db.py.
"""

from __future__ import annotations

from typing import Optional


def seconds_to_str(seconds: Optional[int | float], *, live_label: str = "") -> str:
    """
    Convert *seconds* to a compact time string.

    Parameters
    ----------
    seconds :
        Duration in seconds.  ``None`` or negative values return *live_label*.
    live_label :
        String returned when *seconds* is ``None`` (default ``""``).
        Pass ``"Live"`` for playlist cards or ``"—"`` for history rows.

    Returns
    -------
    str
        ``"M:SS"`` for durations under one hour, ``"H:MM:SS"`` otherwise,
        or *live_label* when the duration is unknown.

    Examples
    --------
    >>> seconds_to_str(65)
    '1:05'
    >>> seconds_to_str(3661)
    '1:01:01'
    >>> seconds_to_str(None, live_label="Live")
    'Live'
    """
    if seconds is None:
        return live_label
    s = int(seconds)
    if s < 0:
        return live_label
    h, remainder = divmod(s, 3600)
    m, sec = divmod(remainder, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"
