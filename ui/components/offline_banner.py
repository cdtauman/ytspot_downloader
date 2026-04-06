"""
ui/components/offline_banner.py  –  Network offline notification banner
========================================================================
A slim, dismissible top-of-window banner that appears when the
OfflineMonitor detects network loss and disappears when connectivity
is restored.

Shown/hidden by AppWindow in response to OfflineMonitor signals:
    monitor.went_offline.connect(banner.show)
    monitor.came_online.connect(banner.hide)

The user can also manually dismiss the banner with the × button.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QWidget
from qfluentwidgets import ToolButton


class OfflineBanner(QFrame):
    """
    A 40-px high warning strip displayed above the main content area
    when the app is offline.

    Does not emit any signals – it is purely informational.
    """

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._build()
        self.hide()   # hidden by default

    def _build(self) -> None:
        self.setFixedHeight(40)
        self.setObjectName("offlineBanner")
        self.setStyleSheet("""
            #offlineBanner {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #ef4444, stop:1 #dc2626);
                border: none;
                border-radius: 0;
            }
        """)

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 0, 12, 0)
        row.setSpacing(8)

        icon = QLabel("📡")
        icon.setStyleSheet("background: transparent; font-size: 16px;")
        row.addWidget(icon)

        msg = QLabel(
            "  No internet connection — search and downloads are paused "
            "until connectivity is restored."
        )
        msg.setStyleSheet(
            "color: #ffffff; font-size: 12px; font-weight: 600; "
            "background: transparent;"
        )
        msg.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row.addWidget(msg)

        close_btn = ToolButton(self)
        close_btn.setText("✕")
        close_btn.setFixedSize(26, 26)
        close_btn.setStyleSheet("""
            ToolButton {
                color: #ffffff;
                background: rgba(255,255,255,0.15);
                border: none;
                border-radius: 4px;
                font-size: 12px;
                font-weight: 700;
            }
            ToolButton:hover { background: rgba(255,255,255,0.30); }
        """)
        close_btn.clicked.connect(self.hide)
        row.addWidget(close_btn)
