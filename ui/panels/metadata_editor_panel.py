"""
ui/panels/metadata_editor_panel.py  –  Tag Editor Tab
======================================================
Visual structure:
  Top toolbar  — folder picker, scan, auto-arrange, apply, revert, summary
  QSplitter:
    Left:   QTreeWidget — folder hierarchy
    Centre: QTableView  — before/after preview (MetadataTableModel)
    Right:  QStackedWidget — context-aware inspector

Zero direct controller calls — all operations emitted as signals and wired
by AppWindow._connect_metadata_signals().
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QItemSelection
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.metadata_models import AudioTrackItem, ScanResult, TrackStatus
from ui.models.metadata_table_model import (
    COL_CHECK,
    COLUMN_COUNT,
    MetadataTableModel,
)
from ui.theme_manager import (
    ACCENT_COLOR,
    get_colors,
)

logger = logging.getLogger(__name__)

# Inspector page indices
_PAGE_EMPTY  = 0
_PAGE_FOLDER = 1
_PAGE_TRACKS = 2


class MetadataEditorPanel(QWidget):
    """
    Full Tag Editor tab widget.

    Signals (wired by AppWindow to MetadataController)
    ---------------------------------------------------
    scan_requested(Path, bool)       — folder, recursive
    auto_requested(list)             — all tracks in current session
    apply_requested(Path)            — backup_dir
    revert_requested(list)           — all tracks
    artist_to_scope(str, list)       — artist text, target tracks
    album_to_folder(str, Path, list) — album text, folder, all tracks
    title_from_filename(list, bool)  — tracks, strip_numbering
    track_from_filename(list)        — tracks
    clear_comments(list)             — tracks
    """

    # ── Signals ───────────────────────────────────────────────────────────────

    scan_requested       = Signal(object, bool)        # (Path, recursive)
    auto_requested       = Signal(list)                # list[AudioTrackItem]
    apply_requested      = Signal(object)              # backup_dir: Path
    revert_requested     = Signal(list)                # list[AudioTrackItem]
    artist_to_scope      = Signal(str, list)
    album_to_folder      = Signal(str, object, list)   # (album, folder, tracks)
    title_from_filename  = Signal(list, bool)
    track_from_filename  = Signal(list)
    clear_comments       = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("metadataEditorPage")

        self._model         = MetadataTableModel(self)
        self._root_folder:  Optional[Path] = None
        self._active_folder: Optional[Path] = None   # tree selection

        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_toolbar())

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #2e2e35; border: none;")
        root_layout.addWidget(sep)

        root_layout.addWidget(self._build_body(), stretch=1)

    def _build_toolbar(self) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(56)
        bar.setStyleSheet(
            f"QFrame {{ background: {get_colors().surface}; "
            f"border-bottom: 1px solid {get_colors().border}; }}"
        )

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(8)

        # Folder picker
        self._browse_btn = QPushButton("📁 בחר תיקייה")
        self._browse_btn.setFixedHeight(32)
        self._browse_btn.clicked.connect(self._on_browse)
        layout.addWidget(self._browse_btn)

        self._folder_lbl = QLabel("לא נבחרה תיקייה")
        self._folder_lbl.setStyleSheet(f"color: {get_colors().text_secondary}; font-size: 12px;")
        self._folder_lbl.setMaximumWidth(260)
        self._folder_lbl.setElideMode = lambda: None  # suppress missing method noise
        layout.addWidget(self._folder_lbl)

        # Scan button
        self._scan_btn = QPushButton("🔍 סריקה")
        self._scan_btn.setFixedHeight(32)
        self._scan_btn.clicked.connect(self._on_scan)
        layout.addWidget(self._scan_btn)

        # Include subdirs
        self._subdirs_cb = QCheckBox("כלול תתי-תיקיות")
        self._subdirs_cb.setChecked(True)
        layout.addWidget(self._subdirs_cb)

        layout.addStretch()

        # Auto-arrange (primary, prominent)
        self._auto_btn = QPushButton("🪄 סדר אוטומטי")
        self._auto_btn.setFixedHeight(34)
        self._auto_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {ACCENT_COLOR}; color: #000; font-weight: bold;"
            f"  border-radius: 6px; padding: 0 14px;"
            f"}}"
            f"QPushButton:hover {{ background: #e09400; }}"
            f"QPushButton:disabled {{ background: #555; color: #888; }}"
        )
        self._auto_btn.setEnabled(False)
        self._auto_btn.clicked.connect(self._on_auto_arrange)
        layout.addWidget(self._auto_btn)

        # Apply
        self._apply_btn = QPushButton("✅ החל שינויים")
        self._apply_btn.setFixedHeight(32)
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._on_apply)
        layout.addWidget(self._apply_btn)

        # Revert
        self._revert_btn = QPushButton("↩ בטל שינויים")
        self._revert_btn.setFixedHeight(32)
        self._revert_btn.setEnabled(False)
        self._revert_btn.clicked.connect(self._on_revert)
        layout.addWidget(self._revert_btn)

        layout.addStretch()

        # Summary
        self._summary_lbl = QLabel("לא נסרקה תיקייה")
        self._summary_lbl.setStyleSheet(f"color: {get_colors().text_secondary}; font-size: 11px;")
        layout.addWidget(self._summary_lbl)

        return bar

    def _build_body(self) -> QSplitter:
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        # ── Left: folder tree ─────────────────────────────────────────────────
        tree_frame = QFrame()
        tree_layout = QVBoxLayout(tree_frame)
        tree_layout.setContentsMargins(4, 4, 0, 4)
        tree_layout.setSpacing(4)

        tree_header = QLabel("📂 תיקיות")
        tree_header.setStyleSheet("font-weight: bold; font-size: 12px; padding: 2px 0;")
        tree_layout.addWidget(tree_header)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setAnimated(True)
        self._tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self._tree.itemClicked.connect(self._on_tree_item_clicked)
        self._tree.setStyleSheet(
            "QTreeWidget { border: none; background: transparent; }"
            "QTreeWidget::item { padding: 3px 2px; }"
            f"QTreeWidget::item:selected {{ background: {ACCENT_COLOR}33; }}"
        )
        tree_layout.addWidget(self._tree)

        splitter.addWidget(tree_frame)
        splitter.setStretchFactor(0, 0)

        # ── Centre: table ─────────────────────────────────────────────────────
        table_frame = QFrame()
        table_layout = QVBoxLayout(table_frame)
        table_layout.setContentsMargins(0, 4, 0, 4)
        table_layout.setSpacing(4)

        # Table header row (select all + label)
        tbl_head = QHBoxLayout()
        self._select_all_cb = QCheckBox("בחר הכל")
        self._select_all_cb.stateChanged.connect(self._on_select_all)
        tbl_head.addWidget(self._select_all_cb)
        tbl_head.addStretch()
        self._table_info_lbl = QLabel("")
        self._table_info_lbl.setStyleSheet(f"color: {get_colors().text_secondary}; font-size: 11px;")
        tbl_head.addWidget(self._table_info_lbl)
        table_layout.addLayout(tbl_head)

        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setWordWrap(False)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        hdr.setStretchLastSection(False)

        # Column widths
        self._table.setColumnWidth(0,  30)   # checkbox
        self._table.setColumnWidth(1, 180)   # filename
        self._table.setColumnWidth(2, 130)   # title cur
        self._table.setColumnWidth(3, 130)   # title new
        self._table.setColumnWidth(4, 110)   # artist cur
        self._table.setColumnWidth(5, 110)   # artist new
        self._table.setColumnWidth(6, 120)   # album cur
        self._table.setColumnWidth(7, 120)   # album new
        self._table.setColumnWidth(8,  55)   # track cur
        self._table.setColumnWidth(9,  55)   # track new
        self._table.setColumnWidth(10, 80)   # status

        self._table.selectionModel().selectionChanged.connect(self._on_table_selection_changed)
        self._model.dataChanged.connect(self._on_model_data_changed)

        table_layout.addWidget(self._table)
        splitter.addWidget(table_frame)
        splitter.setStretchFactor(1, 1)

        # ── Right: inspector ──────────────────────────────────────────────────
        self._inspector = QStackedWidget()
        self._inspector.setFixedWidth(290)

        self._inspector.addWidget(self._build_inspector_empty())   # 0
        self._inspector.addWidget(self._build_inspector_folder())  # 1
        self._inspector.addWidget(self._build_inspector_tracks())  # 2

        splitter.addWidget(self._inspector)
        splitter.setStretchFactor(2, 0)

        # Set initial sizes: tree=200, table=stretch, inspector=290
        splitter.setSizes([200, 600, 290])

        return splitter

    # ── Inspector pages ───────────────────────────────────────────────────────

    def _build_inspector_empty(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setAlignment(Qt.AlignCenter)

        lbl = QLabel("בחר קבצים\nאו תיקייה\nלעריכה")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f"color: {get_colors().text_tertiary}; font-size: 13px;")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)
        return w

    def _build_inspector_folder(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignTop)

        self._insp_folder_title = QLabel("תיקייה")
        self._insp_folder_title.setStyleSheet("font-weight: bold; font-size: 13px;")
        self._insp_folder_title.setWordWrap(True)
        layout.addWidget(self._insp_folder_title)

        # Artist for folder
        grp_artist = QGroupBox("החל אמן")
        grp_layout = QVBoxLayout(grp_artist)
        grp_layout.setSpacing(6)

        self._insp_folder_artist = QLineEdit()
        self._insp_folder_artist.setPlaceholderText("שם האמן…")
        grp_layout.addWidget(self._insp_folder_artist)

        btn_artist = QPushButton("החל על כל הקבצים בתיקייה")
        btn_artist.clicked.connect(self._on_insp_folder_artist)
        grp_layout.addWidget(btn_artist)

        layout.addWidget(grp_artist)

        # Album for folder
        grp_album = QGroupBox("החל אלבום")
        grp_album_layout = QVBoxLayout(grp_album)
        grp_album_layout.setSpacing(6)

        self._insp_folder_album = QLineEdit()
        self._insp_folder_album.setPlaceholderText("שם האלבום…")
        grp_album_layout.addWidget(self._insp_folder_album)

        btn_album = QPushButton("החל אלבום על כל הקבצים")
        btn_album.clicked.connect(self._on_insp_folder_album)
        grp_album_layout.addWidget(btn_album)

        layout.addWidget(grp_album)

        # Magic buttons
        grp_magic = QGroupBox("פעולות קסם")
        grp_magic_layout = QVBoxLayout(grp_magic)
        grp_magic_layout.setSpacing(6)

        btn_title = QPushButton("🪄 כותרת מהשם (הסר מספור)")
        btn_title.clicked.connect(lambda: self._emit_title_from_filename(True))
        grp_magic_layout.addWidget(btn_title)

        btn_track = QPushButton("🪄 מספר רצועה מהשם")
        btn_track.clicked.connect(lambda: self.track_from_filename.emit(self._get_folder_tracks()))
        grp_magic_layout.addWidget(btn_track)

        layout.addWidget(grp_magic)
        layout.addStretch()
        return w

    def _build_inspector_tracks(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignTop)

        self._insp_tracks_title = QLabel("0 שירים נבחרו")
        self._insp_tracks_title.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(self._insp_tracks_title)

        # Fields
        fields_grp = QGroupBox("עריכת תגיות")
        fields_layout = QVBoxLayout(fields_grp)
        fields_layout.setSpacing(6)

        def _field(label: str) -> QLineEdit:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(85)
            lbl.setStyleSheet("font-size: 11px;")
            edit = QLineEdit()
            edit.setPlaceholderText("ריק / מעורב")
            row.addWidget(lbl)
            row.addWidget(edit)
            fields_layout.addLayout(row)
            return edit

        self._insp_title        = _field("כותרת:")
        self._insp_artist       = _field("אמן:")
        self._insp_album        = _field("אלבום:")
        self._insp_album_artist = _field("אמן אלבום:")
        self._insp_track        = _field("רצועה:")

        btn_apply_fields = QPushButton("✅ החל על הבחירה")
        btn_apply_fields.setStyleSheet(
            f"QPushButton {{ background: {ACCENT_COLOR}; color: #000; "
            f"font-weight: bold; border-radius: 5px; padding: 4px 8px; }}"
            f"QPushButton:hover {{ background: #e09400; }}"
        )
        btn_apply_fields.clicked.connect(self._on_insp_apply_fields)
        fields_layout.addWidget(btn_apply_fields)

        layout.addWidget(fields_grp)

        # Magic buttons for selected
        magic_grp = QGroupBox("פעולות קסם")
        magic_layout = QVBoxLayout(magic_grp)
        magic_layout.setSpacing(6)

        btn_title_strip = QPushButton("🪄 כותרת = שם קובץ (ללא מספור)")
        btn_title_strip.clicked.connect(lambda: self._emit_title_from_filename(True, selected_only=True))
        magic_layout.addWidget(btn_title_strip)

        btn_title_full = QPushButton("🪄 כותרת = שם קובץ (כולל מספור)")
        btn_title_full.clicked.connect(lambda: self._emit_title_from_filename(False, selected_only=True))
        magic_layout.addWidget(btn_title_full)

        btn_track_num = QPushButton("🪄 מספר רצועה מהשם")
        btn_track_num.clicked.connect(lambda: self.track_from_filename.emit(self._get_selected_tracks()))
        magic_layout.addWidget(btn_track_num)

        btn_clear_comments = QPushButton("🧹 נקה הערות")
        btn_clear_comments.clicked.connect(lambda: self.clear_comments.emit(self._get_selected_tracks()))
        magic_layout.addWidget(btn_clear_comments)

        layout.addWidget(magic_grp)
        layout.addStretch()
        return w

    # ── Toolbar handlers ──────────────────────────────────────────────────────

    def _on_browse(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "בחר תיקיית מוזיקה", str(Path.home())
        )
        if path:
            self._root_folder = Path(path)
            name = self._root_folder.name or str(self._root_folder)
            display = name if len(name) <= 40 else "…" + name[-37:]
            self._folder_lbl.setText(display)
            self._folder_lbl.setToolTip(path)

    def _on_scan(self) -> None:
        if not self._root_folder:
            return
        self._model.load_tracks([])
        self._tree.clear()
        self._active_folder = None
        self._inspector.setCurrentIndex(_PAGE_EMPTY)
        self._auto_btn.setEnabled(False)
        self._apply_btn.setEnabled(False)
        self._revert_btn.setEnabled(False)
        self._summary_lbl.setText("סורק…")
        recursive = self._subdirs_cb.isChecked()
        self.scan_requested.emit(self._root_folder, recursive)

    def _on_auto_arrange(self) -> None:
        self.auto_requested.emit(self._model.get_all_tracks())

    def _on_apply(self) -> None:
        from pathlib import Path as _Path
        backup_dir = _Path.home() / ".ytspot" / "tag_backups"
        self.apply_requested.emit(backup_dir)

    def _on_revert(self) -> None:
        self.revert_requested.emit(self._model.get_all_tracks())

    # ── Tree handlers ─────────────────────────────────────────────────────────

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        folder = item.data(0, Qt.UserRole)
        self._active_folder = folder
        self._model.set_folder_filter(folder)
        self._table.selectionModel().clearSelection()

        if folder is not None:
            self._insp_folder_title.setText(f"📁 {folder.name}")
            self._insp_folder_artist.clear()
            self._insp_folder_album.setText(folder.name)
            self._inspector.setCurrentIndex(_PAGE_FOLDER)
        else:
            self._inspector.setCurrentIndex(_PAGE_EMPTY)

        self._update_table_info()

    # ── Table handlers ────────────────────────────────────────────────────────

    def _on_table_selection_changed(self, selected: QItemSelection, _desel) -> None:
        rows = self._table.selectionModel().selectedRows()
        if rows:
            tracks = []
            for idx in rows:
                vis = self._model._visible
                if idx.row() < len(vis):
                    tracks.append(self._model._tracks[vis[idx.row()]])
            self._populate_track_inspector(tracks)
            self._inspector.setCurrentIndex(_PAGE_TRACKS)
        elif self._active_folder is not None:
            self._inspector.setCurrentIndex(_PAGE_FOLDER)
        else:
            self._inspector.setCurrentIndex(_PAGE_EMPTY)

    def _on_select_all(self, state: int) -> None:
        self._model.set_all_checked(state == Qt.Checked)

    def _on_model_data_changed(self, *_) -> None:
        self._update_summary()

    # ── Inspector handlers ────────────────────────────────────────────────────

    def _on_insp_folder_artist(self) -> None:
        artist = self._insp_folder_artist.text().strip()
        if not artist:
            return
        scope = self._get_folder_tracks()
        self.artist_to_scope.emit(artist, scope)

    def _on_insp_folder_album(self) -> None:
        album = self._insp_folder_album.text().strip()
        if not album or self._active_folder is None:
            return
        self.album_to_folder.emit(album, self._active_folder, self._model.get_all_tracks())

    def _on_insp_apply_fields(self) -> None:
        tracks = self._get_selected_tracks()
        if not tracks:
            return

        title        = self._insp_title.text().strip()
        artist       = self._insp_artist.text().strip()
        album        = self._insp_album.text().strip()
        album_artist = self._insp_album_artist.text().strip()
        track_str    = self._insp_track.text().strip()

        for item in tracks:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            if title:
                item.proposed.title = title
            if artist:
                item.proposed.artist = artist
            if album:
                item.proposed.album = album
            if album_artist:
                item.proposed.album_artist = album_artist
            if track_str:
                try:
                    item.proposed.track_num = int(track_str)
                except ValueError:
                    pass

        self._model.refresh_all()
        self._update_summary()

    # ── Public slots (wired by AppWindow) ─────────────────────────────────────

    def on_track_discovered(self, item: AudioTrackItem) -> None:
        self._model.add_track(item)
        self._update_tree_for_folder(item.folder)

    def on_scan_complete(self, result: ScanResult) -> None:
        n = result.files_count
        self._auto_btn.setEnabled(n > 0)
        self._apply_btn.setEnabled(n > 0)
        self._revert_btn.setEnabled(n > 0)
        self._update_summary()

        # Expand root in tree
        if self._tree.topLevelItemCount() > 0:
            self._tree.topLevelItem(0).setExpanded(True)

    def on_auto_rules_applied(self) -> None:
        self._model.refresh_all()
        self._update_summary()

    def on_apply_progress(self, done: int, total: int) -> None:
        self._summary_lbl.setText(f"כותב תגיות… {done}/{total}")

    def on_apply_file_done(self, path_str: str, success: bool) -> None:
        path = Path(path_str)
        for item in self._model.get_all_tracks():
            if item.path == path:
                self._model.refresh_track(item)
                break

    def on_apply_complete(self, success: int, fail: int, skip: int) -> None:
        self._update_summary()
        self._model.refresh_all()

        msg = f"הושלם: {success} הצליחו"
        if fail:
            msg += f", {fail} נכשלו"
        if skip:
            msg += f", {skip} דולגו"
        self._summary_lbl.setText(msg)

        try:
            from qfluentwidgets import InfoBar, InfoBarPosition
            if fail == 0:
                InfoBar.success(
                    title="הצלחה",
                    content=msg,
                    parent=self,
                    position=InfoBarPosition.BOTTOM_RIGHT,
                    duration=4000,
                )
            else:
                InfoBar.warning(
                    title="הושלם עם שגיאות",
                    content=msg,
                    parent=self,
                    position=InfoBarPosition.BOTTOM_RIGHT,
                    duration=6000,
                )
        except Exception:
            pass

    def on_status_update(self, msg: str) -> None:
        self._summary_lbl.setText(msg)

    # ── Tree helpers ──────────────────────────────────────────────────────────

    def _update_tree_for_folder(self, folder: Path) -> None:
        """Add folder to tree if not already present."""
        if not self._root_folder:
            return

        # Ensure root item exists
        if self._tree.topLevelItemCount() == 0:
            root_item = QTreeWidgetItem([self._root_folder.name])
            root_item.setData(0, Qt.UserRole, None)  # None = show all
            root_item.setFont(0, _bold_font())
            self._tree.addTopLevelItem(root_item)

        root_item = self._tree.topLevelItem(0)

        if folder == self._root_folder:
            return

        # Check if this folder is already listed
        for i in range(root_item.childCount()):
            child = root_item.child(i)
            if child.data(0, Qt.UserRole) == folder:
                return

        child_item = QTreeWidgetItem([folder.name])
        child_item.setData(0, Qt.UserRole, folder)
        root_item.addChild(child_item)

    # ── Summary helpers ───────────────────────────────────────────────────────

    def _update_summary(self) -> None:
        tracks = self._model.get_all_tracks()
        folders = len({t.folder for t in tracks})
        changed = self._model.get_changed_count()
        warnings = self._model.get_warning_count()
        parts = [f"{len(tracks)} קבצים", f"{folders} תיקיות"]
        if changed:
            parts.append(f"{changed} שינויים מוצעים")
        if warnings:
            parts.append(f"{warnings} אזהרות")
        self._summary_lbl.setText(" | ".join(parts) if parts else "")

    def _update_table_info(self) -> None:
        vis = len(self._model.get_visible_tracks())
        total = len(self._model.get_all_tracks())
        if vis == total:
            self._table_info_lbl.setText(f"{total} קבצים")
        else:
            self._table_info_lbl.setText(f"מציג {vis} מתוך {total}")

    # ── Selection helpers ─────────────────────────────────────────────────────

    def _get_selected_tracks(self) -> list[AudioTrackItem]:
        rows = self._table.selectionModel().selectedRows()
        result = []
        vis = self._model._visible
        for idx in rows:
            r = idx.row()
            if r < len(vis):
                result.append(self._model._tracks[vis[r]])
        return result

    def _get_folder_tracks(self) -> list[AudioTrackItem]:
        return self._model.get_visible_tracks()

    def _populate_track_inspector(self, tracks: list[AudioTrackItem]) -> None:
        self._insp_tracks_title.setText(f"{len(tracks)} שיר{'ים' if len(tracks) != 1 else ''} נבחרו")

        # Show common values or clear if mixed
        def _common(vals):
            unique = set(str(v) for v in vals if v is not None)
            return list(unique)[0] if len(unique) == 1 else ""

        self._insp_title.setText(
            _common([t.proposed.title if t.proposed.title is not None else t.original.title for t in tracks])
        )
        self._insp_artist.setText(
            _common([t.proposed.artist if t.proposed.artist is not None else t.original.artist for t in tracks])
        )
        self._insp_album.setText(
            _common([t.proposed.album if t.proposed.album is not None else t.original.album for t in tracks])
        )
        self._insp_album_artist.setText(
            _common([t.proposed.album_artist if t.proposed.album_artist is not None else t.original.album_artist for t in tracks])
        )
        self._insp_track.setText(
            _common([t.proposed.track_num if t.proposed.track_num is not None else t.original.track_num for t in tracks])
        )

    # ── Signal helpers ────────────────────────────────────────────────────────

    def _emit_title_from_filename(self, strip: bool, selected_only: bool = False) -> None:
        tracks = self._get_selected_tracks() if selected_only else self._get_folder_tracks()
        self.title_from_filename.emit(tracks, strip)


def _bold_font() -> QFont:
    f = QFont()
    f.setBold(True)
    return f
