"""
ui/workers/update_worker.py  –  GitHub release update check worker
===================================================================
Queries the GitHub Releases API on a background thread and emits
update_available only when a newer version is found.  On any failure
(network error, malformed JSON, rate-limit, etc.) the worker exits silently –
a failed update check must never produce a dialog or status-bar message.

This worker is started once, shortly after the main window is shown, and is
never restarted during the app's lifetime.  If the user wants to force a
re-check they can trigger it from the Settings panel.

Signal summary
--------------
update_available(ReleaseInfo)
    Emitted exactly once if a newer version is found.
    Never emitted if the app is up to date or if the check fails.
    The receiving slot in AppWindow shows the UpdateBanner.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from core.update_checker import ReleaseInfo, UpdateChecker


class UpdateWorker(QThread):
    """
    One-shot background update checker.

    Parameters
    ----------
    repo_owner          : GitHub username / org that owns the repo.
                          Replace with your actual GitHub username before release.
    repo_name           : Repository name on GitHub.
                          Replace with your actual repo name before release.
    include_prereleases : When True, pre-release versions are also considered.
                          Controlled by a settings toggle (default False).
    parent              : Optional Qt parent object.
    """

    # ── Signals ───────────────────────────────────────────────────────────────

    update_available = Signal(object)
    # ReleaseInfo – emitted only when a strictly newer version exists.
    # The AppWindow slot connects this to UpdateBanner.show_release(info).

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def __init__(
        self,
        repo_owner:          str  = "your-github-username",   # ← replace before release
        repo_name:           str  = "ytspot-downloader",       # ← replace before release
        include_prereleases: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._checker = UpdateChecker(
            repo_owner=repo_owner,
            repo_name=repo_name,
        )
        self._include_prereleases = include_prereleases

    # ── QThread.run ───────────────────────────────────────────────────────────

    def run(self) -> None:
        """
        Entry point executed on the worker thread.

        UpdateChecker.check() is guaranteed never to raise – all exceptions
        are caught internally and expressed as a None return value.  This run()
        method therefore needs no try/except of its own.
        """
        info: ReleaseInfo | None = self._checker.check(
            include_prereleases=self._include_prereleases,
        )

        if info is not None:
            # A newer version exists – hand it to the UI thread via signal
            self.update_available.emit(info)

        # If info is None (up to date or check failed), emit nothing.
        # The thread exits cleanly and is garbage-collected by Qt.
