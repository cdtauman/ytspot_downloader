"""
app_window_shutdown_patch.py  –  Drop-in replacement for AppWindow.closeEvent
==============================================================================
Replace the existing closeEvent method in ui/app_window.py with this version.

Changes from original:
1. Uses DownloadWorker.shutdown(timeout_ms) instead of quit()+wait().
2. Proper cancel-then-join for all QThread workers (not quit()).
3. Structured logging at every step for post-mortem debugging.
4. Explicit timeout per worker (3s for download, 2s for others).
5. Global hotkey cleanup via keyboard.unhook_all().
"""

# ─── Paste this method into AppWindow, replacing the existing closeEvent ──────

def closeEvent(self, event) -> None:
    """
    Clean shutdown sequence.

    Order matters:
    1. Tray intercept (if enabled).
    2. Persist window state and queue.
    3. Stop non-threaded monitors (clipboard, network).
    4. Cancel + join threaded workers (download first, then others).
    5. Unregister global hotkeys.
    6. Close the database.
    7. Accept the close event.
    """
    # ── 1. Tray intercept ─────────────────────────────────────────────────
    if self._cfg.tray_on_close and self._tray and self._tray.isVisible():
        event.ignore()
        self.hide()
        self._tray.showMessage(
            "YTSpot Downloader",
            "Running in the background. Double-click the tray icon to restore.",
            QSystemTrayIcon.MessageIcon.Information,
            3000,
        )
        return

    logger.info("[AppWindow] closeEvent — beginning shutdown sequence")

    # ── 2. Persist state ──────────────────────────────────────────────────
    self._save_state()
    self._save_queue_state()

    # ── 3. Stop non-threaded monitors ─────────────────────────────────────
    if hasattr(self, "_net_monitor"):
        self._net_monitor.stop()
        logger.debug("[AppWindow] Network monitor stopped")
    if hasattr(self, "_clipboard_worker"):
        self._clipboard_worker.stop()
        logger.debug("[AppWindow] Clipboard monitor stopped")

    # ── 4. Cancel + join threaded workers ─────────────────────────────────
    # Download worker gets special treatment: it owns a ThreadPoolExecutor
    # that must be shut down non-blockingly before we wait on the QThread.
    if self._dl_worker and self._dl_worker.isRunning():
        logger.info("[AppWindow] Shutting down DownloadWorker…")
        self._dl_worker.shutdown(timeout_ms=3000)

    # Other QThread workers: request cancellation, then wait with timeout.
    other_workers = []
    for attr in ("_fetch_worker", "_search_worker", "_scraper_worker"):
        w = getattr(self, attr, None)
        if w and w.isRunning():
            other_workers.append((attr, w))

    for attr_name, w in other_workers:
        logger.debug("[AppWindow] Cancelling %s…", attr_name)
        if hasattr(w, "cancel"):
            w.cancel()

    for attr_name, w in other_workers:
        finished = w.wait(2000)
        if finished:
            logger.debug("[AppWindow] %s joined cleanly", attr_name)
        else:
            logger.warning(
                "[AppWindow] %s did not finish within 2s — abandoning", attr_name,
            )

    # ── 5. Global hotkeys ─────────────────────────────────────────────────
    try:
        import keyboard
        keyboard.unhook_all()
        logger.debug("[AppWindow] Global hotkeys unregistered")
    except Exception:
        pass

    # ── 6. Hide tray & close DB ───────────────────────────────────────────
    if self._tray:
        self._tray.hide()

    self._db.close()
    logger.info("[AppWindow] Database closed — shutdown complete")

    super().closeEvent(event)
