#!/usr/bin/env python3
"""
cli.py  –  Headless CLI for YTSpot Downloader
===============================================
Downloads audio/video from YouTube, Spotify, and other supported sites
from the command line — no GUI, no Qt.

Uses the same core engine as the desktop app:
  PlaylistParser → DownloadOrchestrator → DownloadEngine

Usage
-----
    # Single track
    python cli.py "https://www.youtube.com/watch?v=TESTVIDEOAAA"

    # Playlist (downloads all tracks)
    python cli.py "https://www.youtube.com/playlist?list=PLxxxxx"

    # Spotify album → YouTube match → download
    python cli.py "https://open.spotify.com/album/TESTALBUMID00001"

    # Options
    python cli.py URL --format mp4 --quality 720p --output ~/Music
    python cli.py URL --audio-format flac --parallel 4
    python cli.py URL --cookies cookies.txt

    # List available tracks without downloading
    python cli.py URL --list

Run ``python cli.py --help`` for full options.
"""

from __future__ import annotations

import argparse
import sys
import os
from pathlib import Path

# On Windows, the Playwright browser is bundled inside the EXE folder.
# On macOS, Chromium is bundled as loose files (chrome-mac directory) inside
# the .app to avoid nested .app re-signing issues. Point Playwright there.
if getattr(sys, 'frozen', False):
    if sys.platform == 'win32':
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(Path(sys._MEIPASS) / 'ms-playwright')
    elif sys.platform == 'darwin':
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(Path(sys._MEIPASS))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
import logging
import threading
from pathlib import Path

# Bootstrap logging before any project import
from utils.logging_config import setup_logging


# ──────────────────────────────────────────────────────────────────────────────
# Terminal callbacks (implements OrchestratorCallbacks protocol)
# ──────────────────────────────────────────────────────────────────────────────

class TerminalCallbacks:
    """Prints progress to stderr so stdout stays clean for piping."""

    def __init__(self, total: int, quiet: bool = False) -> None:
        self._total = total
        self._quiet = quiet
        self._completed = 0
        self._failed = 0
        self._lock = threading.Lock()

    def on_track_progress(self, key: str, fraction: float) -> None:
        if self._quiet:
            return
        pct = int(fraction * 100)
        bar_w = 25
        filled = int(bar_w * fraction)
        bar = "█" * filled + "░" * (bar_w - filled)
        print(f"\r  [{bar}] {pct:>3}%", end="", flush=True, file=sys.stderr)

    def on_track_status(self, key: str, status: str) -> None:
        pass  # handled by finished/error

    def on_track_finished(self, key: str, output_path: str) -> None:
        with self._lock:
            self._completed += 1
            n = self._completed
        name = Path(output_path).name if output_path else "unknown"
        print(f"\r  ✅  [{n}/{self._total}] {name}", file=sys.stderr)

    def on_track_error(self, key: str, error) -> None:
        with self._lock:
            self._failed += 1
        headline = getattr(error, "headline", str(error))
        print(f"\r  ❌  {key}: {headline}", file=sys.stderr)

    def on_overall_progress(self, fraction: float) -> None:
        pass

    def on_metrics(self, speed: str, eta: str) -> None:
        if self._quiet or not speed:
            return
        print(f"  {speed}  {eta}    ", end="", flush=True, file=sys.stderr)

    def on_status_message(self, msg: str) -> None:
        if not self._quiet:
            print(f"\n{msg}", file=sys.stderr)

    def on_batch_finished(self) -> None:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Argument parser
