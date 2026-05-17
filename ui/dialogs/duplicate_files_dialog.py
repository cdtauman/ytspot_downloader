"""
ui/dialogs/duplicate_files_dialog.py  –  Duplicate-file conflict resolution dialog
====================================================================================
Presents every duplicate group as a two-column card grid (Windows Explorer style).

Layout per group
----------------
  right col (col 0, index 0, 2, 4…)   |   left col (col 1, index 1, 3, 5…)
  ──────────────────────────────────────────────────────────────────────────
  [ ☑  file_A.mp3 ]                   |   [ ☑  file_B.mp3 ]
    Albums\\Artist\\file_A.mp3             Albums\\ArtistCopy\\file_B.mp3
    4.2 MB  |  12/05/2025 14:30            4.2 MB  |  10/03/2025 09:15
  ──────────────────────────────────────────────────────────────────────────
  [ ☑  file_C.mp3 ]                   |   (empty if group has odd count)
    ...

Bulk toolbar (top)
------------------
  ✅ שניהם         → check ALL files across all groups
  ➡ עמודה ימנית   → keep only even-index files (right column) per group
  ⬅ עמודה שמאלית  → keep only odd-index  files (left  column) per group

Paths displayed
---------------
  Relative to the root_folder passed in (mirrors what the Tag Editor loaded).
  Fallback to absolute path if the file is outside the root.

Usage
-----
    dlg = DuplicateFilesDialog(groups, elapsed, strategy, root_folder, parent=self)
    if dlg.exec() == QDialog.Accepted:
        paths = dlg.files_to_delete   # list[Path]
"""

from __future__ import annotations

