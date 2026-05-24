"""
utils/cookie_validator.py  –  Netscape cookies.txt freshness checker
=====================================================================
Parses a Netscape-format cookies file and reports whether the session
cookies are still valid (not all expired).

Zero GUI imports — pure stdlib only.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from ui.i18n import t

logger = logging.getLogger(__name__)


def check_cookies_valid(path: str | Path) -> tuple[bool, str]:
    """
    Parse a Netscape cookies.txt file and check expiry.

    Returns
    -------
    (True, "")
        If the file is valid and at least one non-expired cookie exists.
    (False, warning_message)
        If the file is missing, unreadable, or all cookies have expired.
    """
    p = Path(path)
    if not p.exists():
        return False, t("cookies_file_not_found", path=p)

    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return False, t("cookies_read_error", exc=exc)

    now = time.time()
    total = 0
    expired = 0

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        total += 1
        try:
            expiry = int(parts[4])
        except (ValueError, IndexError):
            continue
        # 0 means session cookie (no expiry) — treat as valid
        if expiry == 0:
            continue
        if expiry < now:
            expired += 1

    if total == 0:
        return False, t("cookies_empty_or_invalid")

    if expired == total:
        return False, t("cookies_all_expired")

    if expired > 0:
        pct = int(expired / total * 100)
        logger.debug("[CookieValidator] %d/%d cookies expired (%d%%)", expired, total, pct)

    return True, ""
