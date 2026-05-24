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
from ui.direction import force_ltr, force_ltr_input
from ui.i18n import t
from ui.theme_manager import ACCENT_COLOR, ThemeManager, get_colors


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

        tm = ThemeManager.instance()
        if tm is not None:
            tm.theme_changed.connect(self._apply_theme)

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

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 6, 12, 6)
        row.setSpacing(6)

        # ── Format ────────────────────────────────────────────────────────────
        self._lbl_format = QLabel()
        row.addWidget(self._lbl_format)
        self._fmt_combo = ComboBox()
        self._fmt_combo.addItems(["mp3", "mp4"])
        self._fmt_combo.setFixedWidth(74)
        force_ltr(self._fmt_combo)  # codec/container names are Latin
        self._fmt_combo.currentTextChanged.connect(self._on_format_change)
        row.addWidget(self._fmt_combo)

        self._sep1 = self._make_sep()
        row.addWidget(self._sep1)

        # ── Quality ───────────────────────────────────────────────────────────
        self._lbl_quality = QLabel()
        row.addWidget(self._lbl_quality)
        self._quality_combo = ComboBox()
        self._quality_combo.addItems(AUDIO_QUALITY_OPTIONS)
        self._quality_combo.setFixedWidth(140)
        force_ltr(self._quality_combo)  # bitrate strings are Latin
        self._quality_combo.currentTextChanged.connect(
            lambda _: self.options_changed.emit()
        )
        row.addWidget(self._quality_combo)

        self._sep2 = self._make_sep()
        row.addWidget(self._sep2)

        # ── Codec ─────────────────────────────────────────────────────────────
        self._lbl_codec = QLabel()
        row.addWidget(self._lbl_codec)
        self._codec_combo = ComboBox()
        self._codec_combo.addItems(AUDIO_FORMAT_OPTIONS)
        self._codec_combo.setFixedWidth(78)
        force_ltr(self._codec_combo)  # codec names are Latin
        self._codec_combo.currentTextChanged.connect(
            lambda _: self.options_changed.emit()
        )
        row.addWidget(self._codec_combo)

        self._sep3 = self._make_sep()
        row.addWidget(self._sep3)

        # ── Output directory ──────────────────────────────────────────────────
        self._lbl_save = QLabel()
        row.addWidget(self._lbl_save)
        self._dir_entry = LineEdit()
        self._dir_entry.setMinimumWidth(200)
        self._dir_entry.setFixedHeight(30)
        force_ltr_input(self._dir_entry)  # file path must read L→R
        self._dir_entry.textChanged.connect(lambda _: self.options_changed.emit())
        self._dir_entry.editingFinished.connect(self._on_dir_committed)
        row.addWidget(self._dir_entry, stretch=1)

        self._browse_btn = ToolButton()
        self._browse_btn.setText("📁")
        self._browse_btn.setFixedSize(30, 30)
        self._browse_btn.clicked.connect(self._on_browse)
        row.addWidget(self._browse_btn)

        self._sep4 = self._make_sep()
        row.addWidget(self._sep4)

        # ── Clipboard monitor toggle ──────────────────────────────────────────
        self._lbl_clip = QLabel()
        row.addWidget(self._lbl_clip)
        self._clip_switch = SwitchButton()
        self._clip_switch.setOnText("ON")
        self._clip_switch.setOffText("OFF")
        self._clip_switch.setFixedHeight(30)
        self._clip_switch.checkedChanged.connect(self._on_clip_toggle)
        row.addWidget(self._clip_switch)

        self._seps = [self._sep1, self._sep2, self._sep3, self._sep4]
        self._labels = [self._lbl_format, self._lbl_quality, self._lbl_codec,
                        self._lbl_save, self._lbl_clip]
        self._combos = [self._fmt_combo, self._quality_combo, self._codec_combo]

        self._retranslate()
        self._apply_theme()

    def _retranslate(self) -> None:
        """Set all translatable label texts. Called from ``_build`` so the
        ``_retranslate()`` naming convention is in place for a future
        live-language-switch upgrade (see ui/i18n.py LanguageManager)."""
        self._lbl_format.setText(t("options_format_label"))
        self._lbl_quality.setText(t("options_quality_label"))
        self._lbl_codec.setText(t("options_codec_label"))
        self._lbl_save.setText(t("options_save_label"))
        self._lbl_clip.setText(t("options_clipboard_label"))

    @staticmethod
    def _make_sep() -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.VLine)
        f.setFixedWidth(1)
        return f

    # ── Theme ──────────────────────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        c = get_colors()

        self.setStyleSheet(
            f"background: {c.bg}; border-top: 1px solid {c.border};"
            f" border-bottom: 1px solid {c.border};"
        )

        lbl_style = f"color: {c.text_secondary}; font-size: 11px; background: transparent;"
        for lbl in self._labels:
            lbl.setStyleSheet(lbl_style)

        combo_style = f"""
            ComboBox {{
                background: {c.surface};
                border: 1px solid {c.border};
                border-radius: 5px;
                color: {c.text_primary};
                font-size: 12px;
                padding: 0 6px;
                min-height: 30px;
            }}
            ComboBox:hover {{ border-color: {ACCENT_COLOR}; }}
        """
        for combo in self._combos:
            combo.setStyleSheet(combo_style)

        dir_style = f"""
            LineEdit {{
                background: {c.surface};
                border: 1px solid {c.border};
                border-radius: 5px;
                color: {c.text_primary};
                font-size: 12px;
            }}
            LineEdit:focus {{ border-color: {ACCENT_COLOR}; }}
        """
        self._dir_entry.setStyleSheet(dir_style)

        browse_style = f"""
            ToolButton {{
                background: {c.surface};
                border: 1px solid {c.border};
                border-radius: 5px;
                font-size: 14px;
                color: {c.text_primary};
            }}
            ToolButton:hover {{ border-color: {ACCENT_COLOR}; }}
        """
        self._browse_btn.setStyleSheet(browse_style)

        sep_style = f"background: {c.border}; border: none;"
        for sep in self._seps:
            sep.setStyleSheet(sep_style)

    # ── Helpers ───────────────────────────────────────────────────────────────

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

    def _on_dir_committed(self) -> None:
        """Persist a manually-typed output directory to config.

        The path is not validated here — DownloadController.start_batch
        runs the writability check before any download starts.
        """
        path = self._dir_entry.text().strip()
        if path and path != self._config.output_dir:
            self._config.output_dir = path
            self._config.save()

    def _on_clip_toggle(self, checked: bool) -> None:
        self._config.clipboard_monitor = checked
        self._config.save()
        self.options_changed.emit()
