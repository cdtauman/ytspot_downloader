"""
ui/models/metadata_table_model.py  –  Qt model for the Tag Editor preview table
================================================================================
QAbstractTableModel subclass that displays AudioTrackItem objects in a
before/after layout.  Changed cells are highlighted in accent colour.
"""

from __future__ import annotations

import bisect
from pathlib import Path

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    Qt,
)
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import QApplication

from core.metadata_models import AudioTrackItem, TrackStatus
from ui.i18n import t
from ui.theme_manager import ACCENT_COLOR, ERROR_COLOR, WARNING_COLOR

# ── Column constants ──────────────────────────────────────────────────────────

COL_CHECK        = 0
COL_FILENAME     = 1
COL_TITLE_CUR    = 2
COL_TITLE_NEW    = 3
COL_ARTIST_CUR   = 4
COL_ARTIST_NEW   = 5
COL_ALBUM_CUR    = 6
COL_ALBUM_NEW    = 7
COL_TRACK_CUR    = 8
COL_TRACK_NEW    = 9
COL_STATUS       = 10
# Extended columns (hidden by default, user-toggleable)
COL_FILENAME_NEW = 11
COL_GENRE_CUR    = 12
COL_GENRE_NEW    = 13
COL_COMMENT_CUR  = 14
COL_COMMENT_NEW  = 15
COLUMN_COUNT     = 16

# Header *translation keys*, looked up via t() in headerData() so the
# headers reflect the active language each time the view repaints.
_HEADER_KEYS: list[str] = [
    "",
    "mt_col_filename",
    "mt_col_title",        "mt_col_title_new",
    "mt_col_artist",       "mt_col_artist_new",
    "mt_col_album",        "mt_col_album_new",
    "mt_col_track",        "mt_col_track_new",
    "mt_col_status",
    "mt_col_filename_new",
    "mt_col_genre",        "mt_col_genre_new",
    "mt_col_comment",      "mt_col_comment_new",
]


def _headers() -> list[str]:
    return [t(k) if k else "" for k in _HEADER_KEYS]


# Backwards-compat alias for any external importer that reads `_HEADERS`
# at import time. Captures the English headers at module load — UI code
# should use ``_headers()`` (or ``model.headerData()``) for live values.
_HEADERS = _headers()

# Alpha-blended accent / warning brush colours
_ACCENT_BG  = QColor(ACCENT_COLOR)
_ACCENT_BG.setAlpha(55)
_ERROR_BG   = QColor(ERROR_COLOR)
_ERROR_BG.setAlpha(35)
_WARN_BG    = QColor(WARNING_COLOR)
_WARN_BG.setAlpha(35)

_ACCENT_BRUSH = QBrush(_ACCENT_BG)
_ERROR_BRUSH  = QBrush(_ERROR_BG)
_WARN_BRUSH   = QBrush(_WARN_BG)


# Per-column sort key extractors. The model's sort() looks up the column
# in this table; columns not listed (e.g. CHECK with no meaningful order)
# are no-ops. Strings are case-folded so sorting is locale-friendly.
def _safe_int(v) -> int:
    try:
        return int(v) if v is not None else 0
    except (TypeError, ValueError):
        return 0

def _fold(s) -> str:
    return s.casefold() if isinstance(s, str) else ""

_SORT_KEYS = {
    COL_CHECK:        lambda t: 0,
    COL_FILENAME:     lambda t: _fold(getattr(t, "display_name", "") or t.path.name),
    COL_FILENAME_NEW: lambda t: _fold(getattr(t, "proposed_filename", "") or ""),
    COL_TITLE_CUR:    lambda t: _fold(t.original.title or ""),
    COL_TITLE_NEW:    lambda t: _fold((t.proposed.title  if t.proposed.title  is not None else t.original.title)  or ""),
    COL_ARTIST_CUR:   lambda t: _fold(t.original.artist or ""),
    COL_ARTIST_NEW:   lambda t: _fold((t.proposed.artist if t.proposed.artist is not None else t.original.artist) or ""),
    COL_ALBUM_CUR:    lambda t: _fold(t.original.album  or ""),
    COL_ALBUM_NEW:    lambda t: _fold((t.proposed.album  if t.proposed.album  is not None else t.original.album)  or ""),
    COL_TRACK_CUR:    lambda t: _safe_int(t.original.track_num),
    COL_TRACK_NEW:    lambda t: _safe_int(t.proposed.track_num if t.proposed.track_num is not None else t.original.track_num),
    COL_GENRE_CUR:    lambda t: _fold(t.original.genre   or ""),
    COL_GENRE_NEW:    lambda t: _fold((t.proposed.genre   if t.proposed.genre   is not None else t.original.genre)   or ""),
    COL_COMMENT_CUR:  lambda t: _fold(t.original.comment or ""),
    COL_COMMENT_NEW:  lambda t: _fold((t.proposed.comment if t.proposed.comment is not None else t.original.comment) or ""),
    COL_STATUS:       lambda t: str(t.status),
}


