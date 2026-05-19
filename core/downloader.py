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

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Optional

import yt_dlp
try:
    import yt_dlp_ejs  # noqa: F401
except ImportError:
    pass

from utils.cookie_validator import check_cookies_valid
from utils.paths import get_app_cookies_path
from utils.yt_dlp_opts import build_base_ydl_opts as _build_base_opts
from core.playlist_parser import SourcePlatform


logger = logging.getLogger(__name__)


class SilentLogger:
    """Captures yt-dlp output and avoids polluting the console."""
    def debug(self, msg: str) -> None:
        if msg.startswith("[debug] "):
            return
        logger.debug(f"[yt-dlp] {msg}")

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        # Filter technical noise that clutters the console
        if any(x in msg for x in [
            "No supported JavaScript runtime",
            "Signature solving failed",
            "n challenge solving failed",
            "Incomplete data received",
            "re-fetching using API",
            "Some formats may be missing"
        ]):
            return
        logger.warning(f"[yt-dlp] {msg}")

    def error(self, msg: str) -> None:
        # Filter some redundancy in error messages
        if "Signature solving failed" in msg and "EJS" in msg:
            return
        logger.error(f"[yt-dlp] {msg}")

# ──────────────────────────────────────────────────────────────────────────────
# Enumerations
# ──────────────────────────────────────────────────────────────────────────────

class MediaType(Enum):
    AUDIO = auto()
    VIDEO = auto()


class VideoQuality(Enum):
    BEST   = "bestvideo+bestaudio/best"
    UHD_4K = "bestvideo[height<=2160]+bestaudio/best[height<=2160]"
    QHD_2K = "bestvideo[height<=1440]+bestaudio/best[height<=1440]"
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
    warning_message:   str               = ""   # non-fatal post-processing failures
    output_path:       str               = ""
    thumbnail_url:     Optional[str]     = None


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
    forced_album:    Optional[str] = None
    forced_index:    Optional[int] = None
    forced_duration: Optional[int] = None    # seconds, for duplicate check

    # Playlist sub-folder routing
    playlist_name:   Optional[str] = None

    # Custom Thumbnail Overrides
    thumbnail_url:   Optional[str] = None

    # Proxy (passed to yt-dlp; empty/None = direct connection)
    proxy_url: Optional[str] = None

    # NEW v3 feature flags (all default to off for backward compat)
    sponsorblock:               bool              = False   # cut non-music segments
    sponsorblock_categories:    Optional[list[str]] = None  # None = use default set
    resumable:                  bool              = False   # pick up .part file if present
    embed_lyrics:           bool = False   # fetch + embed lyrics after download
    replay_gain:            bool = False   # ReplayGain analysis after download
    musicbrainz:            bool = False   # MusicBrainz tag enrichment after download
    square_thumbnails:      bool = False   # crop embedded art to 1:1 square
    expand_thumbnails:      bool = False   # pad 1:1 art to 16:9 for video
    clean_filename:         bool = False   # use minimal filename (Title only)
    randomize_user_agent:   bool = False   # rotate UA string per download (anti-ban) (kept for signature but unused)
    is_solo:                bool = False   # single track download flag (no folder, no index, no artist name)

    # Universal / HLS / DASH stream (set when URL came from universal_extractor)
    # Values: "hls" | "dash" | "mp4" | "webm" | "ts" | None (= use yt-dlp)
    stream_type: Optional[str] = None
    platform: Optional[SourcePlatform] = None

    # Category tag forwarded from TrackMeta (e.g. "stream_intercept", "stream:hls")
    category: Optional[str] = None

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

    # Internal: set by yt-dlp post-processor hook to record the final output path.
    # Declared here (not set dynamically) so type-checkers and frozen-dataclass
    # tools can see it.
    _final_output_path: str = field(default="", init=False, repr=False)
    _thumb_sent: bool = field(default=False, init=False, repr=False)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _strip_ansi_codes(text: str) -> str:
    """Remove [0;31m style escape codes from strings."""
    if not text: return ""
    import re as _re
    return _re.sub(r'\x1b\[[0-9;]*[mK]', '', text)


