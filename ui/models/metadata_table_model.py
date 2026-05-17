"""
ui/models/metadata_table_model.py  –  Qt model for the Tag Editor preview table
================================================================================
QAbstractTableModel subclass that displays AudioTrackItem objects in a
before/after layout.  Changed cells are highlighted in accent colour.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    Qt,
)
from PySide6.QtGui import QBrush, QColor, QFont

from core.metadata_models import AudioTrackItem, TrackStatus
from ui.theme_manager import ACCENT_COLOR, ERROR_COLOR, WARNING_COLOR

# ── Column constants ──────────────────────────────────────────────────────────

COL_CHECK      = 0
COL_FILENAME   = 1
COL_TITLE_CUR  = 2
COL_TITLE_NEW  = 3
COL_ARTIST_CUR = 4
COL_ARTIST_NEW = 5
COL_ALBUM_CUR  = 6
COL_ALBUM_NEW  = 7
COL_TRACK_CUR  = 8
COL_TRACK_NEW  = 9
COL_STATUS     = 10
COLUMN_COUNT   = 11

_HEADERS = [
    "", "שם קובץ",
    "כותרת", "כותרת (חדש)",
    "אמן", "אמן (חדש)",
    "אלבום", "אלבום (חדש)",
    "רצועה", "רצועה (חדש)",
    "סטטוס",
]

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


class MetadataTableModel(QAbstractTableModel):
    """
    Displays a filtered list of AudioTrackItem objects.

    All tracks are stored in self._tracks (master list).
    self._visible holds indices into _tracks after applying folder filter.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tracks:  list[AudioTrackItem] = []
        self._checked: set[int] = set()          # indices into _tracks
        self._filter:  Optional[Path] = None

        # Computed view
        self._visible: list[int] = []            # indices into _tracks

    # ── QAbstractTableModel interface ─────────────────────────────────────────

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._visible)

    def columnCount(self, parent=QModelIndex()) -> int:
        return COLUMN_COUNT

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return _HEADERS[section] if section < len(_HEADERS) else ""
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
            if col == COL_TRACK_NEW  and p.track_num is not None and p.track_num != o.track_num:
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
            if col in (COL_TITLE_NEW, COL_ARTIST_NEW, COL_ALBUM_NEW, COL_TRACK_NEW):
                if item.has_changes:
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
        if col in (COL_TITLE_NEW, COL_ARTIST_NEW, COL_ALBUM_NEW, COL_TRACK_NEW):
            return base | Qt.ItemIsEditable
        return base

    # ── Public API ─────────────────────────────────────────────────────────────

    def load_tracks(self, tracks: list[AudioTrackItem]) -> None:
        """Replace entire dataset and rebuild view."""
        self.beginResetModel()
        self._tracks = list(tracks)
        self._checked.clear()
        self._rebuild_visible()
        self.endResetModel()

    def add_track(self, item: AudioTrackItem) -> None:
        """Incrementally insert one track; respects active folder filter."""
        master_idx = len(self._tracks)
        self._tracks.append(item)

        if self._filter is None or item.folder == self._filter:
            new_vis_row = len(self._visible)
            self.beginInsertRows(QModelIndex(), new_vis_row, new_vis_row)
            self._visible.append(master_idx)
            self.endInsertRows()

    def set_folder_filter(self, folder: Optional[Path]) -> None:
        """Show only tracks inside folder (None = show all)."""
        self.beginResetModel()
        self._filter = folder
        self._rebuild_visible()
        self.endResetModel()

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
            self._checked = set(self._visible)
        else:
            self._checked -= set(self._visible)
        if self._visible:
            self.dataChanged.emit(
                self.index(0, COL_CHECK),
                self.index(len(self._visible) - 1, COL_CHECK),
                [Qt.CheckStateRole],
            )

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

    # ── Private ───────────────────────────────────────────────────────────────

    def _rebuild_visible(self) -> None:
        if self._filter is None:
            self._visible = list(range(len(self._tracks)))
        else:
            self._visible = [
                i for i, t in enumerate(self._tracks)
                if t.folder == self._filter
            ]


def _status_label(status: str) -> str:
    return {
        TrackStatus.PENDING:     "",
        TrackStatus.CHANGED:     "שונה",
        TrackStatus.DONE:        "✓ הושלם",
        TrackStatus.ERROR:       "✗ שגיאה",
        TrackStatus.UNSUPPORTED: "לא נתמך",
    }.get(status, status)
