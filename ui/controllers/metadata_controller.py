"""
ui/controllers/metadata_controller.py  –  Tag Editor business logic controller
===============================================================================
QObject — zero widget imports.  Owns MetadataScanWorker and MetadataApplyWorker.
Manages TagEditSession state and exposes a clean public API for the panel.

AppWindow wires all signals in _connect_metadata_signals().
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from core.metadata_models import AudioTrackItem, TagEditSession, TrackStatus
from core.metadata_processor import (
    clean_filename_to_title,
    extract_track_number,
)

logger = logging.getLogger(__name__)

# Backup files land in ~/.ytspot/tag_backups/
_BACKUP_DIR = Path.home() / ".ytspot" / "tag_backups"


class MetadataController(QObject):
    """
    Manages the tag-editor session lifecycle.

    Signals
    -------
    scan_started          — emitted when a new scan begins
    track_discovered      — one AudioTrackItem found during scan
    scan_complete         — ScanResult with totals
    auto_rules_applied    — proposed tags were bulk-computed
    apply_started         — apply worker launched
    apply_progress        — (done: int, total: int)
    apply_file_done       — (path: str, success: bool)
    apply_complete        — (success: int, fail: int, skip: int)
    apply_error           — str error message
    status_update         — human-readable status string for UI
    """

    scan_started       = Signal()
    track_discovered   = Signal(object)        # AudioTrackItem
    scan_complete      = Signal(object)        # ScanResult
    auto_rules_applied = Signal()
    apply_started      = Signal()
    apply_progress     = Signal(int, int)      # done, total
    apply_file_done    = Signal(str, bool)     # path, success
    apply_complete     = Signal(int, int, int) # success, fail, skip
    apply_error        = Signal(str)
    status_update      = Signal(str)

    def __init__(self, parent: QObject = None) -> None:
        super().__init__(parent)
        self._scan_worker  = None
        self._apply_worker = None
        self._session      = TagEditSession()

    # ── Public API ─────────────────────────────────────────────────────────────

    def scan(self, folder: Path, recursive: bool) -> None:
        """Cancel any running scan and start a new one."""
        from ui.workers.metadata_worker import MetadataScanWorker

        self._cancel_scan()
        self._session = TagEditSession()

        self.scan_started.emit()
        self.status_update.emit(f"סורק: {folder.name}…")

        self._scan_worker = MetadataScanWorker(folder, recursive, parent=self)
        self._scan_worker.track_found.connect(self._on_track_found)
        self._scan_worker.scan_complete.connect(self._on_scan_complete)
        self._scan_worker.scan_error.connect(self._on_scan_error)
        self._scan_worker.start()

    def cancel_scan(self) -> None:
        self._cancel_scan()

    def apply_auto_rules(self, tracks: list[AudioTrackItem]) -> None:
        """
        Compute proposed tags for every track using filename / folder heuristics.

        Rules:
          album     = immediate parent folder name
          title     = cleaned filename (no leading number)
          track_num = leading number from filename
          artist    = grandparent folder name (only if folder ≠ scan root)
          album_artist = same as artist when artist is set
        """
        root = self._session.scan_result.root if self._session.scan_result else None

        for item in tracks:
            if item.status == TrackStatus.UNSUPPORTED:
                continue

            p = item.proposed

            # Album ← direct parent folder name
            album_name = item.folder.name
            if album_name != item.original.album:
                p.album = album_name

            # Title ← cleaned filename
            clean_title = clean_filename_to_title(item.path.name)
            if clean_title and clean_title != item.original.title:
                p.title = clean_title

            # Track number ← leading digits
            num = extract_track_number(item.path.name)
            if num is not None and num != item.original.track_num:
                p.track_num = num

            # Artist ← grandparent folder (only if we are at least 2 levels deep)
            grandparent = item.folder.parent
            if root is None or grandparent != root:
                artist_name = grandparent.name
                if artist_name and artist_name != item.original.artist:
                    p.artist = artist_name
                    if p.album_artist is None and artist_name != item.original.album_artist:
                        p.album_artist = artist_name

        self.auto_rules_applied.emit()
        self.status_update.emit("הצעות אוטומטיות חושבו")

    def apply_artist_to_scope(self, artist: str, tracks: list[AudioTrackItem]) -> None:
        """Set proposed.artist (and album_artist) on all given tracks."""
        for item in tracks:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            item.proposed.artist = artist
            if not item.proposed.album_artist:
                item.proposed.album_artist = artist
        self.status_update.emit(f"אמן '{artist}' הוחל על {len(tracks)} קבצים")

    def apply_album_to_folder(
        self, album: str, folder: Path, tracks: list[AudioTrackItem]
    ) -> None:
        """Set proposed.album on all tracks whose folder matches."""
        affected = [t for t in tracks if t.folder == folder]
        for item in affected:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            item.proposed.album = album
        self.status_update.emit(f"אלבום '{album}' הוחל על {len(affected)} קבצים")

    def apply_title_from_filename(
        self, tracks: list[AudioTrackItem], strip_numbering: bool = True
    ) -> None:
        for item in tracks:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            if strip_numbering:
                item.proposed.title = clean_filename_to_title(item.path.name)
            else:
                item.proposed.title = item.path.stem

    def apply_track_from_filename(self, tracks: list[AudioTrackItem]) -> None:
        for item in tracks:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            num = extract_track_number(item.path.name)
            if num is not None:
                item.proposed.track_num = num

    def clear_comments(self, tracks: list[AudioTrackItem]) -> None:
        for item in tracks:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            item.proposed.comment = ""

    def apply_changes(self, backup_dir: Optional[Path] = None) -> None:
        """Launch MetadataApplyWorker on all tracks that have proposed changes."""
        from ui.workers.metadata_worker import MetadataApplyWorker

        if self._apply_worker and self._apply_worker.isRunning():
            return  # already running

        tracks = self._session.scan_result.tracks if self._session.scan_result else []
        changed = [t for t in tracks if t.has_changes]

        if not changed:
            self.status_update.emit("אין שינויים להחלה")
            return

        bd = backup_dir or _BACKUP_DIR
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = bd / f"ytspot_tag_backup_{timestamp}.json"
        self._session.backup_path = backup_path

        self.apply_started.emit()
        self.status_update.emit(f"כותב תגיות ל-{len(changed)} קבצים…")

        self._apply_worker = MetadataApplyWorker(tracks, backup_path, parent=self)
        self._apply_worker.progress.connect(self._on_apply_progress)
        self._apply_worker.file_done.connect(self.apply_file_done)
        self._apply_worker.finished.connect(self._on_apply_finished)
        self._apply_worker.start()

    def cancel_apply(self) -> None:
        if self._apply_worker and self._apply_worker.isRunning():
            self._apply_worker.cancel()

    def revert_all(self, tracks: list[AudioTrackItem]) -> None:
        """Clear all proposed tags on every given track."""
        for item in tracks:
            item.proposed.clear()
        self.status_update.emit("כל השינויים בוטלו")

    # ── Private slots ──────────────────────────────────────────────────────────

    def _on_track_found(self, item: AudioTrackItem) -> None:
        if self._session.scan_result is not None:
            self._session.scan_result.tracks.append(item)
            self._session.scan_result.folder_set.add(item.folder)
        self.track_discovered.emit(item)

    def _on_scan_complete(self, result) -> None:
        self._session.scan_result = result
        self.scan_complete.emit(result)
        n = result.files_count
        self.status_update.emit(
            f"נסרקו {n} קבצים ב-{result.folders_count} תיקיות"
        )

    def _on_scan_error(self, msg: str) -> None:
        logger.error("[MetadataController] Scan error: %s", msg)
        self.status_update.emit(f"שגיאה בסריקה: {msg}")

    def _on_apply_progress(self, done: int, total: int) -> None:
        self.apply_progress.emit(done, total)
        self.status_update.emit(f"כותב תגיות… {done}/{total}")

    def _on_apply_finished(self, success: int, fail: int, skip: int) -> None:
        self._session.apply_done    = success
        self._session.apply_failed  = fail
        self._session.apply_skipped = skip
        self.apply_complete.emit(success, fail, skip)
        bp = self._session.backup_path
        bp_note = f" (גיבוי: {bp.name})" if bp else ""
        self.status_update.emit(
            f"הושלם — {success} הצליחו, {fail} נכשלו, {skip} דולגו{bp_note}"
        )

    def _cancel_scan(self) -> None:
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.cancel()
            self._scan_worker.wait(1000)