def _get_friendly_error(raw_err: str) -> str:
    """Analyze technical yt-dlp error and add Hebrew tips."""
    clean = _strip_ansi_codes(raw_err)

    if "Sign in to confirm you’re not a bot" in clean or "Sign in to confirm your age" in clean or "Confirm you're not a bot" in clean:
        return (
            f"{clean}\n\n"
            "💡 יוטיוב דורש אימות (חשבון גוגל) כדי להמשיך בהורדה.\n\n"
            "יש לך שתי אפשרויות:\n"
            "1. התחברות מהירה: לחץ על 'תיקון התחברות' כדי להתחבר לחשבון גוגל ישירות מהתוכנה (הכי פשוט).\n"
            "2. ייצוא קוקיז: השתמש בתוסף 'Get cookies.txt LOCALLY' לדפדפן כדי לייצא קובץ טקסט ולהגדיר אותו בהגדרות.\n"
            "קישור לתוסף: https://chromewebstore.google.com/detail/get-cookiestxt-locally/ccmgnabidkenghhcidlkgeimdbgefecl\n"
        )

    if "Could not copy Chrome cookie database" in clean or "Failed to decrypt with DPAPI" in clean:
        return (
            f"{clean}\n\n"
            "💡 טיפ: דפדפן Chrome נעול או מוצפן. סגור את הדפדפן לגמרי ונסה שוב.\n"
            "אם זה לא עוזר, השתמש בלחצן 'תיקון התחברות (פשוט)' כדי לעקוף את ההצפנה של כרום."
        )

    if "Signature solving failed" in clean or "n challenge solving failed" in clean:
        return (
            f"{clean}\n\n"
            "💡 טיפ: חסר רכיב להרצת JavaScript (נחוץ לפתרון ה'חידות' של יוטיוב).\n"
            "יש להריץ בטרמינל את הפקודות הבאות:\n"
            "1. pip install quickjs\n"
            "2. pip install -U yt-dlp"
        )

    if "Requested format is not available" in clean or "Please sign in" in clean:
        return (
            f"{clean}\n\n"
            "💡 טיפ: יוטיוב דורש רכיב אימות נוסף (PO Token) או התחברות לחשבון.\n"
            "ייתכן שתצטרך לעדכן את קובץ ה-Cookies שלך דרך 'אשף ההתחברות' או להשתמש בלחצן 'תיקון ידני בדפדפן' כדי לחמם את ה-Token."
        )

    if "HTTP Error 403" in clean or "Forbidden" in clean:
        return f"{clean}\n\n💡 טיפ: שגיאת גישה (403). ייתכן שצריך לעדכן את קובץ ה-Cookies או להחליף כתובת IP."

    return clean


def _sanitize_filename(name: str) -> str:
    """Sanitise a string for use as a filename stem on Windows + POSIX.

    Single source of truth: imported by ``core.duplicate_checker`` so the
    pre-download duplicate check builds the exact same stem the downloader
    writes to disk. Any change here must preserve byte equality with the
    on-disk filename.

    Truncates to 200 chars to stay under the Windows MAX_PATH=260 limit
    once a typical playlist subfolder and extension are added.
    """
    if not name:
        return "Unknown"
    # Replace restricted Windows characters with safer alternatives
    # Use two single quotes for double quotes (common practice for "שיר לממ''ד")
    # Replace colon with hyphen space for better flow
    name = name.replace('"', "''").replace(":", " - ").replace("/", "-").replace("\\", "-").replace("|", "-")
    # Remove remaining truly forbidden characters
    name = re.sub(r'[*?<>:]', " ", name)
    name = re.sub(r'\s+', " ", name)  # Collapse multiple spaces
    name = re.sub(r'[\x00-\x1f]', "", name)
    return name.strip(". ")[:200]


