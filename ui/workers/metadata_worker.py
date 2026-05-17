"""
ui/workers/metadata_worker.py  –  Background workers for the Tag Editor
========================================================================
MetadataScanWorker   – scans a folder and emits tracks incrementally.
MetadataApplyWorker  – writes proposed tags file-by-file with a backup.

Both workers use threading.Event for cancellation (same pattern as FetchWorker).
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal

from core.metadata_models import AudioTrackItem, ScanResult, TrackStatus
from core.metadata_processor import (
    backup_tags,
    build_scan_result,
    scan_folder,
    scan_folders,
    write_tags,
)


class MetadataScanWorker(QThread):
    """
    Runs scan_folder() in a background thread and emits each track as it
    is discovered so the table can populate live.

    Signals
    -------
    track_found(AudioTrackItem)   One file scanned and ready.
    scan_complete(ScanResult)     All files processed.
    scan_error(str)               Unrecoverable failure (rare).
    """

    track_found   = Signal(object)   # AudioTrackItem
    scan_complete = Signal(object)   # ScanResult
    scan_error    = Signal(str)

    def __init__(self, root: Path, recursive: bool, parent=None) -> None:
        super().__init__(parent)
        self._root      = root
        self._recursive = recursive
        self._cancel    = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        tracks: list[AudioTrackItem] = []
        skipped = 0
        folders: set[Path] = {self._root}

        try:
            folders = scan_folders(self._root, self._recursive)
            for item in scan_folder(self._root, self._recursive):
                if self._cancel.is_set():
                    break
                tracks.append(item)
                self.track_found.emit(item)

        except Exception as exc:
            self.scan_error.emit(str(exc))
            return

        result = build_scan_result(self._root, tracks, skipped, folders)
        self.scan_complete.emit(result)


class MetadataApplyWorker(QThread):
    """
    Writes proposed tags for each track that has changes.
    Creates a JSON backup before the first write.

    Signals
    -------
    progress(int, int)            (done_count, total_count)
    file_done(str, bool)          (path_str, success)
    finished(int, int, int)       (success_count, fail_count, skip_count)
    """

    progress  = Signal(int, int)
    file_done = Signal(str, bool)
    finished  = Signal(int, int, int)

    def __init__(
        self,
        tracks:      list[AudioTrackItem],
        backup_path: Path,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._tracks      = tracks
        self._backup_path = backup_path
        self._cancel      = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        changed = [t for t in self._tracks if t.has_changes]
        total   = len(changed)

        if total == 0:
            self.finished.emit(0, 0, 0)
            return

        # Always back up original tags first
        try:
            backup_tags(changed, self._backup_path)
        except Exception as exc:
            # Backup failure is non-fatal — warn but continue
            import logging
            logging.getLogger(__name__).warning(
                "[MetadataApplyWorker] Backup failed: %s", exc
            )

        success = 0
        fail    = 0
        skip    = 0

        for i, item in enumerate(changed):
            if self._cancel.is_set():
                skip += total - i
                break

            if item.status == TrackStatus.UNSUPPORTED:
                skip += 1
                self.progress.emit(i + 1, total)
                continue

            ok = write_tags(item.path, item.proposed, item.original)

            # Rename file if requested
            if ok and item.proposed_filename and item.proposed_filename != item.path.name:
                new_path = item.path.parent / item.proposed_filename
                try:
                    if not new_path.exists():
                        item.path.rename(new_path)
                        item.path   = new_path
                        item.folder = new_path.parent
                    item.proposed_filename = None
                except Exception as exc:
                    import logging
                    logging.getLogger(__name__).warning(
                        "[MetadataApplyWorker] Rename failed %s → %s: %s",
                        item.path.name, item.proposed_filename, exc,
                    )

            if ok:
                item.status = TrackStatus.DONE
                success += 1
            else:
                item.status = TrackStatus.ERROR
                fail += 1

            self.file_done.emit(str(item.path), ok)
            self.progress.emit(i + 1, total)

        self.finished.emit(success, fail, skip)