# ──────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    from version import __version__, PRODUCT_NAME

    p = argparse.ArgumentParser(
        prog="ytspot-cli",
        description=f"{PRODUCT_NAME} — headless CLI mode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s https://youtu.be/TESTVIDEOAAA\n"
            "  %(prog)s https://youtube.com/playlist?list=PLxxx --format mp4\n"
            "  %(prog)s https://open.spotify.com/album/xxx --audio-format flac\n"
            "  %(prog)s URL --list\n"
            "  %(prog)s --version\n"
            "  %(prog)s --doctor\n"
        ),
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    p.add_argument(
        "--doctor",
        action="store_true",
        help=(
            "Run startup diagnostics (FFmpeg, network, output dir, "
            "cookies, Playwright) and exit. URL not required."
        ),
    )
    # URL is optional so --version / --doctor work without it. main()
    # enforces the requirement once the early-exit flags are handled.
    p.add_argument(
        "url",
        nargs="?",
        help="YouTube, Spotify, or supported URL",
    )
    p.add_argument(
        "-o", "--output",
        default=str(Path.home() / "Downloads" / "YTSpot"),
        help="Output directory (default: ~/Downloads/YTSpot)",
    )
    p.add_argument(
        "-f", "--format",
        choices=["mp3", "mp4"],
        default="mp3",
        help="Media format (default: mp3)",
    )
    p.add_argument(
        "--audio-format",
        choices=["mp3", "m4a", "flac", "opus"],
        default="mp3",
        help="Audio codec (default: mp3)",
    )
    p.add_argument(
        "--quality",
        default="Best (320k)",
        help="Quality label: 'Best (320k)', 'High (256k)', '1080p', '720p', etc.",
    )
    p.add_argument(
        "--parallel", "-j",
        type=int, default=3,
        help="Concurrent downloads (1-6, default: 3)",
    )
    p.add_argument(
        "--cookies",
        default=None,
        help="Path to cookies.txt (Netscape format)",
    )
    p.add_argument(
        "--list", "-l",
        action="store_true",
        help="List tracks without downloading",
    )
    p.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress progress output (errors still shown)",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging to console",
    )
    return p


# ──────────────────────────────────────────────────────────────────────────────
# Quality maps (mirrors AppWindow logic)
# ──────────────────────────────────────────────────────────────────────────────

def _resolve_quality(label: str, is_audio: bool):
    from core.downloader import AudioQuality, VideoQuality
    if is_audio:
        _map = {
            "Best (320k)":   AudioQuality.BEST,
            "High (256k)":   AudioQuality.HIGH,
            "Medium (192k)": AudioQuality.MEDIUM,
            "Low (128k)":    AudioQuality.LOW,
        }
        return _map.get(label, AudioQuality.BEST)
    else:
        _map = {
            "Best":  VideoQuality.BEST,
            "1080p": VideoQuality.HIGH,
            "720p":  VideoQuality.MEDIUM,
            "480p":  VideoQuality.LOW,
            "Worst": VideoQuality.WORST,
        }
        return _map.get(label, VideoQuality.HIGH)


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def _run_doctor(args) -> int:
    """Print preflight diagnostics and exit.

    Does not require a URL and never raises. Returns 0 if every
    blocking check passes (FFmpeg, network, output dir); 1 otherwise.
    Informational checks (Playwright, cookies file) print their state
    but do not change the exit code.
    """
    from error_handler import run_preflight
    from version import __version__, PRODUCT_NAME

    output_dir = args.output if args.output else ""
    cookies_file = args.cookies if args.cookies else ""

    print(f"{PRODUCT_NAME} v{__version__}  —  diagnostics")
    print("=" * 60)
    result = run_preflight(output_dir=output_dir, cookies_file=cookies_file)
    print(result.detail_text())
    print("=" * 60)
    if result.all_ok():
        print("All blocking checks PASSED.")
        if result.warnings:
            print()
            print("Informational warnings:")
            print(result.warning_text())
        return 0
    print("FAILED — at least one blocking check did not pass:")
    print()
    print(result.warning_text())
    return 1


