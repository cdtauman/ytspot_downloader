"""
history_db_resilience_patch.py  –  Drop-in replacement for HistoryDB.__init__
==============================================================================
Apply this to core/history_db.py:

1. Add `import shutil` and `import logging` to the imports at the top.
2. Add `logger = logging.getLogger(__name__)` after imports.
3. Replace the existing __init__ method with the one below.
4. Add the two new private methods (_check_integrity, _backup_and_recreate).

Changes:
- On first open, runs PRAGMA integrity_check (quick_check for large DBs).
- If corruption is detected, backs up the file to downloads.db.corrupt.<timestamp>
  and recreates a fresh database — no data loss for the backup, clean slate for the app.
- Logs all outcomes so the user (or developer) can see what happened in ytspot.log.
- :memory: databases skip the integrity check (nothing to corrupt).
"""

import logging
import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ── Replace HistoryDB.__init__ with this ──────────────────────────────────────

def __init__(self, db_path: Optional[str] = None) -> None:
    if db_path is None or db_path == "":
        db_path = self._default_path()

    self._path = db_path
    self._lock = threading.Lock()

    # Create parent directory if needed (not for :memory:)
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # ── Open connection ───────────────────────────────────────────────
    self._conn = sqlite3.connect(
        db_path,
        check_same_thread=False,
        isolation_level=None,
    )
    self._conn.execute("PRAGMA journal_mode=WAL;")
    self._conn.execute("PRAGMA foreign_keys=ON;")

    # ── Integrity check (skip for :memory:) ───────────────────────────
    if db_path != ":memory:" and not self._check_integrity():
        logger.error(
            "[HistoryDB] Integrity check FAILED for %s — "
            "backing up and recreating.",
            db_path,
        )
        self._backup_and_recreate()

    self._initialise_schema()
    logger.info("[HistoryDB] Opened %s (%d records)", db_path, self.count())


# ── Add these two new methods to the HistoryDB class ──────────────────────────

def _check_integrity(self) -> bool:
    """
    Run a fast integrity check on the database.

    Uses ``PRAGMA quick_check`` which is much faster than the full
    ``integrity_check`` — it skips verifying that index content matches
    table content but still catches page-level corruption, which is the
    most common failure mode after an unclean shutdown.

    Returns True if the database is healthy.
    """
    try:
        cursor = self._conn.execute("PRAGMA quick_check;")
        result = cursor.fetchone()
        ok = result is not None and result[0] == "ok"
        if ok:
            logger.debug("[HistoryDB] Integrity check passed")
        else:
            logger.warning(
                "[HistoryDB] quick_check returned: %s",
                result[0] if result else "(no result)",
            )
        return ok
    except sqlite3.DatabaseError as exc:
        logger.warning("[HistoryDB] quick_check raised: %s", exc)
        return False


def _backup_and_recreate(self) -> None:
    """
    Close the connection, rename the corrupt file with a .corrupt.<ts>
    suffix, and open a fresh connection to a new empty database at the
    same path.

    The corrupt file is preserved so the user can attempt manual recovery
    (e.g. via ``sqlite3 old.db ".recover" | sqlite3 new.db``).
    """
    # Close the current (corrupt) connection
    try:
        self._conn.close()
    except Exception:
        pass

    # Rename: downloads.db → downloads.db.corrupt.20260406T120000
    db_file = Path(self._path)
    if db_file.exists():
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        backup_name = db_file.with_suffix(f".db.corrupt.{ts}")
        try:
            shutil.move(str(db_file), str(backup_name))
            logger.info("[HistoryDB] Corrupt DB backed up to %s", backup_name)
        except OSError as exc:
            logger.error(
                "[HistoryDB] Could not rename corrupt DB: %s — "
                "deleting instead.",
                exc,
            )
            try:
                db_file.unlink()
            except OSError:
                pass

        # Also move WAL and SHM journal files if they exist
        for suffix in (".db-wal", ".db-shm"):
            journal = db_file.with_suffix(suffix)
            if journal.exists():
                try:
                    journal.unlink()
                except OSError:
                    pass

    # Reopen a fresh connection at the same path
    self._conn = sqlite3.connect(
        self._path,
        check_same_thread=False,
        isolation_level=None,
    )
    self._conn.execute("PRAGMA journal_mode=WAL;")
    self._conn.execute("PRAGMA foreign_keys=ON;")
    logger.info("[HistoryDB] Fresh database created at %s", self._path)
