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
from ui.i18n import t

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

    def __init__(self, config=None, parent: QObject = None) -> None:
        super().__init__(parent)
        self._cfg          = config
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
        self.status_update.emit(t("md_scanning_folder", folder=folder.name))

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

        changed_count = sum(1 for tr in tracks if tr.has_changes)
        self.auto_rules_applied.emit()
        self.tags_modified.emit()
        if changed_count:
            self.status_update.emit(t("md_auto_changes_proposed", n=changed_count))
        else:
            self.status_update.emit(t("md_auto_no_changes"))

    def apply_artist_to_scope(self, artist: str, tracks: list[AudioTrackItem]) -> None:
        """Set proposed.artist (and album_artist) on all given tracks."""
        for item in tracks:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            item.proposed.artist = artist
            if not item.proposed.album_artist:
                item.proposed.album_artist = artist
        self.tags_modified.emit()
        self.status_update.emit(t("md_artist_applied", artist=artist, n=len(tracks)))

    def apply_album_to_folder(
        self, album: str, folder: Path, tracks: list[AudioTrackItem]
    ) -> None:
        """Set proposed.album on all tracks whose folder matches."""
        affected = [tr for tr in tracks if tr.folder == folder]
        for item in affected:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            item.proposed.album = album
        self.tags_modified.emit()
        self.status_update.emit(t("md_album_applied", album=album, n=len(affected)))

    def apply_album_to_scope(self, album: str, tracks: list[AudioTrackItem]) -> None:
        """Set proposed.album on all given tracks (regardless of folder)."""
        affected = 0
        for item in tracks:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            item.proposed.album = album
            affected += 1
        self.tags_modified.emit()
        self.status_update.emit(t("md_album_applied", album=album, n=affected))

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
            self.status_update.emit(t("md_no_changes_to_apply"))
            return

        bd = backup_dir or _BACKUP_DIR
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = bd / f"ytspot_tag_backup_{timestamp}.json"
        self._session.backup_path = backup_path

        self.apply_started.emit()
        self.status_update.emit(t("md_writing_tags_to_n", n=len(changed)))

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
        self.status_update.emit(t("md_album_artist_copied", n=len(tracks)))

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
        self.status_update.emit(t("md_artist_title_split_done", n=count))

    def clear_year(self, tracks: list[AudioTrackItem]) -> None:
        for item in tracks:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            item.proposed.year = ""
        self.tags_modified.emit()
        self.status_update.emit(t("md_year_cleared"))

    def clear_genre(self, tracks: list[AudioTrackItem]) -> None:
        for item in tracks:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            item.proposed.genre = ""
        self.tags_modified.emit()
        self.status_update.emit(t("md_genre_cleared"))

    def clear_track_num(self, tracks: list[AudioTrackItem]) -> None:
        for item in tracks:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            item.proposed.track_num = ""
        self.tags_modified.emit()
        self.status_update.emit(t("md_track_num_cleared"))

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
        self.status_update.emit(t("md_spaces_normalised", n=count))

    def strip_web_junk_from_title(self, tracks: list[AudioTrackItem]) -> None:
        """Remove common YouTube/web annotations from title based on config settings."""
        import re
        
        terms = []
        if not self._cfg or getattr(self._cfg, "tag_clean_title_remove_web_junk", True):
            terms.extend([
                r"Official\s*(?:Music\s*)?(?:Video|Audio|Lyric[s]?|MV)",
                r"Lyric[s]?(?:\s*Video)?", r"HD", r"HQ", r"4K", r"8D(?:\s*Audio)?", r"360(?:\s*Audio)?",
                r"Visualizer", r"Audio", r"Video", 
                r"feat\.?\s*[^\]\)\-\|]+", r"ft\.?\s*[^\]\)\-\|]+", r"featuring\s*[^\]\)\-\|]+",
                r"Remastered(?:\s*\d{4})?", r"Live(?:\s*Version)?", r"Live\s*Performance",
                r"Cover", r"Remix", r"Extended", r"Radio\s*Edit", r"Acoustic", r"Unplugged",
                r"Instrumental", r"Sped\s*up", r"Slowed(?:\s*\+\s*Reverb)?",
                r"Prod\.(?:\s*by)?\s*[^\]\)\-\|]+", r"Directed\s*by\s*[^\]\)\-\|]+", r"Vevo"
            ])
            
        if not self._cfg or getattr(self._cfg, "tag_clean_title_remove_hebrew", True):
            terms.extend([
                r"מוזיקה\s*רשמית", r"קליפ\s*רשמי", r"קאבר", r"רמיקס", 
                r"הופעה\s*חיה", r"מילים", r"קליפ\s*מילים", r"לייב", 
                r"ביצוע\s*אקוסטי", r"קריוקי", r"גרסת\s*כיסוי", r"אודיו", r"הקלטה"
            ])
            
        if not terms:
            self.status_update.emit(t("md_clean_settings_empty"))
            return
            
        terms_pattern = "|".join(terms)
        
        patterns = []
        if not self._cfg or getattr(self._cfg, "tag_clean_title_remove_brackets", True):
            patterns.append(rf"\s*[\[\(](?:{terms_pattern})[^\]\)]*[\]\)]")
            
        # Outside brackets, separated by - or |
        patterns.append(rf"\s*[\-\|]\s*(?:{terms_pattern})(?:\s*[\-\|]|\s*$)")
        patterns.append(rf"\s+(?:{terms_pattern})\s*$")
        
        _JUNK_RE = re.compile("|".join(patterns), re.IGNORECASE)
        _PUNC_RE = re.compile(r"[\-\|]\s*$")
        _SPACE_RE = re.compile(r"\s{2,}")
        
        count = 0
        for item in tracks:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            src = item.proposed.title if item.proposed.title is not None else item.original.title
            if src:
                cleaned = src
                for _ in range(3):
                    old_cleaned = cleaned
                    cleaned = _JUNK_RE.sub("", cleaned).strip()
                    if cleaned == old_cleaned:
                        break
                        
                if not self._cfg or getattr(self._cfg, "tag_clean_title_fix_punctuation", True):
                    cleaned = _PUNC_RE.sub("", cleaned).strip()
                    cleaned = _SPACE_RE.sub(" ", cleaned)
                    
                if cleaned != src and cleaned: 
                    item.proposed.title = cleaned
                    count += 1
        self.tags_modified.emit()
        self.status_update.emit(t("md_junk_removed", n=count))

    def clean_filename(self, tracks: list[AudioTrackItem]) -> None:
        """Clean the physical filename based on config settings."""
        import re
        count = 0
        
        smart_brackets = not self._cfg or getattr(self._cfg, "tag_clean_filename_smart_brackets", True)
        remove_domains = not self._cfg or getattr(self._cfg, "tag_clean_filename_remove_domains", True)
        remove_emojis = not self._cfg or getattr(self._cfg, "tag_clean_filename_remove_emojis", True)
        fix_spaces = not self._cfg or getattr(self._cfg, "tag_clean_filename_fix_spaces", True)
        
        if smart_brackets:
            terms = [
                r"Official\s*(?:Music\s*)?(?:Video|Audio|Lyric[s]?|MV)",
                r"Lyric[s]?(?:\s*Video)?", r"HD", r"HQ", r"4K", r"8D(?:\s*Audio)?", r"360(?:\s*Audio)?",
                r"Visualizer", r"Audio", r"Video", 
                r"Remastered(?:\s*\d{4})?", r"Live(?:\s*Version)?", r"Live\s*Performance",
                r"Cover", r"Remix", r"Extended", r"Radio\s*Edit", r"Acoustic", r"Unplugged",
                r"Instrumental", r"Sped\s*up", r"Slowed(?:\s*\+\s*Reverb)?",
                r"מוזיקה\s*רשמית", r"קליפ\s*רשמי", r"קאבר", r"רמיקס", 
                r"הופעה\s*חיה", r"מילים", r"קליפ\s*מילים", r"לייב", 
                r"ביצוע\s*אקוסטי", r"קריוקי", r"גרסת\s*כיסוי", r"אודיו", r"הקלטה"
            ]
            terms_pattern = "|".join(terms)
            _BRACKET_RE = re.compile(rf"\s*[\[\(](?:{terms_pattern})[^\]\)]*[\]\)]", re.IGNORECASE)
        else:
            _BRACKET_RE = re.compile(r'\s*[\(\[].*?[\)\]]')
            
        _DOMAIN_RE = re.compile(r"(?i)\b(?:yt1s\.com|y2mate\.com|\[SPOTIFY-DL\]|ytdownloader)\s*[\-\|]?\s*")
        
        for item in tracks:
            if item.status == TrackStatus.UNSUPPORTED:
                continue
            current_name = item.proposed_filename if item.proposed_filename else item.path.name
            stem = current_name.rsplit('.', 1)[0] if '.' in current_name else current_name
            ext = item.path.suffix
            
            cleaned = stem
            
            if remove_domains:
                cleaned = _DOMAIN_RE.sub("", cleaned)
                
            cleaned = _BRACKET_RE.sub("", cleaned)
            
            if remove_emojis:
                cleaned = re.sub(r'[\\/*?:"<>|!@#$%^&~`+={}]', '', cleaned)
                cleaned = re.sub(r'[\U00010000-\U0010ffff]', '', cleaned)
                
            if fix_spaces:
                cleaned = cleaned.replace("_", " ")
                cleaned = re.sub(r'\s*\-\s*\-\s*', ' - ', cleaned)
                cleaned = re.sub(r'\s+', ' ', cleaned).strip(" .-")
                
            if cleaned and cleaned != stem:
                item.proposed_filename = cleaned + ext
                count += 1
                
        self.tags_modified.emit()
        self.status_update.emit(t("md_filename_cleaned", n=count))

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
        self.status_update.emit(t("md_filename_numbering_removed", n=count))

    def find_duplicates(self, folder: Path, recursive: bool) -> None:
        """Launch DuplicateDetectorWorker to scan for duplicate audio files."""
        from ui.workers.duplicate_detector_worker import DuplicateDetectorWorker

        if self._dup_worker and self._dup_worker.isRunning():
            self._dup_worker.cancel()
            self._dup_worker.wait(1000)

        self.status_update.emit(t("md_searching_duplicates_in", folder=folder.name))
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
        note = t("md_duplicates_deleted_errors_suffix", fail=fail) if fail else ""
        self.status_update.emit(t("md_duplicates_deleted", success=success, note=note))

    def cancel_apply(self) -> None:
        if self._apply_worker and self._apply_worker.isRunning():
            self._apply_worker.cancel()

    def revert_all(self, tracks: list[AudioTrackItem]) -> None:
        """Clear all proposed tags on every given track."""
        for item in tracks:
            item.proposed.clear()
        self.tags_modified.emit()
        self.status_update.emit(t("md_all_changes_reverted"))

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
        self.status_update.emit(t("md_scan_done", n=n, folders=result.folders_count))

    def _on_scan_error(self, msg: str) -> None:
        logger.error("[MetadataController] Scan error: %s", msg)
        self.status_update.emit(t("md_scan_error", msg=msg))

    def _on_apply_progress(self, done: int, total: int) -> None:
        self.apply_progress.emit(done, total)
        self.status_update.emit(t("md_writing_tags_progress", done=done, total=total))

    def _on_apply_finished(self, success: int, fail: int, skip: int) -> None:
        self._session.apply_done    = success
        self._session.apply_failed  = fail
        self._session.apply_skipped = skip
        self.apply_complete.emit(success, fail, skip)
        bp = self._session.backup_path
        bp_note = t("md_apply_done_backup_note", name=bp.name) if bp else ""
        self.status_update.emit(t("md_apply_done", success=success, fail=fail, skip=skip, bp_note=bp_note))

    def _on_dup_finished(self, groups: dict, elapsed: float, strategy: str) -> None:
        n_groups = len(groups)
        n_files  = sum(len(v) for v in groups.values())
        strat_lbl = t("md_strategy_size") if strategy == "size" else t("md_strategy_md5")
        self.status_update.emit(
            t("md_duplicates_found_summary", n_files=n_files, n_groups=n_groups, strat=strat_lbl, elapsed=elapsed)
        )
        self.duplicate_scan_complete.emit(groups, elapsed, strategy)

    def _cancel_scan(self) -> None:
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.cancel()
            self._scan_worker.wait(1000)