class MetadataTableModel(QAbstractTableModel):
    """
    Displays checked AudioTrackItem objects.

    All tracks are stored in self._tracks (master list).
    self._visible holds master-indices of tracks that are currently checked,
    sorted in discovery order — this is the only filter.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tracks:      list[AudioTrackItem] = []
        self._checked:     set[int] = set()          # indices into _tracks
        self._path_to_idx: dict[Path, int] = {}      # fast path → master-idx lookup

        # Computed view: sorted(self._checked) + last applied sort order
        self._visible: list[int] = []
        self._sort_column: int | None = None
        self._sort_order: Qt.SortOrder = Qt.AscendingOrder

    # ── QAbstractTableModel interface ─────────────────────────────────────────

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._visible)

    def columnCount(self, parent=QModelIndex()) -> int:
        return COLUMN_COUNT

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal:
            if role == Qt.DisplayRole:
                if section < len(_HEADER_KEYS):
                    key = _HEADER_KEYS[section]
                    text = t(key) if key else ""
                    return text
                return ""
            elif role == Qt.TextAlignmentRole:
                if orientation == Qt.Orientation.Horizontal:
                    if QApplication.layoutDirection() == Qt.RightToLeft:
                        return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter
                    else:
                        return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        row = index.row()
        col = index.column()
        if row >= len(self._visible):
            return None

        track_idx = self._visible[row]
        item = self._tracks[track_idx]
        p = item.proposed
        o = item.original

        # ── CheckState ────────────────────────────────────────────────────────
        if role == Qt.CheckStateRole and col == COL_CHECK:
            return Qt.Checked if track_idx in self._checked else Qt.Unchecked

        # ── TextAlignmentRole ─────────────────────────────────────────────────
        if role == Qt.TextAlignmentRole:
            if QApplication.layoutDirection() == Qt.RightToLeft:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter
            else:
                return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter

        # ── DisplayRole ───────────────────────────────────────────────────────
        if role == Qt.DisplayRole:
            if col == COL_FILENAME:
                return item.display_name
            if col == COL_TITLE_CUR:
                return o.title
            if col == COL_TITLE_NEW:
                return p.title if p.title is not None else ""
            if col == COL_ARTIST_CUR:
                return o.artist
            if col == COL_ARTIST_NEW:
                return p.artist if p.artist is not None else ""
            if col == COL_ALBUM_CUR:
                return o.album
            if col == COL_ALBUM_NEW:
                return p.album if p.album is not None else ""
            if col == COL_TRACK_CUR:
                return str(o.track_num) if o.track_num is not None else ""
            if col == COL_TRACK_NEW:
                if p.track_num is not None:
                    return "" if p.track_num == -1 else str(p.track_num)
                return ""
            if col == COL_STATUS:
                return _status_label(item.status)
            if col == COL_FILENAME_NEW:
                return item.proposed_filename or ""
            if col == COL_GENRE_CUR:
                return o.genre
            if col == COL_GENRE_NEW:
                return p.genre if p.genre is not None else ""
            if col == COL_COMMENT_CUR:
                return o.comment
            if col == COL_COMMENT_NEW:
                return p.comment if p.comment is not None else ""
            return None

        # ── BackgroundRole ────────────────────────────────────────────────────
        if role == Qt.BackgroundRole:
            if item.status == TrackStatus.ERROR:
                return _ERROR_BRUSH
            if item.status == TrackStatus.UNSUPPORTED:
                return _WARN_BRUSH
            # Highlight "New" cells that differ from original
            if col == COL_TITLE_NEW  and p.title  is not None and p.title  != o.title:
                return _ACCENT_BRUSH
            if col == COL_ARTIST_NEW and p.artist is not None and p.artist != o.artist:
                return _ACCENT_BRUSH
            if col == COL_ALBUM_NEW  and p.album  is not None and p.album  != o.album:
                return _ACCENT_BRUSH
            if col == COL_TRACK_NEW     and p.track_num is not None and p.track_num != o.track_num:
                return _ACCENT_BRUSH
            if col == COL_FILENAME_NEW  and item.proposed_filename:
                return _ACCENT_BRUSH
            if col == COL_GENRE_NEW     and p.genre    is not None and p.genre    != o.genre:
                return _ACCENT_BRUSH
            if col == COL_COMMENT_NEW   and p.comment  is not None and p.comment  != o.comment:
                return _ACCENT_BRUSH
            return None

        # ── ForegroundRole ────────────────────────────────────────────────────
        if role == Qt.ForegroundRole:
            if item.status in (TrackStatus.UNSUPPORTED, TrackStatus.ERROR):
                from ui.theme_manager import get_colors
                return QBrush(QColor(get_colors().text_tertiary))
            return None

        # ── FontRole ─────────────────────────────────────────────────────────
        if role == Qt.FontRole:
            _new_cols = (
                COL_TITLE_NEW, COL_ARTIST_NEW, COL_ALBUM_NEW, COL_TRACK_NEW,
                COL_FILENAME_NEW, COL_GENRE_NEW, COL_COMMENT_NEW,
            )
            if col in _new_cols and item.has_changes:
                f = QFont()
                f.setBold(True)
                return f
            return None

        # ── ToolTipRole ───────────────────────────────────────────────────────
        if role == Qt.ToolTipRole:
            if item.error_msg:
                return item.error_msg
            if col == COL_FILENAME:
                return str(item.path)
            return None

        return None

    def setData(self, index: QModelIndex, value, role=Qt.EditRole) -> bool:
        if not index.isValid() or role not in (Qt.EditRole, Qt.CheckStateRole):
            return False

        row = index.row()
        col = index.column()
        if row >= len(self._visible):
            return False

        track_idx = self._visible[row]
        item = self._tracks[track_idx]

        if role == Qt.CheckStateRole and col == COL_CHECK:
            if value == Qt.Checked:
                self._checked.add(track_idx)
            else:
                self._checked.discard(track_idx)
            self.dataChanged.emit(index, index, [Qt.CheckStateRole])
            return True

        if role == Qt.EditRole:
            val = str(value).strip()
            if col == COL_TITLE_NEW:
                item.proposed.title = val
            elif col == COL_ARTIST_NEW:
                item.proposed.artist = val
            elif col == COL_ALBUM_NEW:
                item.proposed.album = val
            elif col == COL_TRACK_NEW:
                try:
                    item.proposed.track_num = int(val) if val else None
                except ValueError:
                    return False
            elif col == COL_FILENAME_NEW:
                item.proposed_filename = val if val else None
            elif col == COL_GENRE_NEW:
                item.proposed.genre = val
            elif col == COL_COMMENT_NEW:
                item.proposed.comment = val
            else:
                return False
            self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.BackgroundRole, Qt.FontRole])
            return True

        return False

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.NoItemFlags
        col = index.column()
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if col == COL_CHECK:
            return base | Qt.ItemIsUserCheckable
        if col in (
            COL_TITLE_NEW, COL_ARTIST_NEW, COL_ALBUM_NEW, COL_TRACK_NEW,
            COL_FILENAME_NEW, COL_GENRE_NEW, COL_COMMENT_NEW,
        ):
            return base | Qt.ItemIsEditable
        return base

    # ── Public API ─────────────────────────────────────────────────────────────

    def load_tracks(self, tracks: list[AudioTrackItem]) -> None:
        """Replace entire dataset and rebuild view."""
        self.beginResetModel()
        self._tracks = list(tracks)
        self._checked.clear()
        self._path_to_idx = {t.path: i for i, t in enumerate(self._tracks)}
        self._rebuild_visible()
        self.endResetModel()

    def add_track(self, item: AudioTrackItem) -> None:
        """Incrementally insert one track. All new tracks start checked and visible."""
        master_idx = len(self._tracks)
        self._tracks.append(item)
        self._path_to_idx[item.path] = master_idx
        self._checked.add(master_idx)

        new_vis_row = len(self._visible)
        self.beginInsertRows(QModelIndex(), new_vis_row, new_vis_row)
        self._visible.append(master_idx)
        self.endInsertRows()

    def set_folder_filter(self, folder) -> None:
        """No-op — table always shows checked tracks regardless of folder."""

    def get_visible_tracks(self) -> list[AudioTrackItem]:
        return [self._tracks[i] for i in self._visible]

    def get_checked_tracks(self) -> list[AudioTrackItem]:
        return [self._tracks[i] for i in sorted(self._checked)]

    def get_all_tracks(self) -> list[AudioTrackItem]:
        return list(self._tracks)

    def refresh_track(self, item: AudioTrackItem) -> None:
        """Emit dataChanged for the row containing item."""
        try:
            master_idx = self._tracks.index(item)
        except ValueError:
            return
        if master_idx in self._visible:
            row = self._visible.index(master_idx)
            top_left = self.index(row, 0)
            bot_right = self.index(row, COLUMN_COUNT - 1)
            self.dataChanged.emit(top_left, bot_right)

    def set_all_checked(self, checked: bool) -> None:
        if checked:
            self._checked = set(range(len(self._tracks)))
        else:
            self._checked = set()
        self.beginResetModel()
        self._rebuild_visible()
        self.endResetModel()

    def get_changed_count(self) -> int:
        return sum(1 for t in self._tracks if t.has_changes)

    def get_warning_count(self) -> int:
        return sum(
            1 for t in self._tracks
            if t.status in (TrackStatus.ERROR, TrackStatus.UNSUPPORTED)
        )

    def refresh_all(self) -> None:
        """Force full repaint (after bulk proposed-tag changes)."""
        if self._visible:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._visible) - 1, COLUMN_COUNT - 1),
            )

    def set_path_checked(self, path: Path, checked: bool) -> None:
        """Check or uncheck a track by file path (called from tree checkboxes)."""
        idx = self._path_to_idx.get(path)
        if idx is None:
            return

        if checked and idx not in self._checked:
            self._checked.add(idx)
            pos = bisect.bisect_left(self._visible, idx)
            self.beginInsertRows(QModelIndex(), pos, pos)
            self._visible.insert(pos, idx)
            self.endInsertRows()

        elif not checked and idx in self._checked:
            self._checked.discard(idx)
            try:
                pos = self._visible.index(idx)
                self.beginRemoveRows(QModelIndex(), pos, pos)
                self._visible.pop(pos)
                self.endRemoveRows()
            except ValueError:
                pass

    def get_visible_row_for_path(self, path: Path) -> int:
        """Return visible-row index for this path, or -1 if not found/not visible."""
        idx = self._path_to_idx.get(path)
        if idx is None:
            return -1
        try:
            return self._visible.index(idx)
        except ValueError:
            return -1

    # ── Sorting (Win11 Explorer header-click-to-sort) ─────────────────────────

    def sort(self, column: int, order: Qt.SortOrder = Qt.AscendingOrder) -> None:
        """Sort visible rows by the given column.

        Re-applied automatically inside ``_rebuild_visible`` so that scans,
        edits, and check-state changes preserve the user's chosen order
        (Qt's QTableView with ``setSortingEnabled(True)`` will also call
        this whenever its header indicator changes).
        """
        keyfn = _SORT_KEYS.get(column)
        if keyfn is None:
            return
        self.layoutAboutToBeChanged.emit()
        self._sort_column = column
        self._sort_order = order
        self._visible.sort(
            key=lambda master_idx: keyfn(self._tracks[master_idx]),
            reverse=(order == Qt.DescendingOrder),
        )
        self.layoutChanged.emit()

    # ── Private ───────────────────────────────────────────────────────────────

    def _rebuild_visible(self) -> None:
        self._visible = sorted(self._checked)
        if self._sort_column is not None:
            keyfn = _SORT_KEYS.get(self._sort_column)
            if keyfn is not None:
                self._visible.sort(
                    key=lambda master_idx: keyfn(self._tracks[master_idx]),
                    reverse=(self._sort_order == Qt.DescendingOrder),
                )


def _status_label(status: str) -> str:
    return {
        TrackStatus.PENDING:     "",
        TrackStatus.CHANGED:     t("mt_status_changed"),
        TrackStatus.DONE:        t("mt_status_done"),
        TrackStatus.ERROR:       t("mt_status_error"),
        TrackStatus.UNSUPPORTED: t("mt_status_unsupported"),
    }.get(status, status)
