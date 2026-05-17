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
    tags_modified      = Signal()              # any in-memory tag edit (triggers table refresh)
    apply_started      = Signal()
    apply_progress     = Signal(int, int)      # done, total
    apply_file_done    = Signal(str, bool)     # path, success
    apply_complete     = Signal(int, int, int) # success, fail, skip
    apply_error        = Signal(str)
    status_update      = Signal(str)

    # Duplicate detector signals
    duplicate_scan_progress  = Signal(int, int, str)     # done, total, eta_str
    duplicate_scan_complete  = Signal(object, float, str) # groups dict, elapsed, strategy
    duplicate_scan_error     = Signal(str)
    duplicate_delete_complete = Signal(int, int)          # success, fail

    def __init__(self, parent: QObject = None) -> None:
        super().__init__(parent)
        self._scan_worker  = None
        self._apply_worker = None
        self._dup_worker   = None
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

        changed_count = sum(1 for t in tracks if t.has_changes)
        self.auto_rules_applied.emit()
        self.tags_modified.emit()
        if changed_count:
            self.status_update.emit(f"סדר אוטומטי: {changed_count} שינויים הוצעו")
        else:
            self.status_update.emit("סדר אוטומטי: כל הקבצים כבר מסודרים")

    def apply_artist_to_scope(self, artist: str, tracks: list[AudioTrackItem]) -> None:
        """Set proposed.artist (and album_artist) on all given tracks."""
        for item in tracks:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            item.proposed.artist = artist
            if not item.proposed.album_artist:
                item.proposed.album_artist = artist
        self.tags_modified.emit()
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
        self.tags_modified.emit()
        self.status_update.emit(f"אלבום '{album}' הוחל על {len(affected)} קבצים")

    def apply_album_to_scope(self, album: str, tracks: list[AudioTrackItem]) -> None:
        """Set proposed.album on all given tracks (regardless of folder)."""
        affected = 0
        for item in tracks:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            item.proposed.album = album
            affected += 1
        self.tags_modified.emit()
        self.status_update.emit(f"אלבום '{album}' הוחל על {affected} קבצים")

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
        self.tags_modified.emit()

    def apply_track_from_filename(self, tracks: list[AudioTrackItem]) -> None:
        for item in tracks:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            num = extract_track_number(item.path.name)
            if num is not None:
                item.proposed.track_num = num
        self.tags_modified.emit()

    def clear_comments(self, tracks: list[AudioTrackItem]) -> None:
        for item in tracks:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            item.proposed.comment = ""
        self.tags_modified.emit()

    def apply_changes(
        self,
        backup_dir: Optional[Path] = None,
        tracks_to_apply: Optional[list] = None,
    ) -> None:
        """Launch MetadataApplyWorker.  If tracks_to_apply is given (checked tracks),
        only those are written; otherwise every changed track in the session is written."""
        from ui.workers.metadata_worker import MetadataApplyWorker

        if self._apply_worker and self._apply_worker.isRunning():
            return

        candidates = (
            tracks_to_apply
            if tracks_to_apply is not None
            else (self._session.scan_result.tracks if self._session.scan_result else [])
        )
        changed = [t for t in candidates if t.has_changes]

        if not changed:
            self.status_update.emit("אין שינויים להחלה בקבצים הנבחרים")
            return

        bd = backup_dir or _BACKUP_DIR
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = bd / f"ytspot_tag_backup_{timestamp}.json"
        self._session.backup_path = backup_path

        self.apply_started.emit()
        self.status_update.emit(f"כותב תגיות ל-{len(changed)} קבצים…")

        self._apply_worker = MetadataApplyWorker(candidates, backup_path, parent=self)
        self._apply_worker.progress.connect(self._on_apply_progress)
        self._apply_worker.file_done.connect(self.apply_file_done)
        self._apply_worker.finished.connect(self._on_apply_finished)
        self._apply_worker.start()

    # ── New magic operations ───────────────────────────────────────────────────

    def apply_album_artist_from_artist(self, tracks: list[AudioTrackItem]) -> None:
        """Set album_artist to the current (or proposed) artist value."""
        for item in tracks:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            src = item.proposed.artist if item.proposed.artist is not None else item.original.artist
            if src:
                item.proposed.album_artist = src
        self.tags_modified.emit()
        self.status_update.emit(f"אמן אלבום הועתק מ-אמן ({len(tracks)} קבצים)")

    def split_artist_title_from_filename(self, tracks: list[AudioTrackItem]) -> None:
        """Parse filenames of the form 'Artist – Title.ext' into separate fields."""
        import re
        _SPLIT_RE = re.compile(r"^(.+?)\s*[-–—]\s*(.+)$")
        count = 0
        for item in tracks:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            m = _SPLIT_RE.match(item.path.stem)
            if m:
                item.proposed.artist = m.group(1).strip()
                item.proposed.title  = m.group(2).strip()
                count += 1
        self.tags_modified.emit()
        self.status_update.emit(f"פיצול אמן-כותרת הושלם ({count} קבצים)")

    def clear_year(self, tracks: list[AudioTrackItem]) -> None:
        for item in tracks:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            item.proposed.year = ""
        self.tags_modified.emit()
        self.status_update.emit("שנה נוקתה")

    def clear_genre(self, tracks: list[AudioTrackItem]) -> None:
        for item in tracks:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            item.proposed.genre = ""
        self.tags_modified.emit()
        self.status_update.emit("ז'אנר נוקה")

    def clear_track_num(self, tracks: list[AudioTrackItem]) -> None:
        for item in tracks:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            item.proposed.track_num = ""
        self.tags_modified.emit()
        self.status_update.emit("מספר רצועה נוקה")

    def normalize_title_spaces(self, tracks: list[AudioTrackItem]) -> None:
        """Replace underscores with spaces and collapse multiple spaces in title."""
        count = 0
        for item in tracks:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            src = item.proposed.title if item.proposed.title is not None else item.original.title
            if src:
                cleaned = src.replace("_", " ")
                cleaned = " ".join(cleaned.split())
                if cleaned != src:
                    item.proposed.title = cleaned
                    count += 1
        self.tags_modified.emit()
        self.status_update.emit(f"נוקה רווחים ב-{count} כותרות")

    def strip_web_junk_from_title(self, tracks: list[AudioTrackItem]) -> None:
        """Remove common YouTube/web annotations from title (Official Video, HD, etc.)."""
        import re
        _JUNK_RE = re.compile(
            r"\s*[\[\(]"
            r"(?:Official\s*(?:Music\s*)?(?:Video|Audio|Lyric[s]?|MV)|"
            r"Lyric[s]?|HD|HQ|4K|Visualizer|Audio|Video|"
            r"feat\.?\s*[^\]\)]+|ft\.?\s*[^\]\)]+|"
            r"Remastered(?:\s*\d{4})?|Live(?:\s*Version)?|"
            r"Cover|Remix|Extended|Radio\s*Edit|"
            r"מוזיקה\s*רשמית|קליפ\s*רשמי)"
            r"[^\]\)]*[\]\)]",
            re.IGNORECASE,
        )
        count = 0
        for item in tracks:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            src = item.proposed.title if item.proposed.title is not None else item.original.title
            if src:
                cleaned = _JUNK_RE.sub("", src).strip()
                if cleaned != src:
                    item.proposed.title = cleaned
                    count += 1
        self.tags_modified.emit()
        self.status_update.emit(f"זבל הוסר מ-{count} כותרות")

    def clean_filename(self, tracks: list[AudioTrackItem]) -> None:
        """Clean the physical filename (remove underscores, brackets, etc.)."""
        import re
        count = 0
        for item in tracks:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            current_name = item.proposed_filename if item.proposed_filename else item.path.name
            stem = current_name.rsplit('.', 1)[0] if '.' in current_name else current_name
            ext = item.path.suffix
            
            cleaned = stem.replace("_", " ")
            cleaned = re.sub(r'\(.*?\)', '', cleaned)
            cleaned = re.sub(r'\[.*?\]', '', cleaned)
            cleaned = " ".join(cleaned.split())
            
            if cleaned and cleaned != stem:
                item.proposed_filename = cleaned + ext
                count += 1
                
        self.tags_modified.emit()
        self.status_update.emit(f"שם קובץ פיזי נוקה עבור {count} קבצים")

    def strip_filename_numbering(self, tracks: list[AudioTrackItem]) -> None:
        """Remove leading numbering (e.g. '01 - ') from physical filename."""
        import re
        _PREFIX_RE = re.compile(r'^\s*\d+\s*[-_.]?\s*')
        count = 0
        for item in tracks:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            current_name = item.proposed_filename if item.proposed_filename else item.path.name
            stem = current_name.rsplit('.', 1)[0] if '.' in current_name else current_name
            ext = item.path.suffix
            
            cleaned = _PREFIX_RE.sub('', stem).strip()
            
            if cleaned and cleaned != stem:
                item.proposed_filename = cleaned + ext
                count += 1
                
        self.tags_modified.emit()
        self.status_update.emit(f"מספור הוסר משם הקובץ עבור {count} קבצים")

    def find_duplicates(self, folder: Path, recursive: bool) -> None:
        """Launch DuplicateDetectorWorker to scan for duplicate audio files."""
        from ui.workers.duplicate_detector_worker import DuplicateDetectorWorker

        if self._dup_worker and self._dup_worker.isRunning():
            self._dup_worker.cancel()
            self._dup_worker.wait(1000)

        self.status_update.emit(f"מחפש כפילויות ב-{folder.name}…")
        self._dup_worker = DuplicateDetectorWorker(folder, recursive, parent=self)
        self._dup_worker.progress.connect(self.duplicate_scan_progress)
        self._dup_worker.finished.connect(self._on_dup_finished)
        self._dup_worker.error.connect(self.duplicate_scan_error)
        self._dup_worker.start()

    def delete_duplicate_files(self, paths: list) -> None:
        """Delete the given file paths, preferring send2trash (Recycle Bin)."""
        success = 0
        fail    = 0
        for p in paths:
            path = Path(p) if not isinstance(p, Path) else p
            if not path.exists():
                logger.warning("[MetadataController] File already gone, skipping: %s", path)
                continue
            try:
                try:
                    import send2trash
                    send2trash.send2trash(str(path))
                except ImportError:
                    path.unlink()
                success += 1
            except Exception as exc:
                logger.warning("[MetadataController] Delete failed %s: %s", path, exc)
                fail += 1

        self.duplicate_delete_complete.emit(success, fail)
        note = f", {fail} שגיאות" if fail else ""
        self.status_update.emit(f"נמחקו {success} קבצים כפולים{note}")

    def cancel_apply(self) -> None:
        if self._apply_worker and self._apply_worker.isRunning():
            self._apply_worker.cancel()

    def revert_all(self, tracks: list[AudioTrackItem]) -> None:
        """Clear all proposed tags on every given track."""
        for item in tracks:
            item.proposed.clear()
        self.tags_modified.emit()
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

    def _on_dup_finished(self, groups: dict, elapsed: float, strategy: str) -> None:
        n_groups = len(groups)
        n_files  = sum(len(v) for v in groups.values())
        strat_lbl = "גודל קובץ" if strategy == "size" else "MD5"
        self.status_update.emit(
            f"נמצאו {n_files} כפילויות ב-{n_groups} קבוצות ({strat_lbl}, {elapsed:.1f}s)"
        )
        self.duplicate_scan_complete.emit(groups, elapsed, strategy)

    def _cancel_scan(self) -> None:
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.cancel()
            self._scan_worker.wait(1000)
