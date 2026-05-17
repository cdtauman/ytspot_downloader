"""
ui/panels/metadata_editor_panel.py  –  Tag Editor Tab
======================================================
Visual structure:
  Top toolbar  — folder picker, scan, auto-arrange, apply, revert, summary
  QSplitter:
    Left:   QTreeWidget — full nested folder/file hierarchy with checkboxes
    Centre: QTableView  — before/after preview (MetadataTableModel)
    Right:  QStackedWidget — context-aware inspector

Zero direct controller calls — all operations emitted as signals and wired
by AppWindow._connect_metadata_signals().
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QFileInfo, QModelIndex, QPoint, QRect, QSize, Qt, Signal, QItemSelection, QItemSelectionModel
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFileIconProvider,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QRubberBand,
    QInputDialog,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionViewItem,
    QTableView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.metadata_models import AudioTrackItem, ScanResult, TrackStatus
from ui.models.metadata_table_model import (
    COL_CHECK, COL_FILENAME, COL_TITLE_CUR, COL_TITLE_NEW,
    COL_ARTIST_CUR, COL_ARTIST_NEW, COL_ALBUM_CUR, COL_ALBUM_NEW,
    COL_TRACK_CUR, COL_TRACK_NEW, COL_STATUS,
    COL_FILENAME_NEW, COL_GENRE_CUR, COL_GENRE_NEW,
    COL_COMMENT_CUR, COL_COMMENT_NEW,
    COLUMN_COUNT, _HEADERS, MetadataTableModel,
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

# All magic operations: (key, toolbar label, inspector label)
_MAGIC_OP_DEFS: list[tuple[str, str, str]] = [
    ("title_strip",      "העתק שם קובץ לכותרת (ללא מספר)", "לוקח את שם הקובץ הקיים ומעתיק אותו לתוך שדה 'כותרת', תוך הסרת מספרים בתחילת השם (למשל '01 שיר' יהפוך ל-'שיר')."),
    ("title_full",       "העתק שם קובץ לכותרת (כולל מספר)", "לוקח את שם הקובץ הקיים ומעתיק אותו לתוך שדה 'כותרת' בדיוק כפי שהוא."),
    ("normalize_spaces", "מחק רווחים כפולים וקווים תחתונים מהכותרת", "סורק את הכותרת, מחליף קווים תחתונים (_) ברווחים, ומוחק רווחים כפולים או מיותרים מהכותרת."),
    ("track_num",        "חלץ מספר רצועה משם הקובץ", "מחפש מספר בתחילת שם הקובץ (למשל '03') ושומר אותו בתור מספר הרצועה."),
    ("split_at",         "פצל שם קובץ ל'אמן' ו'כותרת'", "מזהה מקף (-) בשם הקובץ. מה שלפני המקף הופך ל'אמן', ומה שאחריו ל'כותרת'."),
    ("album_artist",     "העתק 'אמן' ל'אמן אלבום'", "מעתיק את שם ה'אמן' של כל שיר ושם אותו גם בשדה 'אמן אלבום' (חשוב לסידור נכון של אלבומים בנגנים)."),
    ("strip_junk",       "נקה מילים מיותרות מהכותרת", "מנקה מהכותרת תוספות שכיחות מיוטיוב כמו '(Official Video)', '[HD]', או 'Lyrics'."),
    ("clear_comments",   "מחק תוכן מתגית 'הערות'", "מוחק לחלוטין את כל מה שכתוב בשדה ההערות של השיר."),
    ("clear_track_num",  "מחק תוכן מתגית 'מספר רצועה'", "מוחק לחלוטין את מספר הרצועה של השיר."),
    ("clear_year",       "מחק תוכן מתגית 'שנה'", "מוחק את שנת ההוצאה מהתגיות."),
    ("clear_genre",      "מחק תוכן מתגית 'ז'אנר'", "מוחק את סגנון המוזיקה (ז'אנר) מהתגיות."),
    ("clean_filename",   "נקה שם קובץ פיזי", "מנקה את שם הקובץ עצמו: מסיר קווים תחתונים, מוחק כל מה שבתוך סוגריים () או [], ומסדר רווחים כפולים."),
    ("strip_filename_numbering", "הסר מספור משם הקובץ הפיזי", "מוחק משם הקובץ הפיזי מספור בתחילתו (כמו '01-', '01 -', או '01_')."),
]

# Which ops the auto-arrange button runs by default
_DEFAULT_AUTO_OPS: frozenset[str] = frozenset({
    "title_strip", "track_num", "normalize_spaces",
})


class _ExplorerFileListDelegate(QStyledItemDelegate):
    """
    Draw only the item contents.  Row backgrounds are painted by
    _ExplorerFileListView so selected rows stay one continuous strip.
    """
    _PADDING_X = 8

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        cell_rect = QRect(option.rect)

        painter.save()

        table = self.parent()
        if hasattr(table, "_should_paint_row_background") and table._should_paint_row_background(index):
            table._paint_explorer_row_background(painter, cell_rect, index.row())

        if index.column() == COL_CHECK and hasattr(table, "_explorer_palette"):
            colors = table._explorer_palette()
            painter.fillRect(cell_rect, colors["base"])
            painter.setPen(colors["separator"])
            if table.layoutDirection() == Qt.RightToLeft:
                painter.drawLine(cell_rect.left(), cell_rect.top(), cell_rect.left(), cell_rect.bottom())
            else:
                painter.drawLine(cell_rect.right(), cell_rect.top(), cell_rect.right(), cell_rect.bottom())
            painter.fillRect(cell_rect.left(), cell_rect.bottom(), cell_rect.width(), 1, colors["separator"])
            painter.restore()
            return

        if not (opt.state & QStyle.State_Selected) and opt.backgroundBrush.style() != Qt.NoBrush:
            painter.fillRect(cell_rect.adjusted(0, 1, 0, -1), opt.backgroundBrush)

        opt.state &= ~QStyle.State_Selected
        opt.state &= ~QStyle.State_HasFocus
        opt.backgroundBrush = QBrush(Qt.NoBrush)
        text_color = QColor(get_colors().text_primary)
        opt.palette.setColor(QPalette.Text, text_color)
        opt.palette.setColor(QPalette.HighlightedText, text_color)
        opt.rect = cell_rect.adjusted(self._PADDING_X, 1, -self._PADDING_X, -1)

        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
        if hasattr(table, "_explorer_palette"):
            painter.fillRect(cell_rect.left(), cell_rect.bottom(), cell_rect.width(), 1, table._explorer_palette()["separator"])
        painter.restore()


class _ExplorerFileListView(QTableView):
    """QTableView with Explorer-like empty-area deselect and rubber-band rows."""

    _SIDE_EMPTY_GUTTER = 28
    _RUBBER_STYLE = (
        "QRubberBand {"
        "  background-color: rgba(0, 120, 215, 35);"
        "  border: 1px solid rgba(0, 120, 215, 140);"
        "}"
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rubber_origin = QPoint()
        self._rubber_active = False
        self._rubber_dragging = False
        self._rubber_modifiers = Qt.NoModifier
        self._rubber_base_selection = QItemSelection()
        self._hovered_row = -1
        self._rubber_band = QRubberBand(QRubberBand.Rectangle, self.viewport())
        self._rubber_band.setStyleSheet(self._RUBBER_STYLE)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

    def drawRow(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        self._paint_explorer_row_background(painter, option.rect, index.row())
        super().drawRow(painter, option, index)
        self._paint_explorer_row_separator(painter, option.rect)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._is_empty_viewport_area(self._event_pos(event)):
            self._begin_empty_area_interaction(self._event_pos(event), event.modifiers())
            event.accept()
            return

        self._cancel_rubber_band()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._rubber_active and event.buttons() & Qt.LeftButton:
            self._update_empty_area_drag(self._event_pos(event))
            event.accept()
            return

        self._update_hover_row(self._event_pos(event))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._rubber_active:
            self._finish_empty_area_interaction(self._event_pos(event))
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        self._update_hover_row(QPoint(-1, -1))
        super().leaveEvent(event)

    @staticmethod
    def _event_pos(event) -> QPoint:
        if hasattr(event, "position"):
            return event.position().toPoint()
        return event.pos()

    def _cancel_rubber_band(self) -> None:
        self._rubber_active = False
        self._rubber_dragging = False
        self._rubber_band.hide()

    def _begin_empty_area_interaction(self, pos: QPoint, modifiers) -> None:
        self._rubber_origin = pos
        self._rubber_active = True
        self._rubber_dragging = False
        self._rubber_modifiers = modifiers
        selection_model = self.selectionModel()
        self._rubber_base_selection = (
            selection_model.selection() if selection_model is not None else QItemSelection()
        )

        self.clearSelection()
        self.setCurrentIndex(QModelIndex())

        self._rubber_band.setGeometry(QRect(self._rubber_origin, QSize()))
        self._rubber_band.hide()

    def _update_empty_area_drag(self, pos: QPoint) -> None:
        if (
            self._rubber_dragging
            or (pos - self._rubber_origin).manhattanLength() >= QApplication.startDragDistance()
        ):
            self._rubber_dragging = True
            self._scroll_for_rubber(pos)
            self._rubber_band.setGeometry(QRect(self._rubber_origin, pos).normalized())
            self._rubber_band.show()
            self._select_rows_in_rubber_band()

    def _finish_empty_area_interaction(self, pos: QPoint) -> None:
        if self._rubber_dragging:
            self._rubber_band.setGeometry(QRect(self._rubber_origin, pos).normalized())
            self._select_rows_in_rubber_band()
        self._cancel_rubber_band()

    def _explorer_palette(self) -> dict[str, QColor]:
        colors = get_colors()
        is_dark = QColor(colors.bg).lightness() < 128
        if is_dark:
            return {
                "base": QColor("#0d0d12"),
                "row_alt": QColor("#111118"),
                "hover": QColor("#172b3e"),
                "hover_border": QColor("#25577c"),
                "selected": QColor("#123d62"),
                "selected_inactive": QColor("#242a34"),
                "selected_border": QColor("#2f88c9"),
                "selected_inactive_border": QColor("#3a4658"),
                "separator": QColor("#20202b"),
            }
        return {
            "base": QColor("#ffffff"),
            "row_alt": QColor("#ffffff"),
            "hover": QColor("#e5f3ff"),
            "hover_border": QColor("#cce8ff"),
            "selected": QColor("#cce8ff"),
            "selected_inactive": QColor("#e6e6e6"),
            "selected_border": QColor("#99d1ff"),
            "selected_inactive_border": QColor("#d0d0d0"),
            "separator": QColor("#f1f1f1"),
        }

    def _content_row_rect(self, row_rect: QRect, row: int) -> QRect:
        rect = QRect(0, row_rect.top(), self.viewport().width(), row_rect.height())
        model = self.model()
        if model is not None and 0 <= row < model.rowCount() and not self.isColumnHidden(COL_CHECK):
            gutter_rect = self.visualRect(model.index(row, COL_CHECK))
            if gutter_rect.isValid():
                if self.layoutDirection() == Qt.RightToLeft:
                    rect.setRight(max(0, gutter_rect.left() - 1))
                else:
                    rect.setLeft(min(self.viewport().width(), gutter_rect.right() + 1))
        return rect

    def _empty_side_rect(self) -> QRect:
        return QRect()

    def _should_paint_row_background(self, index) -> bool:
        header = self.horizontalHeader()
        for visual in range(header.count()):
            logical = header.logicalIndex(visual)
            if self.isColumnHidden(logical):
                continue
            cell_rect = self.visualRect(index.siblingAtColumn(logical))
            if cell_rect.isValid() and cell_rect.intersects(self.viewport().rect()):
                return index.column() == logical
        return False

    def _paint_explorer_row_background(self, painter: QPainter, row_rect: QRect, row: int) -> None:
        colors = self._explorer_palette()
        selection_model = self.selectionModel()
        is_selected = bool(selection_model and selection_model.isRowSelected(row, QModelIndex()))
        fill_rect = self._content_row_rect(row_rect, row).adjusted(0, 1, 0, -1)

        painter.save()
        painter.setClipRect(QRect(0, row_rect.top(), self.viewport().width(), row_rect.height()), Qt.ReplaceClip)
        if is_selected:
            key = "selected" if self.hasFocus() else "selected_inactive"
            border_key = "selected_border" if self.hasFocus() else "selected_inactive_border"
            painter.fillRect(fill_rect, colors[key])
            painter.setPen(colors[border_key])
            painter.drawRect(fill_rect.adjusted(0, 0, -1, -1))
        elif row == self._hovered_row:
            painter.fillRect(fill_rect, colors["hover"])
            painter.setPen(colors["hover_border"])
            painter.drawRect(fill_rect.adjusted(0, 0, -1, -1))
        painter.restore()

    def _paint_explorer_row_separator(self, painter: QPainter, row_rect: QRect) -> None:
        painter.save()
        painter.setClipRect(QRect(0, row_rect.top(), self.viewport().width(), row_rect.height()), Qt.ReplaceClip)
        painter.fillRect(0, row_rect.bottom(), self.viewport().width(), 1, self._explorer_palette()["separator"])
        painter.restore()

    def _is_empty_viewport_area(self, pos: QPoint) -> bool:
        if not self.viewport().rect().contains(pos):
            return True
        idx = self.indexAt(pos)
        if idx.isValid() and idx.column() == COL_CHECK:
            return True
        if not idx.isValid():
            return True

        model = self.model()
        if model is None or model.rowCount() == 0:
            return True
        last_row = model.rowCount() - 1
        last_bottom = self.rowViewportPosition(last_row) + self.rowHeight(last_row)
        return pos.y() >= last_bottom

    def _update_hover_row(self, pos: QPoint) -> None:
        row = self.indexAt(pos).row() if self.viewport().rect().contains(pos) else -1
        if row == self._hovered_row:
            return
        old_row = self._hovered_row
        self._hovered_row = row
        for changed_row in (old_row, row):
            if changed_row >= 0:
                self.viewport().update(
                    QRect(0, self.rowViewportPosition(changed_row), self.viewport().width(), self.rowHeight(changed_row))
                )

    def _scroll_for_rubber(self, pos: QPoint) -> None:
        margin = 24
        bar = self.verticalScrollBar()
        if pos.y() < margin:
            bar.setValue(bar.value() - 1)
        elif pos.y() > self.viewport().height() - margin:
            bar.setValue(bar.value() + 1)

    def _select_rows_in_rubber_band(self) -> None:
        model = self.model()
        selection_model = self.selectionModel()
        if model is None or selection_model is None:
            return

        rubber_rect = self._rubber_band.geometry().normalized()
        rubber_selection = QItemSelection()
        last_col = model.columnCount() - 1
        if last_col < 0:
            selection_model.clearSelection()
            return

        for row in range(model.rowCount()):
            row_rect = QRect(
                0,
                self.rowViewportPosition(row),
                self.viewport().width(),
                self.rowHeight(row),
            )
            if rubber_rect.intersects(row_rect):
                rubber_selection.select(model.index(row, 0), model.index(row, last_col))

        final_selection = rubber_selection
        if self._rubber_modifiers & (Qt.ControlModifier | Qt.ShiftModifier):
            final_selection = QItemSelection()
            final_selection.merge(self._rubber_base_selection, QItemSelectionModel.Select)
            final_selection.merge(rubber_selection, QItemSelectionModel.Select)

        if final_selection.isEmpty():
            selection_model.clearSelection()
        else:
            selection_model.select(
                final_selection,
                QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
            )


class _AutoArrangeSettingsDialog(QDialog):
    """Choose which magic operations the 🪄 auto-arrange button runs."""

    def __init__(self, enabled: set[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("הגדרות סדר אוטומטי")
        self.resize(400, 480)

        self._result = set(enabled)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        hdr = QLabel("בחר אילו פעולות יבצע כפתור 'סדר אוטומטי':")
        hdr.setStyleSheet("font-weight: bold;")
        layout.addWidget(hdr)

        note = QLabel("(אלבום משם תיקייה תמיד פעיל)")
        note.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(note)
        layout.addSpacing(4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(6)

        self._cbs: dict[str, QCheckBox] = {}
        for key, label, desc in _MAGIC_OP_DEFS:
            row = QHBoxLayout()
            row.setSpacing(4)
            cb = QCheckBox(label)
            cb.setChecked(key in enabled)
            self._cbs[key] = cb
            row.addWidget(cb)
            
            info_btn = QPushButton("ℹ️")
            info_btn.setFixedSize(20, 20)
            info_btn.setStyleSheet("QPushButton { border: none; background: transparent; font-size: 14px; } QPushButton:hover { color: #88aaff; }")
            info_btn.setToolTip(desc)
            info_btn.clicked.connect(lambda _, l=label, d=desc: self._show_info(l, d))
            row.addWidget(info_btn)
            row.addStretch()
            scroll_layout.addLayout(row)

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        layout.addSpacing(8)
        row = QHBoxLayout()
        row.addStretch()
        cancel_btn = QPushButton("ביטול")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("אישור")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._accept)
        row.addWidget(cancel_btn)
        row.addWidget(ok_btn)
        layout.addLayout(row)

    def _accept(self) -> None:
        self._result = {k for k, cb in self._cbs.items() if cb.isChecked()}
        self.accept()

    def _show_info(self, title: str, desc: str) -> None:
        from qfluentwidgets import MessageBox
        msg = MessageBox(title, desc, self)
        msg.cancelButton.hide()
        msg.exec()

    @property
    def result_ops(self) -> set[str]:
        return self._result


_BTN_STYLE = (
    "QPushButton { background: #2a2d3a; color: #d0d0e0; border: 1px solid #444460;"
    "  border-radius: 4px; padding: 3px 5px; text-align: left; font-size: 10px; }"
    "QPushButton:hover { background: #3a3d50; border-color: #6060a0; }"
    "QPushButton:pressed { background: #1a1d28; }"
)


class _ExplorerTreeWidget(QTreeWidget):
    """Tree view with physical drag and drop to move files/folders, and custom drop handling."""
    item_moved = Signal(Path, Path)  # src, dest

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(True)

    def dragEnterEvent(self, event) -> None:
        if event.source() == self:
            super().dragEnterEvent(event)
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if event.source() == self:
            super().dragMoveEvent(event)
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        target_item = self.itemAt(event.pos())
        # If dropping in empty space, default to root item (index 0) if it exists
        if not target_item and self.topLevelItemCount() > 0:
            target_item = self.topLevelItem(0)

        if not target_item:
            event.ignore()
            return

        selected = self.selectedItems()
        source_item = selected[0] if selected else None
        if not source_item or source_item == target_item:
            event.ignore()
            return

        # Prevent dropping a folder/item into one of its own descendants
        curr = target_item
        while curr:
            if curr == source_item:
                event.ignore()
                return
            curr = curr.parent()

        src_path = source_item.data(0, Qt.UserRole)
        if not src_path:
            event.ignore()
            return
        src_path = Path(src_path)

        is_target_file = target_item.data(0, Qt.UserRole + 1)
        target_path = target_item.data(0, Qt.UserRole)
        if not target_path:
            event.ignore()
            return
        target_path = Path(target_path)

        if is_target_file:
            dest_dir = target_path.parent
        else:
            dest_dir = target_path

        dest_path = dest_dir / src_path.name

        if src_path == dest_path or src_path.parent == dest_dir:
            event.ignore()
            return

        self.item_moved.emit(src_path, dest_path)
        event.accept()


class MetadataEditorPanel(QWidget):
    """
    Full Tag Editor tab widget.

    Signals (wired by AppWindow to MetadataController)
    ---------------------------------------------------
    scan_requested(Path, bool)              — folder, recursive
    auto_requested(list)                    — all tracks in current session
    apply_requested(Path, list)             — backup_dir, checked_tracks
    revert_requested(list)                  — all tracks
    artist_to_scope(str, list)              — artist text, target tracks
    album_to_scope(str, list)               — album text, checked tracks
    title_from_filename(list, bool)         — tracks, strip_numbering
    track_from_filename(list)               — tracks
    clear_comments(list)                    — tracks
    album_artist_from_artist(list)          — tracks
    title_case(list)                        — tracks
    split_artist_title(list)               — tracks
    clear_year(list)                        — tracks
    strip_web_junk(list)                    — tracks
    renumber_sequentially(list)             — tracks (ordered)
    """

    # ── Signals ───────────────────────────────────────────────────────────────

    scan_requested           = Signal(object, bool)
    auto_requested           = Signal(list)
    apply_requested          = Signal(object, list)     # (backup_dir, checked_tracks)
    revert_requested         = Signal(list)
    artist_to_scope          = Signal(str, list)
    album_to_scope           = Signal(str, list)
    title_from_filename      = Signal(list, bool)
    track_from_filename      = Signal(list)
    clear_comments           = Signal(list)
    album_artist_from_artist = Signal(list)
    split_artist_title       = Signal(list)
    clear_track_num          = Signal(list)
    clear_year               = Signal(list)
    clear_genre              = Signal(list)
    normalize_title_spaces   = Signal(list)
    strip_web_junk           = Signal(list)
    clean_filename           = Signal(list)
    strip_filename_numbering = Signal(list)

    # Duplicate file detector signals
    find_duplicates_requested   = Signal(object, bool)  # (Path, recursive)
    delete_duplicates_requested = Signal(list)           # list[Path]

    def __init__(self, config: Optional[AppConfig] = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("metadataEditorPage")
        self._cfg          = config

        self._model        = MetadataTableModel(self)
        self._root_folder: Optional[Path] = None
        self._icon_provider = QFileIconProvider()
        self._audio_icon    = self._make_audio_icon()

        # Auto-arrange configurable ops
        if self._cfg:
            self._auto_ops = set(self._cfg.magic_auto_ops)
            self._zoom_level = self._cfg.tag_editor_zoom
        else:
            self._auto_ops = set(_DEFAULT_AUTO_OPS)
            self._zoom_level = 100

        # Tree item lookup maps
        self._folder_items:       dict[Path, QTreeWidgetItem] = {}
        self._file_items:         dict[Path, QTreeWidgetItem] = {}
        self._ignore_tree_changes = False

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

        self._browse_btn = QPushButton("📁 בחר תיקייה")
        self._browse_btn.setFixedHeight(32)
        self._browse_btn.clicked.connect(self._on_browse)
        layout.addWidget(self._browse_btn)

        self._folder_lbl = QLabel("לא נבחרה תיקייה")
        self._folder_lbl.setStyleSheet(f"color: {get_colors().text_secondary}; font-size: 12px;")
        self._folder_lbl.setMaximumWidth(260)
        layout.addWidget(self._folder_lbl)

        self._subdirs_cb = QCheckBox("כלול תתי-תיקיות")
        self._subdirs_cb.setChecked(True)
        layout.addWidget(self._subdirs_cb)

        layout.addStretch()

        auto_wrap = QHBoxLayout()
        auto_wrap.setSpacing(2)
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
        auto_wrap.addWidget(self._auto_btn)

        self._auto_cfg_btn = QPushButton("⚙")
        self._auto_cfg_btn.setFixedSize(28, 34)
        self._auto_cfg_btn.setToolTip("הגדר מה סדר אוטומטי יבצע")
        self._auto_cfg_btn.setStyleSheet(
            "QPushButton { background: #3a3a4a; color: #ccc; border: 1px solid #555;"
            "  border-radius: 4px; font-size: 14px; }"
            "QPushButton:hover { background: #4a4a5a; }"
        )
        self._auto_cfg_btn.clicked.connect(self._on_auto_arrange_settings)
        auto_wrap.addWidget(self._auto_cfg_btn)
        layout.addLayout(auto_wrap)

        self._apply_btn = QPushButton("✅ החל שינויים")
        self._apply_btn.setFixedHeight(32)
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._on_apply)
        layout.addWidget(self._apply_btn)

        self._revert_btn = QPushButton("↩ בטל שינויים")
        self._revert_btn.setFixedHeight(32)
        self._revert_btn.setEnabled(False)
        self._revert_btn.clicked.connect(self._on_revert)
        layout.addWidget(self._revert_btn)

        self._dupes_btn = QPushButton("🔍 חפש כפילויות")
        self._dupes_btn.setFixedHeight(32)
        self._dupes_btn.setEnabled(False)
        self._dupes_btn.setToolTip("סרוק את התיקייה לאיתור קבצי מוזיקה כפולים")
        self._dupes_btn.clicked.connect(self._on_find_duplicates)
        layout.addWidget(self._dupes_btn)

        layout.addStretch()

        self._summary_lbl = QLabel("לא נסרקה תיקייה")
        self._summary_lbl.setStyleSheet(f"color: {get_colors().text_secondary}; font-size: 11px;")
        layout.addWidget(self._summary_lbl)

        return bar

    def _build_body(self) -> QSplitter:
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(True)
        splitter.setHandleWidth(5)
        splitter.setStyleSheet(
            "QSplitter::handle { background: #3a3a50; }"
            "QSplitter::handle:hover { background: #6060a0; }"
            "QSplitter::handle:pressed { background: #8080c0; }"
        )

        # ── Left: folder/file tree ────────────────────────────────────────────
        tree_frame = QFrame()
        tree_frame.setMinimumWidth(70)
        tree_layout = QVBoxLayout(tree_frame)
        tree_layout.setContentsMargins(4, 4, 0, 4)
        tree_layout.setSpacing(4)

        tree_header = QLabel("📂 קבצים ותיקיות")
        tree_header.setStyleSheet("font-weight: bold; font-size: 12px; padding: 2px 0;")
        tree_layout.addWidget(tree_header)

        self._tree = _ExplorerTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setAnimated(True)
        self._tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self._tree.itemChanged.connect(self._on_tree_item_changed)
        self._tree.item_moved.connect(self._on_tree_item_moved)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        self._tree.setStyleSheet(
            "QTreeWidget { border: none; background: transparent; }"
            "QTreeWidget::item { padding: 3px 2px; }"
            "QTreeWidget::item:selected { background: #2a3a5a; color: #ffffff; }"
            "QTreeWidget::item:hover { background: #1e2a40; }"
        )
        tree_layout.addWidget(self._tree)

        splitter.addWidget(tree_frame)
        splitter.setStretchFactor(0, 0)

        # ── Centre: table ─────────────────────────────────────────────────────
        table_frame = QFrame()
        table_layout = QVBoxLayout(table_frame)
        table_layout.setContentsMargins(0, 4, 0, 4)
        table_layout.setSpacing(4)

        tbl_head = QHBoxLayout()
        tbl_head.setContentsMargins(0, 0, 0, 0)
        
        # Zoom controls
        zoom_lbl = QLabel("🔍")
        zoom_lbl.setStyleSheet("font-size: 13px; color: #aaa; margin-left: 4px;")
        tbl_head.addWidget(zoom_lbl)
        
        self._zoom_minus_btn = QPushButton("-")
        self._zoom_minus_btn.setFixedSize(26, 26)
        self._zoom_minus_btn.setStyleSheet(
            "QPushButton { background: #2b2b3a; color: #fff; border: 1px solid #555; border-radius: 3px; font-weight: bold; font-size: 14px; }"
            "QPushButton:hover { background: #3a3a4a; }"
        )
        self._zoom_minus_btn.clicked.connect(self._on_zoom_minus)
        tbl_head.addWidget(self._zoom_minus_btn)
        
        self._zoom_val_lbl = QLineEdit("100%")
        self._zoom_val_lbl.setFixedSize(50, 26)
        self._zoom_val_lbl.setAlignment(Qt.AlignCenter)
        self._zoom_val_lbl.setStyleSheet(
            "QLineEdit { background: #1a1a24; color: #fff; border: 1px solid #555; border-radius: 3px; font-size: 11px; padding: 0px 2px; }"
        )
        self._zoom_val_lbl.editingFinished.connect(self._on_zoom_custom)
        tbl_head.addWidget(self._zoom_val_lbl)
        
        self._zoom_plus_btn = QPushButton("+")
        self._zoom_plus_btn.setFixedSize(26, 26)
        self._zoom_plus_btn.setStyleSheet(
            "QPushButton { background: #2b2b3a; color: #fff; border: 1px solid #555; border-radius: 3px; font-weight: bold; font-size: 14px; }"
            "QPushButton:hover { background: #3a3a4a; }"
        )
        self._zoom_plus_btn.clicked.connect(self._on_zoom_plus)
        tbl_head.addWidget(self._zoom_plus_btn)
        
        tbl_head.addSpacing(10)
        tbl_head.addStretch()

        self._table_info_lbl = QLabel("")
        self._table_info_lbl.setStyleSheet(f"color: {get_colors().text_secondary}; font-size: 11px;")
        tbl_head.addWidget(self._table_info_lbl)
        table_layout.addLayout(tbl_head)

        self._table = _ExplorerFileListView()
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._table.setEditTriggers(
            QAbstractItemView.DoubleClicked |
            QAbstractItemView.SelectedClicked |
            QAbstractItemView.AnyKeyPressed
        )
        self._table.setAlternatingRowColors(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setWordWrap(False)
        self._table.setLayoutDirection(Qt.RightToLeft)
        table_colors = get_colors()
        self._table.setItemDelegate(_ExplorerFileListDelegate(self._table))

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        hdr.setStretchLastSection(False)
        hdr.setContextMenuPolicy(Qt.CustomContextMenu)
        hdr.customContextMenuRequested.connect(self._on_header_context_menu)

        self._table.setColumnHidden(COL_CHECK,       False)
        self._table.setColumnHidden(COL_FILENAME_NEW, False)
        self._table.setColumnHidden(COL_GENRE_CUR,    True)
        self._table.setColumnHidden(COL_GENRE_NEW,    True)
        self._table.setColumnHidden(COL_COMMENT_CUR,  True)
        self._table.setColumnHidden(COL_COMMENT_NEW,  True)

        self._table.setColumnWidth(COL_CHECK,       _ExplorerFileListView._SIDE_EMPTY_GUTTER)
        self._table.setColumnWidth(COL_FILENAME,   180)
        self._table.setColumnWidth(COL_TITLE_CUR,  130)
        self._table.setColumnWidth(COL_TITLE_NEW,  130)
        self._table.setColumnWidth(COL_ARTIST_CUR, 110)
        self._table.setColumnWidth(COL_ARTIST_NEW, 110)
        self._table.setColumnWidth(COL_ALBUM_CUR,  120)
        self._table.setColumnWidth(COL_ALBUM_NEW,  120)
        self._table.setColumnWidth(COL_TRACK_CUR,   55)
        self._table.setColumnWidth(COL_TRACK_NEW,   55)
        self._table.setColumnWidth(COL_STATUS,       80)
        self._table.setColumnWidth(COL_FILENAME_NEW, 180)
        self._table.setColumnWidth(COL_GENRE_CUR,   100)
        self._table.setColumnWidth(COL_GENRE_NEW,   100)
        self._table.setColumnWidth(COL_COMMENT_CUR, 150)
        self._table.setColumnWidth(COL_COMMENT_NEW, 150)

        # Allow drag reordering; STATUS is pinned at the last visual slot
        # (= far LEFT in RTL rendering). Connect before the initial moveSection
        # so the lock is active from the start.
        hdr.setSectionsMovable(True)
        hdr.sectionMoved.connect(self._on_section_moved)
        hdr.setSectionResizeMode(COL_CHECK, QHeaderView.Fixed)
        hdr.moveSection(hdr.visualIndex(COL_CHECK), 0)
        hdr.moveSection(hdr.visualIndex(COL_STATUS), COLUMN_COUNT - 1)
        # Move new filename right next to original filename
        hdr.moveSection(hdr.visualIndex(COL_FILENAME_NEW), hdr.visualIndex(COL_FILENAME) + 1)

        self._table.selectionModel().selectionChanged.connect(self._on_table_selection_changed)
        self._model.dataChanged.connect(self._on_model_data_changed)
        self._model.rowsInserted.connect(lambda *_: self._update_table_info())
        self._model.rowsRemoved.connect(lambda *_: self._update_table_info())

        table_layout.addWidget(self._table)
        splitter.addWidget(table_frame)
        splitter.setStretchFactor(1, 1)

        # ── Right: inspector ──────────────────────────────────────────────────
        self._inspector = QStackedWidget()
        self._inspector.setMinimumWidth(80)
        self._inspector.setStyleSheet(
            "QWidget { font-size: 10px; }"
            "QGroupBox { font-weight: bold; font-size: 10px; margin-top: 4px; padding: 4px; }"
            "QLineEdit { font-size: 10px; height: 18px; padding: 1px 3px; }"
            "QPushButton { font-size: 10px; padding: 2px 4px; }"
            "QLabel { font-size: 10px; }"
        )

        self._inspector.addWidget(self._build_inspector_empty())   # 0
        self._inspector.addWidget(self._build_inspector_folder())  # 1
        self._inspector.addWidget(self._build_inspector_tracks())  # 2

        splitter.addWidget(self._inspector)
        splitter.setStretchFactor(2, 0)

        if self._cfg and self._cfg.tag_editor_splitter_sizes:
            splitter.setSizes(self._cfg.tag_editor_splitter_sizes)
        else:
            splitter.setSizes([220, 680, 200])

        # setChildrenCollapsible(True) lets Qt ignore minimumWidth by default.
        # setCollapsible(False) per child overrides that — tree and inspector
        # always stay at least their minimumWidth wide.
        splitter.setCollapsible(0, False)   # tree frame
        splitter.setCollapsible(2, False)   # inspector

        splitter.splitterMoved.connect(
            lambda pos, index: self._save_splitter_sizes(splitter)
        )

        # Set initial table zoom level
        self._set_zoom(self._zoom_level)

        return splitter

    def _save_splitter_sizes(self, splitter: QSplitter) -> None:
        if self._cfg:
            self._cfg.tag_editor_splitter_sizes = splitter.sizes()
            self._cfg.save()

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

    def _build_inspector_folder(self) -> QScrollArea:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignTop)

        self._insp_folder_title = QLabel("כל הקבצים המסומנים")
        self._insp_folder_title.setStyleSheet("font-weight: bold; font-size: 13px;")
        self._insp_folder_title.setWordWrap(True)
        layout.addWidget(self._insp_folder_title)

        _btn_style = (
            f"QPushButton {{ background: {ACCENT_COLOR}; color: #000; font-weight: bold;"
            f"  border-radius: 4px; padding: 3px 6px; font-size: 10px; }}"
            f"QPushButton:hover {{ background: #e09400; }}"
        )

        grp_artist = QGroupBox("החל אמן")
        grp_layout = QVBoxLayout(grp_artist)
        grp_layout.setSpacing(6)
        self._insp_folder_artist = QLineEdit()
        self._insp_folder_artist.setPlaceholderText("שם האמן…")
        grp_layout.addWidget(self._insp_folder_artist)
        btn_artist = QPushButton("✅ החל אמן על המסומנים")
        btn_artist.setStyleSheet(_btn_style)
        btn_artist.clicked.connect(self._on_insp_folder_artist)
        grp_layout.addWidget(btn_artist)
        layout.addWidget(grp_artist)

        grp_album = QGroupBox("החל אלבום")
        grp_album_layout = QVBoxLayout(grp_album)
        grp_album_layout.setSpacing(6)
        self._insp_folder_album = QLineEdit()
        self._insp_folder_album.setPlaceholderText("שם האלבום…")
        grp_album_layout.addWidget(self._insp_folder_album)
        btn_album = QPushButton("✅ החל אלבום על המסומנים")
        btn_album.setStyleSheet(_btn_style)
        btn_album.clicked.connect(self._on_insp_folder_album)
        grp_album_layout.addWidget(btn_album)
        layout.addWidget(grp_album)

        layout.addWidget(self._build_magic_ops_widget())
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(w)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        return scroll

    def _build_inspector_tracks(self) -> QScrollArea:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignTop)

        self._insp_tracks_title = QLabel("0 שירים נבחרו")
        self._insp_tracks_title.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(self._insp_tracks_title)

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

        rename_grp = QGroupBox("שינוי שם קובץ")
        rename_layout = QVBoxLayout(rename_grp)
        rename_layout.setSpacing(6)
        rename_note = QLabel("שנה את שם הקובץ הפיזי לפי הכותרת החדשה")
        rename_note.setWordWrap(True)
        rename_note.setStyleSheet(f"color: {get_colors().text_secondary}; font-size: 11px;")
        rename_layout.addWidget(rename_note)
        btn_rename = QPushButton("📝 שנה שם קובץ לפי כותרת")
        btn_rename.setStyleSheet(_BTN_STYLE)
        btn_rename.clicked.connect(
            lambda: self.rename_from_title.emit(self._get_selected_tracks())
        )
        rename_layout.addWidget(btn_rename)
        layout.addWidget(rename_grp)

        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(w)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        return scroll

    def _build_magic_ops_widget(self) -> QGroupBox:
        """Build magic operations group — all ops always visible, all act on checked tracks."""
        grp = QGroupBox("פעולות על המסומנים")
        grp_layout = QVBoxLayout(grp)
        grp_layout.setSpacing(4)

        checked = self._model.get_checked_tracks

        op_handlers: dict[str, object] = {
            "title_strip":      lambda: self.title_from_filename.emit(checked(), True),
            "title_full":       lambda: self.title_from_filename.emit(checked(), False),
            "normalize_spaces": lambda: self.normalize_title_spaces.emit(checked()),
            "track_num":        lambda: self.track_from_filename.emit(checked()),
            "split_at":         lambda: self.split_artist_title.emit(checked()),
            "album_artist":     lambda: self.album_artist_from_artist.emit(checked()),
            "strip_junk":       lambda: self.strip_web_junk.emit(checked()),
            "clear_comments":   lambda: self.clear_comments.emit(checked()),
            "clear_track_num":  lambda: self.clear_track_num.emit(checked()),
            "clear_year":       lambda: self.clear_year.emit(checked()),
            "clear_genre":      lambda: self.clear_genre.emit(checked()),
            "clean_filename":   lambda: self.clean_filename.emit(checked()),
            "strip_filename_numbering": lambda: self.strip_filename_numbering.emit(checked()),
        }

        for key, label, desc in _MAGIC_OP_DEFS:
            row_layout = QHBoxLayout()
            row_layout.setSpacing(4)
            row_layout.setContentsMargins(0, 0, 0, 0)
            btn = QPushButton(label)
            btn.setStyleSheet(_BTN_STYLE)
            if key in op_handlers:
                btn.clicked.connect(op_handlers[key])
            row_layout.addWidget(btn, stretch=1)
            
            info_btn = QPushButton("ℹ️")
            info_btn.setFixedSize(24, 24)
            info_btn.setStyleSheet("QPushButton { border: none; background: transparent; font-size: 14px; } QPushButton:hover { color: #88aaff; }")
            info_btn.setToolTip(desc)
            info_btn.clicked.connect(lambda _, l=label, d=desc: self._show_info(l, d))
            row_layout.addWidget(info_btn)
            grp_layout.addLayout(row_layout)

        return grp

    def _show_info(self, title: str, desc: str) -> None:
        from qfluentwidgets import MessageBox
        msg = MessageBox(title, desc, self)
        msg.cancelButton.hide()
        msg.exec()

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
            self._on_scan()

    def _on_scan(self) -> None:
        if not self._root_folder:
            return
        self._model.load_tracks([])
        self._tree.clear()
        self._folder_items.clear()
        self._file_items.clear()
        self._inspector.setCurrentIndex(_PAGE_EMPTY)
        self._auto_btn.setEnabled(False)
        self._apply_btn.setEnabled(False)
        self._revert_btn.setEnabled(False)
        self._summary_lbl.setText("סורק…")
        self.scan_requested.emit(self._root_folder, self._subdirs_cb.isChecked())

    def _on_auto_arrange(self) -> None:
        tracks = self._model.get_checked_tracks()
        self.auto_requested.emit(tracks)
        # Run additional configured ops in order
        op_signals = {
            "title_strip":      lambda t: self.title_from_filename.emit(t, True),
            "title_full":       lambda t: self.title_from_filename.emit(t, False),
            "normalize_spaces": lambda t: self.normalize_title_spaces.emit(t),
            "track_num":        lambda t: self.track_from_filename.emit(t),
            "split_at":         lambda t: self.split_artist_title.emit(t),
            "album_artist":     lambda t: self.album_artist_from_artist.emit(t),
            "strip_junk":       lambda t: self.strip_web_junk.emit(t),
            "clear_comments":   lambda t: self.clear_comments.emit(t),
            "clear_track_num":  lambda t: self.clear_track_num.emit(t),
            "clear_year":       lambda t: self.clear_year.emit(t),
            "clear_genre":      lambda t: self.clear_genre.emit(t),
            "clean_filename":   lambda t: self.clean_filename.emit(t),
            "strip_filename_numbering": lambda t: self.strip_filename_numbering.emit(t),
        }
        for key, _, _ in _MAGIC_OP_DEFS:
            if key in self._auto_ops and key in op_signals:
                op_signals[key](tracks)

    def _on_apply(self) -> None:
        backup_dir = Path.home() / ".ytspot" / "tag_backups"
        checked = self._model.get_checked_tracks()
        self.apply_requested.emit(backup_dir, checked)

    def _on_revert(self) -> None:
        self.revert_requested.emit(self._model.get_all_tracks())

    def _on_find_duplicates(self) -> None:
        if not self._root_folder:
            return
        self._dupes_btn.setEnabled(False)
        self._summary_lbl.setText("מחפש כפילויות…")
        self.find_duplicates_requested.emit(self._root_folder, True)  # always recursive

    # ── Tree handlers ─────────────────────────────────────────────────────────

    _ROLE_IS_FILE = Qt.UserRole + 1

    def _on_tree_item_changed(self, item: QTreeWidgetItem, col: int) -> None:
        """Propagate checkbox state to descendants and sync with the table model."""
        if col != 0 or self._ignore_tree_changes:
            return

        is_file = item.data(0, self._ROLE_IS_FILE)
        state   = item.checkState(0)

        if is_file:
            path = item.data(0, Qt.UserRole)
            if path:
                self._model.set_path_checked(path, state == Qt.Checked)
        else:
            if state == Qt.PartiallyChecked:
                return  # Qt.ItemIsAutoTristate manages this internally
            self._ignore_tree_changes = True
            self._propagate_check_state(item, state)
            self._ignore_tree_changes = False

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
        elif self._model.get_all_tracks():
            # Default back to "apply to all checked" panel
            checked = len(self._model.get_checked_tracks())
            self._insp_folder_title.setText(f"{checked} קבצים מסומנים")
            self._inspector.setCurrentIndex(_PAGE_FOLDER)
        else:
            self._inspector.setCurrentIndex(_PAGE_EMPTY)

    def _on_model_data_changed(self, *_) -> None:
        self._update_summary()

    # ── Inspector handlers ────────────────────────────────────────────────────

    def _on_insp_folder_artist(self) -> None:
        artist = self._insp_folder_artist.text().strip()
        if not artist:
            return
        self.artist_to_scope.emit(artist, self._model.get_checked_tracks())

    def _on_insp_folder_album(self) -> None:
        album = self._insp_folder_album.text().strip()
        if not album:
            return
        self.album_to_scope.emit(album, self._model.get_checked_tracks())

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

    def _on_auto_arrange_settings(self) -> None:
        dlg = _AutoArrangeSettingsDialog(self._auto_ops, self)
        if dlg.exec():
            self._auto_ops = dlg.result_ops
            if self._cfg:
                self._cfg.magic_auto_ops = list(self._auto_ops)
                self._cfg.save()

    def _on_section_moved(self, logical: int, old_visual: int, new_visual: int) -> None:
        """Keep the blank gutter at the right edge and STATUS at the far left."""
        hdr = self._table.horizontalHeader()
        target = COLUMN_COUNT - 1
        if hdr.visualIndex(COL_CHECK) != 0 or hdr.visualIndex(COL_STATUS) != target:
            hdr.blockSignals(True)
            try:
                if hdr.visualIndex(COL_CHECK) != 0:
                    hdr.moveSection(hdr.visualIndex(COL_CHECK), 0)
                hdr.moveSection(hdr.visualIndex(COL_STATUS), target)
            finally:
                hdr.blockSignals(False)

    def _on_header_context_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        # Not shown in menu at all (always hidden or locked with no toggle needed)
        NO_MENU = {COL_CHECK, COL_STATUS}
        # Shown in menu but grayed out (always visible, user cannot hide)
        ALWAYS_VISIBLE = {COL_FILENAME}
        for col in range(COLUMN_COUNT):
            if col in NO_MENU:
                continue
            lbl = _HEADERS[col] if col < len(_HEADERS) else str(col)
            if not lbl:
                continue
            action = menu.addAction(lbl)
            action.setCheckable(True)
            action.setChecked(not self._table.isColumnHidden(col))
            if col in ALWAYS_VISIBLE:
                action.setEnabled(False)
            else:
                action.triggered.connect(
                    lambda checked, c=col: self._table.setColumnHidden(c, not checked)
                )
        menu.exec(self._table.horizontalHeader().mapToGlobal(pos))

    # ── Public slots (wired by AppWindow) ─────────────────────────────────────

    def on_track_discovered(self, item: AudioTrackItem) -> None:
        self._model.add_track(item)
        self._add_to_tree(item)

    def on_scan_complete(self, result: ScanResult) -> None:
        n = result.files_count
        self._ignore_tree_changes = True
        try:
            for folder in sorted(result.folder_set, key=lambda p: (len(p.parts), str(p).lower())):
                self._get_or_create_folder_item(folder)
        finally:
            self._ignore_tree_changes = False

        self._auto_btn.setEnabled(n > 0)
        self._apply_btn.setEnabled(n > 0)
        self._revert_btn.setEnabled(n > 0)
        self._dupes_btn.setEnabled(True)
        self._update_summary()

        if self._tree.topLevelItemCount() > 0:
            self._tree.topLevelItem(0).setExpanded(True)

        if n > 0:
            self._insp_folder_title.setText(f"{n} קבצים מסומנים")
            self._inspector.setCurrentIndex(_PAGE_FOLDER)

    def on_auto_rules_applied(self) -> None:
        self._model.refresh_all()
        self._table.viewport().update()
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
                    title="הצלחה", content=msg, parent=self,
                    position=InfoBarPosition.BOTTOM_RIGHT, duration=4000,
                )
            else:
                InfoBar.warning(
                    title="הושלם עם שגיאות", content=msg, parent=self,
                    position=InfoBarPosition.BOTTOM_RIGHT, duration=6000,
                )
        except Exception:
            pass

    def on_status_update(self, msg: str) -> None:
        self._summary_lbl.setText(msg)

    def on_duplicate_scan_progress(self, done: int, total: int, eta: str) -> None:
        self._summary_lbl.setText(f"מחפש כפילויות… {done}/{total}  ({eta})")

    def on_duplicate_scan_complete(self, groups: dict, elapsed: float, strategy: str) -> None:
        self._dupes_btn.setEnabled(True)
        if not groups:
            self.on_status_update(f"לא נמצאו כפילויות ({elapsed:.1f}s)")
            self._update_summary()
            return

        from ui.dialogs.duplicate_files_dialog import DuplicateFilesDialog
        dlg = DuplicateFilesDialog(groups, elapsed, strategy, self._root_folder, parent=self)
        if dlg.exec() == QDialog.Accepted and dlg.files_to_delete:
            self.delete_duplicates_requested.emit(dlg.files_to_delete)

    def on_duplicate_scan_error(self, msg: str) -> None:
        self._dupes_btn.setEnabled(True)
        self.on_status_update(f"שגיאה בחיפוש כפילויות: {msg}")
        self._update_summary()

    def on_duplicate_delete_complete(self, success: int, fail: int) -> None:
        note = f" ({fail} שגיאות)" if fail else ""
        self.on_status_update(f"נמחקו {success} קבצים כפולים{note}")
        self._on_scan()   # trigger full folder rescan → refreshes tree and table

    # ── Tree construction helpers ─────────────────────────────────────────────

    def _make_audio_icon(self) -> QIcon:
        pix = QPixmap(18, 18)
        pix.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#27d3c4"))
        painter.drawRoundedRect(2, 2, 14, 14, 4, 4)

        font = QFont()
        font.setBold(True)
        font.setPointSize(12)
        painter.setFont(font)
        painter.setPen(QColor("#061a1c"))
        painter.drawText(pix.rect().adjusted(0, -1, 0, 0), Qt.AlignmentFlag.AlignCenter, "♪")
        painter.end()

        return QIcon(pix)

    def _folder_icon(self, folder: Path) -> QIcon:
        icon = self._icon_provider.icon(QFileInfo(str(folder)))
        if not icon.isNull():
            return icon
        return self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)

    def _track_icon(self, item: AudioTrackItem) -> QIcon:
        if item.status == TrackStatus.UNSUPPORTED:
            return self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)

        icon = self._icon_provider.icon(QFileInfo(str(item.path)))
        if not icon.isNull():
            return icon
        return self._audio_icon

    def _ensure_root_item(self) -> QTreeWidgetItem:
        if not self._root_folder:
            raise RuntimeError("Cannot build tree before root folder is selected")

        if self._tree.topLevelItemCount() > 0:
            root_item = self._tree.topLevelItem(0)
            self._folder_items.setdefault(self._root_folder, root_item)
            return root_item

        root_item = QTreeWidgetItem([self._root_folder.name])
        root_item.setIcon(0, self._folder_icon(self._root_folder))
        root_item.setData(0, Qt.UserRole, self._root_folder)
        root_item.setData(0, self._ROLE_IS_FILE, False)
        root_item.setFont(0, _bold_font())
        root_item.setFlags(
            Qt.ItemIsEnabled | Qt.ItemIsSelectable |
            Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate |
            Qt.ItemIsDropEnabled
        )
        root_item.setCheckState(0, Qt.Checked)
        self._tree.addTopLevelItem(root_item)
        self._folder_items[self._root_folder] = root_item
        return root_item

    def _get_or_create_folder_item(self, folder: Path) -> QTreeWidgetItem:
        """Recursively ensure a tree item exists for folder and all its ancestors."""
        if folder in self._folder_items:
            return self._folder_items[folder]

        if self._root_folder and folder == self._root_folder:
            return self._ensure_root_item()

        parent = folder.parent
        if parent == folder:
            # Reached filesystem root — safety guard, return top-level item
            return self._ensure_root_item()

        parent_item = self._get_or_create_folder_item(parent)

        folder_item = QTreeWidgetItem([folder.name])
        folder_item.setIcon(0, self._folder_icon(folder))
        folder_item.setData(0, Qt.UserRole, folder)
        folder_item.setData(0, self._ROLE_IS_FILE, False)
        folder_item.setFlags(
            Qt.ItemIsEnabled | Qt.ItemIsSelectable |
            Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate |
            Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled
        )
        folder_item.setCheckState(0, Qt.Checked)
        parent_item.addChild(folder_item)
        self._folder_items[folder] = folder_item
        return folder_item

    def _propagate_check_state(self, item: QTreeWidgetItem, state: Qt.CheckState) -> None:
        """Recursively apply check state to all descendant items and sync model."""
        for i in range(item.childCount()):
            child = item.child(i)
            child.setCheckState(0, state)
            if child.data(0, self._ROLE_IS_FILE):
                path = child.data(0, Qt.UserRole)
                if path:
                    self._model.set_path_checked(path, state == Qt.Checked)
            else:
                self._propagate_check_state(child, state)

    def _add_to_tree(self, item: AudioTrackItem) -> None:
        """Add a discovered audio file to the tree, creating all ancestor folders."""
        if not self._root_folder:
            return

        self._ignore_tree_changes = True

        self._ensure_root_item()

        # Get or create the full folder hierarchy
        folder_item = self._get_or_create_folder_item(item.folder)

        # Add file item
        if item.path not in self._file_items:
            file_item = QTreeWidgetItem([item.display_name])
            file_item.setIcon(0, self._track_icon(item))
            file_item.setData(0, Qt.UserRole, item.path)
            file_item.setData(0, self._ROLE_IS_FILE, True)
            file_item.setFlags(
                Qt.ItemIsEnabled | Qt.ItemIsSelectable |
                Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled |
                Qt.ItemIsDropEnabled
            )
            file_item.setCheckState(0, Qt.Checked)
            file_item.setToolTip(0, str(item.path))
            folder_item.addChild(file_item)
            self._file_items[item.path] = file_item

        self._ignore_tree_changes = False

    # ── Summary / info helpers ────────────────────────────────────────────────

    def _update_summary(self) -> None:
        tracks = self._model.get_all_tracks()
        folders = len(self._folder_items) if self._folder_items else len({t.folder for t in tracks})
        changed = self._model.get_changed_count()
        warnings = self._model.get_warning_count()
        parts = [f"{len(tracks)} קבצים", f"{folders} תיקיות"]
        if changed:
            parts.append(f"{changed} שינויים מוצעים")
        if warnings:
            parts.append(f"{warnings} אזהרות")
        self._summary_lbl.setText(" | ".join(parts) if parts else "")

    def _update_table_info(self) -> None:
        checked = len(self._model.get_checked_tracks())
        total   = len(self._model.get_all_tracks())
        if checked == total:
            self._table_info_lbl.setText(f"{total} קבצים")
        else:
            self._table_info_lbl.setText(f"מציג {checked} מסומנים מתוך {total}")

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
        self._insp_tracks_title.setText(
            f"{len(tracks)} שיר{'ים' if len(tracks) != 1 else ''} נבחרו"
        )

        def _common(vals):
            unique = {str(v) for v in vals if v is not None}
            return list(unique)[0] if len(unique) == 1 else ""

        self._insp_title.setText(
            _common([t.proposed.title  if t.proposed.title  is not None else t.original.title  for t in tracks])
        )
        self._insp_artist.setText(
            _common([t.proposed.artist if t.proposed.artist is not None else t.original.artist for t in tracks])
        )
        self._insp_album.setText(
            _common([t.proposed.album  if t.proposed.album  is not None else t.original.album  for t in tracks])
        )
        self._insp_album_artist.setText(
            _common([t.proposed.album_artist if t.proposed.album_artist is not None else t.original.album_artist for t in tracks])
        )
        self._insp_track.setText(
            _common([t.proposed.track_num if t.proposed.track_num is not None else t.original.track_num for t in tracks])
        )

    def _on_zoom_minus(self) -> None:
        self._change_zoom(-10)

    def _on_zoom_plus(self) -> None:
        self._change_zoom(10)

    def _on_zoom_custom(self) -> None:
        text = self._zoom_val_lbl.text().replace("%", "").strip()
        try:
            val = int(text)
            val = max(50, min(200, val))
            self._set_zoom(val)
        except ValueError:
            self._zoom_val_lbl.setText(f"{self._zoom_level}%")

    def _change_zoom(self, delta: int) -> None:
        new_val = max(50, min(200, self._zoom_level + delta))
        self._set_zoom(new_val)

    def _set_zoom(self, pct: int) -> None:
        self._zoom_level = pct
        self._zoom_val_lbl.setText(f"{pct}%")
        
        if self._cfg:
            self._cfg.tag_editor_zoom = pct
            self._cfg.save()
            
        font_size = max(6, int(10 * (pct / 100.0)))
        factor = pct / 100.0
        
        table_colors = get_colors()
        self._table.setStyleSheet(
            f"QTableView {{ background: #0d0d12; color: {table_colors.text_primary};"
            f"  border: 1px solid {table_colors.border};"
            f"  selection-background-color: transparent; selection-color: {table_colors.text_primary};"
            f"  font-size: {font_size}pt; }}"
            "QTableView::item { background: transparent; border: none; }"
            f"QHeaderView::section {{ background: #101018; color: {table_colors.text_primary};"
            f"  border: none; border-left: 1px solid {table_colors.border};"
            f"  border-bottom: 1px solid {table_colors.border}; padding: {int(4 * factor)}px {int(8 * factor)}px;"
            f"  font-size: {font_size}pt; font-weight: bold; }}"
            f"QTableCornerButton::section {{ background: #101018; border: 1px solid {table_colors.border}; }}"
        )

        font = self._table.font()
        font.setPointSize(font_size)
        self._table.setFont(font)
        
        hdr = self._table.horizontalHeader()
        hdr_font = hdr.font()
        hdr_font.setPointSize(font_size)
        hdr.setFont(hdr_font)
        
        self._table.setColumnWidth(COL_CHECK, int(_ExplorerFileListView._SIDE_EMPTY_GUTTER * factor))
        self._table.setColumnWidth(COL_FILENAME, int(180 * factor))
        self._table.setColumnWidth(COL_TITLE_CUR, int(130 * factor))
        self._table.setColumnWidth(COL_TITLE_NEW, int(130 * factor))
        self._table.setColumnWidth(COL_ARTIST_CUR, int(110 * factor))
        self._table.setColumnWidth(COL_ARTIST_NEW, int(110 * factor))
        self._table.setColumnWidth(COL_ALBUM_CUR, int(120 * factor))
        self._table.setColumnWidth(COL_ALBUM_NEW, int(120 * factor))
        self._table.setColumnWidth(COL_TRACK_CUR, int(55 * factor))
        self._table.setColumnWidth(COL_TRACK_NEW, int(55 * factor))
        self._table.setColumnWidth(COL_STATUS, int(80 * factor))
        self._table.setColumnWidth(COL_FILENAME_NEW, int(180 * factor))
        self._table.setColumnWidth(COL_GENRE_CUR, int(100 * factor))
        self._table.setColumnWidth(COL_GENRE_NEW, int(100 * factor))
        self._table.setColumnWidth(COL_COMMENT_CUR, int(150 * factor))
        self._table.setColumnWidth(COL_COMMENT_NEW, int(150 * factor))

    def _on_tree_item_moved(self, src: Path, dest: Path) -> None:
        """Physically moves a file or folder on the disk, and updates UI."""
        try:
            if dest.exists():
                from qfluentwidgets import MessageBox
                MessageBox("שגיאה", f"היעד כבר קיים:\n{dest.name}", self).exec()
                return

            import shutil
            shutil.move(str(src), str(dest))
            self._on_scan()
        except Exception as e:
            logger.exception("Failed to move tree item")
            from qfluentwidgets import MessageBox
            MessageBox("שגיאה", f"כשל בהעברת הקובץ:\n{str(e)}", self).exec()

    def _on_tree_context_menu(self, pos: QPoint) -> None:
        item = self._tree.itemAt(pos)
        if not item:
            return

        path_str = item.data(0, Qt.UserRole)
        if not path_str:
            return
        path = Path(path_str)
        is_file = item.data(0, self._ROLE_IS_FILE)
        add_folder_action = None

        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        if not is_file:
            add_folder_action = menu.addAction("📁 הוסף תיקייה")
            menu.addSeparator()

        rename_action = menu.addAction("✏️ שנה שם")
        delete_action = menu.addAction("🗑️ מחק")

        action = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if add_folder_action is not None and action == add_folder_action:
            self._on_tree_add_folder(path)
        elif action == rename_action:
            self._on_tree_rename(path, is_file)
        elif action == delete_action:
            self._on_tree_delete(path, is_file)

    def _on_tree_add_folder(self, parent_path: Path) -> None:
        new_name, ok = QInputDialog.getText(
            self,
            "הוסף תיקייה",
            "שם התיקייה החדשה:",
            text="תיקייה חדשה"
        )
        if not ok or not new_name.strip():
            return

        new_name = new_name.strip()
        invalid_chars = set('<>:"|?*')
        if (
            new_name in {".", ".."}
            or any(ch in new_name for ch in invalid_chars)
            or "/" in new_name
            or "\\" in new_name
        ):
            from qfluentwidgets import MessageBox
            MessageBox("שגיאה", "שם התיקייה אינו חוקי.", self).exec()
            return

        dest = parent_path / new_name
        try:
            if dest.exists():
                from qfluentwidgets import MessageBox
                MessageBox("שגיאה", "תיקייה בשם הזה כבר קיימת.", self).exec()
                return

            dest.mkdir()
            self._on_scan()
        except Exception as e:
            logger.exception("Failed to create tree folder")
            from qfluentwidgets import MessageBox
            MessageBox("שגיאה", f"כשל ביצירת התיקייה:\n{str(e)}", self).exec()

    def _on_tree_rename(self, path: Path, is_file: bool) -> None:
        new_name, ok = QInputDialog.getText(
            self,
            "שנה שם",
            "הכנס שם חדש:",
            text=path.name
        )
        if not ok or not new_name.strip():
            return

        new_name = new_name.strip()
        dest = path.parent / new_name
        if dest == path:
            return

        try:
            if dest.exists():
                from qfluentwidgets import MessageBox
                MessageBox("שגיאה", "שם היעד כבר קיים בתיקייה זו.", self).exec()
                return

            path.rename(dest)
            self._on_scan()
        except Exception as e:
            logger.exception("Failed to rename tree item")
            from qfluentwidgets import MessageBox
            MessageBox("שגיאה", f"כשל בשינוי השם:\n{str(e)}", self).exec()

    def _on_tree_delete(self, path: Path, is_file: bool) -> None:
        from qfluentwidgets import MessageBox
        title = "מחיקת קובץ" if is_file else "מחיקת תיקייה"
        text = f"האם אתה בטוח שברצונך למחוק לצמיתות את:\n{path.name}?"
        if not is_file:
            text += "\n(כל הקבצים בתוך התיקייה יימחקו גם הם)"

        msg = MessageBox(title, text, self)
        if msg.exec():
            try:
                import shutil
                if is_file:
                    path.unlink()
                else:
                    shutil.rmtree(path)
                self._on_scan()
            except Exception as e:
                logger.exception("Failed to delete tree item")
                from qfluentwidgets import MessageBox
                MessageBox("שגיאה", f"כשל במחיקה:\n{str(e)}", self).exec()




def _bold_font() -> QFont:
    f = QFont()
    f.setBold(True)
    return f
