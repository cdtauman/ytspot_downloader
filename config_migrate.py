"""
config_migrate.py  –  Schema migration for ~/.ytspot/config.json
=================================================================
Each time the config schema changes in a breaking way (key renamed,
type changed, value meaning redefined), add a new migration function
to the ``_MIGRATIONS`` list below.

The ``migrate()`` function is called by ``AppConfig._load()`` after
reading the raw JSON.  It inspects ``config_version``, runs any
pending migrations in order, bumps the version, and returns the
updated dict — which AppConfig then saves back to disk.

Rules
-----
* Additive keys (new key with a default) do NOT need a migration —
  AppConfig already merges missing keys from _DEFAULTS.
* Only breaking changes need a migration: renamed keys, changed
  value semantics, removed keys, type changes.
* Each migration takes a ``dict`` and mutates it in place.
* Migrations are numbered sequentially starting at 1.
* ``config_version`` 0 (or absent) means "original schema, no
  migrations ever applied".

Zero GUI imports.  Zero side effects beyond mutating the passed dict.
"""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)

# Current schema version — bump this when adding a new migration.
CURRENT_VERSION: int = 1


# ──────────────────────────────────────────────────────────────────────────────
# Migration registry
# ──────────────────────────────────────────────────────────────────────────────
# Each entry: (target_version, description, callable)
# The callable receives the raw config dict and mutates it.

_MIGRATIONS: list[tuple[int, str, Callable[[dict], None]]] = [

    # ── Migration 1: add config_version itself ────────────────────────────────
    # This is a bootstrap migration.  All configs written before the version
    # system existed have no "config_version" key.  After this migration the
    # key exists and is set to 1.
    (
        1,
        "Bootstrap: add config_version key",
        lambda d: None,   # no-op; version is set by migrate() after running
    ),

    # ── Future migrations go here ─────────────────────────────────────────────
    # Example:
    # (
    #     2,
    #     "Rename 'audio_quality' values from 'Best (320k)' → '320k'",
    #     _migrate_v2,
    # ),
]


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def migrate(data: dict) -> bool:
    """
    Apply all pending migrations to ``data`` in place.

    Parameters
    ----------
    data : The raw config dict loaded from JSON.

    Returns
    -------
    bool
        True if any migration was applied (caller should save to disk).
    """
    current = data.get("config_version", 0)
    if not isinstance(current, int):
        current = 0

    if current >= CURRENT_VERSION:
        return False   # already up to date

    applied = False
    for target_ver, description, fn in _MIGRATIONS:
        if target_ver <= current:
            continue
        logger.info(
            "[ConfigMigrate] Applying migration %d: %s", target_ver, description,
        )
        try:
            fn(data)
        except Exception:
            logger.error(
                "[ConfigMigrate] Migration %d failed — skipping",
                target_ver, exc_info=True,
            )
            # Don't bump version past the failed migration
            break
        current = target_ver
        applied = True

    data["config_version"] = current
    if applied:
        logger.info("[ConfigMigrate] Config upgraded to version %d", current)
    return applied


# ──────────────────────────────────────────────────────────────────────────────
# Example future migration function (kept commented for reference)
# ──────────────────────────────────────────────────────────────────────────────
#
# def _migrate_v2(data: dict) -> None:
#     """
#     v2: Normalise audio_quality values.
#     Old: "Best (320k)" → New: "320k"
#     """
#     _MAP = {
#         "Best (320k)":   "320k",
#         "High (256k)":   "256k",
#         "Medium (192k)": "192k",
#         "Low (128k)":    "128k",
#     }
#     old_val = data.get("audio_quality", "")
#     if old_val in _MAP:
#         data["audio_quality"] = _MAP[old_val]
