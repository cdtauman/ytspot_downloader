"""
ui/panels/converter_panel.py  –  Local File Format Converter
=============================================================
A completely separate panel (registered as its own navigation tab)
for converting local audio files between formats via FFmpeg/mutagen.

This panel has ZERO overlap with the online downloader UI.  It deals
only with files already present on the user's disk.

Features
--------
* Drag-and-drop or file-browser input (supports multi-file selection)
* Output format selection: MP3 / M4A / FLAC / OPUS / WAV
* Bitrate selection for lossy formats
* Batch conversion with per-file progress bars
* Output folder: same as input (default) or user-specified
* Conversion runs on a QThread (ConvertWorker) so the UI stays responsive

Signals emitted upward
----------------------
None – the panel is self-contained.  Errors are shown inline.
"""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel,
    QProgressBar, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, ComboBox, FluentIcon,
    PushButton, SegmentedWidget, SwitchButton, ToolButton,
)

from ui.theme_manager import (
    ACCENT_COLOR, BG_DARK, SURFACE_DARK, SURFACE2_DARK,
    BORDER_DARK, TEXT_DARK, TEXT2_DARK, TEXT3_DARK,
    SUCCESS_COLOR, ERROR_COLOR,
)


# ── Design tokens ──────────────────────────────────────────────────────────────
_BG       = BG_DARK
_SURFACE  = SURFACE_DARK
_SURFACE2 = SURFACE2_DARK
_BORDER   = BORDER_DARK
_TEXT     = TEXT_DARK
_TEXT_2   = TEXT2_DARK
_TEXT_3   = TEXT3_DARK

_OUTPUT_FORMATS = ["mp3", "m4a", "flac", "opus", "wav"]
_BITRATES       = ["320k", "256k", "192k", "128k", "96k"]
_INPUT_EXTS     = {".mp3", ".m4a", ".flac", ".opus", ".wav", ".ogg", ".aac",
                   ".wma", ".alac", ".aiff", ".mp4", ".webm", ".mkv"}


# ──────────────────────────────────────────────────────────────────────────────
# ConvertWorker
# ──────────────────────────────────────────────────────────────────────────────

