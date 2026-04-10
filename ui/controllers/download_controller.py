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
import re
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
    show_error_dialog   = Signal(object)    # ErrorInfo
    batch_finished      = Signal()
    batch_started       = Signal()

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

        jobs: list[tuple[str, DownloadRequest]] = []

        for card in selected:
            track_playlist_name:   Optional[str] = None
            is_parent_discography: bool          = False

            if self._cfg.playlist_subfolders:
                parent_artist = (card.parent_artist or "").strip()
                kind          = (card.release_type  or "").strip()
                album         = (card.album         or "").strip()

                if parent_artist:
                    is_live     = "live" in card.title.lower() or "הופעה" in card.title
                    is_spotify  = card.platform == SourcePlatform.SPOTIFY.value

                    if kind == "album":
                        category = "אלבומים"
                    elif not is_spotify and (kind == "performance" or is_live):
                        category = "הופעות חיות"
                    elif not is_spotify and kind == "video":
                        category = "סרטונים"
                    elif not is_spotify and kind == "playlist":
                        category = "פלייליסטים"
                    else:
                        category = "סינגלים ו-EP"

                    if kind == "album" and album:
                        clean_album = album.replace("Album - ", "").replace("Album -", "").strip()
                        track_playlist_name = f"{parent_artist}/{category}/{clean_album}"
                    else:
                        track_playlist_name = f"{parent_artist}/{category}"

                    is_parent_discography = (last_url_kind == UrlKind.ARTIST)

                elif is_multi:
                    if last_url_kind == UrlKind.ARTIST:
                        album_part          = card.album if card.album else "Singles & EPs"
                        track_playlist_name = f"{card.artist}/{album_part}"
                    else:
                        track_playlist_name = last_playlist_title or "Playlist"
                elif card.artist:
                    pass  # single track — no subfolder

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

            # Smart clean filename
            is_clean = not is_multi_batch
            if is_multi_batch and card.artist and card.parent_artist:
                if card.artist.strip().lower() == card.parent_artist.strip().lower():
                    is_clean = True

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
                    card.album_index
                    if (card.release_type == "album" and card.album_index > 0)
                    else (
                        None if card.release_type == "playlist"
                        else (
                            card.queue_index
                            if (self._cfg.playlist_index_prefix and not is_parent_discography)
                            else None
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
                embed_lyrics=self._cfg.lyrics_enabled,
                replay_gain=self._cfg.replay_gain_enabled,
                musicbrainz=self._cfg.musicbrainz_enabled,
                square_thumbnails=self._cfg.square_thumbnails,
                clean_filename=is_clean,
                randomize_user_agent=self._cfg.randomize_user_agent,
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
        self._dl_worker.track_status.connect(self._on_track_status)
        self._dl_worker.track_finished.connect(self._on_track_finished)
        self._dl_worker.overall_progress.connect(self.overall_progress)
        self._dl_worker.metrics.connect(self.metrics_update)
        self._dl_worker.status_msg.connect(self.status_update)
        self._dl_worker.job_count_changed.connect(self.job_count_changed)
        self._dl_worker.job_error.connect(self._on_track_error)
        self._dl_worker.all_finished.connect(self._on_batch_done)
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
                resumable=True,   # pick up .part file on resume
                embed_lyrics=req.embed_lyrics,
                replay_gain=req.replay_gain,
                musicbrainz=req.musicbrainz,
                square_thumbnails=req.square_thumbnails,
                clean_filename=req.clean_filename,
                cookies_file=req.cookies_file,
                randomize_user_agent=req.randomize_user_agent,
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
            db=self._db,
            max_workers=1,
            parent=self,
        )
        self._resume_workers.append(resume_worker)
        resume_worker.track_progress.connect(self._on_track_progress)
        resume_worker.track_status.connect(self._on_track_status)
        resume_worker.track_finished.connect(self._on_track_finished)
        resume_worker.job_error.connect(self._on_track_error)
        resume_worker.all_finished.connect(self._on_batch_done)
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
        self.show_error_dialog.emit(err)

    def _on_batch_done(self) -> None:
        self._dl_worker = None
        self.cancel_visible.emit(False)
        self.downloading_changed.emit(False)
        self.metrics_update.emit("", "")
        self.batch_finished.emit()

    # ── Helpers ───────────────────────────────────────────────────────────────

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
        Construct a folder path like 'Artist / Category / Album' without redundancy.
        Preserves the de-duplication pass to prevent paths like 'Name/אלבומים/Name'.
        """
        artist   = (card.parent_artist or card.artist or "").strip()
        album    = (card.album or "").strip()
        rel_type = (card.release_type or "album").lower()

        CAT_ALBUMS  = "אלבומים"  # noqa: F841  (kept for symmetry with original)
        CAT_SINGLES = "סינגלים ו-EP"

        path_parts: list[str] = []

        if is_discography and artist and rel_type != "album":
            path_parts.append(artist)

        if is_discography:
            if rel_type == "album":
                if album:
                    path_parts.append(album.replace("Album - ", "").strip())
            else:
                path_parts.append(CAT_SINGLES)
        elif album:
            path_parts.append(album.replace("Album - ", "").strip())
        elif artist:
            path_parts.append(artist)

        # De-duplication (case-insensitive)
        seen: list[str] = []
        for part in path_parts:
            if not seen or part.lower() != seen[-1].lower():
                seen.append(part)

        return "/".join(seen)