import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.theme_manager import ACCENT_COLOR, get_colors


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fmt_size(n_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n_bytes < 1024:
            return f"{n_bytes:.1f} {unit}"
        n_bytes /= 1024  # type: ignore[assignment]
    return f"{n_bytes:.1f} TB"


def _fmt_date(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")


def _rel_path(path: Path, root: Path | None) -> str:
    if root is None:
        return str(path)
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


# ── Dialog ─────────────────────────────────────────────────────────────────────

class DuplicateFilesDialog(QDialog):
    """
    Two-column card-grid conflict dialog for duplicate audio files.

    Parameters
    ----------
    groups      : {key: [Path, …], …}  — output from DuplicateDetectorWorker
    elapsed     : scan duration in seconds
    strategy    : "md5" or "size"
    root_folder : the Tag Editor's currently loaded root (for relative paths)
    """

    def __init__(
        self,
        groups:      dict,
        elapsed:     float,
        strategy:    str = "md5",
        root_folder: Path | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._groups   = groups
        self._elapsed  = elapsed
        self._strategy = strategy
        self._root     = root_folder
        self._files_to_delete: list[Path] = []

        # _group_cbs[group_idx] = [QCheckBox for file_0, file_1, …]
        self._group_cbs: list[list[QCheckBox]] = []

        self.setWindowTitle("🔍 ניהול קבצים כפולים")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumSize(880, 560)
        self.resize(1040, 720)
        self.setModal(True)

        self._build()
        self._apply_theme()

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def files_to_delete(self) -> list[Path]:
        """Paths whose checkboxes were UNCHECKED when the user confirmed."""
        return self._files_to_delete

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        c = get_colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(10)

        layout.addWidget(self._make_header(c))
        layout.addWidget(self._make_hint(c))
        layout.addLayout(self._make_bulk_toolbar())
        layout.addWidget(self._make_scroll_area(), stretch=1)
        layout.addLayout(self._make_footer())

    # ── Section builders ───────────────────────────────────────────────────────

    def _make_header(self, c) -> QLabel:
        n_groups = len(self._groups)
        n_files  = sum(len(v) for v in self._groups.values())
        strat = "לפי גודל קובץ (מהיר)" if self._strategy == "size" else "לפי תוכן MD5 (מדויק)"
        lbl = QLabel(
            f"נמצאו <b>{n_files}</b> קבצים כפולים ב-<b>{n_groups}</b> קבוצות  "
            f"(אסטרטגיה: {strat})  |  זמן סריקה: {self._elapsed:.1f}s"
        )
        lbl.setStyleSheet(
            f"font-size: 14px; color: {c.text_primary}; padding: 4px 0; border: none;"
        )
        return lbl

    def _make_hint(self, c) -> QLabel:
        lbl = QLabel("☑ מסומן = שמור קובץ    ☐ לא מסומן = מחק קובץ")
        lbl.setStyleSheet(
            f"font-size: 12px; color: {c.text_secondary}; border: none; padding-bottom: 2px;"
        )
        return lbl

    def _make_bulk_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self._both_btn = QPushButton("✅ שמור את כולם")
        self._both_btn.setFixedHeight(30)
        self._both_btn.setToolTip("סמן את כל הקבצים בכל הקבוצות לשמירה")
        self._both_btn.clicked.connect(self._on_keep_both)
        row.addWidget(self._both_btn)

        row.addStretch()
        return row

    def _make_scroll_area(self) -> QScrollArea:
        c = get_colors()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        content.setLayoutDirection(Qt.RightToLeft)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(20)

        hdr_font = QFont()
        hdr_font.setBold(True)
        hdr_font.setPointSize(10)

        for group_idx, (_key, paths) in enumerate(self._groups.items(), start=1):
            # ── Group header ─────────────────────────────────────────────────
            grp_lbl = QLabel(f"קבוצה {group_idx}  —  {len(paths)} קבצים כפולים")
            grp_lbl.setFont(hdr_font)
            grp_lbl.setStyleSheet(
                f"color: {c.accent}; padding: 4px 0 2px 0;"
                f"border: none; border-bottom: 1px solid {c.border};"
            )
            content_layout.addWidget(grp_lbl)

            # ── 2-column card grid ───────────────────────────────────────────
            grid_widget = QWidget()
            grid_widget.setLayoutDirection(Qt.RightToLeft)
            grid = QGridLayout(grid_widget)
            grid.setSpacing(10)
            grid.setContentsMargins(0, 4, 0, 0)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)

            group_cbs: list[QCheckBox] = []
            for file_idx, path in enumerate(paths):
                row_num = file_idx // 2
                col_num = file_idx % 2
                card, cb = self._make_file_card(path, c)
                grid.addWidget(card, row_num, col_num)
                group_cbs.append(cb)

            self._group_cbs.append(group_cbs)
            content_layout.addWidget(grid_widget)

        content_layout.addStretch()
        scroll.setWidget(content)
        return scroll

    def _make_file_card(self, path: Path, c) -> tuple[QFrame, QCheckBox]:
        card = QFrame()
        card.setObjectName("fileCard")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        card.setLayoutDirection(Qt.RightToLeft)

        vbox = QVBoxLayout(card)
        vbox.setContentsMargins(12, 10, 12, 10)
        vbox.setSpacing(5)

        # Row 1: checkbox + filename (bold)
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        cb = QCheckBox()
        cb.setChecked(True)  # Checked = KEEP
        cb.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        top_row.addWidget(cb)

        name_font = QFont()
        name_font.setBold(True)
        name_lbl = QLabel(path.name)
        name_lbl.setFont(name_font)
        name_lbl.setStyleSheet(f"color: {c.text_primary}; border: none;")
        name_lbl.setWordWrap(True)
        top_row.addWidget(name_lbl, stretch=1)
        vbox.addLayout(top_row)

        # Row 2: relative path (shown like Windows Explorer, relative to root)
        rel = _rel_path(path, self._root)
        path_lbl = QLabel(rel)
        path_lbl.setStyleSheet(
            f"color: {c.text_secondary}; font-size: 11px; border: none;"
        )
        path_lbl.setWordWrap(True)
        path_lbl.setToolTip(str(path))  # full absolute path in tooltip
        vbox.addWidget(path_lbl)

        # Row 3: size + modification date
        try:
            st       = path.stat()
            meta_str = f"{_fmt_size(st.st_size)}   |   {_fmt_date(st.st_mtime)}"
        except OSError:
            meta_str = "—"
        meta_lbl = QLabel(meta_str)
        meta_lbl.setStyleSheet(
            f"color: {c.text_tertiary}; font-size: 11px; border: none;"
        )
        vbox.addWidget(meta_lbl)

        return card, cb

    def _make_footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch()

        self._cancel_btn = QPushButton("ביטול")
        self._cancel_btn.setFixedHeight(36)
        self._cancel_btn.setMinimumWidth(90)
        self._cancel_btn.setObjectName("cancelBtn")
        self._cancel_btn.clicked.connect(self.reject)
        row.addWidget(self._cancel_btn)

        self._apply_btn = QPushButton("🗑 בצע מחיקה וניקוי")
        self._apply_btn.setFixedHeight(36)
        self._apply_btn.setMinimumWidth(170)
        self._apply_btn.clicked.connect(self._on_apply)
        row.addWidget(self._apply_btn)

        return row

    # ── Bulk column operations ─────────────────────────────────────────────────

    def _on_keep_both(self) -> None:
        """Check all checkboxes across every group."""
        for group_cbs in self._group_cbs:
            for cb in group_cbs:
                cb.setChecked(True)

    # ── Apply & confirm ────────────────────────────────────────────────────────

    def _on_apply(self) -> None:
        to_delete = self._collect_unchecked()
        if not to_delete:
            QMessageBox.information(
                self, "אין מה למחוק",
                "כל הקבצים מסומנים לשמירה.\nבטל סימון של הקבצים שברצונך למחוק.",
            )
            return

        confirm = QMessageBox(self)
        confirm.setWindowTitle("אישור מחיקה סופי")
        confirm.setIcon(QMessageBox.Warning)
        confirm.setLayoutDirection(Qt.RightToLeft)
        confirm.setText(
            f"אזהרה: פעולה זו תמחק לצמיתות את {len(to_delete)} הקבצים "
            f"המסומנים מהדיסק.\n\nהאם אתה בטוח?"
        )
        confirm.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        confirm.setDefaultButton(QMessageBox.No)
        confirm.button(QMessageBox.Yes).setText("כן, מחק")
        confirm.button(QMessageBox.No).setText("לא, חזור")

        if confirm.exec() == QMessageBox.Yes:
            self._files_to_delete = to_delete
            self.accept()

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _collect_unchecked(self) -> list[Path]:
        result: list[Path] = []
        for group_idx, (_key, paths) in enumerate(self._groups.items()):
            cbs = self._group_cbs[group_idx] if group_idx < len(self._group_cbs) else []
            for file_idx, path in enumerate(paths):
                if file_idx < len(cbs) and not cbs[file_idx].isChecked():
                    result.append(path)
        return result

    # ── Theming ────────────────────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        c = get_colors()
        self.setStyleSheet(
            f"QDialog {{ background: {c.bg}; }}"
            f"QScrollArea {{"
            f"  background: {c.bg}; border: 1px solid {c.border}; border-radius: 6px;"
            f"}}"
            f"QScrollArea > QWidget > QWidget {{ background: {c.bg}; border: none; }}"
            f"QWidget {{ background: transparent; border: none; }}"
            f"QFrame#fileCard {{"
            f"  background: {c.surface};"
            f"  border: 1px solid {c.border};"
            f"  border-radius: 8px;"
            f"}}"
            f"QFrame#fileCard:hover {{"
            f"  border: 1px solid {c.accent};"
            f"}}"
            f"QPushButton {{"
            f"  background: {ACCENT_COLOR}; color: #000; font-weight: bold;"
            f"  border: none; border-radius: 6px; padding: 0 14px;"
            f"}}"
            f"QPushButton:hover {{ background: #e09400; }}"
            f"QPushButton:disabled {{"
            f"  background: {c.surface2}; color: {c.text_tertiary};"
            f"}}"
            f"QPushButton#cancelBtn {{"
            f"  background: {c.surface2}; color: {c.text_primary};"
            f"  border: 1px solid {c.border};"
            f"}}"
            f"QPushButton#cancelBtn:hover {{ background: {c.border}; }}"
            f"QCheckBox {{ background: transparent; border: none; spacing: 0px; }}"
        )