def _sanitize_folder_name(name: str) -> str:
    if not name:
        return "Playlist"
    # Replace colon with hyphen for safe path
    # Split by forward slash to handle hierarchical subfolders (e.g. Artist/Album)
    path_parts = name.replace("\\", "/").split("/")
    clean: list[str] = []
    for part in path_parts:
        if not part: continue
        # Sanitize individual segment
        p = part.replace('"', "''").replace(":", " - ").replace("|", "-")
        # Remove truly forbidden chars and control chars
        p = re.sub(r'[*?<> ]', " ", p)
        p = re.sub(r'\s+', " ", p)
        p = re.sub(r'[\x00-\x1f]', "", p)
        p = p.strip(". ")
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

        # HLS / DASH / direct stream: bypass yt-dlp and use ffmpeg directly
        if request.stream_type in ("hls", "dash", "mp4", "webm", "ts"):
            self._download_hls_stream(request)
            return

        # Generic video page (any site): intercept HLS/DASH stream, then download via ffmpeg
        if request.category == "stream_intercept":
            self._download_with_stream_intercept(request)
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

            opts.setdefault("progress_hooks", []).append(_abort_hook)

            if request.media_type == MediaType.AUDIO:
                opts.update(self._audio_opts(request))
            else:
                opts.update(self._video_opts(request))

            # SponsorBlock (categories configurable per-request)
            if request.sponsorblock:
                sb_cats = request.sponsorblock_categories or [
                    "music_offtopic", "sponsor", "intro", "outro", "selfpromo"
                ]
                opts.setdefault("postprocessors", [])
                opts["postprocessors"].insert(0, {"key": "SponsorBlock", "categories": sb_cats})
                opts["postprocessors"].insert(1, {
                    "key": "ModifyChapters",
                    "remove_sponsor_segments": sb_cats,
                })

            # Resume / continuedl
            if request.resumable:
                opts["continuedl"] = True

            max_retries = 3
            with yt_dlp.YoutubeDL(opts) as ydl:
                for attempt in range(max_retries):
                    try:
                        ydl.download([url])
                        break
                    except Exception as exc:
                        # Check for Windows file-lock errors by winerror code (locale-safe)
                        # winerror 5 = ACCESS_DENIED, winerror 32 = SHARING_VIOLATION
                        winerror = getattr(exc, "winerror", None)
                        is_locked = winerror in (5, 32)
                        if is_locked and attempt < max_retries - 1:
                            logger.warning("[Downloader] File locked, retrying in 2s... (Attempt %d/%d)", attempt + 1, max_retries)
                            time.sleep(2)
                            continue
                        raise

            # ── Finalized: Run custom pipeline before emitting FINISHED ──────────────
            final_path = request._final_output_path  # noqa: SLF001
            if final_path and os.path.exists(final_path):
                # Notify UI we are processing
                self._fire(request, DownloadProgress(
                    status=DownloadStatus.PROCESSING,
                    url=url,
                    title=request.forced_title or "",
                    output_path=final_path,
                ))
                
                # Execute steps; collect non-fatal failures for the UI
                pp_failures = self._run_final_pipeline(request, final_path)
            else:
                pp_failures = []

            warning_msg = ""
            if pp_failures:
                warning_msg = "Post-processing partial failure: " + "; ".join(pp_failures)
                logger.warning(f"[Downloader] {warning_msg}")

            self._fire(request, DownloadProgress(
                status=DownloadStatus.FINISHED,
                url=url,
                title=request.forced_title or "",
                fraction=1.0,
                warning_message=warning_msg,
                output_path=final_path,
            ))

        except yt_dlp.utils.DownloadCancelled:
            self._fire(request, DownloadProgress(
                status=DownloadStatus.CANCELLED,
                url=url,
                title=request.forced_title or "",
            ))
        except yt_dlp.utils.DownloadError as exc:
            err_msg = _get_friendly_error(str(exc))
            self._fire(request, DownloadProgress(
                status=DownloadStatus.ERROR,
                url=url,
                title=request.forced_title or "",
                error_message=err_msg,
            ), error=True)
        except Exception as exc:
            err_msg = _get_friendly_error(f"Unexpected error: {exc}")
            self._fire(request, DownloadProgress(
                status=DownloadStatus.ERROR,
                url=url,
                title=request.forced_title or "",
                error_message=err_msg,
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

    # ── HLS / DASH stream download via ffmpeg ─────────────────────────────────

    def _download_hls_stream(self, request: DownloadRequest) -> None:
        """Download a raw HLS/DASH/direct stream URL using ffmpeg (not yt-dlp)."""
        from core.hls_downloader import download_hls

        url       = request.url
        ext       = "mp3" if request.media_type == MediaType.AUDIO else "mp4"
        if request.media_type == MediaType.AUDIO and request.audio_format:
            ext = request.audio_format

        out_dir   = Path(request.output_dir).expanduser().resolve()
        if request.playlist_name:
            out_dir = out_dir / request.playlist_name
        out_dir.mkdir(parents=True, exist_ok=True)

        # Build filename
        title  = request.forced_title or "stream"
        stem   = title
        # Sanitize
        stem = re.sub(r'[\\/*?:"<>|]', "_", stem)
        if request.forced_index:
            stem = f"{request.forced_index:02d} {stem}"

        output_path = str(out_dir / f"{stem}.{ext}")

        self._fire(request, DownloadProgress(
            status=DownloadStatus.DOWNLOADING,
            url=url,
            title=title,
        ))

        try:
            download_hls(
                url=url,
                output_path=output_path,
                cookies_file=request.cookies_file,
            )
        except Exception as exc:
            self._fire(request, DownloadProgress(
                status=DownloadStatus.ERROR,
                url=url,
                title=title,
                error_message=str(exc),
            ), error=True)
            return

        self._fire(request, DownloadProgress(
            status=DownloadStatus.FINISHED,
            url=url,
            title=title,
            fraction=1.0,
            output_path=output_path,
        ))

    # ── Generic stream-intercept download (any video page) ───────────────────

    def _download_with_stream_intercept(self, request: DownloadRequest) -> None:
        """
        Universal video page downloader — works for any site whose video pages
        set category='stream_intercept'.

        Steps:
          1. Open the video page with Playwright (headless)
          2. Intercept the best HLS/DASH stream URL
          3. Download via ffmpeg (same mechanism as mpmux.com staticdownloader)

        Falls back to yt-dlp if stream interception fails.
        """
        page_url = request.url

        self._fire(request, DownloadProgress(
            status=DownloadStatus.EXTRACTING,
            url=page_url,
            title=request.forced_title or "",
        ))

        logger.debug("[Downloader] Intercepting stream from %s", page_url)

        try:
            from core.universal_extractor import find_best_stream_with_title
            stream_url, stream_type, page_title = find_best_stream_with_title(
                page_url, timeout_ms=35_000
            )
        except Exception as exc:
            logger.warning("[Downloader] Stream interception failed: %s — falling back to yt-dlp", exc)
            stream_url = ""
            stream_type = "unknown"
            page_title = ""

        if not stream_url or stream_type == "unknown":
            logger.info("[Downloader] No stream intercepted — trying yt-dlp for %s", page_url)
            # We do NOT return early here; we call the yt-dlp path below
            try:
                opts = self._build_ydl_opts(request)
                cancel_ev = request.cancel_event or self._cancel_event
                if request.media_type == MediaType.AUDIO:
                    opts.update(self._audio_opts(request))
                else:
                    opts.update(self._video_opts(request))

                def _abort_hook(_info: dict) -> None:
                    if cancel_ev.is_set() or self._cancel_event.is_set():
                        raise yt_dlp.utils.DownloadCancelled()

                opts.setdefault("progress_hooks", []).append(_abort_hook)

                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([page_url])

                final_path = request._final_output_path  # noqa: SLF001
                self._fire(request, DownloadProgress(
                    status=DownloadStatus.FINISHED,
                    url=page_url,
                    title=request.forced_title or "",
                    fraction=1.0,
                    output_path=final_path,
                ))
            except Exception as exc:
                err_msg = _get_friendly_error(str(exc))
                self._fire(request, DownloadProgress(
                    status=DownloadStatus.ERROR,
                    url=page_url,
                    title=request.forced_title or "",
                    error_message=err_msg,
                ), error=True)
            return

        # Use page_title if our forced_title is a generic placeholder
        title = request.forced_title
        if (not title or title in ("Unknown Title", "stream")) and page_title:
            title = page_title
        if not title:
            title = page_url.rstrip("/").split("/")[-1].replace("-", " ") or "stream"

        # Update the request so the filename builder uses the real title
        request.forced_title = title

        logger.info(
            "[Downloader] Intercepted %s stream for '%s'",
            stream_type.upper(), title,
        )

        # Build output path
        ext = "mp3" if request.media_type == MediaType.AUDIO else "mp4"
        if request.media_type == MediaType.AUDIO and request.audio_format:
            ext = request.audio_format

        out_dir = Path(request.output_dir).expanduser().resolve()
        if request.playlist_name:
            out_dir = out_dir / _sanitize_folder_name(request.playlist_name)
        out_dir.mkdir(parents=True, exist_ok=True)

        stem = _sanitize_filename(title)
        if request.forced_index:
            stem = f"{request.forced_index:02d} - {stem}"

        output_path = str(out_dir / f"{stem}.{ext}")

        self._fire(request, DownloadProgress(
            status=DownloadStatus.DOWNLOADING,
            url=page_url,
            title=title,
        ))

        try:
            from core.hls_downloader import download_hls
            download_hls(
                url=stream_url,
                output_path=output_path,
                cookies_file=request.cookies_file,
            )
        except Exception as exc:
            self._fire(request, DownloadProgress(
                status=DownloadStatus.ERROR,
                url=page_url,
                title=title,
                error_message=str(exc),
            ), error=True)
            return

        self._fire(request, DownloadProgress(
            status=DownloadStatus.FINISHED,
            url=page_url,
            title=title,
            fraction=1.0,
            output_path=output_path,
        ))

    # ── yt-dlp options builder ─────────────────────────────────────────────────

    def _build_ydl_opts(self, req: DownloadRequest) -> dict[str, Any]:
        out_dir = Path(req.output_dir).expanduser().resolve()

        # Playlist subfolder
        if req.playlist_name:
            sub = _sanitize_folder_name(req.playlist_name)
            out_dir = out_dir / sub

        out_dir.mkdir(parents=True, exist_ok=True)

        # Output template
        raw_title = req.forced_title if (req.forced_title and req.forced_title != "Unknown Title") else None
        use_ydlp_title = raw_title is None

        if use_ydlp_title:
            raw_title = "%(title)s"

        # Comprehensive clean: strip common parenthetical labels and promotional suffixes
        # WE EXCLUDE 'Remix', 'Edit', 'Acoustic', 'Live' to prevent collisions in EPs
        clean_title = re.sub(r'\s*[([].*?(Official|Video|Clip|Audio|Prod|By|Remaster|Lyrics|HD|4K|Direct|Studio).*?[)\]]', '', raw_title, flags=re.IGNORECASE)
        # Strip anything in parens at the end
        clean_title = re.sub(r'\s*\([^)]*\)\s*$', '', clean_title).strip()
        # Strip trailing hyphens or dashes followed by common tags
        clean_title = re.sub(r'\s*-\s*(Club Edit|Official|Prod|Original).*$', '', clean_title, flags=re.IGNORECASE).strip()
        
        if not clean_title:
            clean_title = raw_title

        title = _sanitize_filename(clean_title)

        if use_ydlp_title:
            # No forced title — let yt-dlp determine the title
            if req.is_solo:
                outtmpl = str(out_dir / "%(title)s.%(ext)s")
            elif req.clean_filename:
                idx_prefix = f"{req.forced_index:02d} - " if (req.forced_index is not None and req.forced_index > 0) else ""
                outtmpl = str(out_dir / f"{idx_prefix}%(title)s.%(ext)s")
            else:
                outtmpl = str(out_dir / "%(playlist_index)s%(title)s.%(ext)s")
        elif req.is_solo:
            # Solo download: No artist, no index, just the clean title.
            outtmpl = str(out_dir / f"{title}.%(ext)s")
        elif req.clean_filename:
            # IMPORTANT: For clean_filename, we ONLY use the title, NO artist.
            idx_prefix = f"{req.forced_index:02d} - " if (req.forced_index is not None and req.forced_index > 0) else ""
            outtmpl = str(out_dir / f"{idx_prefix}{title}.%(ext)s")
        elif req.forced_title or req.forced_artist:
            idx_prefix = f"{req.forced_index:02d} - " if (req.forced_index is not None and req.forced_index > 0) else ""
            artist     = _sanitize_filename(req.forced_artist or "Unknown Artist")
            # In the 'Artist - Title' format, we still use the cleaned title
            outtmpl    = str(out_dir / f"{idx_prefix}{artist} - {title}.%(ext)s")
        else:
            outtmpl = str(out_dir / "%(playlist_index)s%(title)s.%(ext)s")

        # Automatic pickup of wizard cookies
        cookies_file = req.cookies_file
        if not cookies_file and not req.cookies_browser:
            wizard_cookies = get_app_cookies_path()
            if wizard_cookies.exists():
                cookies_file = str(wizard_cookies)

        # Warn if cookies are expired (non-blocking)
        if cookies_file:
            valid, warn_msg = check_cookies_valid(cookies_file)
            if not valid:
                logger.warning("[Downloader] %s", warn_msg)

        opts: dict[str, Any] = _build_base_opts(
            cookies_file=cookies_file or None,
            cookies_browser=req.cookies_browser or None,
            logger=SilentLogger(),
            quiet=True,
            retries=10,
            randomize_user_agent=req.randomize_user_agent,
            proxy=req.proxy_url or None,
        )

        opts["outtmpl"]           = outtmpl
        opts["restrictfilenames"] = False
        opts["windowsfilenames"]  = True
        opts["ignoreerrors"]      = False
        opts["playliststart"]     = req.playlist_start
        if req.playlist_end:
            opts["playlistend"]   = req.playlist_end

        opts["progress_hooks"]      = [self._make_progress_hook(req)]
        opts["postprocessor_hooks"] = [self._make_pp_hook(req)]
        opts["no_warnings"]         = True

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
        use_ytdlp_thumb = req.embed_thumbnail and not req.thumbnail_url
        if use_ytdlp_thumb:
            postprocessors.append({"key": "EmbedThumbnail"})

        opts: dict[str, Any] = {
            "format":         "bestaudio/best",
            "postprocessors": postprocessors,
            "writethumbnail": use_ytdlp_thumb,
        }

        if req.forced_title or req.forced_artist or req.forced_album:
            meta_args: list[str] = []
            if req.forced_title:
                meta_args.extend(["-metadata", f"title={req.forced_title}"])
            if req.forced_artist:
                meta_args.extend(["-metadata", f"artist={req.forced_artist}"])
            if req.forced_album:
                meta_args.extend(["-metadata", f"album={req.forced_album}"])
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
        use_ytdlp_thumb = req.embed_thumbnail and not req.thumbnail_url
        if use_ytdlp_thumb:
            postprocessors.append({"key": "EmbedThumbnail"})
        if req.write_subtitles:
            postprocessors.append({
                "key": "FFmpegEmbedSubtitle",
                "already_have_subtitle": False,
            })

        opts: dict[str, Any] = {
            "format":              req.video_quality.value,
            "postprocessors":      postprocessors,
            "merge_output_format": "mp4",
            "writethumbnail":      use_ytdlp_thumb,
        }
        if req.write_subtitles:
            opts["writesubtitles"]  = True
            opts["subtitleslangs"]  = ["en"]
            opts["subtitlesformat"] = "vtt"

        if req.forced_title or req.forced_artist or req.forced_album:
            meta_args = []
            if req.forced_title:
                meta_args.extend(["-metadata", f"title={req.forced_title}"])
            if req.forced_artist:
                meta_args.extend(["-metadata", f"artist={req.forced_artist}"])
            if req.forced_album:
                meta_args.extend(["-metadata", f"album={req.forced_album}"])
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
            thumb      = info.get("thumbnail")

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
                    thumbnail_url=thumb,
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

            pp_key = (d.get("postprocessor", "") or "").lower()
            output_path: str = d.get("info_dict", {}).get("filepath", "") or ""

            logger.debug("[Downloader] PP Hook: status=finished, pp=%s, path=%s", pp_key, output_path)

            if output_path:
                output_path = os.path.abspath(output_path)
                # Capture the most recent valid file path
                if not req._final_output_path or os.path.exists(output_path):  # noqa: SLF001
                    req._final_output_path = output_path  # noqa: SLF001

        return hook

    def _run_final_pipeline(self, req: DownloadRequest, final_path: str) -> list[str]:
        """
        Execute all custom post-processing steps sequentially.
        Called after yt-dlp has completely finished.
        Returns a list of non-fatal error messages.
        """
        # 0. Stability delay to ensure file system is ready (mitigates ffprobe locking)
        time.sleep(1.5)

        if not os.path.exists(final_path):
            logger.warning(f"[Downloader] Final path does not exist, skipping pipeline: {final_path}")
            return [f"Output file missing: {Path(final_path).name}"]

        logger.info(f"[Downloader] Starting final post-processing for: {Path(final_path).name}")
        failures: list[str] = []

        # 1. Custom Thumbnail Embedding & Cropping
        if req.thumbnail_url:
            should_crop = False
            should_pad = False
            is_audio = req.media_type == MediaType.AUDIO
            is_video = req.media_type == MediaType.VIDEO

            if req.square_thumbnails and is_audio:
                platform_needs_crop = req.platform in (SourcePlatform.YOUTUBE, SourcePlatform.GENERIC)
                if platform_needs_crop:
                    should_crop = True
                    
            if req.expand_thumbnails and is_video:
                should_pad = True

            logger.debug(f"[Downloader] Embedding custom thumbnail (crop={should_crop}, pad={should_pad})...")
            try:
                from core.thumbnail_cropper import embed_custom_thumbnail
                ok = embed_custom_thumbnail(final_path, req.thumbnail_url, crop=should_crop, pad=should_pad)
                if ok:
                    logger.debug(f"[Downloader] Custom thumbnail embedded successfully.")
                else:
                    logger.warning(f"[Downloader] Failed to embed custom thumbnail.")
                    failures.append("thumbnail embed")
            except Exception as exc:
                logger.error(f"[Downloader] Thumbnail error: {exc}", exc_info=True)
                failures.append(f"thumbnail: {exc}")
        elif (req.square_thumbnails and req.media_type == MediaType.AUDIO) or (req.expand_thumbnails and req.media_type == MediaType.VIDEO):
            should_pad = req.expand_thumbnails and req.media_type == MediaType.VIDEO
            try:
                from core.thumbnail_cropper import crop_embedded_thumbnail
                action = "Padding" if should_pad else "Cropping"
                logger.debug(f"[Downloader] {action} embedded yt-dlp thumbnail...")
                ok = crop_embedded_thumbnail(final_path, pad=should_pad)
                if ok:
                    logger.debug(f"[Downloader] Embedded thumbnail {action.lower()} successfully.")
                else:
                    logger.warning(f"[Downloader] Failed to process embedded thumbnail.")
                    failures.append("thumbnail process")
            except Exception as exc:
                logger.error(f"[Downloader] Thumbnail process error: {exc}", exc_info=True)
                failures.append(f"thumbnail process: {exc}")

        # 2. MusicBrainz enrichment
        if req.musicbrainz:
            try:
                logger.debug(f"[Downloader] Fetching MusicBrainz metadata...")
                from core.musicbrainz_enricher import enrich_file
                enrich_file(final_path, title=req.forced_title, artist=req.forced_artist)
                logger.debug("[Downloader] MusicBrainz metadata enriched.")
            except Exception as exc:
                logger.error(f"[Downloader] MusicBrainz error: {exc}")
                failures.append(f"MusicBrainz: {exc}")

        # 3. Lyrics embedding
        if req.embed_lyrics:
            try:
                logger.debug(f"[Downloader] Fetching lyrics...")
                from core.lyrics_embedder import embed_lyrics
                embed_lyrics(final_path, title=req.forced_title, artist=req.forced_artist)
                logger.debug("[Downloader] Lyrics embedded.")
            except Exception as exc:
                logger.error(f"[Downloader] Lyrics error: {exc}")
                failures.append(f"lyrics: {exc}")

        # 4. ReplayGain analysis
        if req.replay_gain:
            try:
                logger.debug(f"[Downloader] Analyzing ReplayGain...")
                from core.replay_gain import analyse_and_embed
                analyse_and_embed(final_path)
                logger.debug("[Downloader] ReplayGain added.")
            except Exception as exc:
                logger.error(f"[Downloader] ReplayGain error: {exc}")
                failures.append(f"ReplayGain: {exc}")

        logger.info(f"[Downloader] Post-processing finished for: {Path(final_path).name}")
        return failures


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
            except Exception as exc:
                logger.warning("[Downloader] on_error callback raised: %s", exc, exc_info=True)
        elif progress.status == DownloadStatus.FINISHED and req.on_finished:
            try:
                req.on_finished(progress)
            except Exception as exc:
                logger.warning("[Downloader] on_finished callback raised: %s", exc, exc_info=True)
        elif req.on_progress:
            try:
                req.on_progress(progress)
            except Exception as exc:
                logger.warning("[Downloader] on_progress callback raised: %s", exc, exc_info=True)
