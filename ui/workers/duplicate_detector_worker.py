"""
ui/workers/duplicate_detector_worker.py  –  Background duplicate audio file detector
======================================================================================
Scans a folder for duplicate audio files using two strategies:

  > 10 000 files → group by file size only         (fast, near-instant)
  ≤ 10 000 files → group by AUDIO-ONLY MD5 hash    (accurate, tag-change-safe)

Audio-only hashing
------------------
Files that share identical audio but differ only in their embedded cover art
(album art / APIC tag) are now correctly detected as duplicates.

The worker parses format-specific container headers to locate where the raw audio
stream begins and ends, then hashes ONLY those bytes — skipping ID3 tags, Vorbis
comments, cover-art blobs, and any other metadata:

  .mp3   — skips ID3v2 header at start of file (syncsafe size field);
            skips trailing ID3v1 tag (128-byte "TAG" footer) if present.
  .flac  — walks FLAC metadata-block chain ("fLaC" marker) and starts
            hashing from the first audio frame that follows.
  .m4a / .aac / .mp4
         — scans top-level atoms; hashes only the content of the
            "mdat" atom (raw compressed audio data).
  all other formats (.ogg, .wav, .opus, .wma …)
         — falls back to full-file hashing (metadata is a tiny fraction
            of these files' sizes, so false-negatives are rare).

Signals
-------
progress(int, int, str)      scanned_count, total_count, eta_string
finished(object, float, str) {key: [Path, …]}, elapsed_seconds, strategy_label
error(str)                   unrecoverable error message
"""

from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ui.i18n import t

_AUDIO_EXTS = frozenset({
    ".mp3", ".flac", ".m4a", ".ogg",
    ".wav", ".aac", ".opus", ".wma",
})