class ConvertWorker(QThread):
    """
    Background thread that converts a list of audio files using FFmpeg.

    Signals
    -------
    file_started(str)          – absolute path of the file being converted
    file_done(str, str)        – (input_path, output_path) on success
    file_error(str, str)       – (input_path, error_message) on failure
    all_done()
    """

    file_started = Signal(str)
    file_done    = Signal(str, str)
    file_error   = Signal(str, str)
    all_done     = Signal()

    def __init__(
        self,
        files:        list[str],
        out_format:   str,
        bitrate:      str,
        out_dir:      Optional[str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._files      = files
        self._out_format = out_format
        self._bitrate    = bitrate
        self._out_dir    = out_dir
        self._cancel     = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        for file_path in self._files:
            if self._cancel.is_set():
                break
            self.file_started.emit(file_path)
            try:
                out_path = self._convert_one(file_path)
                self.file_done.emit(file_path, out_path)
            except Exception as exc:
                self.file_error.emit(file_path, str(exc))
        self.all_done.emit()

    def _convert_one(self, input_path: str) -> str:
        src = Path(input_path)
        if self._out_dir:
            dest_dir = Path(self._out_dir)
        else:
            dest_dir = src.parent
        dest_dir.mkdir(parents=True, exist_ok=True)

        dest = dest_dir / f"{src.stem}.{self._out_format}"
        # Avoid overwriting source if same format and same folder
        if dest.resolve() == src.resolve():
            dest = dest_dir / f"{src.stem}_converted.{self._out_format}"

        cmd = ["ffmpeg", "-y", "-i", str(src)]

        if self._out_format in ("mp3", "m4a", "opus"):
            cmd += ["-b:a", self._bitrate]

        if self._out_format == "mp3":
            cmd += ["-codec:a", "libmp3lame"]
        elif self._out_format == "m4a":
            cmd += ["-codec:a", "aac", "-movflags", "+faststart"]
        elif self._out_format == "flac":
            cmd += ["-codec:a", "flac", "-compression_level", "8"]
        elif self._out_format == "opus":
            cmd += ["-codec:a", "libopus"]
        elif self._out_format == "wav":
            cmd += ["-codec:a", "pcm_s16le"]

        cmd.append(str(dest))

        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=600,
        )
        if result.returncode != 0:
            raise RuntimeError(
                result.stderr.decode(errors="replace")[-300:] or "FFmpeg error"
            )
        return str(dest)


# ──────────────────────────────────────────────────────────────────────────────
# _FileRow  –  one row in the file list
# ──────────────────────────────────────────────────────────────────────────────

class _FileRow(QFrame):
    remove_requested = Signal(str)

    def __init__(self, file_path: str, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.file_path = file_path
        self._build()

    def _build(self) -> None:
        self.setFixedHeight(52)
        self.setStyleSheet(f"""
            QFrame {{
                background: {_SURFACE};
                border: 1px solid {_BORDER};
                border-radius: 8px;
            }}
        """)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 6, 8, 6)
        row.setSpacing(10)

        # File icon
        icon_lbl = QLabel("🎵")
        icon_lbl.setStyleSheet("background: transparent; font-size: 18px;")
        icon_lbl.setFixedWidth(24)
        row.addWidget(icon_lbl)

        # Name + path
        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        p = Path(self.file_path)
        name_lbl = BodyLabel(p.name[:60])
        name_lbl.setStyleSheet(f"color: {_TEXT}; background: transparent; font-size: 12px;")
        dir_lbl  = CaptionLabel(str(p.parent)[:70])
        dir_lbl.setStyleSheet(f"color: {_TEXT_3}; background: transparent;")
        text_col.addWidget(name_lbl)
        text_col.addWidget(dir_lbl)
        row.addLayout(text_col, stretch=1)

        # Progress bar (hidden until conversion starts)
        self._bar = QProgressBar()
        self._bar.setRange(0, 0)   # indeterminate
        self._bar.setFixedSize(80, 6)
        self._bar.setTextVisible(False)
        self._bar.setVisible(False)
        self._bar.setStyleSheet(f"""
            QProgressBar {{
                background: {_BORDER};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background: {ACCENT_COLOR};
                border-radius: 3px;
            }}
        """)
        row.addWidget(self._bar)

        # Status label
        self._status_lbl = QLabel("")
        self._status_lbl.setFixedWidth(60)
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setStyleSheet("background: transparent; font-size: 11px;")
        row.addWidget(self._status_lbl)

        # Remove button
        rm_btn = ToolButton()
        rm_btn.setText("✕")
        rm_btn.setFixedSize(24, 24)
        rm_btn.setStyleSheet(f"""
            ToolButton {{
                color: {_TEXT_3}; background: transparent; border: none;
                font-size: 11px;
            }}
            ToolButton:hover {{ color: {ERROR_COLOR}; }}
        """)
        rm_btn.clicked.connect(lambda: self.remove_requested.emit(self.file_path))
        row.addWidget(rm_btn)

    def set_converting(self) -> None:
        self._bar.setVisible(True)
        self._status_lbl.setText("⏳")
        self._status_lbl.setStyleSheet(f"color: {ACCENT_COLOR}; background: transparent; font-size: 11px;")

    def set_done(self) -> None:
        self._bar.setVisible(False)
        self._status_lbl.setText("✅")
        self._status_lbl.setStyleSheet(f"color: {SUCCESS_COLOR}; background: transparent; font-size: 11px;")

    def set_error(self, msg: str) -> None:
        self._bar.setVisible(False)
        self._status_lbl.setText("❌")
        self._status_lbl.setStyleSheet(f"color: {ERROR_COLOR}; background: transparent; font-size: 11px;")
        self._status_lbl.setToolTip(msg)


# ──────────────────────────────────────────────────────────────────────────────
# ConverterPanel
# ──────────────────────────────────────────────────────────────────────────────

class ConverterPanel(QWidget):
    """
    Standalone local-file audio converter panel.

    Registered as a top-level navigation item in AppWindow, completely
    separate from the downloader workflow.
    """

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._files:    dict[str, _FileRow] = {}   # path → row widget
        self._worker:   Optional[ConvertWorker] = None
        self._out_dir:  Optional[str] = None
        self._build()
        self.setAcceptDrops(True)

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.setObjectName("converterPage")
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # Header
        header_lbl = QLabel("🔄  Local File Converter")
        header_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 20px; font-weight: 700; background: transparent;"
        )
        root.addWidget(header_lbl)

        sub_lbl = QLabel(
            "Convert audio files already on your disk to a different format. "
            "Drag files here or use the Add button — no internet connection needed."
        )
        sub_lbl.setWordWrap(True)
        sub_lbl.setStyleSheet(f"color: {_TEXT_2}; font-size: 12px; background: transparent;")
        root.addWidget(sub_lbl)

        # Drop zone / file list
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setMinimumHeight(200)
        self._scroll.setStyleSheet(f"""
            QScrollArea {{ background: {_BG}; border: 2px dashed {_BORDER};
                border-radius: 12px; }}
        """)

        self._list_widget = QWidget()
        self._list_widget.setStyleSheet(f"background: {_BG};")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(10, 10, 10, 10)
        self._list_layout.setSpacing(6)
        self._list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._drop_hint = QLabel("⬆  Drop audio files here or click Add Files")
        self._drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drop_hint.setStyleSheet(
            f"color: {_TEXT_3}; font-size: 14px; background: transparent;"
        )
        self._list_layout.addWidget(self._drop_hint)

        self._scroll.setWidget(self._list_widget)
        root.addWidget(self._scroll, stretch=1)

        # Controls row
        controls = QFrame()
        controls.setStyleSheet(f"""
            QFrame {{
                background: {_SURFACE};
                border: 1px solid {_BORDER};
                border-radius: 10px;
            }}
        """)
        ctrl_row = QHBoxLayout(controls)
        ctrl_row.setContentsMargins(16, 10, 16, 10)
        ctrl_row.setSpacing(12)

        # Add files button
        add_btn = PushButton(FluentIcon.ADD, "Add Files")
        add_btn.clicked.connect(self._on_add_files)
        ctrl_row.addWidget(add_btn)

        # Clear button
        clear_btn = PushButton(FluentIcon.DELETE, "Clear All")
        clear_btn.clicked.connect(self._on_clear)
        ctrl_row.addWidget(clear_btn)

        ctrl_row.addStretch()

        # Format selector
        fmt_lbl = QLabel("Output Format:")
        fmt_lbl.setStyleSheet(f"color: {_TEXT_2}; background: transparent;")
        ctrl_row.addWidget(fmt_lbl)

        self._fmt_combo = ComboBox()
        for fmt in _OUTPUT_FORMATS:
            self._fmt_combo.addItem(fmt.upper(), userData=fmt)
        self._fmt_combo.setCurrentIndex(0)
        self._fmt_combo.setFixedWidth(100)
        ctrl_row.addWidget(self._fmt_combo)

        # Bitrate selector
        br_lbl = QLabel("Bitrate:")
        br_lbl.setStyleSheet(f"color: {_TEXT_2}; background: transparent;")
        ctrl_row.addWidget(br_lbl)

        self._br_combo = ComboBox()
        for br in _BITRATES:
            self._br_combo.addItem(br)
        self._br_combo.setCurrentIndex(0)
        self._br_combo.setFixedWidth(90)
        ctrl_row.addWidget(self._br_combo)

        ctrl_row.addSpacing(12)

        # Output folder toggle
        same_dir_lbl = QLabel("Same folder as source")
        same_dir_lbl.setStyleSheet(f"color: {_TEXT_2}; background: transparent;")
        ctrl_row.addWidget(same_dir_lbl)

        self._same_dir_sw = SwitchButton()
        self._same_dir_sw.setChecked(True)
        self._same_dir_sw.checkedChanged.connect(self._on_same_dir_toggle)
        ctrl_row.addWidget(self._same_dir_sw)

        self._out_dir_btn = PushButton(FluentIcon.FOLDER, "Output Folder")
        self._out_dir_btn.setVisible(False)
        self._out_dir_btn.clicked.connect(self._on_browse_out)
        ctrl_row.addWidget(self._out_dir_btn)

        root.addWidget(controls)

        # Convert button
        self._convert_btn = PushButton(FluentIcon.PLAY, "Convert All")
        self._convert_btn.setFixedHeight(42)
        self._convert_btn.clicked.connect(self._on_convert)
        self._convert_btn.setStyleSheet(f"""
            PushButton {{
                background: {ACCENT_COLOR};
                color: #000;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 700;
            }}
            PushButton:hover {{ background: #c47d0e; }}
            PushButton:disabled {{ background: {_BORDER}; color: {_TEXT_3}; }}
        """)
        root.addWidget(self._convert_btn)

    # ── Drag & Drop ────────────────────────────────────────────────────────────

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and Path(path).suffix.lower() in _INPUT_EXTS:
                self._add_file(path)
        event.acceptProposedAction()

    # ── Handlers ───────────────────────────────────────────────────────────────

    def _on_add_files(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(_INPUT_EXTS))
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Audio Files", "", f"Audio Files ({exts});;All Files (*)"
        )
        for p in paths:
            self._add_file(p)

    def _on_clear(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
        for row in list(self._files.values()):
            self._list_layout.removeWidget(row)
            row.deleteLater()
        self._files.clear()
        self._drop_hint.setVisible(True)

    def _on_same_dir_toggle(self, checked: bool) -> None:
        self._out_dir_btn.setVisible(not checked)
        if checked:
            self._out_dir = None

    def _on_browse_out(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if path:
            self._out_dir = path
            self._out_dir_btn.setText(Path(path).name[:30])

    def _on_convert(self) -> None:
        if not self._files:
            return
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            return

        fmt     = self._fmt_combo.currentData() or "mp3"
        bitrate = self._br_combo.currentText() or "320k"
        files   = list(self._files.keys())

        out_dir = None if self._same_dir_sw.isChecked() else self._out_dir

        self._worker = ConvertWorker(files, fmt, bitrate, out_dir, parent=self)
        self._worker.file_started.connect(self._on_file_started)
        self._worker.file_done.connect(self._on_file_done)
        self._worker.file_error.connect(self._on_file_error)
        self._worker.all_done.connect(self._on_all_done)
        self._convert_btn.setText("⏹  Cancel")
        self._worker.start()

    def _on_file_started(self, path: str) -> None:
        if path in self._files:
            self._files[path].set_converting()

    def _on_file_done(self, in_path: str, _out_path: str) -> None:
        if in_path in self._files:
            self._files[in_path].set_done()

    def _on_file_error(self, in_path: str, msg: str) -> None:
        if in_path in self._files:
            self._files[in_path].set_error(msg)

    def _on_all_done(self) -> None:
        self._convert_btn.setText("Convert All")

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _add_file(self, path: str) -> None:
        if path in self._files:
            return
        row = _FileRow(path, parent=self._list_widget)
        row.remove_requested.connect(self._remove_file)
        self._files[path] = row
        self._list_layout.addWidget(row)
        self._drop_hint.setVisible(False)

    def _remove_file(self, path: str) -> None:
        row = self._files.pop(path, None)
        if row:
            self._list_layout.removeWidget(row)
            row.deleteLater()
        if not self._files:
            self._drop_hint.setVisible(True)