def main() -> int:
    args = build_parser().parse_args()
    setup_logging(debug=args.debug)
    logger = logging.getLogger("cli")

    # ── 0. Early-exit flags ──────────────────────────────────────────────
    # --version is handled by argparse before this point.
    if args.doctor:
        return _run_doctor(args)

    # URL is required for every other path. argparse made it optional so
    # --version / --doctor could run without it; enforce the requirement
    # here with a friendly error.
    if not args.url:
        print(
            "error: URL is required (use --version or --doctor for "
            "no-URL operations)",
            file=sys.stderr,
        )
        return 2

    # ── 1. Parse URL → track list ─────────────────────────────────────────
    from core.playlist_parser import PlaylistParser, TrackMeta, classify_url, SourcePlatform

    platform, kind = classify_url(args.url)
    if platform == SourcePlatform.UNKNOWN:
        print(f"❌  Unsupported URL: {args.url}", file=sys.stderr)
        return 1

    print(f"🔍  Resolving: {args.url}", file=sys.stderr)
    print(f"    Platform: {platform.name}  Kind: {kind.name}", file=sys.stderr)

    parser = PlaylistParser()
    tracks_seen: list[TrackMeta] = []

    def on_item(track: TrackMeta, idx: int, total) -> None:
        tracks_seen.append(track)
        total_str = str(total) if total else "?"
        if not args.quiet:
            print(
                f"  [{idx:>3}/{total_str}]  {track.artist[:20]:<20}  "
                f"{track.title[:45]:<45}  {track.duration_str}",
                file=sys.stderr,
            )

    result = parser.parse(
        args.url,
        cookies_file=args.cookies,
        on_item=on_item,
        on_progress=lambda msg: (
            print(f"  ℹ  {msg}", file=sys.stderr) if not args.quiet else None
        ),
        on_error=lambda msg: print(f"  ⚠  {msg}", file=sys.stderr),
    )

    if not result.tracks:
        print(f"❌  No tracks found. {result.error or ''}", file=sys.stderr)
        return 1

    print(f"\n📋  {result.summary()}", file=sys.stderr)

    # ── 2. List-only mode ─────────────────────────────────────────────────
    if args.list:
        print()  # blank line for readability
        for t in result.tracks:
            # stdout: machine-parseable output
            print(f"{t.index}\t{t.artist}\t{t.title}\t{t.duration_str}\t{t.url}")
        return 0

    # ── 3. Build download jobs ────────────────────────────────────────────
    from core.downloader import DownloadEngine, DownloadRequest, MediaType

    is_audio   = args.format == "mp3"
    media_type = MediaType.AUDIO if is_audio else MediaType.VIDEO
    quality    = _resolve_quality(args.quality, is_audio)
    output_dir = args.output

    Path(output_dir).expanduser().mkdir(parents=True, exist_ok=True)

    engine = DownloadEngine()
    jobs: list[tuple[str, DownloadRequest]] = []

    playlist_name = result.playlist_title if len(result.tracks) > 1 else None

    for track in result.tracks:
        key = f"track-{track.index}"
        req_kwargs = dict(
            url=track.url,
            output_dir=output_dir,
            media_type=media_type,
            audio_format=args.audio_format,
            embed_thumbnail=True,
            embed_metadata=True,
            forced_title=track.title,
            forced_artist=track.artist,
            forced_index=track.index if playlist_name else None,
            forced_duration=track.duration_sec,
            playlist_name=playlist_name,
            cookies_file=args.cookies,
        )
        if is_audio:
            req_kwargs["audio_quality"] = quality
        else:
            req_kwargs["video_quality"] = quality

        jobs.append((key, DownloadRequest(**req_kwargs)))

    # ── 4. Run orchestrator ───────────────────────────────────────────────
    from core.download_orchestrator import DownloadOrchestrator
    from core.history_db import HistoryDB

    db = HistoryDB()  # default path
    cb = TerminalCallbacks(total=len(jobs), quiet=args.quiet)

    orch = DownloadOrchestrator(
        engine=engine,
        callbacks=cb,
        db=db,
        max_workers=max(1, min(6, args.parallel)),
    )

    print(
        f"\n⬇  Downloading {len(jobs)} track(s) "
        f"({args.format}, {args.quality}, {args.parallel} threads)…\n",
        file=sys.stderr,
    )

    batch = orch.run_batch(jobs)

    # ── 5. Summary ────────────────────────────────────────────────────────
    db.close()

    print(file=sys.stderr)
    if batch.cancelled:
        print("🚫  Cancelled.", file=sys.stderr)
        return 130
    if batch.failed > 0:
        print(
            f"⚠  Done with errors: {batch.completed} succeeded, "
            f"{batch.failed} failed.",
            file=sys.stderr,
        )
        return 1

    print(f"✅  All {batch.completed} track(s) downloaded.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