class DuplicateDetectorWorker(QThread):
    """
    QThread worker that finds duplicate audio files in a folder.

    Emits incremental progress with a live ETA, then emits the duplicate
    groups dict together with elapsed time and the strategy name used.
    """

    progress = Signal(int, int, str)      # done, total, eta_str
    finished = Signal(object, float, str) # groups dict, elapsed_sec, strategy
    error    = Signal(str)

    def __init__(self, folder: Path, recursive: bool, parent=None) -> None:
        super().__init__(parent)
        self._folder    = folder
        self._recursive = recursive
        self._cancel    = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        t0 = time.perf_counter()
        try:
            pattern = "**/*" if self._recursive else "*"
            all_files = [
                p for p in self._folder.glob(pattern)
                if p.is_file() and p.suffix.lower() in _AUDIO_EXTS
            ]

            total = len(all_files)
            if total == 0:
                self.finished.emit({}, time.perf_counter() - t0, "md5")
                return

            if total > 10_000:
                groups   = self._find_by_size(all_files, total, t0)
                strategy = "size"
            else:
                groups   = self._find_by_md5(all_files, total, t0)
                strategy = "md5"

            if self._cancel.is_set():
                return

            self.finished.emit(groups, time.perf_counter() - t0, strategy)

        except Exception as exc:
            self.error.emit(str(exc))

    # ── Grouping strategies ────────────────────────────────────────────────────

    def _find_by_size(self, files: list[Path], total: int, t0: float) -> dict:
        from collections import defaultdict
        size_map: dict[int, list[Path]] = defaultdict(list)

        for i, f in enumerate(files):
            if self._cancel.is_set():
                return {}
            try:
                size_map[f.stat().st_size].append(f)
            except OSError:
                pass
            if i % 200 == 0 or i == total - 1:
                self.progress.emit(i + 1, total, self._eta(i + 1, total, t0))

        return {k: v for k, v in size_map.items() if len(v) > 1}

    def _find_by_md5(self, files: list[Path], total: int, t0: float) -> dict:
        from collections import defaultdict
        hash_map: dict[str, list[Path]] = defaultdict(list)

        for i, f in enumerate(files):
            if self._cancel.is_set():
                return {}
            try:
                digest = self._audio_hash(f)
                if digest is not None:
                    hash_map[digest].append(f)
            except OSError:
                pass
            self.progress.emit(i + 1, total, self._eta(i + 1, total, t0))

        return {k: v for k, v in hash_map.items() if len(v) > 1}

    # ── Audio-only hashing ─────────────────────────────────────────────────────

    def _audio_hash(self, path: Path) -> str | None:
        """
        Hash only the raw audio stream bytes, ignoring embedded metadata and
        cover art so that files differing only in their album art are detected
        as duplicates.
        """
        suffix = path.suffix.lower()
        h      = hashlib.md5()

        with open(path, "rb") as fp:
            if suffix == ".mp3":
                start = self._mp3_audio_start(fp)
                end   = self._mp3_audio_end(fp)
            elif suffix == ".flac":
                start = self._flac_audio_start(fp)
                end   = None
            elif suffix in (".m4a", ".aac", ".mp4"):
                bounds = self._m4a_mdat_bounds(fp)
                start, end = bounds if bounds else (0, None)
            else:
                # Fallback: hash entire file
                start, end = 0, None

            fp.seek(start)
            remaining = (end - start) if end is not None else None

            while True:
                if self._cancel.is_set():
                    return None
                to_read = min(8192, remaining) if remaining is not None else 8192
                chunk   = fp.read(to_read)
                if not chunk:
                    break
                h.update(chunk)
                if remaining is not None:
                    remaining -= len(chunk)
                    if remaining <= 0:
                        break

        return h.hexdigest()

    # ── Format-specific offset parsers ─────────────────────────────────────────

    @staticmethod
    def _mp3_audio_start(fp) -> int:
        """
        Return the byte offset where MP3 audio frames begin.

        ID3v2 tag sits at the very start of the file.  Its size is stored in
        bytes 6-9 as a 4-byte syncsafe integer (each byte contributes 7 bits,
        MSB is always 0).  The fixed 10-byte header is not included in this
        size field, so audio_start = 10 + syncsafe_size.
        """
        fp.seek(0)
        header = fp.read(10)
        if len(header) < 10 or header[:3] != b"ID3":
            return 0
        size = (
            (header[6] & 0x7F) << 21 |
            (header[7] & 0x7F) << 14 |
            (header[8] & 0x7F) << 7  |
            (header[9] & 0x7F)
        )
        return 10 + size

    @staticmethod
    def _mp3_audio_end(fp) -> int | None:
        """
        Return the byte offset of a trailing ID3v1 tag if one is present,
        or None if the audio runs to end-of-file.

        ID3v1 is always exactly 128 bytes, positioned at the very end of the
        file, and starts with the three ASCII bytes 'TAG'.
        """
        try:
            fp.seek(-128, 2)          # 128 bytes before EOF
            if fp.read(3) == b"TAG":
                fp.seek(0, 2)         # go to EOF to read total size
                return fp.tell() - 128
        except OSError:
            pass
        return None

    @staticmethod
    def _flac_audio_start(fp) -> int:
        """
        Return the byte offset where FLAC audio frame data begins.

        A FLAC file starts with the 4-byte marker "fLaC" followed by one or
        more METADATA_BLOCK structures.  Each block has a 4-byte header:
          - bit 7     : 1 if this is the last metadata block
          - bits 6-0  : block type (STREAMINFO=0, PICTURE=6, …)
          - bytes 1-3 : 24-bit block data length (big-endian)
        Audio frames immediately follow the final metadata block.
        """
        fp.seek(0)
        if fp.read(4) != b"fLaC":
            return 0
        offset = 4
        while True:
            block_header = fp.read(4)
            if len(block_header) < 4:
                break
            is_last = bool(block_header[0] & 0x80)
            blk_len = (block_header[1] << 16) | (block_header[2] << 8) | block_header[3]
            offset += 4 + blk_len
            if is_last:
                break
            fp.seek(offset)
        return offset

    @staticmethod
    def _m4a_mdat_bounds(fp) -> tuple[int, int] | None:
        """
        Scan top-level MP4/M4A atoms and return (content_start, content_end)
        for the first 'mdat' atom found (raw compressed audio data).

        Each atom begins with:
          - 4 bytes: atom size in bytes (including the 8-byte header)
          - 4 bytes: atom type (FourCC, e.g. b'ftyp', b'moov', b'mdat')
        The content of 'mdat' is the audio bitstream with no tags mixed in.
        """
        fp.seek(0)
        while True:
            size_bytes = fp.read(4)
            type_bytes = fp.read(4)
            if len(size_bytes) < 4 or len(type_bytes) < 4:
                return None
            atom_size = int.from_bytes(size_bytes, "big")
            if atom_size < 8:
                return None
            if type_bytes == b"mdat":
                content_start = fp.tell()                   # right after 8-byte header
                content_end   = content_start + atom_size - 8
                return (content_start, content_end)
            fp.seek(atom_size - 8, 1)                       # skip to next atom

    # ── ETA helper ─────────────────────────────────────────────────────────────

    @staticmethod
    def _eta(done: int, total: int, t0: float) -> str:
        if done == 0:
            return t("dup_calculating")
        elapsed   = time.perf_counter() - t0
        remaining = (total - done) / (done / elapsed)
        if remaining < 60:
            return f"~{int(remaining)}s"
        mins, secs = divmod(int(remaining), 60)
        return f"~{mins}m{secs:02d}s"
