"""
ui/components/update_banner.py  –  Slide-in update notification banner
=======================================================================
A fixed-height QFrame that slides smoothly down from zero height to its
full height when show_release() is called, and slides back up when the
user dismisses it.  It sits at the top of the main window's central widget,
above the URL bar.

Animation
---------
Uses QPropertyAnimation on the "maximumHeight" property so Qt's layout
engine naturally pushes all content down as the banner expands — no manual
geometry manipulation needed.  The animation duration is 280 ms with an
OutCubic easing curve for a polished feel.

Signals
-------
dismissed()
    Emitted after the close animation completes, so AppWindow can remove
    the widget from the layout if desired.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve, QPropertyAnimation, Qt, Signal, QUrl,
)
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel,
    QSizePolicy, QWidget,
)
from qfluentwidgets import PrimaryPushButton, ToolButton

from core.update_checker import ReleaseInfo
from ui.i18n import t
from ui.theme_manager import ACCENT_COLOR, ACCENT_COLOR_DIM


# ──────────────────────────────────────────────────────────────────────────────
# Design tokens
# ──────────────────────────────────────────────────────────────────────────────

_BANNER_BG     = "#1a1200"       # Very dark amber tint
_BANNER_BORDER = "#8b5e00"       # Muted amber border
_TEXT          = "#f5e0a0"       # Warm off-white on the dark amber bg
_TEXT_DIM      = "#c4a95a"
_FULL_HEIGHT   = 52              # px – banner height when fully expanded
_ANIM_MS       = 280             # animation duration in milliseconds


# ──────────────────────────────────────────────────────────────────────────────
# UpdateBanner
# ──────────────────────────────────────────────────────────────────────────────

class UpdateBanner(QFrame):
    """
    Animated top-of-window banner that announces a new app release.

    Typical usage inside AppWindow
    --------------------------------
        self._update_banner = UpdateBanner(parent=self)
        self._layout.insertWidget(0, self._update_banner)   # top of layout
        # … later, when UpdateWorker fires:
        self._update_banner.show_release(release_info)

    Parameters
    ----------
    parent : Qt parent widget (typically AppWindow's central widget).
    """

    dismissed = Signal()

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._release: ReleaseInfo | None = None
        self._build()
        self._setup_animation()

        # Start collapsed so it takes zero space before show_release() is called
        self.setMaximumHeight(0)
        self.setVisible(False)

    # ── Public API ─────────────────────────────────────────────────────────────

    def show_release(self, info: ReleaseInfo) -> None:
        """
        Populate the banner with release details and animate it open.
        Safe to call from any thread via a connected Qt signal.
        """
        self._release = info

        # Update label text before expanding
        self._version_lbl.setText(
            f"🎉  YTSpot {info.display_version()} is available!"
        )

        short_notes = info.short_notes(max_chars=90)
        if short_notes:
            self._notes_lbl.setText(short_notes)
            self._notes_lbl.setVisible(True)
        else:
            self._notes_lbl.setVisible(False)

        # Show the download button only when a direct asset URL exists
        self._download_btn.setVisible(bool(info.asset_url))

        self.setVisible(True)
        self._expand_anim.setStartValue(0)
        self._expand_anim.setEndValue(_FULL_HEIGHT)
        self._expand_anim.start()

    def dismiss(self) -> None:
        """Animate the banner closed."""
        self._collapse_anim.setStartValue(self.maximumHeight())
        self._collapse_anim.setEndValue(0)
        self._collapse_anim.start()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.setFixedHeight(_FULL_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(f"""
            UpdateBanner {{
                background-color: {_BANNER_BG};
                border-bottom: 1px solid {_BANNER_BORDER};
            }}
        """)

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 0, 8, 0)
        row.setSpacing(0)

        # ── Bell / version label ──────────────────────────────────────────────
        self._version_lbl = QLabel(t("update_available"))
        self._version_lbl.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
        self._version_lbl.setStyleSheet(
            f"color: {ACCENT_COLOR}; background: transparent;"
        )
        row.addWidget(self._version_lbl)
        row.addSpacing(16)

        # ── Short release notes ───────────────────────────────────────────────
        self._notes_lbl = QLabel("")
        self._notes_lbl.setFont(QFont("Consolas", 9))
        self._notes_lbl.setStyleSheet(
            f"color: {_TEXT_DIM}; background: transparent;"
        )
        self._notes_lbl.setVisible(False)
        row.addWidget(self._notes_lbl, stretch=1)
        row.addSpacing(12)

        # ── View release button ───────────────────────────────────────────────
        view_btn = PrimaryPushButton(t("view_release"))
        view_btn.setFixedSize(108, 32)
        view_btn.clicked.connect(self._open_release_page)
        row.addWidget(view_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(6)

        # ── Download button (visible only when asset URL is present) ──────────
        self._download_btn = PrimaryPushButton(t("download_btn"))
        self._download_btn.setFixedSize(90, 32)
        self._download_btn.setVisible(False)
        self._download_btn.setStyleSheet(f"""
            PrimaryPushButton {{
                background-color: {ACCENT_COLOR};
                color: #000000;
                border: none;
                border-radius: 6px;
            }}
            PrimaryPushButton:hover {{
                background-color: {ACCENT_COLOR_DIM};
            }}
        """)
        self._download_btn.clicked.connect(self._open_download_link)
        row.addWidget(self._download_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(8)

        # ── Dismiss (×) button ────────────────────────────────────────────────
        dismiss_btn = ToolButton()
        dismiss_btn.setText("✕")
        dismiss_btn.setFixedSize(28, 28)
        dismiss_btn.setToolTip(t("dismiss_tooltip"))
        dismiss_btn.setStyleSheet(f"""
            ToolButton {{
                background: transparent;
                border: none;
                color: {_TEXT_DIM};
                font-size: 12px;
            }}
            ToolButton:hover {{ color: {_TEXT}; }}
        """)
        dismiss_btn.clicked.connect(self.dismiss)
        row.addWidget(dismiss_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

    # ── Animations ────────────────────────────────────────────────────────────

    def _setup_animation(self) -> None:
        # Expand animation (slide down)
        self._expand_anim = QPropertyAnimation(self, b"maximumHeight")
        self._expand_anim.setDuration(_ANIM_MS)
        self._expand_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Collapse animation (slide up)
        self._collapse_anim = QPropertyAnimation(self, b"maximumHeight")
        self._collapse_anim.setDuration(_ANIM_MS)
        self._collapse_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._collapse_anim.finished.connect(self._on_collapse_finished)

    def _on_collapse_finished(self) -> None:
        self.setVisible(False)
        self.dismissed.emit()

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _open_release_page(self) -> None:
        if self._release and self._release.release_url:
            QDesktopServices.openUrl(QUrl(self._release.release_url))

    def _open_download_link(self) -> None:
        if self._release and self._release.asset_url:
            QDesktopServices.openUrl(QUrl(self._release.asset_url))


# ──────────────────────────────────────────────────────────────────────────────
# Smoke-test  (python -m ui.components.update_banner)
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
    from PySide6.QtCore import QTimer
    from qfluentwidgets import setTheme, Theme, BodyLabel

    app = QApplication(sys.argv)
    setTheme(Theme.DARK)

    window = QWidget()
    window.setWindowTitle("UpdateBanner – smoke-test")
    window.setMinimumSize(720, 200)
    window.setStyleSheet("background: #0e0e0f;")

    layout = QVBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    banner = UpdateBanner()
    layout.addWidget(banner)

    hint = BodyLabel(
        "The banner will slide in after 1 s, then dismiss after 4 s.\n"
        "Click ✕ to dismiss early."
    )
    hint.setStyleSheet("color: #9090a0; padding: 16px;")
    layout.addWidget(hint)
    layout.addStretch()

    sample_release = ReleaseInfo(
        version="2.1.0",
        release_url="https://github.com/cdtauman-projects/ytspot_downloader/releases/tag/v2.1.0",
        release_notes=(
            "## Highlights\n\n"
            "- **Clipboard Monitor** now detects media links from additional sources\n"
            "- Fixed crash when output directory contains Unicode characters\n"
            "- Search panel now shows album art for Spotify results\n"
        ),
        published_at="2025-07-15T10:00:00Z",
        asset_url="https://github.com/cdtauman-projects/ytspot_downloader/releases/download/v2.1.0/YTSpot-Setup.exe",
    )

    dismissed_flag = [False]

    def _on_dismissed() -> None:
        dismissed_flag[0] = True
        hint.setText("Banner dismissed ✅  Test complete.")

    banner.dismissed.connect(_on_dismissed)

    # Show after 1 s, auto-dismiss after 4 s
    QTimer.singleShot(1000, lambda: banner.show_release(sample_release))
    QTimer.singleShot(5000, banner.dismiss)
    QTimer.singleShot(6000, app.quit)

    window.show()

    print("UpdateBanner smoke-test running…")
    print("  Banner will slide in after 1 s")
    print("  Banner will auto-dismiss after 5 s")
    print("  App will close after 6 s")

    sys.exit(app.exec())
