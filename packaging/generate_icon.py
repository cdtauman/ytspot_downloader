"""Generate the YTSpot Downloader application icon.

Produces ``packaging/ytspot.ico`` containing every standard Windows
icon size (16, 24, 32, 48, 64, 128, 256). Run once and commit the
resulting .ico; the build script does not regenerate it on every
release because the artwork is stable.

Usage:
    python packaging/generate_icon.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "ytspot.ico"

# Sizes Windows Explorer and the taskbar expect in a multi-resolution
# ICO. Match the standard PyInstaller --icon set.
SIZES: tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)

# Amber accent matches ui.theme_manager.ACCENT_COLOR (#F5A623).
ACCENT = (245, 166, 35, 255)
BG = (24, 24, 27, 255)        # matches options_bar _BG
TEXT = (250, 250, 252, 255)


def _draw_one(size: int) -> Image.Image:
    """Draw a single-resolution PNG that becomes one frame of the ICO."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded-rectangle background with the accent as a 2 px ring.
    pad = max(1, size // 16)
    radius = max(2, size // 5)
    draw.rounded_rectangle(
        (pad, pad, size - pad, size - pad),
        radius=radius,
        fill=BG,
        outline=ACCENT,
        width=max(1, size // 32),
    )

    # "YS" monogram in the centre. Use a built-in font; size scales with
    # the icon size so the glyphs stay legible at every resolution.
    text = "YS"
    try:
        font = ImageFont.truetype("arialbd.ttf", int(size * 0.55))
    except OSError:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(
        ((size - tw) // 2 - bbox[0], (size - th) // 2 - bbox[1] - size // 24),
        text,
        font=font,
        fill=TEXT,
    )

    # Subtle amber underbar to echo the queue panel's accent line.
    bar_top = int(size * 0.78)
    bar_bot = int(size * 0.84)
    bar_x0 = int(size * 0.30)
    bar_x1 = int(size * 0.70)
    if bar_bot - bar_top >= 1:
        draw.rectangle((bar_x0, bar_top, bar_x1, bar_bot), fill=ACCENT)

    return img


def build(out_path: Path = OUT, sizes: Iterable[int] = SIZES) -> Path:
    """Write a multi-resolution ICO and return its path."""
    frames = [_draw_one(s) for s in sorted(set(sizes))]
    # Pillow's ICO writer accepts a list via append_images on the primary.
    primary = frames[-1]   # 256x256 = highest quality, used as the base
    out_path.parent.mkdir(parents=True, exist_ok=True)
    primary.save(
        out_path,
        format="ICO",
        sizes=[(f.width, f.height) for f in frames],
    )
    return out_path


if __name__ == "__main__":
    p = build()
    print(f"Wrote {p}  ({p.stat().st_size} bytes)")
