"""
ui/panels/options_bar.py  –  Format / quality / output controls bar
====================================================================
A compact horizontal bar shown above the queue panel that lets the user
pick the download format, quality, audio codec, output folder, and toggle
the clipboard monitor — all without opening Settings.

It reads its initial state from AppConfig on construction and exposes
apply_config() so AppWindow can sync it after a Settings save.

Signals emitted upward
----------------------
options_changed()     Any control changed; AppWindow reads get_options().
browse_requested()    User clicked the folder button (AppWindow opens dialog).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel,
    QSizePolicy, QWidget,
)
from qfluentwidgets import (
    ComboBox, LineEdit, SwitchButton, ToolButton,
)

from config import AppConfig
from ui.theme_manager import ACCENT_COLOR


# ──────────────────────────────────────────────────────────────────────────────
# Quality / format maps  (mirrors the original main.py)
# ──────────────────────────────────────────────────────────────────────────────

AUDIO_QUALITY_OPTIONS: list[str] = [
    "Best (320k)", "High (256k)", "Medium (192k)", "Low (128k)",
]
VIDEO_QUALITY_OPTIONS: list[str] = [
    "Best", "2160p (4K)", "1440p (2K)", "1080p", "720p", "480p", "Worst",
]
AUDIO_FORMAT_OPTIONS: list[str] = ["mp3", "m4a", "flac", "opus"]

# ──────────────────────────────────────────────────────────────────────────────
# Design tokens
# ──────────────────────────────────────────────────────────────────────────────

_BG      = "#18181b"
_BORDER  = "#2e2e35"
_TEXT    = "#f0f0f0"
_TEXT_2  = "#9090a0"
_TEXT_3  = "#55555f"


# ──────────────────────────────────────────────────────────────────────────────
# OptionsBar
# ──────────────────────────────────────────────────────────────────────────────

class OptionsBar(QFrame):
    """
    Compact one-row controls bar.

    Parameters
    ----------
    config : AppConfig – read on construction; written back on apply_config().
    parent : Optional Qt parent.
    """

    options_changed = Signal()

    def __init__(self, config: AppConfig, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._config = config
        self._build()
        self.apply_config(config)

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_options(self) -> dict:
        """
        Return a dict of the current control values.

        Keys
        ----
        format        : "mp3" | "mp4"
        quality_label : e.g. "Best (320k)" or "1080p"
        audio_format  : "mp3" | "m4a" | "flac" | "opus"
        output_dir    : absolute path string
        is_audio      : bool
        """
        fmt      = self._fmt_combo.currentText()
        is_audio = fmt == "mp3"
        return {
            "format":        fmt,
            "is_audio":      is_audio,
            "quality_label": self._quality_combo.currentText(),
            "audio_format":  self._codec_combo.currentText(),
            "output_dir":    self._dir_entry.text().strip(),
        }

    def apply_config(self, cfg: AppConfig) -> None:
        """Sync all controls from a (possibly freshly saved) AppConfig."""
        self._dir_entry.setText(cfg.output_dir)

        fmt_idx = self._fmt_combo.findText(cfg.media_format)
        if fmt_idx >= 0:
            self._fmt_combo.setCurrentIndex(fmt_idx)

        self._update_quality_options(cfg.media_format)

        if cfg.media_format == "mp3":
            q_idx = self._quality_combo.findText(cfg.audio_quality)
        else:
            q_idx = self._quality_combo.findText(cfg.video_quality)
        if q_idx >= 0:
            self._quality_combo.setCurrentIndex(q_idx)

        codec_idx = self._codec_combo.findText(cfg.audio_format)
        if codec_idx >= 0:
            self._codec_combo.setCurrentIndex(codec_idx)

        self._clip_switch.setChecked(cfg.clipboard_monitor)

    def set_directory(self, path: str) -> None:
        self._dir_entry.setText(path)
        self.options_changed.emit()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.setFixedHeight(52)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            f"background: {_BG}; border-top: 1px solid {_BORDER};"
            f" border-bottom: 1px solid {_BORDER};"
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 6, 12, 6)
        row.setSpacing(6)

        lbl_style = (
            f"color: {_TEXT_2}; font-size: 11px; background: transparent;"
        )
        combo_style = f"""
            ComboBox {{
                background: #0e0e0f;
                border: 1px solid {_BORDER};
                border-radius: 5px;
                color: {_TEXT};
                font-size: 12px;
                padding: 0 6px;
                min-height: 30px;
            }}
            ComboBox:hover {{ border-color: {ACCENT_COLOR}; }}
        """

        # ── Format ────────────────────────────────────────────────────────────
        row.addWidget(self._lbl("Format:", lbl_style))
        self._fmt_combo = ComboBox()
        self._fmt_combo.addItems(["mp3", "mp4"])
        self._fmt_combo.setFixedWidth(74)
        self._fmt_combo.setStyleSheet(combo_style)
        self._fmt_combo.currentTextChanged.connect(self._on_format_change)
        row.addWidget(self._fmt_combo)

        row.addWidget(self._sep())

        # ── Quality ───────────────────────────────────────────────────────────
        row.addWidget(self._lbl("Quality:", lbl_style))
        self._quality_combo = ComboBox()
        self._quality_combo.addItems(AUDIO_QUALITY_OPTIONS)
        self._quality_combo.setFixedWidth(140)
        self._quality_combo.setStyleSheet(combo_style)
        self._quality_combo.currentTextChanged.connect(
            lambda _: self.options_changed.emit()
        )
        row.addWidget(self._quality_combo)

        row.addWidget(self._sep())

        # ── Codec ─────────────────────────────────────────────────────────────
        row.addWidget(self._lbl("Codec:", lbl_style))
        self._codec_combo = ComboBox()
        self._codec_combo.addItems(AUDIO_FORMAT_OPTIONS)
        self._codec_combo.setFixedWidth(78)
        self._codec_combo.setStyleSheet(combo_style)
        self._codec_combo.currentTextChanged.connect(
            lambda _: self.options_changed.emit()
        )
        row.addWidget(self._codec_combo)

        row.addWidget(self._sep())

        # ── Output directory ──────────────────────────────────────────────────
        row.addWidget(self._lbl("Save to:", lbl_style))
        self._dir_entry = LineEdit()
        self._dir_entry.setMinimumWidth(200)
        self._dir_entry.setFixedHeight(30)
        self._dir_entry.setStyleSheet(f"""
            LineEdit {{
                background: #0e0e0f;
                border: 1px solid {_BORDER};
                border-radius: 5px;
                color: {_TEXT};
                font-size: 12px;
            }}
            LineEdit:focus {{ border-color: {ACCENT_COLOR}; }}
        """)
        self._dir_entry.textChanged.connect(lambda _: self.options_changed.emit())
        row.addWidget(self._dir_entry, stretch=1)

        browse_btn = ToolButton()
        browse_btn.setText("📁")
        browse_btn.setFixedSize(30, 30)
        browse_btn.setStyleSheet(f"""
            ToolButton {{
                background: #0e0e0f;
                border: 1px solid {_BORDER};
                border-radius: 5px;
                font-size: 14px;
                color: {_TEXT};
            }}
            ToolButton:hover {{ border-color: {ACCENT_COLOR}; }}
        """)
        browse_btn.clicked.connect(self._on_browse)
        row.addWidget(browse_btn)

        row.addWidget(self._sep())

        # ── Clipboard monitor toggle ──────────────────────────────────────────
        row.addWidget(self._lbl("Clipboard:", lbl_style))
        self._clip_switch = SwitchButton()
        self._clip_switch.setOnText("ON")
        self._clip_switch.setOffText("OFF")
        self._clip_switch.setFixedHeight(30)
        self._clip_switch.checkedChanged.connect(self._on_clip_toggle)
        row.addWidget(self._clip_switch)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _lbl(text: str, style: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(style)
        return l

    @staticmethod
    def _sep() -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.VLine)
        f.setFixedWidth(1)
        f.setStyleSheet(f"background: {_BORDER}; border: none;")
        return f

    def _update_quality_options(self, fmt: str) -> None:
        self._quality_combo.blockSignals(True)
        self._quality_combo.clear()
        if fmt == "mp3":
            self._quality_combo.addItems(AUDIO_QUALITY_OPTIONS)
            self._codec_combo.setEnabled(True)
        else:
            self._quality_combo.addItems(VIDEO_QUALITY_OPTIONS)
            self._codec_combo.setEnabled(False)
        self._quality_combo.blockSignals(False)

    def _on_format_change(self, fmt: str) -> None:
        self._update_quality_options(fmt)
        self.options_changed.emit()

    def _on_browse(self) -> None:
        current = self._dir_entry.text().strip() or str(Path.home())
        path = QFileDialog.getExistingDirectory(
            self, "Choose download folder", current,
        )
        if path:
            self._dir_entry.setText(path)
            self._config.output_dir = path
            self._config.save()
            self.options_changed.emit()

    def _on_clip_toggle(self, checked: bool) -> None:
        self._config.clipboard_monitor = checked
        self._config.save()
        self.options_changed.emit()
