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
    apic: APIC = tags[key]
    cropped = _centre_crop(apic.data, Image)

    tags.delall("APIC")
    tags.add(APIC(
        encoding=3,
        mime="image/jpeg",
        type=3,           # Cover (front)
        desc="Cover",
        data=cropped,
    ))
    tags.save(str(path))
    logger.info("[ThumbnailCropper] Cropped APIC in %s", path.name)
    return True


def _crop_flac(path: Path, Image) -> bool:
    from mutagen.flac import FLAC, Picture

    audio = FLAC(str(path))
    pics = audio.pictures
    if not pics:
        return False

    new_pics: list[Picture] = []
    changed = False

    for pic in pics:
        if pic.type == 3:   # Cover (front)
            cropped = _centre_crop(pic.data, Image)
            new_pic = Picture()
            new_pic.type  = 3
            new_pic.mime  = "image/jpeg"
            new_pic.desc  = pic.desc
            new_pic.data  = cropped
            new_pics.append(new_pic)
            changed = True
        else:
            new_pics.append(pic)

    if changed:
        audio.clear_pictures()
        for p in new_pics:
            audio.add_picture(p)
        audio.save()
        logger.info("[ThumbnailCropper] Cropped FLAC picture in %s", path.name)

    return changed


def _crop_m4a(path: Path, Image) -> bool:
    from mutagen.mp4 import MP4, MP4Cover

    audio = MP4(str(path))
    if audio.tags is None:
        return False

    covers = audio.tags.get("covr")
    if not covers:
        return False

    new_covers: list[MP4Cover] = []
    for cover in covers:
        cropped = _centre_crop(bytes(cover), Image)
        new_covers.append(MP4Cover(cropped, imageformat=MP4Cover.FORMAT_JPEG))

    audio.tags["covr"] = new_covers
    audio.save()
    logger.info("[ThumbnailCropper] Cropped M4A cover in %s", path.name)
    return True
