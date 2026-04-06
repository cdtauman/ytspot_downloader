"""
core/offline_monitor.py  –  Offline / network detection
=========================================================
A lightweight QObject that polls network reachability every 15 seconds
and emits signals when the app goes offline or comes back online.

Design
------
* Uses a QTimer on the main thread (no extra QThread needed).
* Probes via a DNS-only httpx HEAD to dns.google – fast, no data transfer.
* Emits went_offline / came_online signals so AppWindow can show/hide the
  OfflineBanner without blocking the UI.
* Initial check happens 500 ms after start() is called to avoid slowing
  app launch.

Usage (in AppWindow.__init__)
------------------------------
    self._net_monitor = OfflineMonitor(parent=self)
    self._net_monitor.went_offline.connect(self._offline_banner.show)
    self._net_monitor.came_online.connect(self._offline_banner.hide)
    self._net_monitor.start()
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx
from PySide6.QtCore import QObject, QTimer, Signal

logger = logging.getLogger(__name__)

_PROBE_URL     = "https://dns.google"
_PROBE_TIMEOUT = 4.0          # seconds
_POLL_INTERVAL = 15_000       # milliseconds


class OfflineMonitor(QObject):
    """
    Polls network connectivity and emits Qt signals on state changes.

    Signals
    -------
    went_offline()   – fired the first time a probe fails after success.
    came_online()    – fired the first time a probe succeeds after failure.
    """

    went_offline = Signal()
    came_online  = Signal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._online: Optional[bool] = None   # None = unknown (initial state)
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_INTERVAL)
        self._timer.timeout.connect(self._check)

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start polling.  First check fires after 500 ms."""
        QTimer.singleShot(500, self._check)
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    @property
    def is_online(self) -> bool:
        """True if the most recent probe succeeded (or unknown → optimistic True)."""
        return self._online is not False

    # ── Internal ──────────────────────────────────────────────────────────────

    def _check(self) -> None:
        reachable = _probe()
        if reachable == self._online:
            return   # no state change

        prev = self._online
        self._online = reachable

        if reachable:
            logger.info("[OfflineMonitor] Network reachable.")
            if prev is False:        # only emit if we were previously offline
                self.came_online.emit()
        else:
            logger.warning("[OfflineMonitor] Network unreachable.")
            self.went_offline.emit()


def _probe() -> bool:
    """Return True if the probe URL is reachable, False otherwise."""
    try:
        resp = httpx.head(_PROBE_URL, timeout=_PROBE_TIMEOUT, follow_redirects=True)
        return resp.status_code < 500
    except Exception:
        return False
