"""
core/replay_gain.py  –  ReplayGain analysis + tag embedding (Advanced Setting)
===============================================================================
Analyses downloaded audio files for loudness and embeds ReplayGain tags
so every track plays at a normalised volume in music players.

Uses the ``rsgain`` CLI tool if available (most accurate, fastest) and falls
back to the pure-Python ``pyloudnorm`` + ``soundfile`` stack when rsgain is
not installed.

Supported containers (via mutagen)
-----------------------------------
  MP3   → ID3  REPLAYGAIN_TRACK_GAIN / REPLAYGAIN_TRACK_PEAK
  FLAC  → Vorbis comment REPLAYGAIN_TRACK_GAIN / REPLAYGAIN_TRACK_PEAK
  M4A   → iTunes atom  com.apple.iTunes REPLAYGAIN_TRACK_GAIN
  OGG   → Vorbis comment (same as FLAC)

Reference loudness: –18 LUFS (EBU R128 / ReplayGain 2.0 standard).

This module is **disabled by default** and only called when
AppConfig.replay_gain_enabled is True.

Zero GUI imports.  All errors are logged; never raises to the caller.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# EBU R128 reference level used by ReplayGain 2.0
_REFERENCE_LUFS: float = -18.0


def analyse_and_embed(file_path: str) -> bool:
    """
    Analyse the audio file at file_path and embed ReplayGain tags.

    Returns True on success, False on failure (error is logged).
    """
    path = Path(file_path)
    if not path.exists():
        logger.warning("[ReplayGain] File not found: %s", file_path)
        return False

    # Prefer rsgain CLI (fast, accurate, cross-platform binary)
    if shutil.which("rsgain"):
        return _analyse_with_rsgain(path)

    # Fall back to pyloudnorm + soundfile
    return _analyse_with_pyloudnorm(path)


# ── rsgain backend ─────────────────────────────────────────────────────────────

def _analyse_with_rsgain(path: Path) -> bool:
    """
    Use the `rsgain` CLI to compute and write ReplayGain tags in-place.

    rsgain easy -q FILE  writes tags directly; no Python tag-writing needed.
    """
    try:
        result = subprocess.run(
            ["rsgain", "easy", "-q", str(path)],
            capture_output=True,
            timeout=120,
        )
        if result.returncode == 0:
            logger.info("[ReplayGain] rsgain tagged %s", path.name)
            return True
        logger.warning(
            "[ReplayGain] rsgain failed (rc=%d): %s",
            result.returncode,
            result.stderr.decode(errors="replace"),
        )
        return False
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.debug("[ReplayGain] rsgain error: %s", exc)
        return False


# ── pyloudnorm backend ─────────────────────────────────────────────────────────

def _analyse_with_pyloudnorm(path: Path) -> bool:
    """
    Use pyloudnorm + soundfile to compute gain and embed tags manually.

    Requirements (installed separately):
        pip install pyloudnorm soundfile
    """
    try:
        import soundfile as sf          # type: ignore[import]
        import pyloudnorm as pyln       # type: ignore[import]
    except ImportError:
        logger.warning(
            "[ReplayGain] Neither rsgain nor pyloudnorm+soundfile found. "
            "Install rsgain or run: pip install pyloudnorm soundfile"
        )
        return False

    try:
        data, rate = sf.read(str(path), always_2d=True)
    except Exception as exc:
        logger.error("[ReplayGain] soundfile read error on %s: %s", path.name, exc)
        return False

    try:
        meter     = pyln.Meter(rate)
        loudness  = meter.integrated_loudness(data)
        gain_db   = _REFERENCE_LUFS - loudness

        # Peak: max absolute sample value across all channels
        import numpy as np  # soundfile already requires numpy
        peak = float(np.abs(data).max())

        _write_tags(path, gain_db, peak)
        logger.info(
            "[ReplayGain] Tagged %s: gain=%.2f dB, peak=%.6f",
            path.name, gain_db, peak,
        )
        return True
    except Exception as exc:
        logger.error("[ReplayGain] Analysis error on %s: %s", path.name, exc)
        return False


# ── Tag writers ────────────────────────────────────────────────────────────────

def _write_tags(path: Path, gain_db: float, peak: float) -> None:
    """Embed REPLAYGAIN_TRACK_GAIN and REPLAYGAIN_TRACK_PEAK into the file."""
    try:
        import mutagen  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("mutagen not installed") from exc

    suffix = path.suffix.lower()

    if suffix == ".mp3":
        _write_mp3(path, gain_db, peak)
    elif suffix in (".flac",):
        _write_flac(path, gain_db, peak)
    elif suffix in (".m4a", ".mp4", ".aac"):
        _write_m4a(path, gain_db, peak)
    elif suffix in (".ogg", ".opus"):
        _write_ogg(path, gain_db, peak)
    else:
        logger.debug("[ReplayGain] Unsupported format for tag writing: %s", suffix)


def _write_mp3(path: Path, gain_db: float, peak: float) -> None:
    from mutagen.id3 import ID3, TXXX, ID3NoHeaderError

    try:
        tags = ID3(str(path))
    except ID3NoHeaderError:
        tags = ID3()

    def _set_txxx(desc: str, value: str) -> None:
        tags.delall(f"TXXX:{desc}")
        tags.add(TXXX(encoding=3, desc=desc, text=value))

    _set_txxx("REPLAYGAIN_TRACK_GAIN", f"{gain_db:+.2f} dB")
    _set_txxx("REPLAYGAIN_TRACK_PEAK", f"{peak:.6f}")
    tags.save(str(path))


def _write_flac(path: Path, gain_db: float, peak: float) -> None:
    from mutagen.flac import FLAC

    audio = FLAC(str(path))
    audio["REPLAYGAIN_TRACK_GAIN"] = f"{gain_db:+.2f} dB"
    audio["REPLAYGAIN_TRACK_PEAK"] = f"{peak:.6f}"
    audio.save()


def _write_m4a(path: Path, gain_db: float, peak: float) -> None:
    from mutagen.mp4 import MP4, MP4FreeForm

    audio = MP4(str(path))
    if audio.tags is None:
        audio.add_tags()
    # iTunes-style freeform atoms
    audio.tags["----:com.apple.iTunes:REPLAYGAIN_TRACK_GAIN"] = [
        MP4FreeForm(f"{gain_db:+.2f} dB".encode())
    ]
    audio.tags["----:com.apple.iTunes:REPLAYGAIN_TRACK_PEAK"] = [
        MP4FreeForm(f"{peak:.6f}".encode())
    ]
    audio.save()


def _write_ogg(path: Path, gain_db: float, peak: float) -> None:
    try:
        from mutagen.oggopus import OggOpus
        audio = OggOpus(str(path))
    except Exception:
        from mutagen.oggvorbis import OggVorbis
        audio = OggVorbis(str(path))
    audio["REPLAYGAIN_TRACK_GAIN"] = [f"{gain_db:+.2f} dB"]
    audio["REPLAYGAIN_TRACK_PEAK"] = [f"{peak:.6f}"]
    audio.save()
