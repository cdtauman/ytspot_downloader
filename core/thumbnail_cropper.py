"""
core/thumbnail_cropper.py  –  Square thumbnail crop (Advanced Setting)
=======================================================================
After yt-dlp embeds a 16:9 YouTube thumbnail, this post-processor reads
the embedded art, crops it to a centred 1:1 square, and re-embeds it.

Implementation: reads the cover art bytes from the file, decodes with
Pillow, crops from the centre, re-encodes as JPEG, writes back.

Supported containers: MP3 (ID3 APIC), FLAC, M4A (covr).

This module is only called when AppConfig.square_thumbnails is True.
Zero GUI imports.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def crop_embedded_thumbnail(file_path: str) -> bool:
    """
    Read the cover art from file_path, crop to 1:1, and re-embed.

    Returns True on success, False if no art found or on failure.
    """
    try:
        from PIL import Image
    except ImportError:
        logger.warning("[ThumbnailCropper] Pillow not installed. "
                       "Run: pip install Pillow")
        return False

    path = Path(file_path)
    suffix = path.suffix.lower()

    try:
        if suffix == ".mp3":
            return _crop_mp3(path, Image)
        elif suffix == ".flac":
            return _crop_flac(path, Image)
        elif suffix in (".m4a", ".mp4", ".aac"):
            return _crop_m4a(path, Image)
        else:
            logger.debug("[ThumbnailCropper] Unsupported format: %s", suffix)
            return False
    except Exception as exc:
        logger.error("[ThumbnailCropper] Error cropping %s: %s", path.name, exc)
        return False


def embed_custom_thumbnail(file_path: str, url: str) -> bool:
    """Download an image from the given URL, crop to square, and embed it."""
    if not url.startswith("http"):
        return False
    try:
        from PIL import Image
        import urllib.request
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            img_bytes = resp.read()
    except Exception as exc:
        logger.error("[ThumbnailCropper] Failed to download %s: %s", url, exc)
        return False

    path = Path(file_path)
    suffix = path.suffix.lower()

    # Pass the fresh image bytes directly.
    try:
        cropped = _centre_crop(img_bytes, Image)
        logger.debug(f"[ThumbnailCropper] Cropped image to square ({len(img_bytes)} -> {len(cropped)} bytes)")
        if suffix == ".mp3":
            res = _inject_mp3_cover(path, cropped)
            return res
        elif suffix == ".flac":
            res = _inject_flac_cover(path, cropped)
            return res
        elif suffix in (".m4a", ".mp4", ".aac"):
            res = _inject_m4a_cover(path, cropped)
            return res
    except Exception as exc:
        logger.error("[ThumbnailCropper] Failed injecting custom thumb for %s: %s", path.name, exc)
    return False

def _centre_crop(img_bytes: bytes, Image) -> bytes:
    """Crop image bytes to a centred square and return JPEG bytes."""
    img = Image.open(io.BytesIO(img_bytes))
    w, h = img.size
    side = min(w, h)
    left   = (w - side) // 2
    top    = (h - side) // 2
    right  = left + side
    bottom = top  + side
    cropped = img.crop((left, top, right, bottom))
    buf = io.BytesIO()
    cropped.convert("RGB").save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _retry_access(action_fn, path: Path, max_retries: int = 5, delay: float = 1.2):
    """Helper to retry metadata access (load/save) when Windows file locks occur."""
    import time
    if not path.exists():
        logger.debug(f"[ThumbnailCropper] Skipping retry: file not found {path.name}")
        return None
        
    last_exc = None
    for i in range(max_retries):
        try:
            return action_fn()
        except (PermissionError, IOError, OSError, Exception) as exc:
            last_exc = exc
            if i < max_retries - 1:
                logger.warning(f"[ThumbnailCropper] File access blocked ({path.name}), retry {i+1}/{max_retries}...")
                time.sleep(delay * (i + 1))
    logger.error(f"[ThumbnailCropper] Failed after {max_retries} retries: {last_exc}")
    return None

def _inject_mp3_cover(path: Path, cropped: bytes) -> bool:
    from mutagen.id3 import ID3, APIC, ID3NoHeaderError
    def task():
        try:
            tags = ID3(str(path))
        except ID3NoHeaderError:
            return False
        tags.delall("APIC")
        tags.add(APIC(
            encoding=3, mime="image/jpeg", type=3, desc="", data=cropped
        ))
        tags.save(str(path), v2_version=3)
        return True
    
    res = _retry_access(task, path)
    return bool(res)

def _inject_flac_cover(path: Path, cropped: bytes) -> bool:
    from mutagen.flac import FLAC, Picture
    def task():
        audio = FLAC(str(path))
        audio.clear_pictures()
        new_pic = Picture()
        new_pic.type = 3
        new_pic.mime = "image/jpeg"
        new_pic.desc = "Front Cover"
        new_pic.data = cropped
        audio.add_picture(new_pic)
        audio.save()
        return True
    
    res = _retry_access(task, path)
    return bool(res)

def _inject_m4a_cover(path: Path, cropped: bytes) -> bool:
    from mutagen.mp4 import MP4, MP4Cover
    def task():
        audio = MP4(str(path))
        if audio.tags is None:
            audio.add_tags()
        audio.tags["covr"] = [MP4Cover(cropped, imageformat=MP4Cover.FORMAT_JPEG)]
        audio.save()
        return True
    
    res = _retry_access(task, path)
    return bool(res)

def _crop_mp3(path: Path, Image) -> bool:
    from mutagen.id3 import ID3, APIC, ID3NoHeaderError

    try:
        tags = ID3(str(path))
    except ID3NoHeaderError:
        return False

    apic_keys = [k for k in tags.keys() if k.startswith("APIC")]
    if not apic_keys:
        logger.debug("[ThumbnailCropper] No APIC tag in %s", path.name)
        return False

    key = apic_keys[0]
    apic = tags[key]
    cropped = _centre_crop(apic.data, Image)
    return _inject_mp3_cover(path, cropped)

def _crop_flac(path: Path, Image) -> bool:
    from mutagen.flac import FLAC, Picture

    audio = FLAC(str(path))
    pics = audio.pictures
    if not pics:
        return False

    for pic in pics:
        if pic.type == 3:   # Cover (front)
            cropped = _centre_crop(pic.data, Image)
            return _inject_flac_cover(path, cropped)
    return False

def _crop_m4a(path: Path, Image) -> bool:
    from mutagen.mp4 import MP4, MP4Cover

    audio = MP4(str(path))
    if audio.tags is None:
        return False

    covers = audio.tags.get("covr")
    if not covers:
        return False

    cropped = _centre_crop(bytes(covers[0]), Image)
    return _inject_m4a_cover(path, cropped)
