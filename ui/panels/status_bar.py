"""
ui/panels/status_bar.py  –  Global progress + status bar
==========================================================
A fixed-height bar pinned to the bottom of the main window that shows:
  - A ProgressBar (indeterminate while fetching; determinate while downloading)
  - A status text label (left-aligned)
  - Download speed (right side)
  - ETA (right side)
  - A cancel button that appears only during active operations

Signals emitted upward
----------------------
cancel_requested()    User clicked the Cancel button.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel,
    QSizePolicy, QVBoxLayout, QWidget,
)
from qfluentwidgets import IndeterminateProgressBar, ProgressBar, ToolButton

from ui.i18n import t
from ui.theme_manager import ACCENT_COLOR, ThemeManager, get_colors

_ERROR = "#f87171"


# ──────────────────────────────────────────────────────────────────────────────
# StatusBar
# ──────────────────────────────────────────────────────────────────────────────

class StatusBar(QFrame):
    """
    Bottom-anchored status bar.

    Parameters
    ----------
    parent : Optional Qt parent.
    """

    cancel_requested = Signal()

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._indeterminate = False
        self._build()

        tm = ThemeManager.instance()
        if tm is not None:
            tm.theme_changed.connect(self._apply_theme)

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_status(self, text: str) -> None:
        """Update the status text label."""
        self._status_lbl.setText(text)

    def set_progress(self, fraction: float) -> None:
        """
        Set the determinate progress bar to fraction (0.0 – 1.0).
        Switches to determinate mode if currently indeterminate.
        """
        if self._indeterminate:
            self._stop_indeterminate()
        value = int(max(0.0, min(1.0, fraction)) * 100)
        self._det_bar.setValue(value)

    def start_indeterminate(self) -> None:
        """Switch to the indeterminate (pulsing) progress bar for fetching."""
        if self._indeterminate:
            return
        self._indeterminate = True
        self._det_bar.setVisible(False)
        self._ind_bar.setVisible(True)
        self._ind_bar.start()

    def stop_indeterminate(self) -> None:
        """Switch back to determinate mode."""
        self._stop_indeterminate()

    def set_metrics(self, speed: str = "", eta: str = "") -> None:
        """Update the speed and ETA labels on the right side."""
        self._speed_lbl.setText(speed)
        self._eta_lbl.setText(eta)

    def set_cancel_visible(self, visible: bool) -> None:
        """Show or hide the Cancel button."""
        self._cancel_btn.setVisible(visible)

    def reset(self) -> None:
        """Return the bar to its resting 'Ready' state."""
        self._stop_indeterminate()
        self._det_bar.setValue(0)
        self._status_lbl.setText(t("ready"))
        self._speed_lbl.setText("")
        self._eta_lbl.setText("")
        self._cancel_btn.setVisible(False)

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.setFixedHeight(60)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 4, 12, 4)
        root.setSpacing(3)

        # ── Progress bar row ──────────────────────────────────────────────────
        self._det_bar = ProgressBar()
        self._det_bar.setFixedHeight(4)
        self._det_bar.setRange(0, 100)
        self._det_bar.setValue(0)
        self._det_bar.setTextVisible(False)
        root.addWidget(self._det_bar)

        self._ind_bar = IndeterminateProgressBar()
        self._ind_bar.setFixedHeight(4)
        self._ind_bar.setVisible(False)
        root.addWidget(self._ind_bar)

        # ── Text / metrics row ────────────────────────────────────────────────
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(6)

        self._status_lbl = QLabel(t("ready"))
        self._status_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        bottom_row.addWidget(self._status_lbl)

        self._speed_lbl = QLabel("")
        self._speed_lbl.setFixedWidth(90)
        # AlignTrailing follows layout direction (right-aligned in LTR,
        # left-aligned in RTL) so the metric label sits at the bar's edge
        # regardless of language.
        self._speed_lbl.setAlignment(Qt.AlignmentFlag.AlignTrailing | Qt.AlignmentFlag.AlignVCenter)
        bottom_row.addWidget(self._speed_lbl)

        self._eta_lbl = QLabel("")
        self._eta_lbl.setFixedWidth(72)
        self._eta_lbl.setAlignment(Qt.AlignmentFlag.AlignTrailing | Qt.AlignmentFlag.AlignVCenter)
        bottom_row.addWidget(self._eta_lbl)

        self._cancel_btn = ToolButton()
        self._cancel_btn.setText(t("cancel"))
        self._cancel_btn.setFixedSize(70, 26)
        self._cancel_btn.setVisible(False)
        self._cancel_btn.clicked.connect(self.cancel_requested)
        bottom_row.addWidget(self._cancel_btn)

        root.addLayout(bottom_row)

        self._apply_theme()

    # ── Theme ──────────────────────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        c = get_colors()

        self.setStyleSheet(
            f"background: {c.surface}; border-top: 1px solid {c.border};"
        )

        self._det_bar.setStyleSheet(f"""
            ProgressBar {{
                background: {c.border};
                border: none;
                border-radius: 2px;
            }}
            ProgressBar::chunk {{
                background: {ACCENT_COLOR};
                border-radius: 2px;
            }}
        """)

        self._status_lbl.setStyleSheet(
            f"color: {c.text_secondary}; font-size: 12px; background: transparent;"
        )
        self._speed_lbl.setStyleSheet(
            f"color: {c.text_tertiary}; font-size: 11px; background: transparent;"
        )
        self._eta_lbl.setStyleSheet(
            f"color: {c.text_tertiary}; font-size: 11px; background: transparent;"
        )

        self._cancel_btn.setStyleSheet(f"""
            ToolButton {{
                background: transparent;
                border: 1px solid {c.border};
                border-radius: 6px;
                color: {c.text_secondary};
                font-size: 11px;
            }}
            ToolButton:hover {{
                border-color: {_ERROR};
                color: {_ERROR};
            }}
        """)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _stop_indeterminate(self) -> None:
        if self._indeterminate:
            self._ind_bar.stop()
            self._ind_bar.setVisible(False)
            self._det_bar.setVisible(True)
            self._indeterminate = False
