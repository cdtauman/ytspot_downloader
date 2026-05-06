"""
ui/controllers/download_controller.py
=======================================
Manages the full download lifecycle:
  * Building DownloadRequest objects from queue cards + config
  * Running DownloadWorker (batch) and per-track resume workers
  * Pause / resume per-track and global pause
  * Routing DownloadWorker signals to card state (set_progress / set_status)
  * Emitting higher-level signals that AppWindow connects to panels

AppWindow mediates cross-controller interactions and all widget-level UI
(InfoBar, MessageBox, tray notifications, queue state persistence).

Zero Qt widget imports in this file — self.parent() is used only for
MessageBox parent in the duplicate-check dialog (unavoidable Qt requirement).
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from config import AppConfig
from core.downloader import (
    AudioQuality,
    DownloadEngine,
    DownloadRequest,
    MediaType,
    VideoQuality,
)
from core.history_db import HistoryDB
from core.playlist_parser import SourcePlatform, UrlKind

logger = logging.getLogger(__name__)


# ── Quality maps ──────────────────────────────────────────────────────────────

_AUDIO_QUALITY_MAP = {
    "Best (320k)":   AudioQuality.BEST,
    "High (256k)":   AudioQuality.HIGH,
    "Medium (192k)": AudioQuality.MEDIUM,
    "Low (128k)":    AudioQuality.LOW,
}
_VIDEO_QUALITY_MAP = {
    "Best":  VideoQuality.BEST,
    "1080p": VideoQuality.HIGH,
    "720p":  VideoQuality.MEDIUM,
    "480p":  VideoQuality.LOW,
    "Worst": VideoQuality.WORST,
}
_MULTI_KINDS = {UrlKind.PLAYLIST, UrlKind.ALBUM, UrlKind.ARTIST}


def _parse_stream_type(category: str) -> Optional[str]:
    """Extract stream_type from a category string like 'stream:hls'."""
    if category and category.startswith("stream:"):
        return category[len("stream:"):]
    return None


class DownloadController(QObject):
    """
    Owns all download logic extracted from AppWindow.

    Signals to AppWindow / panels
    ------------------------------
    status_update      : str — → status_bar.set_status()
    metrics_update     : (str, str) speed, eta — → status_bar.set_metrics()
    overall_progress   : float — → status_bar.set_progress()
    cancel_visible     : bool — → status_bar.set_cancel_visible()
    downloading_changed: bool — → dl_bar.set_downloading()
    job_count_changed  : (int, int) completed, total
    show_success_bar   : str output_path — AppWindow shows InfoBar
    show_error_dialog  : object ErrorInfo — AppWindow shows MessageBox
    batch_finished     : () — AppWindow resets queue state + tray notification
    batch_started      : () — AppWindow saves queue state to config
    """

    status_update       = Signal(str)
    metrics_update      = Signal(str, str)
    overall_progress    = Signal(float)
    cancel_visible      = Signal(bool)
    downloading_changed = Signal(bool)
    job_count_changed   = Signal(int, int)
    show_success_bar    = Signal(str)       # output_path
    show_error_dialog   = Signal(object, str)    # ErrorInfo, Failing URL
    batch_finished      = Signal()
    batch_started       = Signal()
    browser_lock_warning = Signal(str)  # browser name (e.g. 'Chrome')
    track_thumbnail     = Signal(int, str)

    def __init__(
        self,
        config:  AppConfig,
        engine:  DownloadEngine,
        db:      Optional[HistoryDB] = None,
        parent:  QObject = None,
    ) -> None:
        super().__init__(parent)
        self._cfg    = config
        self._engine = engine
        self._db     = db

        self._dl_worker:      Optional = None
        self._resume_workers: list     = []

        # key (str(id(card))) → TrackCard
        self._key_to_card:   dict = {}
        # key → last reported fraction (throttle UI updates)
        self._card_progress: dict = {}
        # key → DownloadRequest snapshot saved at pause time
        self._paused_requests: dict[str, DownloadRequest] = {}
                
        self._fatal_error_triggered = False  # Track if a fatal dialog was already shown
        self._fatal_lock = threading.Lock()  # Synchronize fatal error reporting

    # ── Public API ────────────────────────────────────────────────────────────

    def start_batch(
        self,
        selected:             list,             # list[TrackCard]
        opts:                 dict,             # from OptionsBar.get_options()
        last_url_kind:        Optional[UrlKind],
        last_playlist_title:  str,
    ) -> None:
        """
        Build DownloadRequest objects for every selected card and start a
        DownloadWorker.  All job-building logic that was in AppWindow._on_download
        lives here.
        """
        from qfluentwidgets import MessageBox
        from ui.i18n import t

        if not selected:
            self.status_update.emit(f"\u26a0  {t('no_tracks_selected')}")
            return

        # Reset the fatal error lock for the new batch
        with self._fatal_lock:
            self._fatal_error_triggered = False
        
        # Simple User Pre-flight Check: is Chrome locking our cookies?
        if self._cfg.cookies_browser == "chrome":
            if self._is_process_running("chrome.exe"):
                self.browser_lock_warning.emit("Chrome")
                return

        is_audio   = opts["is_audio"]
        media_type = MediaType.AUDIO if is_audio else MediaType.VIDEO
        audio_q    = _AUDIO_QUALITY_MAP.get(opts["quality_label"], AudioQuality.BEST)
        video_q    = _VIDEO_QUALITY_MAP.get(opts["quality_label"], VideoQuality.HIGH)
        # Verify the base output dir is writable (opts["output_dir"] from OptionsBar)
        base_output_dir = opts["output_dir"]
        try:
            Path(base_output_dir).expanduser().mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError) as exc:
            MessageBox(
                t("cannot_write_output_title"),
                t("cannot_write_output_detail", path=base_output_dir, exc=exc),
                self.parent(),
            ).exec()
            return

        is_multi = last_url_kind in _MULTI_KINDS
        self._key_to_card.clear()
        self._card_progress.clear()

        unique_artists  = {c.artist for c in selected if c.artist}
        is_multi_batch  = len(unique_artists) > 1
        is_solo         = len(selected) == 1

        jobs: list[tuple[str, DownloadRequest]] = []

        for card in selected:
            track_playlist_name:   Optional[str] = None
            is_parent_discography: bool          = False

            if self._cfg.playlist_subfolders:
                parent_artist = (card.parent_artist or "").strip()
                kind          = (card.release_type  or "").strip()
                album         = (card.album         or "").strip()
                platform      = (card.platform      or "").lower()
                category      = (card.category      or "").strip()

                if parent_artist:
                    is_live     = "live" in card.title.lower() or "הופעה" in card.title
                    is_spotify  = "spotify" in platform
                    
                    # ── CATEGORY MAPPING ──────────────────────────────────────
                    if kind == "album":
                         cat_name = "אלבומים"
                    elif (is_live or kind == "performance") and not is_spotify:
                        cat_name = "הופעות חיות"
                    elif category: # Scraper provided category (e.g. "סינגלים ו-EP", "שורטס")
                        cat_name = category
                    elif kind == "video":
                        cat_name = "סרטונים"
                    elif kind == "playlist":
                        cat_name = "פלייליסטים"
                    elif is_spotify:
                        cat_name = "סינגלים ו-EP"
                    else:
                        cat_name = "סינגלים וגרסאות EP"

                     # ── FOLDER DEPTH LOGIC ────────────────────────────────────
                    # User wants strict separation:
                    # 1. 'אלבומים' ALWAYS get a subfolder if an album name is known.
                    # 2. 'סינגלים ו-EP' only get a subfolder if they have multiple tracks (EP).
                    # 3. YTM/Other releases use the count heuristic.
                    
                    is_grouped = (
                        (kind == "album") or
                        (kind == "ep") or
                        (cat_name == "אלבומים") or
                        (cat_name in ("סינגלים ו-EP", "סינגלים וגרסאות EP") and (card.total_tracks > 1 or kind == "ep")) or
                        (card.total_tracks > 1 and album)
                    )
                    
                    if is_grouped and album:
                        track_playlist_name = f"{parent_artist}/{cat_name}/{album}"
                    else:
                        track_playlist_name = f"{parent_artist}/{cat_name}"

                    is_parent_discography = True

                elif is_multi:
                    # Generic multi-item (Playlist/Album) logic
                    track_playlist_name = last_playlist_title or "Playlist"
                elif card.artist:
                    pass  # single track — no subfolder

            # User wants NO folders for solo downloads
            if is_solo:
                track_playlist_name = ""

            # Always use config output_dir as the base (opts["output_dir"] is verified
            # above only for the mkdir check; the actual base is cfg.output_dir)
            output_dir = str(Path(self._cfg.output_dir))

            # Duplicate detection
            if self._cfg.duplicate_action != "overwrite":
                from core.duplicate_checker import find_duplicate
                dup = find_duplicate(
                    output_dir=output_dir,
                    title=card.title,
                    artist=card.artist,
                    index=card.queue_index if self._cfg.playlist_index_prefix else None,
                    include_index=self._cfg.playlist_index_prefix,
                    duration_s=None,
                    playlist_name=self._get_dynamic_folder(
                        card, track_playlist_name, is_parent_discography
                    ),
                )
                if dup is not None:
                    if self._cfg.duplicate_action == "skip":
                        card.set_status("done")
                        continue
                    else:  # "warn"
                        box = MessageBox(
                            "Duplicate Detected",
                            f'"{card.title}" already exists:\n{dup}\n\n'
                            "Download again and overwrite?",
                            self.parent(),
                        )
                        if not box.exec():
                            card.set_status("done")
                            continue

            # Clean filename (index + title only, no artist) for any multi-track
            # download — the folder path already encodes the artist context.
            is_clean = is_multi or is_solo

            req = DownloadRequest(
                url=card.track_url,
                output_dir=output_dir,
                media_type=media_type,
                audio_quality=audio_q,
                video_quality=video_q,
                audio_format=opts["audio_format"] if is_audio else "mp4",
                embed_thumbnail=self._cfg.embed_thumbnail,
                embed_metadata=self._cfg.embed_metadata,
                forced_title=card.title,
                forced_artist=card.artist,
                forced_album=card.album,
                forced_duration=getattr(card, "duration_sec", None),
                forced_index=(
                    None if is_solo else (
                        card.album_index
                        if (card.release_type in ("album", "ep") and card.album_index > 0)                    
                        else (
                            None if card.release_type == "playlist"
                            else (
                                card.queue_index
                                if (self._cfg.playlist_index_prefix and not is_parent_discography)
                                else None
                            )
                        )
                    )
                ),
                cookies_file=self._cfg.cookies_file or None,
                cookies_browser=self._cfg.cookies_browser or None,
                playlist_name=self._get_dynamic_folder(
                    card, track_playlist_name, is_parent_discography
                ),
                thumbnail_url=card.thumbnail_url,
                sponsorblock=self._cfg.sponsorblock_enabled,
                sponsorblock_categories=self._cfg.get("sponsorblock_categories") or None,
                embed_lyrics=self._cfg.lyrics_enabled,
                replay_gain=self._cfg.replay_gain_enabled,
                musicbrainz=self._cfg.musicbrainz_enabled,
                square_thumbnails=self._cfg.square_thumbnails,
                expand_thumbnails=self._cfg.expand_thumbnails,
                clean_filename=is_clean,
                randomize_user_agent=self._cfg.randomize_user_agent,
                proxy_url=self._cfg.get("youtube_proxy_url") or None,
                is_solo=is_solo,
                stream_type=_parse_stream_type(getattr(card, "category", "")),
                category=getattr(card, "category", "") or None,
            )

            key = str(id(card))
            self._key_to_card[key] = card
            jobs.append((key, req))

        if not jobs:
            return

        self._engine._cancel_event.clear()  # noqa: SLF001
        for card in selected:
            card.set_status("queued")
            card.set_progress(0.0)

        n = len(jobs)
        self.cancel_visible.emit(True)
        self.downloading_changed.emit(True)
        self.status_update.emit(
            t("starting_downloads", n=n, plural=("" if n == 1 else "s"))
        )

        from ui.workers.download_worker import DownloadWorker
        self._dl_worker = DownloadWorker(
            jobs=jobs,
            engine=self._engine,
            config=self._cfg,
            db=self._db,
            max_workers=self._cfg.max_parallel_downloads,
            parent=self,
        )
        self._dl_worker.track_progress.connect(self._on_track_progress)
        self._dl_worker.track_speed.connect(self._on_track_speed)
        self._dl_worker.track_status.connect(self._on_track_status)
        self._dl_worker.track_finished.connect(self._on_track_finished)
        self._dl_worker.overall_progress.connect(self.overall_progress)
        self._dl_worker.metrics.connect(self.metrics_update)
        self._dl_worker.status_msg.connect(self.status_update)
        self._dl_worker.job_count_changed.connect(self.job_count_changed)
        self._dl_worker.job_error.connect(self._on_track_error)
        self._dl_worker.all_finished.connect(self._on_batch_done)
        self._dl_worker.track_thumbnail.connect(self._on_track_thumbnail)
        self._dl_worker.start()

        self.batch_started.emit()

    def global_pause(self) -> None:
        """Cancel the running batch (leaves .part files in place)."""
        if self._dl_worker and self._dl_worker.isRunning():
            self._dl_worker.cancel()

    def cancel_all(self) -> None:
        """Cancel the engine (all in-flight yt-dlp downloads) and the worker."""
        self._engine.cancel_all()
        if self._dl_worker and self._dl_worker.isRunning():
            self._dl_worker.cancel()

    def pause_track(self, card) -> None:
        """
        Save the in-flight request for this card and cancel only that track.
        AppWindow looks up the card from _index_to_card and passes it here.
        """
        key = str(id(card))
        req = self._active_request_for_key(key)
        if req is not None:
            req_copy = DownloadRequest(
                url=req.url,
                output_dir=req.output_dir,
                media_type=req.media_type,
                audio_quality=req.audio_quality,
                video_quality=req.video_quality,
                audio_format=req.audio_format,
                embed_thumbnail=req.embed_thumbnail,
                embed_metadata=req.embed_metadata,
                forced_title=req.forced_title,
                forced_artist=req.forced_artist,
                forced_index=req.forced_index,
                playlist_name=req.playlist_name,
                sponsorblock=req.sponsorblock,
                sponsorblock_categories=req.sponsorblock_categories,
                resumable=True,   # pick up .part file on resume
                embed_lyrics=req.embed_lyrics,
                replay_gain=req.replay_gain,
                musicbrainz=req.musicbrainz,
                square_thumbnails=req.square_thumbnails,
                expand_thumbnails=req.expand_thumbnails,
                clean_filename=req.clean_filename,
                cookies_file=req.cookies_file,
                randomize_user_agent=req.randomize_user_agent,
                proxy_url=req.proxy_url,
                stream_type=req.stream_type,
            )
            self._paused_requests[key] = req_copy

        if self._dl_worker:
            self._dl_worker.cancel_track(key)
        card.set_status("paused")

        paused = self._cfg.paused_items
        paused.append({
            "card_key": key,
            "title":    card.title,
            "artist":   card.artist,
            "url":      card.track_url,
        })
        self._cfg.paused_items = paused
        self._cfg.save()

    def resume_track(self, card) -> None:
        """
        Re-submit the paused DownloadRequest with continuedl=True.
        AppWindow looks up the card from _index_to_card and passes it here.
        """
        from ui.workers.download_worker import DownloadWorker

        key = str(id(card))
        req = self._paused_requests.pop(key, None)
        if req is None:
            logger.warning("[DownloadController] No paused request for card %s", key)
            return

        paused = [p for p in self._cfg.paused_items if p.get("card_key") != key]
        self._cfg.paused_items = paused
        self._cfg.save()

        card.set_status("queued")
        card.set_progress(0.0)

        self._key_to_card[key] = card
        resume_worker = DownloadWorker(
            jobs=[(key, req)],
            engine=self._engine,
            config=self._cfg,
            db=self._db,
            max_workers=1,
            parent=self,
        )
        self._resume_workers.append(resume_worker)
        resume_worker.track_progress.connect(self._on_track_progress)
        resume_worker.track_speed.connect(self._on_track_speed)
        resume_worker.track_status.connect(self._on_track_status)
        resume_worker.track_finished.connect(self._on_track_finished)
        resume_worker.job_error.connect(self._on_track_error)
        resume_worker.all_finished.connect(self._on_batch_done)
        resume_worker.track_thumbnail.connect(self._on_track_thumbnail)
        resume_worker.all_finished.connect(
            lambda w=resume_worker: (
                self._resume_workers.remove(w) if w in self._resume_workers else None
            )
        )
        resume_worker.start()

    # ── Private slots (wired to DownloadWorker signals) ───────────────────────

    def _on_track_progress(self, key: str, fraction: float) -> None:
        prev = self._card_progress.get(key, 0.0)
        if fraction - prev < 0.01 and fraction < 1.0:
            return
        self._card_progress[key] = fraction
        card = self._key_to_card.get(key)
        if card:
            card.set_progress(fraction)
            if card._status != "downloading":  # noqa: SLF001
                card.set_status("downloading")

    def _on_track_speed(self, key: str, speed_bps: float, eta_seconds: float) -> None:
        card = self._key_to_card.get(key)
        if card and hasattr(card, "update_speed"):
            card.update_speed(speed_bps, eta_seconds)

    def _on_track_status(self, key: str, status: str) -> None:
        card = self._key_to_card.get(key)
        if card:
            card.set_status(status)

    def _on_track_finished(self, key: str, output_path: str) -> None:
        card = self._key_to_card.get(key)
        if card:
            card.set_status("done")
            card.set_progress(1.0)
        self.show_success_bar.emit(output_path)

    def _on_track_error(self, key: str, err: object) -> None:
        card = self._key_to_card.get(key)
        if card:
            card.set_status("error")

    def _on_track_thumbnail(self, key: str, thumb_url: str) -> None:
        card = self._key_to_card.get(key)
        if card:
            self.track_thumbnail.emit(card.queue_index, thumb_url)

        err_msg = str(err)
        if hasattr(err, "error_message"):
            err_msg = err.error_message
            
        # Detect fatal errors that should stop the entire batch
        is_fatal = False
        fatal_markers = [
            "confirm you’re not a bot", 
            "cookie database", 
            "DPAPI",
            "HTTP Error 403",
            "Signature solving failed",
            "n challenge solving failed",
            "Requested format is not available",
            "Please sign in",
            "YouTube account cookies are no longer valid"
        ]
        if any(marker in err_msg for marker in fatal_markers):
            is_fatal = True
            
        # Get the failing URL to pass to the UI
        failing_url = ""
        track_req = self._active_request_for_key(key)
        if track_req:
            failing_url = track_req.url

        # Storm prevention: only emit the first fatal dialog (Thread Safe)
        with self._fatal_lock:
            if not is_fatal or not self._fatal_error_triggered:
                if is_fatal:
                    self._fatal_error_triggered = True
                self.show_error_dialog.emit(err, failing_url)
        
        if is_fatal:
            logger.warning("[DownloadController] Fatal error detected. Cancelling batch.")
            self.cancel_all()

    def _on_batch_done(self) -> None:
        self._dl_worker = None
        self.cancel_visible.emit(False)
        self.downloading_changed.emit(False)
        self.metrics_update.emit("", "")
        self.batch_finished.emit()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _is_process_running(self, process_name: str) -> bool:
        """Check if a process is running on Windows using tasklist."""
        import subprocess
        try:
            output = subprocess.check_output('tasklist /FI "IMAGENAME eq ' + process_name + '" /NH', 
                                            shell=True, stderr=subprocess.DEVNULL).decode('utf-8', errors='ignore')
            return process_name.lower() in output.lower()
        except Exception:
            return False

    def _active_request_for_key(self, key: str) -> Optional[DownloadRequest]:
        """Retrieve the live DownloadRequest for a card key from the active worker."""
        if self._dl_worker is None:
            return None
        for card_key, req in self._dl_worker._jobs:  # noqa: SLF001
            if card_key == key:
                return req
        return None

    def _get_dynamic_folder(
        self,
        card,
        fallback: Optional[str] = None,
        is_discography: bool = False,
    ) -> str:
        """
        Construct a folder path. If 'fallback' is provided (from the main loop), it takes priority
        as it was constructed with full context.
        """
        if fallback is not None:
            # Fallback already contains the logic-built path (e.g. "Playlist Name", "Artist/Category/Album", or "" for Solo)
            return fallback

        artist   = (card.parent_artist or card.artist or "").strip()
        album    = (card.album or "").strip()
        rel_type = (card.release_type or "album").lower()

        path_parts: list[str] = []
        if is_discography and artist:
            path_parts.append(artist)
            if rel_type == "album":
                path_parts.append("אלבומים")
            else:
                path_parts.append("סינגלים ו-EP")
    
        if album:
            path_parts.append(album.replace("Album - ", "").strip())
        elif artist:
            path_parts.append(artist)

        # De-duplication (case-insensitive)
        seen: list[str] = []
        for part in path_parts:
            if not part: continue
            if not seen or part.lower() != seen[-1].lower():
                seen.append(part)

        return "/".join(seen)
