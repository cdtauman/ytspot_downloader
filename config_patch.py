"""
config_patch.py  –  Patch instructions for config.py
=====================================================
Apply these 3 changes to the existing config.py file.

Change 1:  Add "config_version" to _DEFAULTS (at the very top of the dict)
Change 2:  Add import of config_migrate at the top of the file
Change 3:  Replace the _load() method with the version below

These are shown as copy-paste-ready code blocks.
"""

# ──────────────────────────────────────────────────────────────────────────────
# CHANGE 1:  Add to the top of _DEFAULTS dict
# ──────────────────────────────────────────────────────────────────────────────
#
#   _DEFAULTS: dict[str, Any] = {
#       "config_version":       1,          # <── ADD THIS LINE
#       "output_dir":           str(Path.home() / "Downloads" / "YTSpot"),
#       ...
#   }


# ──────────────────────────────────────────────────────────────────────────────
# CHANGE 2:  Add import at top of config.py (after existing imports)
# ──────────────────────────────────────────────────────────────────────────────
#
#   from config_migrate import migrate as _run_migrations


# ──────────────────────────────────────────────────────────────────────────────
# CHANGE 3:  Replace the existing _load() method with this one
# ──────────────────────────────────────────────────────────────────────────────

def _load(self) -> None:
    """
    Load config from disk, run any pending schema migrations, and
    merge with current defaults so new keys are always present.
    """
    if not self._path.exists():
        return
    try:
        raw    = self._path.read_text(encoding="utf-8")
        stored = json.loads(raw)
        if not isinstance(stored, dict):
            return

        # Run schema migrations (mutates stored in place)
        migrated = _run_migrations(stored)

        # Merge: only copy keys that exist in _DEFAULTS
        # (unknown keys from future versions are silently ignored)
        for key in _DEFAULTS:
            if key in stored:
                self._data[key] = stored[key]

        # If migrations were applied, persist the upgraded config
        # immediately so the migration doesn't re-run next launch.
        if migrated:
            self.save()

    except (json.JSONDecodeError, OSError):
        pass
