"""
downloader.py  –  Core download engine for YTSpot Downloader
=============================================================
Responsibilities
----------------
* Accept a URL (single video / track OR playlist).
* Resolve the URL type and extract metadata via yt-dlp.
* Download audio (MP3/M4A) or video (MP4/MKV) at a caller-specified quality.
* Fire granular callbacks so any future UI layer can display live progress
  without importing anything GUI-related here.
* Write ID3/MP4 tags (title, artist, album-art thumbnail) via mutagen.

Design decisions
----------------
* Pure Python, zero GUI imports – this module is UI-agnostic.
* All public API uses plain Python types (str, dict, Callable, Enum).
* yt-dlp is configured with a *post-processor chain* so FFmpeg merging and
  tag-writing happen automatically after the download.
* Thread-safety: every callback is dispatched on the calling thread.
  The GUI layer is responsible for marshalling to the main/UI thread
  (e.g., root.after() for Tk, QMetaObject.invokeMethod for Qt).
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
    import yt_dlp_ejs  # noqa: F401  – loads QuickJS runtime for YouTube PO-token
except ImportError:
    pass

try:
    from yt_dlp.networking.impersonate import ImpersonateTarget as _ImpersonateTarget
    _CURL_CFFI_AVAILABLE = True
except ImportError:
    _ImpersonateTarget = None  # type: ignore[assignment,misc]
    _CURL_CFFI_AVAILABLE = False


# ──────────────────────────────────────────────────────────────────────────────
# Public enumerations & data-classes
# ──────────────────────────────────────────────────────────────────────────────

class MediaType(Enum):
    AUDIO = auto()   # Extract audio → MP3 (or M4A for YouTube Music / Spotify)
    VIDEO = auto()   # Download muxed video+audio → MP4


class VideoQuality(Enum):
    """
    Maps human-readable labels to yt-dlp format-selection strings.
    Only used when MediaType == VIDEO.
    """
    BEST     = "bestvideo+bestaudio/best"
    HIGH     = "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
    MEDIUM   = "bestvideo[height<=720]+bestaudio/best[height<=720]"
    LOW      = "bestvideo[height<=480]+bestaudio/best[height<=480]"
    WORST    = "worstvideo+worstaudio/worst"


class AudioQuality(Enum):
    """
    Maps human-readable labels to the yt-dlp audio-bitrate preference.
    Only used when MediaType == AUDIO.
    """
    BEST   = "0"   # VBR best / 320 kbps
    HIGH   = "2"   # ~256 kbps
    MEDIUM = "5"   # ~192 kbps
    LOW    = "7"   # ~128 kbps


class DownloadStatus(Enum):
    QUEUED      = auto()
    EXTRACTING  = auto()   # Fetching metadata
    DOWNLOADING = auto()
    PROCESSING  = auto()   # FFmpeg mux / tag writing
    FINISHED    = auto()
    ERROR       = auto()
    CANCELLED   = auto()


@dataclass
class DownloadProgress:
    """
    Passed to every progress-callback invocation.
    All fields are optional – only the ones relevant to the current phase are
    populated.  The UI should check `status` first.
    """
    status: DownloadStatus

    # ── Track identity ────────────────────────────────────────────────────────
    url: str = ""
    title: str = ""
    playlist_index: Optional[int] = None    # 1-based index inside a playlist
    playlist_count: Optional[int] = None    # total items in playlist

    # ── Download metrics ──────────────────────────────────────────────────────
    downloaded_bytes: int = 0
    total_bytes: Optional[int] = None       # None when unknown
    speed_bps: Optional[float] = None       # bytes / second
    eta_seconds: Optional[float] = None

    # ── Human-readable shorthand (0.0 – 1.0) ─────────────────────────────────
    fraction: float = 0.0                   # overall progress 0→1

    # ── Error payload ─────────────────────────────────────────────────────────
    error_message: str = ""

    # ── Output ────────────────────────────────────────────────────────────────
    output_path: str = ""                   # filled on FINISHED


@dataclass
class DownloadRequest:
    """
    Fully describes a single download job submitted to the engine.
    """
    url: str
    output_dir: str
    media_type: MediaType       = MediaType.AUDIO
    video_quality: VideoQuality = VideoQuality.HIGH
    audio_quality: AudioQuality = AudioQuality.BEST
    audio_format: str           = "mp3"     # "mp3" | "m4a" | "flac" | "opus"
    embed_thumbnail: bool       = True
    embed_metadata: bool        = True
    write_subtitles: bool       = False
    playlist_start: int         = 1         # 1-based; 1 = from beginning
    playlist_end: Optional[int] = None      # None = until last item
    cookies_file:    Optional[str] = None    # path to cookies.txt (Spotify auth)
    cookies_browser: Optional[str] = None   # "chrome"|"firefox"|"edge"|"brave"|"safari"

    # ── Forced metadata (for Spotify / Search fallback) ───────────────────────
    # If set, these override whatever yt-dlp finds on YouTube.
    forced_title:  Optional[str] = None
    forced_artist: Optional[str] = None
    forced_index:  Optional[int] = None

    # Callbacks – set by the caller, never touched by the engine internals
    on_progress: Optional[Callable[[DownloadProgress], None]] = field(
        default=None, repr=False
    )
    on_finished: Optional[Callable[[DownloadProgress], None]] = field(
        default=None, repr=False
    )
    on_error: Optional[Callable[[DownloadProgress], None]] = field(
        default=None, repr=False
    )


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _sanitize_filename(name: str) -> str:
    """Remove / replace characters that are illegal on Windows & macOS."""
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


def _bytes_to_mb(b: Optional[int]) -> Optional[float]:
    if b is None:
        return None
    return round(b / (1024 * 1024), 2)


# ──────────────────────────────────────────────────────────────────────────────
# Main engine class
# ──────────────────────────────────────────────────────────────────────────────

class DownloadEngine:
    """
    Stateless download engine.  Create one instance per application, then call
    `download()` (blocking) or `download_async()` (non-blocking) for each job.

    Example
    -------
    >>> def on_progress(p: DownloadProgress):
    ...     print(f"{p.title}: {p.fraction:.0%}  {p.status.name}")
    ...
    >>> engine = DownloadEngine()
    >>> req = DownloadRequest(
    ...     url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    ...     output_dir="~/Downloads",
    ...     media_type=MediaType.AUDIO,
    ...     on_progress=on_progress,
    ... )
    >>> engine.download(req)
    """

    def __init__(self) -> None:
        self._cancel_event = threading.Event()
        self._lock = threading.Lock()

    # ── Public API ─────────────────────────────────────────────────────────────

    def download(self, request: DownloadRequest) -> None:
        """
        Blocking download.  Runs on the calling thread.
        Safe to call from a background thread spawned by the GUI.
        """
        # Validate URL before attempting download
        url = (request.url or "").strip()
        if not url:
            prog = DownloadProgress(
                status=DownloadStatus.ERROR,
                url=request.url,
                error_message="❌ Download URL is empty. The track may not have been properly loaded from the search.",
            )
            self._fire(request, prog, error=True)
            return
        
        # Check for Spotify URL (not supported)
        if "spotify" in url.lower():
            prog = DownloadProgress(
                status=DownloadStatus.ERROR,
                url=request.url,
                error_message="❌ Spotify is not supported. Only YouTube videos can be downloaded.",
            )
            self._fire(request, prog, error=True)
            return
        
        self._cancel_event.clear()
        
        # Validate output directory
        out_dir = Path(request.output_dir).expanduser().resolve()
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError) as exc:
            prog = DownloadProgress(
                status=DownloadStatus.ERROR,
                url=request.url,
                error_message=f"❌ Cannot write to output folder: {exc}",
            )
            self._fire(request, prog, error=True)
            return
        
        try:
            opts = self._build_ydl_opts(request)
            
            # Record the initial file count in the output directory
            initial_files = set(out_dir.glob("*")) if out_dir.exists() else set()
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                self._fire(request, DownloadProgress(
                    status=DownloadStatus.EXTRACTING,
                    url=request.url,
                ))
                ydl.download([url])
            
            # Check if new files were actually created
            final_files = set(out_dir.glob("*")) if out_dir.exists() else set()
            new_files = final_files - initial_files
            
            # Filter to audio files only
            audio_extensions = {".mp3", ".m4a", ".flac", ".opus", ".wav", ".aac"}
            audio_files = [f for f in new_files if f.is_file() and f.suffix.lower() in audio_extensions]
            
            if not audio_files:
                # yt-dlp completed but no audio files were created
                prog = DownloadProgress(
                    status=DownloadStatus.ERROR,
                    url=request.url,
                    error_message="❌ Download completed but no audio file was found. Check FFmpeg installation: ffmpeg -version",
                )
                self._fire(request, prog, error=True)
                return
            
            # If files were created but the PP hook didn't fire, manually report them
            # (This is a safety fallback)
            for audio_file in audio_files:
                prog = DownloadProgress(
                    status=DownloadStatus.FINISHED,
                    url=request.url,
                    title=audio_file.stem,
                    fraction=1.0,
                    output_path=str(audio_file),
                )
                self._fire(request, prog, finished=True)
        except yt_dlp.utils.DownloadCancelled:
            self._fire(request, DownloadProgress(
                status=DownloadStatus.CANCELLED,
                url=request.url,
            ))
        except yt_dlp.utils.ExtractorError as exc:
            error_msg = str(exc).lower()
            if "bot" in error_msg or "sign in" in error_msg:
                prog = DownloadProgress(
                    status=DownloadStatus.ERROR,
                    url=request.url,
                    error_message="❌ YouTube חוסם הורדה זו. סרטון זה אולי מוגן או לא זמין.\n\n"
                                  "פתרונות:\n"
                                  "• נסה סרטון שונה\n"
                                  "• אם הבעיה חוזרת, השתמש ב-VPN\n"
                                  "(Proton VPN, Windscribe - חינם)",
                )
            elif "cookies" in error_msg or "dpapi" in error_msg:
                prog = DownloadProgress(
                    status=DownloadStatus.ERROR,
                    url=request.url,
                    error_message="❌ בעיה עם אימות. יתכן שצריך להתחבר ל-YouTube בדפדפן שלך.\n\n"
                                  "נסה:\n"
                                  "• אתחל את הדפדפן (Firefox / Chrome / Edge)\n"
                                  "• כנס ל-youtube.com עם חשבון שלך\n"
                                  "• אחרי זה נסה הורדה שוב",
                )
            else:
                prog = DownloadProgress(
                    status=DownloadStatus.ERROR,
                    url=request.url,
                    error_message=f"❌ בעיה: {str(exc)[:100]}",
                )
            self._fire(request, prog, error=True)
        except Exception as exc:  # noqa: BLE001
            prog = DownloadProgress(
                status=DownloadStatus.ERROR,
                url=request.url,
                error_message=f"❌ Download failed: {exc}",
            )
            self._fire(request, prog, error=True)

    def download_async(
        self,
        request: DownloadRequest,
        daemon: bool = True,
    ) -> threading.Thread:
        """
        Non-blocking wrapper – spawns a daemon thread and returns it.
        The caller can join() the thread if synchronisation is needed.
        """
        t = threading.Thread(
            target=self.download,
            args=(request,),
            daemon=daemon,
            name=f"dl-{id(request)}",
        )
        t.start()
        return t

    def cancel(self) -> None:
        """
        Signal the currently running download to stop.
        yt-dlp checks this flag between fragments / items.
        """
        self._cancel_event.set()

    # ── yt-dlp options builder ─────────────────────────────────────────────────

    def _build_ydl_opts(self, req: DownloadRequest) -> dict[str, Any]:
        out_dir = Path(req.output_dir).expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

        # ── Output filename template ──────────────────────────────────────────
        # Use forced metadata if available (typical for Spotify -> YouTube search)
        # to ensure unique filenames and correct naming.
        if req.forced_title or req.forced_artist:
            artist = _sanitize_filename(req.forced_artist or "Unknown Artist")
            title  = _sanitize_filename(req.forced_title  or "Unknown Title")
            idx_prefix = f"{req.forced_index:02d} " if req.forced_index is not None else ""
            # Format: "01 Artist - Title.ext"
            outtmpl = str(out_dir / f"{idx_prefix}{artist} - {title}.%(ext)s")
        else:
            # Standard yt-dlp naming using its own internal metadata
            # %(playlist_index)s is empty for non-playlist downloads – that's fine.
            outtmpl = str(out_dir / "%(playlist_index)s%(title)s.%(ext)s")

        opts: dict[str, Any] = {
            # ── I/O ───────────────────────────────────────────────────────────
            "outtmpl":         outtmpl,
            "restrictfilenames": True,      # ASCII-safe filenames
            "windowsfilenames":  True,      # colon/asterisk safety on Windows
            
            # ── Full Chrome 136 browser fingerprint headers ───────────────────
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/136.0.0.0 Safari/537.36"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;"
                    "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
                ),
                "Accept-Language":  "en-US,en;q=0.9",
                "Accept-Encoding":  "gzip, deflate, br",
                "Sec-Fetch-Dest":   "document",
                "Sec-Fetch-Mode":   "navigate",
                "Sec-Fetch-Site":   "none",
                "Sec-Fetch-User":   "?1",
                "Sec-CH-UA":        '"Chromium";v="136", "Google Chrome";v="136", "Not-A.Brand";v="99"',
                "Sec-CH-UA-Mobile": "?0",
                "Sec-CH-UA-Platform": '"Windows"',
                "Upgrade-Insecure-Requests": "1",
                "Connection":       "keep-alive",
            },

            # ── Age gate bypass ───────────────────────────────────────────────
            "age_limit": 18,

            # ── Network ───────────────────────────────────────────────────────
            "retries":         10,
            "fragment_retries": 10,
            "ignoreerrors":    False,       # surface errors to our handler
            "nocheckcertificate": False,

            # ── Playlist ──────────────────────────────────────────────────────
            "playliststart":   req.playlist_start,
            **({"playlistend": req.playlist_end} if req.playlist_end else {}),

            # ── Cookies: manual file > browser extraction > none ─────────────
            # Browser extraction reads from a real logged-in browser session,
            # bypassing CAPTCHA checks and age-verification walls.
            **({"cookiefile": req.cookies_file} if req.cookies_file
               else {"cookiesfrombrowser": (req.cookies_browser, None, None, None)}
               if req.cookies_browser else {}),

            # ── TLS browser impersonation (curl_cffi) ─────────────────────────
            **({"impersonate": _ImpersonateTarget("chrome")} if _CURL_CFFI_AVAILABLE else {}),
            
            # ── YouTube extractor options ──────────────────────────────────── 
            "extractor_args": {
                "youtube": {
                    # Skip problematic stream types that cause bot detection
                    "skip": ["webpage"],
                }
            },

            # ── Progress & cancel hooks ───────────────────────────────────────
            "progress_hooks":  [self._make_progress_hook(req)],
            "postprocessor_hooks": [self._make_pp_hook(req)],

            # ── Verbosity ────────────────────────────────────────────────────
            "quiet":           True,
            "no_warnings":     False,

            # ── Abort flag ────────────────────────────────────────────────────
            "abort_on_unavailable_fragment": False,
        }

        # ── Cancel support ────────────────────────────────────────────────────
        # yt-dlp checks this callable each iteration.
        cancel_ev = self._cancel_event

        def _abort_hook(_info: dict) -> None:  # noqa: ANN001
            if cancel_ev.is_set():
                raise yt_dlp.utils.DownloadCancelled()

        opts["progress_hooks"].append(_abort_hook)

        # ── Format selection & post-processors ───────────────────────────────
        if req.media_type == MediaType.AUDIO:
            opts.update(self._audio_opts(req))
        else:
            opts.update(self._video_opts(req))

        return opts

    # ── Format-specific option sub-builders ───────────────────────────────────

    @staticmethod
    def _audio_opts(req: DownloadRequest) -> dict[str, Any]:
        postprocessors: list[dict] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec":  req.audio_format,
                "preferredquality": req.audio_quality.value,
            },
        ]

        if req.embed_metadata:
            postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})

        if req.embed_thumbnail:
            postprocessors.append({"key": "EmbedThumbnail"})

        opts = {
            "format":          "bestaudio/best",
            "postprocessors":  postprocessors,
            "writethumbnail":  req.embed_thumbnail,   # needed by EmbedThumbnail
        }

        # ── Global overrides for metadata (ID3 tags) ─────────────────────────
        if req.forced_title or req.forced_artist:
            meta_args = []
            if req.forced_title:
                meta_args.extend(["-metadata", f"title={req.forced_title}"])
            if req.forced_artist:
                meta_args.extend(["-metadata", f"artist={req.forced_artist}"])
            
            opts["postprocessor_args"] = {
                "FFmpegMetadata": meta_args,
                "FFmpegExtractAudio": meta_args  # apply during conversion too
            }

        return opts

    @staticmethod
    def _video_opts(req: DownloadRequest) -> dict[str, Any]:
        postprocessors: list[dict] = [
            {
                # Merge separate video+audio streams into a single container
                "key":            "FFmpegVideoConvertor",
                "preferedformat": "mp4",
            },
        ]

        if req.embed_metadata:
            postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})

        if req.write_subtitles:
            postprocessors.append({
                "key":       "FFmpegEmbedSubtitle",
                "already_have_subtitle": False,
            })

        opts: dict[str, Any] = {
            "format":         req.video_quality.value,
            "postprocessors": postprocessors,
            "merge_output_format": "mp4",
        }

        if req.write_subtitles:
            opts["writesubtitles"]   = True
            opts["subtitleslangs"]   = ["en"]
            opts["subtitlesformat"]  = "vtt"

        # ── Global overrides for metadata (MP4 tags) ─────────────────────────
        if req.forced_title or req.forced_artist:
            meta_args = []
            if req.forced_title:
                meta_args.extend(["-metadata", f"title={req.forced_title}"])
            if req.forced_artist:
                meta_args.extend(["-metadata", f"artist={req.forced_artist}"])
            
            opts["postprocessor_args"] = {
                "FFmpegMetadata": meta_args,
                "FFmpegVideoConvertor": meta_args
            }

        return opts

    # ── Hook factories ────────────────────────────────────────────────────────

    def _make_progress_hook(
        self,
        req: DownloadRequest,
    ) -> Callable[[dict], None]:
        """
        Returns a closure that yt-dlp calls for every download-progress event.
        yt-dlp calls this with a dict containing keys like:
            status          – "downloading" | "error" | "finished"
            downloaded_bytes
            total_bytes / total_bytes_estimate
            speed
            eta
            filename
            info_dict       – full metadata dict for the current item
        """
        def hook(d: dict) -> None:  # noqa: ANN001
            ydl_status   = d.get("status", "")
            info         = d.get("info_dict", {})
            title        = info.get("title", d.get("filename", ""))
            pl_idx       = info.get("playlist_index")
            pl_count     = info.get("n_entries")
            dl_bytes     = d.get("downloaded_bytes", 0)
            total_bytes  = d.get("total_bytes") or d.get("total_bytes_estimate")
            speed        = d.get("speed")
            eta          = d.get("eta")

            fraction: float = 0.0
            if total_bytes and total_bytes > 0:
                fraction = min(dl_bytes / total_bytes, 1.0)

            if ydl_status == "downloading":
                prog = DownloadProgress(
                    status=DownloadStatus.DOWNLOADING,
                    url=req.url,
                    title=title,
                    playlist_index=pl_idx,
                    playlist_count=pl_count,
                    downloaded_bytes=dl_bytes,
                    total_bytes=total_bytes,
                    speed_bps=speed,
                    eta_seconds=eta,
                    fraction=fraction,
                )
                self._fire(req, prog)

            elif ydl_status == "finished":
                # File is downloaded; FFmpeg post-processing starts next.
                prog = DownloadProgress(
                    status=DownloadStatus.PROCESSING,
                    url=req.url,
                    title=title,
                    playlist_index=pl_idx,
                    playlist_count=pl_count,
                    downloaded_bytes=dl_bytes,
                    total_bytes=total_bytes,
                    fraction=1.0,
                )
                self._fire(req, prog)

            elif ydl_status == "error":
                prog = DownloadProgress(
                    status=DownloadStatus.ERROR,
                    url=req.url,
                    title=title,
                    error_message=d.get("error", "Unknown yt-dlp error"),
                )
                self._fire(req, prog, error=True)

        return hook

    def _make_pp_hook(
        self,
        req: DownloadRequest,
    ) -> Callable[[dict], None]:
        """
        Returns a closure called by yt-dlp *after* each post-processor step
        (e.g., after FFmpeg finishes converting to MP3).
        """
        def hook(d: dict) -> None:  # noqa: ANN001
            if d.get("status") != "finished":
                return

            info      = d.get("info_dict", {})
            title     = info.get("title", "")
            pl_idx    = info.get("playlist_index")
            pl_count  = info.get("n_entries")
            filepath  = d.get("info_dict", {}).get("filepath") or \
                        d.get("filepath", "")

            prog = DownloadProgress(
                status=DownloadStatus.FINISHED,
                url=req.url,
                title=title,
                playlist_index=pl_idx,
                playlist_count=pl_count,
                fraction=1.0,
                output_path=filepath,
            )
            self._fire(req, prog, finished=True)

        return hook

    # ── Callback dispatcher ────────────────────────────────────────────────────

    @staticmethod
    def _fire(
        req: DownloadRequest,
        prog: DownloadProgress,
        *,
        finished: bool = False,
        error: bool = False,
    ) -> None:
        """Safely invoke caller-supplied callbacks without raising."""
        try:
            if req.on_progress:
                req.on_progress(prog)
            if finished and req.on_finished:
                req.on_finished(prog)
            if error and req.on_error:
                req.on_error(prog)
        except Exception:  # noqa: BLE001
            # Never let a misbehaving callback crash the download thread.
            pass


# ──────────────────────────────────────────────────────────────────────────────
# Quick smoke-test  (python downloader.py)
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    def _on_progress(p: DownloadProgress) -> None:
        bar_width = 30
        filled    = int(bar_width * p.fraction)
        bar       = "█" * filled + "░" * (bar_width - filled)
        mb_done   = _bytes_to_mb(p.downloaded_bytes) or 0
        mb_total  = _bytes_to_mb(p.total_bytes) or "?"
        speed_kb  = round((p.speed_bps or 0) / 1024, 1)
        eta       = f"{int(p.eta_seconds or 0)}s" if p.eta_seconds else "?"

        status_char = {
            DownloadStatus.EXTRACTING:  "🔍",
            DownloadStatus.DOWNLOADING: "⬇ ",
            DownloadStatus.PROCESSING:  "⚙ ",
            DownloadStatus.FINISHED:    "✅",
            DownloadStatus.ERROR:       "❌",
            DownloadStatus.CANCELLED:   "🚫",
        }.get(p.status, "  ")

        pl_info = ""
        if p.playlist_index and p.playlist_count:
            pl_info = f"  [{p.playlist_index}/{p.playlist_count}]"

        print(
            f"\r{status_char} [{bar}] {p.fraction:>5.1%}  "
            f"{mb_done}/{mb_total} MB  {speed_kb} KB/s  ETA {eta}"
            f"{pl_info}  {p.title[:40]:<40}",
            end="",
            flush=True,
        )
        if p.status in (
            DownloadStatus.FINISHED,
            DownloadStatus.ERROR,
            DownloadStatus.CANCELLED,
        ):
            print()

    def _on_finished(p: DownloadProgress) -> None:
        print(f"\n✅  Saved to: {p.output_path}")

    def _on_error(p: DownloadProgress) -> None:
        print(f"\n❌  Error: {p.error_message}", file=sys.stderr)

    # ── Run ───────────────────────────────────────────────────────────────────
    test_url = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    )

    engine = DownloadEngine()
    request = DownloadRequest(
        url=test_url,
        output_dir="~/Downloads/YTSpot",
        media_type=MediaType.AUDIO,
        audio_quality=AudioQuality.BEST,
        audio_format="mp3",
        embed_thumbnail=True,
        embed_metadata=True,
        on_progress=_on_progress,
        on_finished=_on_finished,
        on_error=_on_error,
    )

    print(f"Downloading: {test_url}\n")
    engine.download(request)
