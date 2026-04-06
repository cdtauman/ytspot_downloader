"""
downloader.py  –  Core download engine for YTSpot Downloader  (v3)
===================================================================
Changelog v3
------------
* SponsorBlock integration: when request.sponsorblock is True, yt-dlp
  removes non-music segments (music_offtopic, sponsor, intro, outro).
* Playlist subfolder + index prefix: request.playlist_name creates
  output_dir/<name>/ and forced_index is always zero-padded.
* Pause & Resume: cancel + continuedl flag.  DownloadRequest.resumable
  controls whether yt-dlp picks up the .part file on retry.
* Post-processing pipeline after FINISHED: lyrics embed, ReplayGain,
  MusicBrainz enrichment, square thumbnail crop.  Each step is guarded
  by the corresponding request flag so it is zero-cost when disabled.
* Backward compatible: all existing DownloadRequest callers work unchanged.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Optional

import yt_dlp
try:
    import yt_dlp_ejs  # noqa: F401
except ImportError:
    pass

from utils.impersonate import (
    ImpersonateTarget as _ImpersonateTarget,
    CURL_CFFI_AVAILABLE as _CURL_CFFI_AVAILABLE,
)
from utils.yt_dlp_opts import build_base_ydl_opts as _build_base_opts


# ──────────────────────────────────────────────────────────────────────────────
# Enumerations
# ──────────────────────────────────────────────────────────────────────────────

class MediaType(Enum):
    AUDIO = auto()
    VIDEO = auto()


class VideoQuality(Enum):
    BEST   = "bestvideo+bestaudio/best"
    HIGH   = "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
    MEDIUM = "bestvideo[height<=720]+bestaudio/best[height<=720]"
    LOW    = "bestvideo[height<=480]+bestaudio/best[height<=480]"
    WORST  = "worstvideo+worstaudio/worst"


class AudioQuality(Enum):
    BEST   = "0"
    HIGH   = "2"
    MEDIUM = "5"
    LOW    = "7"


class DownloadStatus(Enum):
    QUEUED      = auto()
    EXTRACTING  = auto()
    DOWNLOADING = auto()
    PROCESSING  = auto()
    FINISHED    = auto()
    ERROR       = auto()
    CANCELLED   = auto()
    PAUSED      = auto()    # NEW – user paused this item


# ──────────────────────────────────────────────────────────────────────────────
# Data-classes
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class DownloadProgress:
    status:            DownloadStatus
    url:               str               = ""
    title:             str               = ""
    playlist_index:    Optional[int]     = None
    playlist_count:    Optional[int]     = None
    downloaded_bytes:  int               = 0
    total_bytes:       Optional[int]     = None
    speed_bps:         Optional[float]   = None
    eta_seconds:       Optional[float]   = None
    fraction:          float             = 0.0
    error_message:     str               = ""
    output_path:       str               = ""


@dataclass
class DownloadRequest:
    """One complete download job.  All new fields have safe defaults."""

    url:         str
    output_dir:  str
    media_type:  MediaType       = MediaType.AUDIO
    video_quality: VideoQuality  = VideoQuality.HIGH
    audio_quality: AudioQuality  = AudioQuality.BEST
    audio_format:  str           = "mp3"
    embed_thumbnail: bool        = True
    embed_metadata:  bool        = True
    write_subtitles: bool        = False
    playlist_start:  int         = 1
    playlist_end:    Optional[int] = None
    cookies_file:    Optional[str] = None
    cookies_browser: Optional[str] = None

    # Forced metadata
    forced_title:    Optional[str] = None
    forced_artist:   Optional[str] = None
    forced_index:    Optional[int] = None
    forced_duration: Optional[int] = None    # seconds, for duplicate check

    # Playlist sub-folder routing
    playlist_name:   Optional[str] = None

    # NEW v3 feature flags (all default to off for backward compat)
    sponsorblock:       bool = False   # cut non-music segments
    resumable:          bool = False   # pick up .part file if present
    embed_lyrics:       bool = False   # fetch + embed lyrics after download
    replay_gain:        bool = False   # ReplayGain analysis after download
    musicbrainz:        bool = False   # MusicBrainz tag enrichment after download
    square_thumbnails:  bool = False   # crop embedded art to 1:1 square

    # Per-request cancellation (parallel downloads)
    cancel_event: Optional[threading.Event] = field(default=None, repr=False)

    # Callbacks
    on_progress: Optional[Callable[[DownloadProgress], None]] = field(
        default=None, repr=False
    )
    on_finished: Optional[Callable[[DownloadProgress], None]] = field(
        default=None, repr=False
    )
    on_error:    Optional[Callable[[DownloadProgress], None]] = field(
        default=None, repr=False
    )


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


def _sanitize_folder_name(name: str) -> str:
    if not name:
        return "Playlist"
    path  = name.replace("\\", "/")
    parts = path.split("/")
    clean: list[str] = []
    for part in parts:
        p = re.sub(r'[\x00-\x1f]', "", part)
        p = re.sub(r'[:*?"<>|]', "_", p)
        p = p.replace("/", "_").replace("\\", "_").strip(". ")
        if p and p != "..":
            clean.append(p[:100])
    return "/".join(clean) if clean else "Playlist"


def _bytes_to_mb(b: Optional[int]) -> Optional[float]:
    if b is None:
        return None
    return round(b / (1024 * 1024), 2)


# ──────────────────────────────────────────────────────────────────────────────
# DownloadEngine
# ──────────────────────────────────────────────────────────────────────────────

class DownloadEngine:
    """
    Stateless download engine.  One instance per application lifetime.

    Create a DownloadRequest and call download() (blocking) or
    download_async() (background thread).
    """

    def __init__(self) -> None:
        self._cancel_event = threading.Event()
        self._lock = threading.Lock()

    def cancel_all(self) -> None:
        self._cancel_event.set()

    # ── Public API ─────────────────────────────────────────────────────────────

    def download(self, request: DownloadRequest) -> None:
        """Blocking download.  Safe to call from any background thread."""
        url = (request.url or "").strip()
        if not url:
            self._fire(request, DownloadProgress(
                status=DownloadStatus.ERROR,
                url=request.url,
                error_message="❌ Download URL is empty.",
            ), error=True)
            return

        if "spotify" in url.lower():
            self._fire(request, DownloadProgress(
                status=DownloadStatus.ERROR,
                url=request.url,
                error_message="❌ Spotify URLs are not directly downloadable.",
            ), error=True)
            return

        cancel_ev    = request.cancel_event or self._cancel_event
        global_cancel = self._cancel_event

        self._fire(request, DownloadProgress(
            status=DownloadStatus.EXTRACTING,
            url=url,
            title=request.forced_title or "",
        ))

        try:
            opts = self._build_ydl_opts(request)

            def _abort_hook(_info: dict) -> None:  # noqa: ANN001
                if cancel_ev.is_set() or global_cancel.is_set():
                    raise yt_dlp.utils.DownloadCancelled()

            opts["progress_hooks"].append(_abort_hook)

            if request.media_type == MediaType.AUDIO:
                opts.update(self._audio_opts(request))
            else:
                opts.update(self._video_opts(request))

            # SponsorBlock
            if request.sponsorblock:
                sb_cats = ["music_offtopic", "sponsor", "intro", "outro", "selfpromo"]
                opts.setdefault("postprocessors", [])
                opts["postprocessors"].insert(0, {"key": "SponsorBlock", "categories": sb_cats})
                opts["postprocessors"].insert(1, {
                    "key": "ModifyChapters",
                    "remove_sponsor_segments": sb_cats,
                })

            # Resume / continuedl
            if request.resumable:
                opts["continuedl"] = True

            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])

        except yt_dlp.utils.DownloadCancelled:
            self._fire(request, DownloadProgress(
                status=DownloadStatus.CANCELLED,
                url=url,
                title=request.forced_title or "",
            ))
        except yt_dlp.utils.DownloadError as exc:
            err_msg = str(exc)
            self._fire(request, DownloadProgress(
                status=DownloadStatus.ERROR,
                url=url,
                title=request.forced_title or "",
                error_message=err_msg,
            ), error=True)
        except Exception as exc:
            self._fire(request, DownloadProgress(
                status=DownloadStatus.ERROR,
                url=url,
                title=request.forced_title or "",
                error_message=f"Unexpected error: {exc}",
            ), error=True)

    def download_async(
        self,
        request: DownloadRequest,
        daemon:  bool = True,
    ) -> threading.Thread:
        t = threading.Thread(
            target=self.download,
            args=(request,),
            daemon=daemon,
            name=f"dl-{id(request)}",
        )
        t.start()
        return t

    def cancel(self) -> None:
        self._cancel_event.set()

    # ── yt-dlp options builder ─────────────────────────────────────────────────

    def _build_ydl_opts(self, req: DownloadRequest) -> dict[str, Any]:
        out_dir = Path(req.output_dir).expanduser().resolve()

        # Playlist subfolder
        if req.playlist_name:
            sub = _sanitize_folder_name(req.playlist_name)
            out_dir = out_dir / sub

        out_dir.mkdir(parents=True, exist_ok=True)

        # Output template
        if req.forced_title or req.forced_artist:
            artist     = _sanitize_filename(req.forced_artist or "Unknown Artist")
            title      = _sanitize_filename(req.forced_title  or "Unknown Title")
            idx_prefix = f"{req.forced_index:02d} " if req.forced_index is not None else ""
            outtmpl    = str(out_dir / f"{idx_prefix}{artist} - {title}.%(ext)s")
        else:
            outtmpl = str(out_dir / "%(playlist_index)s%(title)s.%(ext)s")

        opts: dict[str, Any] = _build_base_opts(
            cookies_file=req.cookies_file or None,
            cookies_browser=req.cookies_browser or None,
            quiet=True,
            retries=10,
        )

        opts["outtmpl"]           = outtmpl
        opts["restrictfilenames"] = True
        opts["windowsfilenames"]  = True
        opts["ignoreerrors"]      = False
        opts["playliststart"]     = req.playlist_start
        if req.playlist_end:
            opts["playlistend"]   = req.playlist_end

        opts["extractor_args"] = {"youtube": {"skip": ["webpage"]}}
        opts["progress_hooks"]      = [self._make_progress_hook(req)]
        opts["postprocessor_hooks"] = [self._make_pp_hook(req)]
        opts["no_warnings"]         = False

        return opts

    # ── Format-specific option builders ───────────────────────────────────────

    @staticmethod
    def _audio_opts(req: DownloadRequest) -> dict[str, Any]:
        postprocessors: list[dict] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec":   req.audio_format,
                "preferredquality": req.audio_quality.value,
            },
        ]
        if req.embed_metadata:
            postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})
        if req.embed_thumbnail:
            postprocessors.append({"key": "EmbedThumbnail"})

        opts: dict[str, Any] = {
            "format":         "bestaudio/best",
            "postprocessors": postprocessors,
            "writethumbnail": req.embed_thumbnail,
        }

        if req.forced_title or req.forced_artist:
            meta_args: list[str] = []
            if req.forced_title:
                meta_args.extend(["-metadata", f"title={req.forced_title}"])
            if req.forced_artist:
                meta_args.extend(["-metadata", f"artist={req.forced_artist}"])
            opts["postprocessor_args"] = {
                "FFmpegMetadata":      meta_args,
                "FFmpegExtractAudio":  meta_args,
            }

        return opts

    @staticmethod
    def _video_opts(req: DownloadRequest) -> dict[str, Any]:
        postprocessors: list[dict] = [
            {"key": "FFmpegVideoConvertor", "preferedformat": "mp4"},
        ]
        if req.embed_metadata:
            postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})
        if req.write_subtitles:
            postprocessors.append({
                "key": "FFmpegEmbedSubtitle",
                "already_have_subtitle": False,
            })

        opts: dict[str, Any] = {
            "format":              req.video_quality.value,
            "postprocessors":      postprocessors,
            "merge_output_format": "mp4",
        }
        if req.write_subtitles:
            opts["writesubtitles"]  = True
            opts["subtitleslangs"]  = ["en"]
            opts["subtitlesformat"] = "vtt"

        if req.forced_title or req.forced_artist:
            meta_args = []
            if req.forced_title:
                meta_args.extend(["-metadata", f"title={req.forced_title}"])
            if req.forced_artist:
                meta_args.extend(["-metadata", f"artist={req.forced_artist}"])
            opts["postprocessor_args"] = {
                "FFmpegMetadata":        meta_args,
                "FFmpegVideoConvertor":  meta_args,
            }

        return opts

    # ── Hook factories ─────────────────────────────────────────────────────────

    def _make_progress_hook(self, req: DownloadRequest) -> Callable[[dict], None]:
        def hook(d: dict) -> None:
            ydl_status = d.get("status", "")
            info       = d.get("info_dict", {})
            title      = info.get("title", d.get("filename", ""))
            pl_idx     = info.get("playlist_index")
            pl_count   = info.get("n_entries")
            dl_bytes   = d.get("downloaded_bytes", 0)
            total      = d.get("total_bytes") or d.get("total_bytes_estimate")
            speed      = d.get("speed")
            eta        = d.get("eta")

            fraction: float = 0.0
            if total and total > 0:
                fraction = min(dl_bytes / total, 1.0)

            if ydl_status == "downloading":
                self._fire(req, DownloadProgress(
                    status=DownloadStatus.DOWNLOADING,
                    url=req.url,
                    title=title,
                    playlist_index=pl_idx,
                    playlist_count=pl_count,
                    downloaded_bytes=dl_bytes,
                    total_bytes=total,
                    speed_bps=speed,
                    eta_seconds=eta,
                    fraction=fraction,
                ))

            elif ydl_status == "finished":
                self._fire(req, DownloadProgress(
                    status=DownloadStatus.PROCESSING,
                    url=req.url,
                    title=title,
                    fraction=0.95,
                ))

            elif ydl_status == "error":
                self._fire(req, DownloadProgress(
                    status=DownloadStatus.ERROR,
                    url=req.url,
                    title=title,
                    error_message=d.get("error", "Unknown yt-dlp error"),
                ), error=True)

        return hook

    def _make_pp_hook(self, req: DownloadRequest) -> Callable[[dict], None]:
        """Post-processor hook fires after every FFmpeg stage."""

        def hook(d: dict) -> None:
            if d.get("status") != "finished":
                return

            output_path: str = d.get("info_dict", {}).get("filepath", "") or ""

            # ── Post-processing pipeline ──────────────────────────────────────
            if output_path:
                self._run_post_pipeline(req, output_path)

            # Emit FINISHED
            self._fire(req, DownloadProgress(
                status=DownloadStatus.FINISHED,
                url=req.url,
                title=req.forced_title or d.get("info_dict", {}).get("title", ""),
                fraction=1.0,
                output_path=output_path,
            ))

        return hook

    def _run_post_pipeline(self, req: DownloadRequest, output_path: str) -> None:
        """
        Run optional post-processing steps on the finished file.

        Each step is individually guarded and logs its own errors so one
        failing step never prevents the others from running.
        """
        title  = req.forced_title  or ""
        artist = req.forced_artist or ""

        # 1. Square thumbnail crop (before MusicBrainz, which might re-embed art)
        if req.square_thumbnails:
            try:
                from core.thumbnail_cropper import crop_embedded_thumbnail
                crop_embedded_thumbnail(output_path)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).error(
                    "[Downloader] ThumbnailCropper error: %s", exc
                )

        # 2. MusicBrainz enrichment
        if req.musicbrainz and title:
            try:
                from core.musicbrainz_enricher import enrich_file
                enrich_file(
                    output_path,
                    title=title,
                    artist=artist,
                    duration_s=req.forced_duration,
                )
            except Exception as exc:
                import logging
                logging.getLogger(__name__).error(
                    "[Downloader] MusicBrainz error: %s", exc
                )

        # 3. Lyrics embedding
        if req.embed_lyrics and title:
            try:
                from core.lyrics_embedder import embed_lyrics
                embed_lyrics(output_path, title=title, artist=artist)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).error(
                    "[Downloader] LyricsEmbedder error: %s", exc
                )

        # 4. ReplayGain analysis (last – reads final audio content)
        if req.replay_gain:
            try:
                from core.replay_gain import analyse_and_embed
                analyse_and_embed(output_path)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).error(
                    "[Downloader] ReplayGain error: %s", exc
                )

    # ── Signal dispatcher ──────────────────────────────────────────────────────

    @staticmethod
    def _fire(
        req:      DownloadRequest,
        progress: DownloadProgress,
        error:    bool = False,
    ) -> None:
        if error and req.on_error:
            try:
                req.on_error(progress)
            except Exception:
                pass
        elif progress.status == DownloadStatus.FINISHED and req.on_finished:
            try:
                req.on_finished(progress)
            except Exception:
                pass
        elif req.on_progress:
            try:
                req.on_progress(progress)
            except Exception:
                pass
