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

from PySide6.QtCore import QFileInfo, QModelIndex, QPoint, QRect, QRectF, QSize, Qt, Signal, QItemSelection, QItemSelectionModel
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QKeyEvent, QPainter, QPalette, QPen, QPixmap
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
    QInputDialog,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QProxyStyle,
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
from ui.i18n import t
from ui.models.metadata_table_model import (
    COL_CHECK, COL_FILENAME, COL_TITLE_CUR, COL_TITLE_NEW,
    COL_ARTIST_CUR, COL_ARTIST_NEW, COL_ALBUM_CUR, COL_ALBUM_NEW,
    COL_TRACK_CUR, COL_TRACK_NEW, COL_STATUS,
    COL_FILENAME_NEW, COL_GENRE_CUR, COL_GENRE_NEW,
    COL_COMMENT_CUR, COL_COMMENT_NEW,
    COLUMN_COUNT, MetadataTableModel, _HEADER_KEYS,
)
from ui.theme_manager import (
    ACCENT_COLOR,
    get_colors,
)

logger = logging.getLogger(__name__)


def _md_dim_hex(hex_color: str, factor: float = 0.85) -> str:
    """Return a darkened/dimmed variant of a hex color for hover states."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    r = max(0, int(int(h[0:2], 16) * factor))
    g = max(0, int(int(h[2:4], 16) * factor))
    b = max(0, int(int(h[4:6], 16) * factor))
    return f"#{r:02x}{g:02x}{b:02x}"


# Inspector page indices
_PAGE_EMPTY  = 0
_PAGE_FOLDER = 1
_PAGE_TRACKS = 2

# All magic operations: (op_id, label_translation_key, desc_translation_key)
# Labels/descriptions are looked up via t() at display time so they follow the
# user's current language.
_MAGIC_OP_DEFS: list[tuple[str, str, str]] = [
    ("title_strip",              "meta_op_title_strip_label",              "meta_op_title_strip_desc"),
    ("title_full",               "meta_op_title_full_label",               "meta_op_title_full_desc"),
    ("normalize_spaces",         "meta_op_normalize_spaces_label",         "meta_op_normalize_spaces_desc"),
    ("track_num",                "meta_op_track_num_label",                "meta_op_track_num_desc"),
    ("split_at",                 "meta_op_split_at_label",                 "meta_op_split_at_desc"),
    ("album_artist",             "meta_op_album_artist_label",             "meta_op_album_artist_desc"),
    ("strip_junk",               "meta_op_strip_junk_label",               "meta_op_strip_junk_desc"),
    ("clear_comments",           "meta_op_clear_comments_label",           "meta_op_clear_comments_desc"),
    ("clear_track_num",          "meta_op_clear_track_num_label",          "meta_op_clear_track_num_desc"),
    ("clear_year",               "meta_op_clear_year_label",               "meta_op_clear_year_desc"),
    ("clear_genre",              "meta_op_clear_genre_label",              "meta_op_clear_genre_desc"),
    ("clean_filename",           "meta_op_clean_filename_label",           "meta_op_clean_filename_desc"),
    ("strip_filename_numbering", "meta_op_strip_filename_numbering_label", "meta_op_strip_filename_numbering_desc"),
]

# Which ops the auto-arrange button runs by default
_DEFAULT_AUTO_OPS: frozenset[str] = frozenset({
    "title_strip", "track_num", "normalize_spaces",
})

_DEFAULT_COL_WIDTHS: dict[int, int] = {
    COL_CHECK:        28,  # _ExplorerFileListView._SIDE_EMPTY_GUTTER
    COL_FILENAME:     260,
    COL_TITLE_CUR:    130,
    COL_TITLE_NEW:    130,
    COL_ARTIST_CUR:   110,
    COL_ARTIST_NEW:   110,
    COL_ALBUM_CUR:    120,
    COL_ALBUM_NEW:    120,
    COL_TRACK_CUR:    55,
    COL_TRACK_NEW:    55,
    COL_STATUS:       80,
    COL_FILENAME_NEW: 220,
    COL_GENRE_CUR:    100,
    COL_GENRE_NEW:    100,
    COL_COMMENT_CUR:  150,
    COL_COMMENT_NEW:  150,
}


class _ExplorerFileListDelegate(QStyledItemDelegate):
    """
    Draw only the item contents.  Row backgrounds are painted by
    _ExplorerFileListView so selected rows stay one continuous strip.

    The filename columns (COL_FILENAME / COL_FILENAME_NEW) get a 16×16
    file-type icon painted to the left of the text, matching Win11
    Explorer Details View. The icon is resolved through the optional
    ``panel`` reference (which exposes ``_track_icon(path)``); when not
    provided, the columns render text only.
    """
    _PADDING_X = 12        # Win11 horizontal cell inset
    _ICON_SIZE = 16
    _ICON_TEXT_GAP = 8

    def __init__(self, parent=None, panel=None) -> None:
        super().__init__(parent)
        self._panel = panel

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        if index.column() == COL_CHECK:
            return  # Draw absolutely nothing in the gutter column

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        cell_rect = QRect(option.rect)

        painter.save()

        # Row background (hover/selection capsule) is painted once by drawRow —
        # do NOT repaint it here or the border clips to this cell's rect only.

        if not (opt.state & QStyle.State_Selected) and opt.backgroundBrush.style() != Qt.NoBrush:
            painter.fillRect(cell_rect.adjusted(0, 1, 0, -1), opt.backgroundBrush)

        opt.state &= ~QStyle.State_Selected
        opt.state &= ~QStyle.State_HasFocus
        opt.backgroundBrush = QBrush(Qt.NoBrush)
        text_color = QColor(get_colors().text_primary)
        opt.palette.setColor(QPalette.Text, text_color)
        opt.palette.setColor(QPalette.HighlightedText, text_color)

        text_rect = cell_rect.adjusted(self._PADDING_X, 1, -self._PADDING_X, -1)
        opt.rect = text_rect
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
        painter.restore()


class _FilenameDelegate(QStyledItemDelegate):
    """Delegate for the filename columns (COL_FILENAME and COL_FILENAME_NEW).

    Enforces LTR direction, left alignment and middle elision so file paths
    read correctly even when the app runs RTL. Also draws:
      • a 16-px file-type icon on the leading edge
      • a Win11-style circular checkbox indicator when show_checkbox=True,
        visible only on hover or selection so it stays hidden at rest.
    """

    _CB_SIZE   = 16   # checkbox circle diameter, px
    _CB_INSET  = 8    # leading padding before the circle
    _CB_GAP    = 6    # gap between circle right-edge and icon/text
    _ICON_SIZE = 16
    _ICON_GAP  = 6
    _PAD_X     = 12   # trailing cell padding

    def __init__(self, parent=None, panel=None, show_checkbox: bool = False) -> None:
        super().__init__(parent)
        self._panel         = panel
        self._show_checkbox = show_checkbox

    # ── geometry helpers ──────────────────────────────────────────────────────

    @property
    def _checkbox_width(self) -> int:
        return (self._CB_INSET + self._CB_SIZE + self._CB_GAP) if self._show_checkbox else 0

    def checkbox_hit_rect(self, cell_rect: QRect) -> QRect:
        """Return the checkbox hit area within cell_rect.

        In RTL mode the checkbox sits on the RIGHT (trailing) edge so it
        appears at the screen-right of the Name column, matching Win11."""
        if not self._show_checkbox:
            return QRect()
        if QApplication.layoutDirection() == Qt.RightToLeft:
            return QRect(
                cell_rect.right() - 28 - self._checkbox_width,
                cell_rect.top(),
                self._checkbox_width,
                cell_rect.height(),
            )
        return QRect(cell_rect.left() + 8, cell_rect.top(),
                     self._checkbox_width, cell_rect.height())

    # ── QStyledItemDelegate interface ─────────────────────────────────────────

    def initStyleOption(self, option, index) -> None:
        super().initStyleOption(option, index)
        if QApplication.layoutDirection() == Qt.RightToLeft:
            option.direction       = Qt.LayoutDirection.RightToLeft
            option.displayAlignment = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter
        else:
            option.direction       = Qt.LayoutDirection.LeftToRight
            option.displayAlignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter
        option.textElideMode   = Qt.TextElideMode.ElideMiddle

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        cell_rect = QRect(option.rect)
        painter.save()

        # Suppress Qt's default selection fill — the view's drawRow handles it.
        opt.state &= ~QStyle.State_Selected
        opt.state &= ~QStyle.State_HasFocus
        opt.backgroundBrush = QBrush(Qt.NoBrush)

        text_color = QColor(get_colors().text_primary)
        opt.palette.setColor(QPalette.Text, text_color)
        opt.palette.setColor(QPalette.HighlightedText, text_color)

        # Model-level background (error / changed-highlight brush).
        if option.backgroundBrush.style() != Qt.NoBrush:
            painter.fillRect(cell_rect.adjusted(0, 1, 0, -1), option.backgroundBrush)

        table = self.parent()
        row   = index.row()

        # ── Should we show the checkbox? ──────────────────────────────────────
        show_cb   = False
        is_checked = False
        if self._show_checkbox and self._panel is not None and table is not None:
            try:
                model      = self._panel._model
                vis        = model._visible
                if 0 <= row < len(vis):
                    sel_model  = table.selectionModel()
                    is_selected = bool(sel_model and sel_model.isRowSelected(row, QModelIndex()))
                    is_checked = is_selected
                    is_hover    = (hasattr(table, '_hovered_row') and table._hovered_row == row)
                    show_cb     = is_selected or is_hover
            except Exception:
                pass

        # ── Resolve file icon ─────────────────────────────────────────────────
        icon = None
        if self._panel is not None:
            try:
                model = self._panel._model
                vis   = model._visible
                if 0 <= row < len(vis):
                    icon = self._panel._track_icon(model._tracks[vis[row]])
            except Exception:
                pass

        # ── Layout ─────────────────────────────────────────────────────────────
        # Win11 RTL order (right→left on screen):
        #   [CB_INSET][circle][CB_GAP] | [icon][icon_gap] | [text extends left]
        # Win11 LTR order (left→right on screen):
        #   [CB_INSET][circle][CB_GAP] | [icon][icon_gap] | [text extends right]
        # ──────────────────────────────────────────────────────────────────────
        is_rtl = QApplication.layoutDirection() == Qt.RightToLeft
        iy = cell_rect.top() + (cell_rect.height() - self._ICON_SIZE) // 2
        margin_x = 28 if (is_rtl and self._show_checkbox) else 8

        if is_rtl:
            # ── RTL path ──────────────────────────────────────────────────────
            # Checkbox on the RIGHT (leading edge in RTL)
            if self._show_checkbox:
                cb_zone = QRect(
                    cell_rect.right() - margin_x - self._checkbox_width,
                    cell_rect.top(), self._checkbox_width, cell_rect.height(),
                )
                if show_cb:
                    self._draw_checkbox(painter, cb_zone, is_checked)

            # Icon immediately left of the checkbox (or right edge if no checkbox)
            icon_right = (
                cell_rect.right() - margin_x - self._checkbox_width - self._PAD_X
                if self._show_checkbox
                else cell_rect.right() - margin_x - self._PAD_X
            )
            icon_left = icon_right - self._ICON_SIZE
            if icon is not None and not icon.isNull():
                icon.paint(painter, QRect(icon_left, iy, self._ICON_SIZE, self._ICON_SIZE))
                text_right = icon_left - self._ICON_GAP
            else:
                text_right = icon_right

            text_rect = QRect(
                cell_rect.left() + self._PAD_X,
                cell_rect.top() + 1,
                max(0, text_right - cell_rect.left() - self._PAD_X),
                cell_rect.height() - 2,
            )
        else:
            # ── LTR path ──────────────────────────────────────────────────────
            x = cell_rect.left() + margin_x

            # Checkbox on the LEFT (leading edge in LTR)
            if self._show_checkbox:
                cb_zone = QRect(x, cell_rect.top(), self._checkbox_width, cell_rect.height())
                if show_cb:
                    self._draw_checkbox(painter, cb_zone, is_checked)
                x += self._checkbox_width

            # Icon immediately after checkbox (or left pad if no checkbox)
            if icon is not None and not icon.isNull():
                ix = x + self._PAD_X
                icon.paint(painter, QRect(ix, iy, self._ICON_SIZE, self._ICON_SIZE))
                x = ix + self._ICON_SIZE + self._ICON_GAP
            else:
                x += self._PAD_X

            text_rect = QRect(
                x, cell_rect.top() + 1,
                max(0, cell_rect.right() - self._PAD_X - x),
                cell_rect.height() - 2,
            )

        opt.rect = text_rect
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)

        painter.restore()

    # ── Inline rename: exclude extension from initial selection ───────────────

    def createEditor(self, parent, option, index) -> QWidget:
        editor = super().createEditor(parent, option, index)
        return editor

    def setEditorData(self, editor, index) -> None:
        super().setEditorData(editor, index)
        from PySide6.QtWidgets import QLineEdit
        if isinstance(editor, QLineEdit):
            text = editor.text()
            # Select everything except the file extension so renaming is natural.
            dot = text.rfind(".")
            if dot > 0:
                editor.setSelection(0, dot)
            else:
                editor.selectAll()

    # ── Private ───────────────────────────────────────────────────────────────

    def _draw_checkbox(self, painter: QPainter, zone: QRect, is_checked: bool) -> None:
        """Draw a Win11-style circular checkbox centered in zone."""
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        # In RTL the inset is on the right end of the zone; in LTR on the left.
        if QApplication.layoutDirection() == Qt.RightToLeft:
            cx = zone.right() - self._CB_INSET - self._CB_SIZE // 2
        else:
            cx = zone.left() + self._CB_INSET + self._CB_SIZE // 2
        cy = zone.top() + zone.height() // 2
        r  = self._CB_SIZE // 2

        if is_checked:
            painter.setBrush(QBrush(QColor(ACCENT_COLOR)))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(cx - r, cy - r, self._CB_SIZE, self._CB_SIZE)
            # Checkmark
            pen = QPen(QColor("#ffffff"), 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawLine(cx - 4, cy + 1, cx - 1, cy + 4)
            painter.drawLine(cx - 1, cy + 4, cx + 5, cy - 3)
        else:
            border = QColor(get_colors().text_secondary)
            border.setAlpha(150)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(border, 1.5))
            painter.drawEllipse(cx - r + 1, cy - r + 1, self._CB_SIZE - 2, self._CB_SIZE - 2)

        painter.restore()



class _MetadataHeaderView(QHeaderView):
    """Custom horizontal header that draws a Win11-style circular 'Select All' checkbox
    in the filename column, perfectly aligned with the row checkboxes."""
    
    toggled = Signal(bool)

    def __init__(self, table, panel):
        super().__init__(Qt.Orientation.Horizontal, table)
        self._table = table
        self._panel = panel
        self._is_checked = False
        self.setMouseTracking(True)
        if QApplication.layoutDirection() == Qt.RightToLeft:
            self.setDefaultAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter)
        else:
            self.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter)

    def setChecked(self, checked: bool):
        if self._is_checked != checked:
            self._is_checked = checked
            self.viewport().update()

    def _get_cb_rect(self, logicalIndex, rect):
        from ui.models.metadata_table_model import COL_FILENAME
        if logicalIndex != COL_FILENAME:
            return QRect()
            
        is_rtl = QApplication.layoutDirection() == Qt.RightToLeft
        margin_x = 28 if is_rtl else 8
        CB_SIZE = 16
        CB_INSET = 8
        cb_width = CB_SIZE + CB_INSET + 6
        
        if is_rtl:
            return QRect(rect.right() - margin_x - cb_width, rect.top(), cb_width, rect.height())
        else:
            return QRect(rect.left() + margin_x, rect.top(), cb_width, rect.height())

    def _draw_resize_grip(self, painter: QPainter, rect: QRect, logicalIndex: int) -> None:
        """Draw the subtle Windows-like separator that marks resize handles."""
        if self.isSectionHidden(logicalIndex) or rect.width() <= 0:
            return

        is_rtl = self.isRightToLeft()
        colors = get_colors()
        line = QColor(colors.border)
        line.setAlpha(185)
        
        x = rect.left() if is_rtl else rect.right()
        top = rect.top() + 7
        bottom = rect.bottom() - 7
        if bottom <= top:
            return

        painter.save()
        painter.setClipping(False)
        painter.setPen(QPen(line, 1))
        painter.drawLine(x, top, x, bottom)
        painter.restore()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self.viewport())
        try:
            for logical in range(self.count()):
                if self.isSectionHidden(logical):
                    continue
                x = self.sectionViewportPosition(logical)
                rect = QRect(x, 0, self.sectionSize(logical), self.height())
                if rect.intersects(self.viewport().rect()):
                    self._draw_resize_grip(painter, rect, logical)
        finally:
            painter.end()

    def paintSection(self, painter, rect, logicalIndex):
        super().paintSection(painter, rect, logicalIndex)
        
        cb_rect = self._get_cb_rect(logicalIndex, rect)
        if not cb_rect.isValid():
            return
        
        from ui.theme_manager import get_colors, ACCENT_COLOR
        colors = get_colors()
        is_rtl = self.isRightToLeft()

        # --- Step 1: Clear the text/overlap area with normal header background ---
        bg_main = QColor(colors.bg)
        painter.save()
        painter.setClipping(False)
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg_main)
        if is_rtl:
            clear_rect = QRect(cb_rect.left() - 2, rect.top(),
                               rect.right() - cb_rect.left() + 2, rect.height())
        else:
            clear_rect = QRect(rect.left(), rect.top(),
                               cb_rect.right() - rect.left() + 2, rect.height())
        painter.drawRect(clear_rect)
        painter.restore()

        # --- Step 2: Draw the gray square background only around the circle ---
        bg_square = QColor(colors.surface2)
        painter.save()
        painter.setClipping(False)
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg_square)
        gray_rect = QRect(cb_rect.left() - 2, rect.top(), cb_rect.width() + 4, rect.height())
        painter.drawRect(gray_rect)
        painter.restore()

        # --- Step 3: Redraw the header text in the safe area (left of circle) ---
        header_text = self.model().headerData(logicalIndex, Qt.Horizontal, Qt.DisplayRole) or ""
        if header_text:
            painter.save()
            painter.setClipping(False)
            painter.setFont(self.font())
            painter.setPen(QColor(colors.text_secondary))
            PADDING = 8
            if is_rtl:
                text_rect = QRect(rect.left() + PADDING, rect.top(),
                                  cb_rect.left() - rect.left() - PADDING * 2, rect.height())
                # AlignAbsolute forces physical-right regardless of RTL layout direction
                align = (Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute
                         | Qt.AlignmentFlag.AlignVCenter)
            else:
                text_rect = QRect(cb_rect.right() + PADDING, rect.top(),
                                  rect.right() - cb_rect.right() - PADDING * 2, rect.height())
                align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            if text_rect.width() > 0:
                fm = painter.fontMetrics()
                elided = fm.elidedText(header_text, Qt.ElideRight, text_rect.width())
                painter.drawText(text_rect, align, elided)
            painter.restore()

        # --- Step 4: Draw the circle on top ---
        painter.save()
        painter.setClipping(False)
        painter.setRenderHint(QPainter.Antialiasing, True)
        
        CB_SIZE = 16
        CB_INSET = 8
        if is_rtl:
            cx = cb_rect.right() - CB_INSET - CB_SIZE // 2
        else:
            cx = cb_rect.left() + CB_INSET + CB_SIZE // 2
        cy = cb_rect.top() + cb_rect.height() // 2
        r = CB_SIZE // 2
        
        if self._is_checked:
            painter.setBrush(QBrush(QColor(ACCENT_COLOR)))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(cx - r, cy - r, CB_SIZE, CB_SIZE)
            pen = QPen(QColor("#ffffff"), 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawLine(cx - 4, cy + 1, cx - 1, cy + 4)
            painter.drawLine(cx - 1, cy + 4, cx + 5, cy - 3)
        else:
            border = QColor(colors.text_secondary)
            border.setAlpha(150)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(border, 1.5))
            painter.drawEllipse(cx - r + 1, cy - r + 1, CB_SIZE - 2, CB_SIZE - 2)
            
        painter.restore()

    def mousePressEvent(self, e):
        logicalIndex = self.logicalIndexAt(e.position().toPoint().x())
        if logicalIndex >= 0:
            x = self.sectionViewportPosition(logicalIndex)
            w = self.sectionSize(logicalIndex)
            rect = QRect(x, 0, w, self.height())
            
            cb_rect = self._get_cb_rect(logicalIndex, rect)
            hit_rect = cb_rect.adjusted(-4, -4, 4, 4)
            
            if hit_rect.contains(e.position().toPoint()):
                self.setChecked(not self._is_checked)
                self.toggled.emit(self._is_checked)
                return
                
        super().mousePressEvent(e)


class _ExplorerTableStyle(QProxyStyle):
    """QProxyStyle applied to the table view.

    Qt's default QAbstractItemView.drawRow() calls
    QStyle.PE_PanelItemViewRow which draws a FLAT selection rectangle on top
    of our capsule.  This proxy intercepts that primitive and suppresses it so
    _ExplorerFileListView.drawRow() is the sole painter of row backgrounds.

    It also clears State_Selected from CE_ItemViewItem calls so that
    qfluentwidgets (and any other style engine) cannot add per-cell selection
    borders or blue left-edge indicators on top of our capsule fill.
    """

    def drawPrimitive(self, element, option, painter, widget=None):
        if element in (QStyle.PE_PanelItemViewRow, QStyle.PE_PanelItemViewItem):
            return   # drawRow capsule is sole row-background painter
        super().drawPrimitive(element, option, painter, widget)

    def drawControl(self, element, option, painter, widget=None):
        if (element == QStyle.CE_ItemViewItem
                and isinstance(option, QStyleOptionViewItem)
                and (option.state & QStyle.State_Selected)):
            opt = QStyleOptionViewItem(option)
            opt.state &= ~QStyle.State_Selected
            opt.state &= ~QStyle.State_HasFocus
            super().drawControl(element, opt, painter, widget)
            return
        super().drawControl(element, option, painter, widget)


class _ExplorerFileListView(QTableView):
    """QTableView with Explorer-like empty-area deselect and rubber-band rows."""

    _SIDE_EMPTY_GUTTER = 28

    def __init__(self, panel=None, parent=None) -> None:
        super().__init__(parent)
        self._panel = panel
        self._rubber_origin = QPoint()
        self._rubber_active = False
        self._rubber_dragging = False
        self._rubber_modifiers = Qt.NoModifier
        self._rubber_base_selection = QItemSelection()
        self._pending_cb_row = -1   # row whose checkbox toggle is deferred to mouse-release
        self._hovered_row = -1
        # Rubber-band geometry tracked as a plain QRect; drawn directly in
        # paintEvent so SourceOver alpha works without WA_TranslucentBackground.
        self._rubber_rect = QRect()
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

        # Win11 Details View row geometry — 40 px tall, no grid.
        vh = self.verticalHeader()
        vh.setDefaultSectionSize(40)
        vh.setMinimumSectionSize(40)

        # Win11-style inset: small margins around the content area so the row
        # capsule visually floats inside the panel (left/right/bottom gutter).
        self.setViewportMargins(4, 0, 4, 4)

        # Make the empty area follow the theme by default
        bg = QColor(get_colors().bg)
        pal = self.viewport().palette()
        pal.setColor(QPalette.Base, bg)
        pal.setColor(QPalette.Window, bg)
        self.viewport().setPalette(pal)
        self.viewport().setAutoFillBackground(True)

        # Listen for theme changes and refresh
        from ui.theme_manager import ThemeManager as _TM
        _tm = _TM.instance()
        if _tm is not None:
            _tm.theme_changed.connect(self._refresh_viewport_palette)

    def _refresh_viewport_palette(self) -> None:
        bg = QColor(get_colors().bg)
        pal = self.viewport().palette()
        pal.setColor(QPalette.Base, bg)
        pal.setColor(QPalette.Window, bg)
        self.viewport().setPalette(pal)
        self.viewport().update()

    def paintEvent(self, event) -> None:
        # Fill the entire viewport with the theme background first
        painter = QPainter(self.viewport())
        painter.fillRect(self.viewport().rect(), QColor(get_colors().bg))
        
        # Draw custom selection/hover row backgrounds before drawing cells on top
        model = self.model()
        if model is not None:
            for row in range(model.rowCount()):
                row_y = self.rowViewportPosition(row)
                row_h = self.rowHeight(row)
                # Only paint visible rows
                if row_y + row_h < 0 or row_y > self.viewport().height():
                    continue
                row_rect = QRect(0, row_y, self.viewport().width(), row_h)
                self._paint_explorer_row_background(painter, row_rect, row)
                self._paint_explorer_row_separator(painter, row_rect)
        painter.end()

        # Temporarily make QPalette.Base transparent so super().paintEvent won't clear our drawing
        pal = self.viewport().palette()
        old_base = pal.brush(QPalette.Base)
        pal.setColor(QPalette.Base, Qt.transparent)
        self.viewport().setPalette(pal)

        try:
            # Let Qt draw the cells/grid on top (transparent background)
            super().paintEvent(event)
        finally:
            # Restore the palette
            pal.setBrush(QPalette.Base, old_base)
            self.viewport().setPalette(pal)

        # Draw rubber-band AFTER all cells
        if self._rubber_dragging and not self._rubber_rect.isEmpty():
            painter = QPainter(self.viewport())
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.fillRect(self._rubber_rect, QColor(0, 120, 215, 40))
            painter.setPen(QPen(QColor(0, 120, 215, 180), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self._rubber_rect.adjusted(0, 0, -1, -1))
            painter.end()

    def mousePressEvent(self, event) -> None:
        pos = self._event_pos(event)

        if event.button() == Qt.LeftButton:
            # ── Checkbox hit-test in COL_FILENAME ────────────────────────────
            # Toggle is DEFERRED to mouseReleaseEvent so that dragging from the
            # checkbox zone can still start a rubber-band selection.
            idx = self.indexAt(pos)
            if idx.isValid() and idx.column() == COL_FILENAME:
                delegate = self.itemDelegateForColumn(COL_FILENAME)
                if hasattr(delegate, "checkbox_hit_rect"):
                    cell_rect = self.visualRect(idx)
                    if delegate.checkbox_hit_rect(cell_rect).contains(pos):
                        self._pending_cb_row = idx.row()
                        self._rubber_origin = pos
                        self._rubber_active = True
                        self._rubber_dragging = False
                        self._rubber_modifiers = event.modifiers()
                        self._rubber_rect = QRect()
                        selection_model = self.selectionModel()
                        self._rubber_base_selection = (
                            selection_model.selection()
                            if selection_model is not None else QItemSelection()
                        )
                        self._empty_area_pressed = False
                        event.accept()
                        return

            # ── Rubber-band tracking: start on any left-button press ─────────
            self._rubber_origin = pos
            self._rubber_active = True
            self._rubber_dragging = False
            self._rubber_modifiers = event.modifiers()
            self._rubber_rect = QRect()

            if self._is_empty_viewport_area(pos):
                # Empty area: record base, deselect, handle internally
                selection_model = self.selectionModel()
                self._rubber_base_selection = (
                    selection_model.selection() if selection_model is not None else QItemSelection()
                )
                self.clearSelection()
                self.setCurrentIndex(QModelIndex())
                self._empty_area_pressed = True
                event.accept()
                return
        else:
            self._cancel_rubber_band()
            self._empty_area_pressed = False

        self._empty_area_pressed = False
        super().mousePressEvent(event)
        # After Qt selects the clicked row, snapshot it as the rubber band baseline
        if event.button() == Qt.LeftButton and self._rubber_active:
            selection_model = self.selectionModel()
            self._rubber_base_selection = (
                selection_model.selection() if selection_model is not None else QItemSelection()
            )

    def mouseMoveEvent(self, event) -> None:
        if self._rubber_active and event.buttons() & Qt.LeftButton:
            self._update_empty_area_drag(self._event_pos(event))
            event.accept()
            return

        self._update_hover_row(self._event_pos(event))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._rubber_active:
            was_dragging = self._rubber_dragging
            pending_row = self._pending_cb_row
            empty_pressed = getattr(self, "_empty_area_pressed", False)
            self._empty_area_pressed = False
            self._finish_empty_area_interaction(self._event_pos(event))

            # Fire deferred checkbox toggle (only when no rubber-band drag occurred)
            if not was_dragging and pending_row >= 0:
                row = pending_row
                selection_model = self.selectionModel()
                if selection_model is not None:
                    model = self.model()
                    last_col = model.columnCount() - 1
                    row_selection = QItemSelection(model.index(row, 0), model.index(row, last_col))
                    selection_model.select(row_selection, QItemSelectionModel.Toggle | QItemSelectionModel.Rows)
                self.viewport().update()
                event.accept()
                return

            if empty_pressed or was_dragging:
                event.accept()
                return

        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        pos = self._event_pos(event)
        if self._is_empty_viewport_area(pos):
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def leaveEvent(self, event) -> None:
        self._update_hover_row(QPoint(-1, -1))
        super().leaveEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # Win11 Explorer: Delete (and Shift+Delete) sends selection to the
        # Recycle Bin via the panel's confirm-then-trash flow. The panel
        # owns the dialog + the controller signal — the view just collects
        # paths from the current selection.
        if (
            event.key() == Qt.Key_Delete
            and event.modifiers() in (Qt.NoModifier, Qt.ShiftModifier)
            and self._panel is not None
        ):
            model = self._panel._model
            rows = self.selectionModel().selectedRows()
            paths: list[Path] = []
            for idx in rows:
                r = idx.row()
                if 0 <= r < len(model._visible):
                    paths.append(model._tracks[model._visible[r]].path)
            if paths:
                self._panel._request_delete_files(paths)
            event.accept()
            return
        super().keyPressEvent(event)

    @staticmethod
    def _event_pos(event) -> QPoint:
        if hasattr(event, "position"):
            return event.position().toPoint()
        return event.pos()

    def _cancel_rubber_band(self) -> None:
        self._rubber_active = False
        self._rubber_dragging = False
        self._pending_cb_row = -1
        if not self._rubber_rect.isEmpty():
            self._rubber_rect = QRect()
            self.viewport().update()

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
        self._rubber_rect = QRect()

    def _update_empty_area_drag(self, pos: QPoint) -> None:
        if (
            self._rubber_dragging
            or (pos - self._rubber_origin).manhattanLength() >= QApplication.startDragDistance()
        ):
            self._rubber_dragging = True
            self._scroll_for_rubber(pos)
            self._rubber_rect = QRect(self._rubber_origin, pos).normalized()
            self.viewport().update()
            self._select_rows_in_rubber_band()

    def _finish_empty_area_interaction(self, pos: QPoint) -> None:
        if self._rubber_dragging:
            self._rubber_rect = QRect(self._rubber_origin, pos).normalized()
            self._select_rows_in_rubber_band()
        self._cancel_rubber_band()

    def _explorer_palette(self) -> dict[str, QColor]:
        """Win11 Details-View palette in Microsoft system-accent blue.

        Keys ``base`` / ``row_alt`` track the theme background (used by the
        COL_CHECK gutter strip). ``separator`` is transparent — Win11 has
        no inter-row separator lines. ``hover_border`` is transparent too —
        Win11 hover has fill only, no outline.
        """
        colors = get_colors()
        is_dark = QColor(colors.bg).lightness() < 128
        bg = QColor(colors.bg)
        transparent = QColor(0, 0, 0, 0)
        # Win11 accent blue: #0078D4 = rgb(0, 120, 212)
        accent = QColor(0, 120, 212)
        if is_dark:
            # Selected fill at ~50 % opacity over dark bg gives clearly visible blue.
            sel_fill    = QColor(accent); sel_fill.setAlpha(60)
            sel_fill_ia = QColor(accent); sel_fill_ia.setAlpha(35)   # inactive
            sel_border    = QColor(accent); sel_border.setAlpha(220)
            sel_border_ia = QColor(accent); sel_border_ia.setAlpha(90)
            hover_fill = QColor(255, 255, 255, 18)
            return {
                "base": bg, "row_alt": bg,
                "hover": hover_fill, "hover_border": transparent,
                "selected": sel_fill, "selected_inactive": sel_fill_ia,
                "selected_border": sel_border,
                "selected_inactive_border": sel_border_ia,
                "separator": transparent,
            }
        # Light mode
        sel_fill    = QColor(accent); sel_fill.setAlpha(60)
        sel_fill_ia = QColor(accent); sel_fill_ia.setAlpha(35)   # inactive
        sel_border    = QColor(0, 84, 153, 180)
        sel_border_ia = QColor(0, 84, 153, 90)
        hover_fill = QColor(0, 0, 0, 12)
        return {
            "base": bg, "row_alt": bg,
            "hover": hover_fill, "hover_border": transparent,
            "selected": sel_fill, "selected_inactive": sel_fill_ia,
            "selected_border": sel_border,
            "selected_inactive_border": sel_border_ia,
            "separator": transparent,
        }

    def _content_row_rect(self, row_rect: QRect, row: int) -> QRect:
        model = self.model()
        if model is None or not (0 <= row < model.rowCount()):
            return QRect(8, row_rect.top(), max(0, self.viewport().width() - 16), row_rect.height())

        left: int | None = None
        right: int | None = None
        for logical in range(model.columnCount()):
            if logical == COL_CHECK or self.isColumnHidden(logical):
                continue
            width = self.columnWidth(logical)
            if width <= 0:
                continue
            x = self.columnViewportPosition(logical)
            left = x if left is None else min(left, x)
            right = x + width - 1 if right is None else max(right, x + width - 1)

        if left is None or right is None:
            return QRect()

        rect = QRect(left, row_rect.top(), right - left + 1, row_rect.height())
        rect.adjust(8, 0, -8, 0)
        
        is_rtl = QApplication.layoutDirection() == Qt.RightToLeft
        x_check = self.columnViewportPosition(COL_CHECK)
        w_check = self.columnWidth(COL_CHECK)
        
        if is_rtl:
            # In RTL, the check column is on the left.
            # The capsule's left edge must not overlap the check column's right edge.
            gutter_limit = x_check + w_check
            if rect.left() < gutter_limit:
                rect.setLeft(gutter_limit)
        else:
            # In LTR, the check column is on the right.
            # The capsule's right edge must not overlap the check column's left edge.
            gutter_limit = x_check - 1
            if rect.right() > gutter_limit:
                rect.setRight(max(rect.left(), gutter_limit))
        return rect

    def _empty_side_rect(self) -> QRect:
        if QApplication.layoutDirection() == Qt.LayoutDirection.RightToLeft:
            return QRect(0, 0, self._SIDE_EMPTY_GUTTER, self.viewport().height())
        return QRect(self.viewport().width() - self._SIDE_EMPTY_GUTTER, 0,
                     self._SIDE_EMPTY_GUTTER, self.viewport().height())

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

    # Win11 Details View capsule geometry — inset from row edges, rounded.
    _CAPSULE_INSET_X = 4
    _CAPSULE_INSET_Y = 2
    _CAPSULE_RADIUS  = 4

    def _paint_explorer_row_background(self, painter: QPainter, row_rect: QRect, row: int) -> None:
        colors = self._explorer_palette()
        selection_model = self.selectionModel()
        is_selected = bool(
            selection_model and selection_model.rowIntersectsSelection(row, QModelIndex())
        )
        is_hover = (row == self._hovered_row)
        if not (is_selected or is_hover):
            return

        if is_selected:
            fill_key   = "selected"       if self.hasFocus() else "selected_inactive"
            border_key = "selected_border" if self.hasFocus() else "selected_inactive_border"
        else:
            fill_key   = "hover"
            border_key = "hover_border"

        capsule = self._content_row_rect(row_rect, row).adjusted(
            self._CAPSULE_INSET_X,  self._CAPSULE_INSET_Y,
            -self._CAPSULE_INSET_X, -self._CAPSULE_INSET_Y,
        )
        if capsule.width() <= 0 or capsule.height() <= 0:
            return

        painter.save()
        painter.setClipRect(
            QRect(0, row_rect.top(), self.viewport().width(), row_rect.height()),
            Qt.ReplaceClip,
        )
        painter.setRenderHint(QPainter.Antialiasing, True)
        border = colors[border_key]
        if border.alpha() > 0:
            painter.setPen(QPen(border, 1))
        else:
            painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(colors[fill_key]))
        painter.drawRoundedRect(
            QRectF(capsule),
            self._CAPSULE_RADIUS, self._CAPSULE_RADIUS,
        )
        painter.restore()

    def _paint_explorer_row_separator(self, painter: QPainter, row_rect: QRect) -> None:
        # Win11 Details View has no inter-row separator lines.
        return

    def _is_empty_viewport_area(self, pos: QPoint) -> bool:
        if not self.viewport().rect().contains(pos):
            return True

        is_rtl = QApplication.layoutDirection() == Qt.RightToLeft

        # Check side empty gutter based on layout direction
        if is_rtl:
            # In RTL, the left side of the viewport (0 to 28) is the empty gutter.
            if pos.x() < self._SIDE_EMPTY_GUTTER:
                return True
        else:
            # In LTR, the right side of the viewport (width - 28 to width) is the empty gutter.
            if pos.x() >= self.viewport().width() - self._SIDE_EMPTY_GUTTER:
                return True

        idx = self.indexAt(pos)
        if not idx.isValid():
            return True

        # Check specific column margins
        if idx.column() == COL_CHECK:
            return True

        # In RTL, the Name column (COL_FILENAME) is visual index 0 (far right) and has a 28px empty margin on its right side.
        if is_rtl and idx.column() == COL_FILENAME:
            cell_rect = self.visualRect(idx)
            if cell_rect.isValid() and pos.x() >= cell_rect.right() - self._SIDE_EMPTY_GUTTER:
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

        rubber_rect = self._rubber_rect.normalized()
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


class _MoreColumnsDialog(QDialog):
    """Scrollable, searchable list of all table columns — mirrors Windows
    Explorer's 'Choose details…' dialog that appears from 'More…' in the
    column header context menu."""

    def __init__(self, table_view: QTableView, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("mt_more_columns_title"))
        self.resize(360, 460)
        self._table = table_view

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Search bar
        self._search = QLineEdit()
        self._search.setPlaceholderText(t("mt_search_columns"))
        self._search.textChanged.connect(self._on_search)
        layout.addWidget(self._search)

        # Scrollable column list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        content = QWidget()
        self._list_layout = QVBoxLayout(content)
        self._list_layout.setSpacing(4)
        self._list_layout.setContentsMargins(4, 4, 4, 4)

        # Always-visible columns that can't be hidden
        ALWAYS_VISIBLE = {COL_FILENAME}
        # Columns never offered in any menu
        NO_MENU = {COL_CHECK}

        self._rows: list[tuple[int, str, QCheckBox]] = []
        for col in range(COLUMN_COUNT):
            if col in NO_MENU:
                continue
            key = _HEADER_KEYS[col] if col < len(_HEADER_KEYS) else ""
            label = t(key) if key else ""
            if not label:
                continue
            cb = QCheckBox(label)
            cb.setChecked(not table_view.isColumnHidden(col))
            if col in ALWAYS_VISIBLE:
                cb.setEnabled(False)
            self._rows.append((col, label, cb))
            self._list_layout.addWidget(cb)

        self._list_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, stretch=1)

        # OK / Cancel
        btns = QHBoxLayout()
        btns.addStretch()
        cancel_btn = QPushButton(t("meta_cancel"))
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton(t("meta_ok"))
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._accept)
        btns.addWidget(cancel_btn)
        btns.addWidget(ok_btn)
        layout.addLayout(btns)

    def _on_search(self, text: str) -> None:
        needle = text.casefold()
        for _, label, cb in self._rows:
            cb.setVisible(not needle or needle in label.casefold())

    def _accept(self) -> None:
        for col, _, cb in self._rows:
            self._table.setColumnHidden(col, not cb.isChecked())
        self.accept()


class _AutoArrangeSettingsDialog(QDialog):
    """Choose which magic operations the 🪄 auto-arrange button runs."""

    def __init__(self, enabled: set[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("meta_auto_settings_title"))
        self.resize(400, 480)

        self._result = set(enabled)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        hdr = QLabel(t("meta_auto_header"))
        hdr.setStyleSheet("font-weight: bold;")
        layout.addWidget(hdr)

        note = QLabel(t("meta_auto_album_note"))
        note.setStyleSheet(f"color: {get_colors().text_secondary}; font-size: 11px;")
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
        for key, label_key, desc_key in _MAGIC_OP_DEFS:
            label = t(label_key)
            desc  = t(desc_key)
            row = QHBoxLayout()
            row.setSpacing(4)
            cb = QCheckBox(label)
            cb.setChecked(key in enabled)
            self._cbs[key] = cb
            row.addWidget(cb)

            info_btn = QPushButton("ℹ️")
            info_btn.setFixedSize(20, 20)
            info_btn.setStyleSheet(f"QPushButton {{ border: none; background: transparent; font-size: 14px; color: {get_colors().text_secondary}; }} QPushButton:hover {{ color: {ACCENT_COLOR}; }}")
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
        cancel_btn = QPushButton(t("meta_cancel"))
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton(t("meta_ok"))
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


class _CleanSettingsDialog(QDialog):
    """Choose how aggressive the cleaning features should be."""

    def __init__(self, cfg, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("meta_clean_settings_title"))
        self.resize(380, 400)
        self._cfg = cfg

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Title clean settings
        title_grp = QGroupBox(t("meta_clean_title_group"))
        title_lay = QVBoxLayout(title_grp)
        title_lay.setSpacing(6)

        self.cb_title_brackets = QCheckBox(t("meta_clean_brackets"))
        self.cb_title_brackets.setChecked(getattr(self._cfg, "tag_clean_title_remove_brackets", True))

        self.cb_title_english = QCheckBox(t("meta_clean_english_junk"))
        self.cb_title_english.setChecked(getattr(self._cfg, "tag_clean_title_remove_web_junk", True))

        self.cb_title_hebrew = QCheckBox(t("meta_clean_hebrew_junk"))
        self.cb_title_hebrew.setChecked(getattr(self._cfg, "tag_clean_title_remove_hebrew", True))

        self.cb_title_punc = QCheckBox(t("meta_clean_punctuation"))
        self.cb_title_punc.setChecked(getattr(self._cfg, "tag_clean_title_fix_punctuation", True))

        title_lay.addWidget(self.cb_title_brackets)
        title_lay.addWidget(self.cb_title_english)
        title_lay.addWidget(self.cb_title_hebrew)
        title_lay.addWidget(self.cb_title_punc)
        layout.addWidget(title_grp)

        # Filename clean settings
        fn_grp = QGroupBox(t("meta_clean_filename_group"))
        fn_lay = QVBoxLayout(fn_grp)
        fn_lay.setSpacing(6)

        self.cb_fn_brackets = QCheckBox(t("meta_clean_filename_brackets"))
        self.cb_fn_brackets.setChecked(getattr(self._cfg, "tag_clean_filename_smart_brackets", True))
        self.cb_fn_brackets.setToolTip(t("meta_clean_filename_brackets_tooltip"))

        self.cb_fn_domains = QCheckBox(t("meta_clean_filename_domains"))
        self.cb_fn_domains.setChecked(getattr(self._cfg, "tag_clean_filename_remove_domains", True))

        self.cb_fn_emojis = QCheckBox(t("meta_clean_filename_emojis"))
        self.cb_fn_emojis.setChecked(getattr(self._cfg, "tag_clean_filename_remove_emojis", True))

        self.cb_fn_spaces = QCheckBox(t("meta_clean_filename_spaces"))
        self.cb_fn_spaces.setChecked(getattr(self._cfg, "tag_clean_filename_fix_spaces", True))

        fn_lay.addWidget(self.cb_fn_brackets)
        fn_lay.addWidget(self.cb_fn_domains)
        fn_lay.addWidget(self.cb_fn_emojis)
        fn_lay.addWidget(self.cb_fn_spaces)
        layout.addWidget(fn_grp)

        layout.addStretch()

        row = QHBoxLayout()
        row.addStretch()
        cancel_btn = QPushButton(t("meta_cancel"))
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton(t("meta_save_ok"))
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._accept)
        row.addWidget(cancel_btn)
        row.addWidget(ok_btn)
        layout.addLayout(row)

    def _accept(self) -> None:
        if self._cfg:
            self._cfg.tag_clean_title_remove_brackets = self.cb_title_brackets.isChecked()
            self._cfg.tag_clean_title_remove_web_junk = self.cb_title_english.isChecked()
            self._cfg.tag_clean_title_remove_hebrew = self.cb_title_hebrew.isChecked()
            self._cfg.tag_clean_title_fix_punctuation = self.cb_title_punc.isChecked()
            
            self._cfg.tag_clean_filename_smart_brackets = self.cb_fn_brackets.isChecked()
            self._cfg.tag_clean_filename_remove_domains = self.cb_fn_domains.isChecked()
            self._cfg.tag_clean_filename_remove_emojis = self.cb_fn_emojis.isChecked()
            self._cfg.tag_clean_filename_fix_spaces = self.cb_fn_spaces.isChecked()
            self._cfg.save()
        self.accept()


def _btn_style() -> str:
    """Standard op-button style (theme-aware, called fresh each time)."""
    c = get_colors()
    return (
        f"QPushButton {{ background: {c.surface}; color: {c.text_primary};"
        f"  border: 1px solid {c.border};"
        f"  border-radius: 4px; padding: 3px 5px; text-align: left; font-size: 10px; }}"
        f"QPushButton:hover {{ background: {c.surface2}; border-color: {ACCENT_COLOR}; }}"
        f"QPushButton:pressed {{ background: {c.border}; }}"
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
    delete_files_requested      = Signal(list)           # list[Path] (Delete key)

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
        self._ignore_header_resize = True

        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_toolbar())

        self._toolbar_sep = QFrame()
        self._toolbar_sep.setFrameShape(QFrame.Shape.HLine)
        self._toolbar_sep.setFixedHeight(1)
        self._toolbar_sep.setStyleSheet(f"background: {get_colors().border}; border: none;")
        root_layout.addWidget(self._toolbar_sep)

        root_layout.addWidget(self._build_body(), stretch=1)

        from ui.theme_manager import ThemeManager as _TM
        _tm = _TM.instance()
        if _tm is not None:
            _tm.theme_changed.connect(self._apply_theme)
        self._apply_theme()

    def _apply_theme(self) -> None:
        """Re-apply theme-dependent styles for the toolbar, tree, table, buttons."""
        c = get_colors()
        accent_dim = _md_dim_hex(ACCENT_COLOR)

        # Toolbar
        if hasattr(self, "_toolbar_bar"):
            self._toolbar_bar.setStyleSheet(
                f"QFrame {{ background: {c.surface}; border-bottom: 1px solid {c.border}; }}"
            )
        if hasattr(self, "_toolbar_sep"):
            self._toolbar_sep.setStyleSheet(f"background: {c.border}; border: none;")
        if hasattr(self, "_folder_lbl"):
            self._folder_lbl.setStyleSheet(f"color: {c.text_secondary}; font-size: 12px;")
        if hasattr(self, "_summary_lbl"):
            self._summary_lbl.setStyleSheet(f"color: {c.text_secondary}; font-size: 11px;")

        # "Sort automatic" primary button
        if hasattr(self, "_auto_btn"):
            self._auto_btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: {ACCENT_COLOR}; color: #000; font-weight: bold;"
                f"  border-radius: 6px; padding: 0 14px;"
                f"}}"
                f"QPushButton:hover {{ background: {accent_dim}; }}"
                f"QPushButton:disabled {{ background: {c.surface2}; color: {c.text_tertiary}; }}"
            )

        # Gear button
        if hasattr(self, "_auto_cfg_btn"):
            self._auto_cfg_btn.setStyleSheet(
                f"QPushButton {{ background: {c.surface2}; color: {c.text_primary};"
                f"  border: 1px solid {c.border}; border-radius: 4px; font-size: 14px; }}"
                f"QPushButton:hover {{ background: {c.border}; }}"
            )

        # Splitter handle
        if hasattr(self, "_body_splitter"):
            self._body_splitter.setStyleSheet(
                f"QSplitter::handle {{ background: {c.border}; }}"
                f"QSplitter::handle:hover {{ background: {ACCENT_COLOR}; }}"
                f"QSplitter::handle:pressed {{ background: {accent_dim}; }}"
            )

        # Tree widget
        if hasattr(self, "_tree"):
            self._tree.setStyleSheet(
                f"QTreeWidget {{ border: none; background: {c.bg}; color: {c.text_primary}; }}"
                f"QTreeWidget::viewport {{ background: {c.bg}; }}"
                f"QTreeWidget::item {{ padding: 3px 2px; }}"
                f"QTreeWidget::item:selected {{ background: {ACCENT_COLOR}33; color: {c.text_primary}; }}"
                f"QTreeWidget::item:hover {{ background: {c.surface2}; }}"
            )
            tree_pal = self._tree.viewport().palette()
            tree_pal.setColor(QPalette.Base, QColor(c.bg))
            tree_pal.setColor(QPalette.Window, QColor(c.bg))
            self._tree.viewport().setPalette(tree_pal)
            self._tree.viewport().setAutoFillBackground(True)

        # Zoom controls
        zoom_btn_qss = (
            f"QPushButton {{ background: {c.surface2}; color: {c.text_primary};"
            f"  border: 1px solid {c.border}; border-radius: 3px;"
            f"  font-weight: bold; font-size: 14px; }}"
            f"QPushButton:hover {{ background: {c.border}; }}"
        )
        if hasattr(self, "_zoom_minus_btn"):
            self._zoom_minus_btn.setStyleSheet(zoom_btn_qss)
        if hasattr(self, "_zoom_plus_btn"):
            self._zoom_plus_btn.setStyleSheet(zoom_btn_qss)
        if hasattr(self, "_zoom_val_lbl"):
            self._zoom_val_lbl.setStyleSheet(
                f"QLineEdit {{ background: {c.surface}; color: {c.text_primary};"
                f"  border: 1px solid {c.border}; border-radius: 3px;"
                f"  font-size: 11px; padding: 0px 2px; }}"
            )
        if hasattr(self, "_zoom_lbl"):
            self._zoom_lbl.setStyleSheet(
                f"font-size: 13px; color: {c.text_secondary}; margin-left: 4px;"
            )
        if hasattr(self, "_table_info_lbl"):
            self._table_info_lbl.setStyleSheet(
                f"color: {c.text_secondary}; font-size: 11px;"
            )

        # Re-apply zoom (rebuilds the table stylesheet with current theme colors)
        if hasattr(self, "_zoom_level") and hasattr(self, "_table"):
            try:
                self._set_zoom(self._zoom_level)
            except Exception:
                pass

        # Also explicitly paint the table viewport so the empty area follows theme
        if hasattr(self, "_table"):
            tc = get_colors()
            self._table.viewport().setStyleSheet(f"background: {tc.bg};")
            pal = self._table.viewport().palette()
            pal.setColor(QPalette.Base, QColor(tc.bg))
            pal.setColor(QPalette.Window, QColor(tc.bg))
            self._table.viewport().setPalette(pal)
            self._table.viewport().setAutoFillBackground(True)
            self._table.viewport().update()

    def _build_toolbar(self) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(56)
        self._toolbar_bar = bar

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(8)

        self._browse_btn = QPushButton(t("meta_browse_folder"))
        self._browse_btn.setFixedHeight(32)
        self._browse_btn.clicked.connect(self._on_browse)
        layout.addWidget(self._browse_btn)

        self._folder_lbl = QLabel(t("meta_no_folder_selected"))
        self._folder_lbl.setMaximumWidth(260)
        layout.addWidget(self._folder_lbl)

        self._subdirs_cb = QCheckBox(t("meta_include_subdirs"))
        self._subdirs_cb.setChecked(True)
        layout.addWidget(self._subdirs_cb)

        layout.addStretch()

        auto_wrap = QHBoxLayout()
        auto_wrap.setSpacing(2)
        self._auto_btn = QPushButton(t("meta_auto_btn"))
        self._auto_btn.setFixedHeight(34)
        self._auto_btn.setEnabled(False)
        self._auto_btn.clicked.connect(self._on_auto_arrange)
        auto_wrap.addWidget(self._auto_btn)

        self._auto_cfg_btn = QPushButton("⚙")
        self._auto_cfg_btn.setFixedSize(28, 34)
        self._auto_cfg_btn.setToolTip(t("meta_auto_cfg_tooltip"))
        self._auto_cfg_btn.clicked.connect(self._on_auto_arrange_settings)
        auto_wrap.addWidget(self._auto_cfg_btn)
        layout.addLayout(auto_wrap)

        self._apply_btn = QPushButton(t("meta_apply_changes"))
        self._apply_btn.setFixedHeight(32)
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._on_apply)
        layout.addWidget(self._apply_btn)

        self._revert_btn = QPushButton(t("meta_revert_changes"))
        self._revert_btn.setFixedHeight(32)
        self._revert_btn.setEnabled(False)
        self._revert_btn.clicked.connect(self._on_revert)
        layout.addWidget(self._revert_btn)

        self._dupes_btn = QPushButton(t("meta_find_duplicates"))
        self._dupes_btn.setFixedHeight(32)
        self._dupes_btn.setEnabled(False)
        self._dupes_btn.setToolTip(t("meta_dupes_tooltip"))
        self._dupes_btn.clicked.connect(self._on_find_duplicates)
        layout.addWidget(self._dupes_btn)

        layout.addStretch()

        self._summary_lbl = QLabel(t("meta_no_folder_scanned"))
        layout.addWidget(self._summary_lbl)

        return bar

    def _build_body(self) -> QSplitter:
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(True)
        splitter.setHandleWidth(5)
        self._body_splitter = splitter

        # ── Left: folder/file tree ────────────────────────────────────────────
        tree_frame = QFrame()
        tree_frame.setMinimumWidth(70)
        tree_layout = QVBoxLayout(tree_frame)
        tree_layout.setContentsMargins(4, 4, 0, 4)
        tree_layout.setSpacing(4)

        tree_header = QLabel(t("meta_files_folders_header"))
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
        self._zoom_lbl = QLabel("🔍")
        tbl_head.addWidget(self._zoom_lbl)

        self._zoom_minus_btn = QPushButton("-")
        self._zoom_minus_btn.setFixedSize(26, 26)
        self._zoom_minus_btn.clicked.connect(self._on_zoom_minus)
        tbl_head.addWidget(self._zoom_minus_btn)

        self._zoom_val_lbl = QLineEdit("100%")
        self._zoom_val_lbl.setFixedSize(50, 26)
        self._zoom_val_lbl.setAlignment(Qt.AlignCenter)
        self._zoom_val_lbl.editingFinished.connect(self._on_zoom_custom)
        tbl_head.addWidget(self._zoom_val_lbl)

        self._zoom_plus_btn = QPushButton("+")
        self._zoom_plus_btn.setFixedSize(26, 26)
        self._zoom_plus_btn.clicked.connect(self._on_zoom_plus)
        tbl_head.addWidget(self._zoom_plus_btn)
        
        tbl_head.addSpacing(10)
        tbl_head.addStretch()

        self._table_info_lbl = QLabel("")
        tbl_head.addWidget(self._table_info_lbl)
        table_layout.addLayout(tbl_head)

        self._table = _ExplorerFileListView(panel=self)
        # Suppress Qt's built-in row selection fill so our drawRow capsule
        # is the sole selection visual (no qfluentwidgets per-cell borders).
        # setStyle() does NOT transfer ownership — store in instance var so
        # Python GC doesn't destroy the object and leave Qt with a dangling ptr.
        self._explorer_table_style = _ExplorerTableStyle(self._table.style())
        self._table.setStyle(self._explorer_table_style)
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # EditKeyPressed = F2 on Windows (Qt platform edit key) — matches
        # Win11 Explorer rename behavior.
        self._table.setEditTriggers(
            QAbstractItemView.DoubleClicked |
            QAbstractItemView.SelectedClicked |
            QAbstractItemView.AnyKeyPressed  |
            QAbstractItemView.EditKeyPressed
        )
        self._table.setAlternatingRowColors(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setWordWrap(False)
        # Layout direction inherits from the app (RTL for Hebrew, LTR for
        # English). The filename columns get a per-column LTR delegate below
        # so file paths read correctly in either mode.
        self._table.setItemDelegate(
            _ExplorerFileListDelegate(self._table, panel=self)
        )
        # Filename columns get their own delegate: LTR, ElideMiddle, icon, checkbox.
        self._table.setItemDelegateForColumn(
            COL_FILENAME,
            _FilenameDelegate(self._table, panel=self, show_checkbox=True),
        )
        self._table.setItemDelegateForColumn(
            COL_FILENAME_NEW,
            _FilenameDelegate(self._table, panel=self, show_checkbox=False),
        )

        hdr = _MetadataHeaderView(self._table, self)
        self._table.setHorizontalHeader(hdr)
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        hdr.setStretchLastSection(False)
        hdr.setContextMenuPolicy(Qt.CustomContextMenu)
        hdr.customContextMenuRequested.connect(self._on_header_context_menu)
        hdr.toggled.connect(self._on_select_all_toggled)

        # Restore or set default column visibility
        default_hidden = {COL_GENRE_CUR, COL_GENRE_NEW, COL_COMMENT_CUR, COL_COMMENT_NEW}
        saved_visibility = None
        if self._cfg:
            saved_visibility = self._cfg.tag_editor_column_visibility
        for col in range(COLUMN_COUNT):
            if col == COL_CHECK or col == COL_FILENAME:
                self._table.setColumnHidden(col, False)
            elif saved_visibility is not None:
                self._table.setColumnHidden(col, col in saved_visibility)
            else:
                self._table.setColumnHidden(col, col in default_hidden)

        # Allow drag reordering. Restore order from config or apply default.
        hdr.setSectionsMovable(True)
        hdr.setSectionResizeMode(COL_CHECK, QHeaderView.Fixed)

        saved_order = None
        if self._cfg:
            saved_order = self._cfg.tag_editor_column_order

        hdr.blockSignals(True)
        try:
            if saved_order and len(saved_order) == COLUMN_COUNT:
                for visual_idx, logical_idx in enumerate(saved_order):
                    current_visual = hdr.visualIndex(logical_idx)
                    if current_visual != visual_idx:
                        hdr.moveSection(current_visual, visual_idx)
            else:
                # Move new filename right next to original filename
                hdr.moveSection(hdr.visualIndex(COL_FILENAME_NEW), hdr.visualIndex(COL_FILENAME) + 1)
                hdr.moveSection(hdr.visualIndex(COL_CHECK), COLUMN_COUNT - 1)
        finally:
            hdr.blockSignals(False)

        hdr.sectionMoved.connect(self._on_section_moved)

        # Win11 Explorer header-click-to-sort.
        self._table.setSortingEnabled(True)
        hdr.setSectionsClickable(True)

        saved_sort_col = -1
        saved_sort_order = Qt.SortOrder.AscendingOrder
        if self._cfg:
            saved_sort_col = self._cfg.tag_editor_sort_column
            saved_sort_order_val = self._cfg.tag_editor_sort_order
            saved_sort_order = Qt.SortOrder(saved_sort_order_val)

        if saved_sort_col != -1:
            hdr.blockSignals(True)
            try:
                self._table.sortByColumn(saved_sort_col, saved_sort_order)
                hdr.setSortIndicatorShown(True)
            finally:
                hdr.blockSignals(False)
        else:
            hdr.setSortIndicatorShown(False)

        hdr.sortIndicatorChanged.connect(self._on_sort_indicator_changed)

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

        # Connect resize signal and disable the initial resize-ignoring flag
        hdr.sectionResized.connect(self._on_section_resized)
        self._ignore_header_resize = False

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
        lbl = QLabel(t("meta_select_files_prompt"))
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

        self._insp_folder_title = QLabel(t("meta_all_checked_files"))
        self._insp_folder_title.setStyleSheet("font-weight: bold; font-size: 13px;")
        self._insp_folder_title.setWordWrap(True)
        layout.addWidget(self._insp_folder_title)

        _btn_style = (
            f"QPushButton {{ background: {ACCENT_COLOR}; color: #000; font-weight: bold;"
            f"  border-radius: 4px; padding: 3px 6px; font-size: 10px; }}"
            f"QPushButton:hover {{ background: {_md_dim_hex(ACCENT_COLOR)}; }}"
        )

        grp_artist = QGroupBox(t("meta_apply_artist_group"))
        grp_layout = QVBoxLayout(grp_artist)
        grp_layout.setSpacing(6)
        self._insp_folder_artist = QLineEdit()
        self._insp_folder_artist.setPlaceholderText(t("meta_artist_placeholder"))
        grp_layout.addWidget(self._insp_folder_artist)
        btn_artist = QPushButton(t("meta_apply_artist_btn"))
        btn_artist.setStyleSheet(_btn_style)
        btn_artist.clicked.connect(self._on_insp_folder_artist)
        grp_layout.addWidget(btn_artist)
        layout.addWidget(grp_artist)

        grp_album = QGroupBox(t("meta_apply_album_group"))
        grp_album_layout = QVBoxLayout(grp_album)
        grp_album_layout.setSpacing(6)
        self._insp_folder_album = QLineEdit()
        self._insp_folder_album.setPlaceholderText(t("meta_album_placeholder"))
        grp_album_layout.addWidget(self._insp_folder_album)
        btn_album = QPushButton(t("meta_apply_album_btn"))
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

        self._insp_tracks_title = QLabel(t("meta_tracks_selected_count", n=0))
        self._insp_tracks_title.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(self._insp_tracks_title)

        fields_grp = QGroupBox(t("meta_edit_tags_group"))
        fields_layout = QVBoxLayout(fields_grp)
        fields_layout.setSpacing(6)

        def _field(label: str) -> QLineEdit:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(85)
            lbl.setStyleSheet("font-size: 11px;")
            edit = QLineEdit()
            edit.setPlaceholderText(t("meta_mixed_placeholder"))
            row.addWidget(lbl)
            row.addWidget(edit)
            fields_layout.addLayout(row)
            return edit

        self._insp_title        = _field(t("meta_field_title"))
        self._insp_artist       = _field(t("meta_field_artist"))
        self._insp_album        = _field(t("meta_field_album"))
        self._insp_album_artist = _field(t("meta_field_album_artist"))
        self._insp_track        = _field(t("meta_field_track"))

        btn_apply_fields = QPushButton(t("meta_apply_to_selection"))
        btn_apply_fields.setStyleSheet(
            f"QPushButton {{ background: {ACCENT_COLOR}; color: #000; "
            f"font-weight: bold; border-radius: 5px; padding: 4px 8px; }}"
            f"QPushButton:hover {{ background: {_md_dim_hex(ACCENT_COLOR)}; }}"
        )
        btn_apply_fields.clicked.connect(self._on_insp_apply_fields)
        fields_layout.addWidget(btn_apply_fields)
        layout.addWidget(fields_grp)

        rename_grp = QGroupBox(t("meta_rename_group"))
        rename_layout = QVBoxLayout(rename_grp)
        rename_layout.setSpacing(6)
        rename_note = QLabel(t("meta_rename_note"))
        rename_note.setWordWrap(True)
        rename_note.setStyleSheet(f"color: {get_colors().text_secondary}; font-size: 11px;")
        rename_layout.addWidget(rename_note)
        btn_rename = QPushButton(t("meta_rename_btn"))
        btn_rename.setStyleSheet(_btn_style())
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
        grp = QGroupBox(t("meta_actions_on_selected"))
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

        for key, label_key, desc_key in _MAGIC_OP_DEFS:
            label = t(label_key)
            desc  = t(desc_key)
            row_layout = QHBoxLayout()
            row_layout.setSpacing(4)
            row_layout.setContentsMargins(0, 0, 0, 0)
            btn = QPushButton(label)
            btn.setStyleSheet(_btn_style())
            if key in op_handlers:
                btn.clicked.connect(op_handlers[key])
            row_layout.addWidget(btn, stretch=1)

            if key in ("strip_junk", "clean_filename"):
                cfg_btn = QPushButton("⚙️")
                cfg_btn.setFixedSize(24, 24)
                cfg_btn.setStyleSheet(f"QPushButton {{ border: none; background: transparent; font-size: 14px; color: {get_colors().text_secondary}; }} QPushButton:hover {{ color: {ACCENT_COLOR}; }}")
                cfg_btn.setToolTip(t("meta_clean_cfg_tooltip"))
                cfg_btn.clicked.connect(self._on_clean_settings)
                row_layout.addWidget(cfg_btn)
            
            info_btn = QPushButton("ℹ️")
            info_btn.setFixedSize(24, 24)
            info_btn.setStyleSheet(f"QPushButton {{ border: none; background: transparent; font-size: 14px; color: {get_colors().text_secondary}; }} QPushButton:hover {{ color: {ACCENT_COLOR}; }}")
            info_btn.setToolTip(desc)
            info_btn.clicked.connect(lambda _, l=label, d=desc: self._show_info(l, d))
            row_layout.addWidget(info_btn)
            grp_layout.addLayout(row_layout)

        return grp

    def _on_clean_settings(self) -> None:
        dlg = _CleanSettingsDialog(self._cfg, self)
        dlg.exec()

    def _show_info(self, title: str, desc: str) -> None:
        from qfluentwidgets import MessageBox
        msg = MessageBox(title, desc, self)
        msg.cancelButton.hide()
        msg.exec()

    def _request_delete_files(self, paths: list[Path]) -> None:
        """Single-confirm Recycle Bin send for selected table rows.

        Called from `_ExplorerFileListView.keyPressEvent` on Delete. Emits
        `delete_files_requested` only after the user confirms — the actual
        send2trash + rescan is owned by `MetadataController.delete_files`.
        """
        if not paths:
            return
        from qfluentwidgets import MessageBox
        msg = MessageBox(
            t("meta_delete_to_trash_title"),
            t("meta_delete_to_trash_body", n=len(paths)),
            self.window(),
        )
        try:
            msg.yesButton.setText(t("meta_delete_to_trash_confirm"))
        except Exception:
            pass
        if msg.exec():
            self.delete_files_requested.emit(list(paths))

    # ── Toolbar handlers ──────────────────────────────────────────────────────

    def _on_browse(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, t("meta_choose_music_folder"), str(Path.home())
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
        self._summary_lbl.setText(t("meta_scanning"))
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
        self._summary_lbl.setText(t("meta_searching_duplicates"))
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
        
        # Update the header 'Select All' checkbox
        hdr = self._table.horizontalHeader()
        if hasattr(hdr, 'setChecked'):
            total = len(self._model._visible)
            hdr.setChecked(len(rows) == total and total > 0)
            
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
            self._insp_folder_title.setText(t("meta_n_files_checked", n=checked))
            self._inspector.setCurrentIndex(_PAGE_FOLDER)
        else:
            self._inspector.setCurrentIndex(_PAGE_EMPTY)


    def _on_select_all_toggled(self, checked: bool) -> None:
        if checked:
            self._table.selectAll()
        else:
            self._table.clearSelection()

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
        """Keep Name pinned first and the fixed empty gutter pinned last."""
        hdr = self._table.horizontalHeader()

        target_gutter_visual = COLUMN_COUNT - 1
        if hdr.visualIndex(COL_CHECK) != target_gutter_visual:
            hdr.blockSignals(True)
            try:
                hdr.moveSection(hdr.visualIndex(COL_CHECK), target_gutter_visual)
            finally:
                hdr.blockSignals(False)

        if logical == COL_FILENAME and new_visual != 0:
            hdr.blockSignals(True)
            try:
                hdr.moveSection(hdr.visualIndex(COL_FILENAME), 0)
            finally:
                hdr.blockSignals(False)
        elif new_visual == 0 and logical != COL_FILENAME:
            hdr.blockSignals(True)
            try:
                hdr.moveSection(hdr.visualIndex(COL_FILENAME), 0)
            finally:
                hdr.blockSignals(False)

        self._save_column_order()

    def _save_column_order(self) -> None:
        if self._cfg:
            hdr = self._table.horizontalHeader()
            order = []
            for visual_idx in range(COLUMN_COUNT):
                logical_idx = hdr.logicalIndex(visual_idx)
                order.append(logical_idx)
            self._cfg.tag_editor_column_order = order
            self._cfg.save()

    def _on_section_resized(self, logical: int, old_size: int, new_size: int) -> None:
        if getattr(self, "_ignore_header_resize", False):
            return
        if logical == COL_CHECK:
            return

        factor = self._zoom_level / 100.0
        if factor <= 0:
            factor = 1.0

        base_width = int(new_size / factor)
        if self._cfg:
            widths = dict(self._cfg.tag_editor_column_widths)
            widths[str(logical)] = base_width
            self._cfg.tag_editor_column_widths = widths
            self._cfg.save()

    def _on_sort_indicator_changed(self, column: int, order: Qt.SortOrder) -> None:
        hdr = self._table.horizontalHeader()
        hdr.setSortIndicatorShown(column != -1)
        if self._cfg:
            self._cfg.tag_editor_sort_column = column
            order_val = order.value if hasattr(order, 'value') else int(order)
            self._cfg.tag_editor_sort_order = int(order_val)
            self._cfg.save()

    def _save_column_visibility(self) -> None:
        if self._cfg:
            hidden_cols = []
            for col in range(COLUMN_COUNT):
                if self._table.isColumnHidden(col):
                    hidden_cols.append(col)
            self._cfg.tag_editor_column_visibility = hidden_cols
            self._cfg.save()

    def _set_column_hidden(self, col: int, hide: bool) -> None:
        self._table.setColumnHidden(col, hide)
        self._save_column_visibility()

    def _on_header_context_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu

        # Short "common" column list — mirrors the Windows Explorer header
        # right-click menu (5-7 items, not the full attribute sheet).
        COMMON_COLS = [
            COL_FILENAME,      # Name  — always visible
            COL_TITLE_NEW,     # Title (new)
            COL_ARTIST_NEW,    # Artist (new)
            COL_ALBUM_NEW,     # Album (new)
            COL_TRACK_NEW,     # Track (new)
            COL_FILENAME_NEW,  # Filename (new)
            COL_STATUS,        # Status
        ]
        ALWAYS_VISIBLE = {COL_FILENAME}

        menu = QMenu(self)
        for col in COMMON_COLS:
            key = _HEADER_KEYS[col] if col < len(_HEADER_KEYS) else ""
            lbl = t(key) if key else ""
            if not lbl:
                continue
            action = menu.addAction(lbl)
            action.setCheckable(True)
            action.setChecked(not self._table.isColumnHidden(col))
            if col in ALWAYS_VISIBLE:
                action.setEnabled(False)
            else:
                action.triggered.connect(
                    lambda checked, c=col: self._set_column_hidden(c, not checked)
                )

        menu.addSeparator()
        menu.addAction(t("mt_size_all_to_fit")).triggered.connect(
            self._size_all_columns_to_fit
        )
        menu.addSeparator()
        menu.addAction(t("mt_more_columns")).triggered.connect(self._on_more_columns)

        menu.exec(self._table.horizontalHeader().mapToGlobal(pos))

    def _size_all_columns_to_fit(self) -> None:
        """Resize every visible column to its content width (Win11 'Best fit')."""
        for col in range(COLUMN_COUNT):
            if not self._table.isColumnHidden(col):
                self._table.resizeColumnToContents(col)

    def _on_more_columns(self) -> None:
        dlg = _MoreColumnsDialog(self._table, self)
        if dlg.exec() == QDialog.Accepted:
            self._save_column_visibility()

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
            self._insp_folder_title.setText(t("meta_n_files_checked", n=n))
            self._inspector.setCurrentIndex(_PAGE_FOLDER)

    def on_auto_rules_applied(self) -> None:
        self._model.refresh_all()
        self._table.viewport().update()
        self._update_summary()

    def on_apply_progress(self, done: int, total: int) -> None:
        self._summary_lbl.setText(t("meta_writing_tags_progress", done=done, total=total))

    def on_apply_file_done(self, path_str: str, success: bool) -> None:
        path = Path(path_str)
        for item in self._model.get_all_tracks():
            if item.path == path:
                self._model.refresh_track(item)
                break

    def on_apply_complete(self, success: int, fail: int, skip: int) -> None:
        self._update_summary()
        self._model.refresh_all()

        msg = t("meta_done_success_base", success=success)
        if fail:
            msg += t("meta_done_failed_suffix", fail=fail)
        if skip:
            msg += t("meta_done_skipped_suffix", skip=skip)
        self._summary_lbl.setText(msg)

        try:
            from qfluentwidgets import InfoBar, InfoBarPosition
            if fail == 0:
                InfoBar.success(
                    title=t("meta_done_summary_title"), content=msg, parent=self,
                    position=InfoBarPosition.BOTTOM_RIGHT, duration=4000,
                )
            else:
                InfoBar.warning(
                    title=t("meta_done_with_errors_title"), content=msg, parent=self,
                    position=InfoBarPosition.BOTTOM_RIGHT, duration=6000,
                )
        except Exception:
            pass

    def on_status_update(self, msg: str) -> None:
        self._summary_lbl.setText(msg)

    def on_duplicate_scan_progress(self, done: int, total: int, eta: str) -> None:
        self._summary_lbl.setText(t("meta_searching_duplicates_progress", done=done, total=total, eta=eta))

    def on_duplicate_scan_complete(self, groups: dict, elapsed: float, strategy: str) -> None:
        self._dupes_btn.setEnabled(True)
        if not groups:
            self.on_status_update(t("meta_no_duplicates_found", elapsed=elapsed))
            self._update_summary()
            return

        from ui.dialogs.duplicate_files_dialog import DuplicateFilesDialog
        dlg = DuplicateFilesDialog(groups, elapsed, strategy, self._root_folder, parent=self)
        if dlg.exec() == QDialog.Accepted and dlg.files_to_delete:
            self.delete_duplicates_requested.emit(dlg.files_to_delete)

    def on_duplicate_scan_error(self, msg: str) -> None:
        self._dupes_btn.setEnabled(True)
        self.on_status_update(t("meta_duplicate_search_error", msg=msg))
        self._update_summary()

    def on_duplicate_delete_complete(self, success: int, fail: int) -> None:
        note = t("meta_files_deleted_errors_suffix", fail=fail) if fail else ""
        self.on_status_update(t("meta_files_deleted", success=success, note=note))
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
        folders = len(self._folder_items) if self._folder_items else len({tr.folder for tr in tracks})
        changed = self._model.get_changed_count()
        warnings = self._model.get_warning_count()
        parts = [
            t("meta_files_count", n=len(tracks)),
            t("meta_folders_count", n=folders),
        ]
        if changed:
            parts.append(t("meta_changes_proposed", n=changed))
        if warnings:
            parts.append(t("meta_warnings_count", n=warnings))
        self._summary_lbl.setText(" | ".join(parts) if parts else "")

    def _update_table_info(self) -> None:
        checked = len(self._model.get_checked_tracks())
        total   = len(self._model.get_all_tracks())
        if checked == total:
            self._table_info_lbl.setText(t("meta_total_files", total=total))
        else:
            self._table_info_lbl.setText(t("meta_showing_filtered", checked=checked, total=total))

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
        plural = "" if len(tracks) == 1 else "s"
        self._insp_tracks_title.setText(
            t("meta_tracks_selected_summary", n=len(tracks), plural=plural)
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
        # Win11 Details View: flat header (no per-section vertical borders,
        # no bold, muted color, single underline). Capsule paint handles
        # selection — keep selection-background-color transparent so Qt
        # doesn't overdraw it with a flat rectangle.
        self._table.setStyleSheet(
            f"QTableView {{ background: {table_colors.bg}; color: {table_colors.text_primary};"
            f"  border: 1px solid {table_colors.border};"
            f"  selection-background-color: transparent; selection-color: {table_colors.text_primary};"
            f"  font-size: {font_size}pt; }}"
            "QTableView::item { background: transparent; border: none; }"
            f"QHeaderView::section {{ background: {table_colors.bg};"
            f"  color: {table_colors.text_secondary};"
            f"  border: none;"
            f"  padding: 0 12px; height: 32px;"
            f"  font-size: {font_size}pt; font-weight: normal; }}"
            f"QHeaderView::section:hover {{ color: {table_colors.text_primary}; }}"
            f"QTableCornerButton::section {{ background: {table_colors.bg};"
            f"  border: none; }}"
        )

        font = self._table.font()
        font.setPointSize(font_size)
        self._table.setFont(font)
        
        hdr = self._table.horizontalHeader()
        hdr_font = hdr.font()
        hdr_font.setPointSize(font_size)
        hdr.setFont(hdr_font)
        
        # Load saved widths
        saved_widths = {}
        if self._cfg:
            try:
                saved_widths = {int(k): v for k, v in self._cfg.tag_editor_column_widths.items()}
            except Exception:
                pass

        self._ignore_header_resize = True
        try:
            for col in range(COLUMN_COUNT):
                base_w = saved_widths.get(col, _DEFAULT_COL_WIDTHS.get(col, 100))
                if col == COL_CHECK:
                    self._table.setColumnWidth(col, _ExplorerFileListView._SIDE_EMPTY_GUTTER)
                else:
                    self._table.setColumnWidth(col, max(10, int(base_w * factor)))
        finally:
            self._ignore_header_resize = False

    def _on_tree_item_moved(self, src: Path, dest: Path) -> None:
        """Physically moves a file or folder on the disk, and updates UI."""
        try:
            if dest.exists():
                from qfluentwidgets import MessageBox
                MessageBox(t("meta_error_title"), t("meta_move_target_exists", name=dest.name), self).exec()
                return

            import shutil
            shutil.move(str(src), str(dest))
            self._on_scan()
        except Exception as e:
            logger.exception("Failed to move tree item")
            from qfluentwidgets import MessageBox
            MessageBox(t("meta_error_title"), t("meta_move_failed", error=str(e)), self).exec()

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
            add_folder_action = menu.addAction(t("meta_add_folder"))
            menu.addSeparator()

        rename_action = menu.addAction(t("meta_rename_menu"))
        delete_action = menu.addAction(t("meta_delete_menu"))

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
            t("meta_new_folder_dialog_title"),
            t("meta_new_folder_prompt"),
            text=t("meta_new_folder_default"),
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
            MessageBox(t("meta_error_title"), t("meta_invalid_folder_name"), self).exec()
            return

        dest = parent_path / new_name
        try:
            if dest.exists():
                from qfluentwidgets import MessageBox
                MessageBox(t("meta_error_title"), t("meta_folder_exists"), self).exec()
                return

            dest.mkdir()
            self._on_scan()
        except Exception as e:
            logger.exception("Failed to create tree folder")
            from qfluentwidgets import MessageBox
            MessageBox(t("meta_error_title"), t("meta_create_folder_failed", error=str(e)), self).exec()

    def _on_tree_rename(self, path: Path, is_file: bool) -> None:
        new_name, ok = QInputDialog.getText(
            self,
            t("meta_rename_dialog_title"),
            t("meta_rename_prompt"),
            text=path.name,
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
                MessageBox(t("meta_error_title"), t("meta_target_name_exists"), self).exec()
                return

            path.rename(dest)
            self._on_scan()
        except Exception as e:
            logger.exception("Failed to rename tree item")
            from qfluentwidgets import MessageBox
            MessageBox(t("meta_error_title"), t("meta_rename_failed", error=str(e)), self).exec()

    def _on_tree_delete(self, path: Path, is_file: bool) -> None:
        from qfluentwidgets import MessageBox
        title = t("meta_delete_file_title") if is_file else t("meta_delete_folder_title")
        text = t("meta_delete_confirm", name=path.name)
        if not is_file:
            text += t("meta_delete_recursive_note")

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
                MessageBox(t("meta_error_title"), t("meta_delete_failed", error=str(e)), self).exec()




def _bold_font() -> QFont:
    f = QFont()
    f.setBold(True)
    return f
