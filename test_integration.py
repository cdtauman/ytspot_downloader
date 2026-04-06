"""
test_integration.py  –  Parser → Downloader pipeline smoke-test
================================================================
Run:
    python test_integration.py

What it tests
-------------
1.  URL classification (no network).
2.  Metadata extraction for a short public YouTube playlist.
3.  Selective download: picks only the FIRST track from the parsed list
    and downloads it as MP3, using the `DownloadEngine`.

No GUI, no packaging – pure CLI.
"""

from __future__ import annotations

import sys
from typing import Optional

from playlist_parser import (
    PlaylistParser,
    TrackMeta,
    ParseResult,
    classify_url,
    SourcePlatform,
    UrlKind,
)
from downloader import (
    DownloadEngine,
    DownloadRequest,
    DownloadProgress,
    DownloadStatus,
    MediaType,
    AudioQuality,
)


# ──────────────────────────────────────────────────────────────────────────────
# 1.  URL classifier  (pure regex – instant)
# ──────────────────────────────────────────────────────────────────────────────

def test_classify() -> None:
    cases = [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ",                         SourcePlatform.YOUTUBE,  UrlKind.SINGLE_VIDEO),
        ("https://www.youtube.com/playlist?list=PLbZIPy20-1pM5OX8RMwO6DvYkKfFf2dOq", SourcePlatform.YOUTUBE,  UrlKind.PLAYLIST),
        ("https://youtu.be/dQw4w9WgXcQ",                                         SourcePlatform.YOUTUBE,  UrlKind.SINGLE_VIDEO),
        ("https://music.youtube.com/playlist?list=RDCLAK5uy_k",                  SourcePlatform.YOUTUBE_MUSIC, UrlKind.PLAYLIST),
        ("https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC",               SourcePlatform.SPOTIFY,  UrlKind.SINGLE_VIDEO),
        ("https://open.spotify.com/album/1DFixLWuPkv3KT3TnV35m3",               SourcePlatform.SPOTIFY,  UrlKind.ALBUM),
        ("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",            SourcePlatform.SPOTIFY,  UrlKind.PLAYLIST),
    ]

    print("── 1. URL Classification ──────────────────────────────────────────")
    all_ok = True
    for url, exp_plat, exp_kind in cases:
        plat, kind = classify_url(url)
        ok = (plat == exp_plat) and (kind == exp_kind)
        icon = "✅" if ok else "❌"
        print(f"  {icon}  {url[:60]:<60}  →  {plat.name} / {kind.name}")
        if not ok:
            print(f"        expected: {exp_plat.name} / {exp_kind.name}")
            all_ok = False
    print()
    assert all_ok, "URL classification test failed."


# ──────────────────────────────────────────────────────────────────────────────
# 2.  Playlist metadata extraction  (network call)
# ──────────────────────────────────────────────────────────────────────────────

# Short public playlist – 3 items, each < 5 minutes.
TEST_PLAYLIST_URL = (
    "https://www.youtube.com/playlist?list=PLbZIPy20-1pM5OX8RMwO6DvYkKfFf2dOq"
)

def test_parse(url: str = TEST_PLAYLIST_URL) -> ParseResult:
    print("── 2. Playlist Metadata Extraction ────────────────────────────────")
    print(f"  URL: {url}\n")

    parser  = PlaylistParser()
    items_seen: list[TrackMeta] = []

    def on_item(track: TrackMeta, idx: int, total: Optional[int]) -> None:
        items_seen.append(track)
        total_str = str(total) if total else "?"
        print(
            f"  [{idx:>3}/{total_str}]  "
            f"{track.title[:50]:<50}  "
            f"{track.duration_str:<8}  "
            f"thumb={'✓' if track.thumbnail_url else '✗'}"
        )

    def on_progress(msg: str) -> None:
        print(f"  ℹ  {msg}")

    def on_error(msg: str) -> None:
        print(f"  ⚠  {msg}", file=sys.stderr)

    result = parser.parse(
        url,
        on_item=on_item,
        on_progress=on_progress,
        on_error=on_error,
    )

    print()
    print(f"  Summary: {result.summary()}")
    print()

    assert result.success(),  f"Parse did not succeed: {result.error}"
    assert len(result.tracks) > 0, "No tracks extracted."
    for t in result.tracks:
        assert t.url,           f"Track {t.index} has no URL"
        assert t.title,         f"Track {t.index} has no title"
        assert t.thumbnail_url, f"Track {t.index} has no thumbnail"

    print("  ✅  All metadata assertions passed.\n")
    return result


# ──────────────────────────────────────────────────────────────────────────────
# 3.  Selective download – first track only
# ──────────────────────────────────────────────────────────────────────────────

def test_download_first_track(result: ParseResult) -> None:
    print("── 3. Selective Download (first track as MP3) ──────────────────────")

    first_track = result.tracks[0]
    print(f"  Downloading: {first_track.title}")
    print(f"  URL:         {first_track.url}\n")

    engine  = DownloadEngine()
    log: list[str] = []

    def on_progress(p: DownloadProgress) -> None:
        bar_w   = 25
        filled  = int(bar_w * p.fraction)
        bar     = "█" * filled + "░" * (bar_w - filled)
        speed   = f"{(p.speed_bps or 0)/1024:.0f} KB/s"
        eta     = f"ETA {int(p.eta_seconds or 0)}s" if p.eta_seconds else ""
        line    = (
            f"\r  [{bar}] {p.fraction:>5.1%}  "
            f"{speed:<12} {eta:<10} {p.status.name}"
        )
        print(line, end="", flush=True)
        log.append(p.status.name)

    def on_finished(p: DownloadProgress) -> None:
        print()
        print(f"\n  ✅  Saved to: {p.output_path}")

    def on_error(p: DownloadProgress) -> None:
        print()
        print(f"\n  ❌  Error: {p.error_message}", file=sys.stderr)

    req = DownloadRequest(
        url=first_track.url,
        output_dir="~/Downloads/YTSpot_Test",
        media_type=MediaType.AUDIO,
        audio_quality=AudioQuality.BEST,
        audio_format="mp3",
        embed_thumbnail=True,
        embed_metadata=True,
        on_progress=on_progress,
        on_finished=on_finished,
        on_error=on_error,
    )

    engine.download(req)
    print()

    assert DownloadStatus.FINISHED.name in log or DownloadStatus.PROCESSING.name in log, \
        "Download did not reach FINISHED or PROCESSING state."
    print("  ✅  Download assertions passed.\n")


# ──────────────────────────────────────────────────────────────────────────────
# Entry-point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else TEST_PLAYLIST_URL

    try:
        test_classify()
        result = test_parse(url)

        # Only run the download test if explicitly requested (it costs bandwidth)
        if "--download" in sys.argv:
            test_download_first_track(result)
        else:
            print("  (Skipping download test – pass --download to enable it)\n")

        print("=" * 60)
        print("All tests passed ✅")
    except AssertionError as e:
        print(f"\n❌  FAILED: {e}", file=sys.stderr)
        sys.exit(1)
