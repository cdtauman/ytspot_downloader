"""
main.py  –  YTSpot Downloader  entry point
==========================================
Bootstraps the Qt application, loads persistent config and the history
database, applies the saved theme, constructs the main window, and
hands control to the Qt event loop.

Run with:
    python main.py
or, after packaging:
    ytspot
"""

from __future__ import annotations

import sys
import os
import logging

def main() -> int:
    # 1. High-DPI policy must be set before QApplication is constructed
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    # 2. Configure policies
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # 3. Construct the global QApplication object IMMEDIATELY
    #    Every subsequent import that touches Qt widgets (including
    #    the FluentWindow machinery) will find an app already alive.
    app = QApplication(sys.argv)
    app.setApplicationName("YTSpot Downloader")
    app.setApplicationDisplayName("YTSpot Downloader")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("YTSpot")

    # 4. Now that QApplication is alive, safely import backend & UI singletons
    from config import AppConfig

    from core.history_db import HistoryDB
    from ui.theme_manager import ThemeManager
    from ui.app_window import AppWindow

    cfg = AppConfig()
    db  = HistoryDB(cfg.resolved_history_db_path())

    # Set UI language and application layout direction early so widgets
    # are constructed with the correct direction and texts.
    from ui.i18n import set_language
    set_language(cfg.language)
    if cfg.language == "he":
        app.setLayoutDirection(Qt.RightToLeft)
    else:
        app.setLayoutDirection(Qt.LeftToRight)

    # 5. Theme (applied before the window is constructed so the first paint
    #    uses the correct palette — avoids a white flash on startup)
    theme_mgr = ThemeManager(cfg)
    theme_mgr.apply(cfg.theme)

    # 6. Main window
    try:
        window = AppWindow(config=cfg, db=db)
        window.show()
    except Exception as e:
        print(f"CRITICAL STARTUP ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # 7. Event loop
    return app.exec()


if __name__ == "__main__":
    # Protected by __main__ guard to avoid accidental GUI initialization
    # if main.py is imported by another module (e.g. tests or docs).
    sys.exit(main())
