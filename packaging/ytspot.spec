# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the YTSpot Downloader Windows EXE.

Builds a one-folder distribution at ``dist/ytspot/`` containing
``ytspot.exe`` (GUI) plus every Qt/PySide6/qfluentwidgets resource
needed to run on a clean Windows machine with no Python installed.

Build by running ``scripts/build_windows.ps1`` from the repo root.
That script regenerates ``packaging/version_info.txt`` from
``version.py`` and copies bundled FFmpeg binaries (if present) into
``packaging/ffmpeg/`` before invoking PyInstaller.

This spec deliberately does not bundle Playwright browsers (~300 MB).
The user installs them once via ``scripts/install_playwright.ps1``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_submodules,
    copy_metadata,
)

# ── Paths ──────────────────────────────────────────────────────────────────
HERE = Path(SPECPATH).resolve()                 # packaging/
ROOT = HERE.parent                              # repo root

sys.path.insert(0, str(ROOT))                   # so version.py imports
from version import __version__, PRODUCT_NAME   # noqa: E402

# ── Hidden imports + data ──────────────────────────────────────────────────
# qfluentwidgets ships QSS / SVG resources via a generated Qt resource
# module loaded dynamically. PySide6 plugins (platforms, styles, etc.)
# are mostly auto-detected, but a few corner cases still need a nudge.

hiddenimports: list[str] = []
hiddenimports += collect_submodules('qfluentwidgets')
hiddenimports += collect_submodules('ytmusicapi')
hiddenimports += collect_submodules('mutagen')
# yt_dlp has a generated set of extractor modules; let PyInstaller's
# yt_dlp hook handle them when present, but force the top-level module
# in case the hook is missing on older PyInstaller versions.
hiddenimports += [
    'yt_dlp',
    'yt_dlp.utils',
    'syncedlyrics',
    'pyloudnorm',
    'soundfile',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont',
]

datas: list[tuple[str, str]] = []
datas += collect_data_files('qfluentwidgets')
datas += collect_data_files('ytmusicapi', includes=['locales/**/*'])
# yt_dlp ships extractor data; collect_data_files handles it.
datas += collect_data_files('yt_dlp')
# Distribution metadata for packages that read their own version via
# importlib.metadata. Avoids ``PackageNotFoundError`` at runtime.
for pkg in ('yt-dlp', 'mutagen', 'ytmusicapi', 'PySide6'):
    try:
        datas += copy_metadata(pkg)
    except Exception:
        # copy_metadata raises on dotted/normalised name mismatches.
        # Best-effort: silently skip; the EXE will fall back to
        # version='unknown' for any package that needs it.
        pass

# Bundled FFmpeg / ffprobe (LGPL build). The build script downloads
# them into packaging/ffmpeg/ before invoking PyInstaller; if the
# folder is absent we ship without them and the user gets the
# preflight warning at startup.
FFMPEG_DIR = HERE / 'ffmpeg'
binaries: list[tuple[str, str]] = []
if FFMPEG_DIR.exists():
    for name in ('ffmpeg.exe', 'ffprobe.exe'):
        src = FFMPEG_DIR / name
        if src.exists():
            # Place the binaries inside the EXE folder so
            # core.downloader can locate them next to ytspot.exe.
            binaries.append((str(src), '.'))

# Application icon — generated once by packaging/generate_icon.py and
# committed.
ICON = HERE / 'ytspot.ico'
icon_path = str(ICON) if ICON.exists() else None

# Generated VS_VERSIONINFO. The build script writes this file just
# before PyInstaller runs.
VERSION_FILE = HERE / 'version_info.txt'
version_file = str(VERSION_FILE) if VERSION_FILE.exists() else None

# ── Excludes ───────────────────────────────────────────────────────────────
# Pull these modules OUT of the bundle. They are dev-only or pulled in
# transitively but never used at runtime by the GUI.

excludes = [
    'tkinter',
    'pytest',
    'pytest_mock',
    'unittest',
    # numpy/scipy/matplotlib are not direct deps; if a transitive dep
    # pulls them, the EXE gets large for no reason.
    'matplotlib',
    'tests',
    'tools',
    'tools.audit',
]

# ── Analysis ───────────────────────────────────────────────────────────────

a = Analysis(
    [str(ROOT / 'main.py')],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# ── EXE ────────────────────────────────────────────────────────────────────

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ytspot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,           # UPX trips many AV scanners; not worth the size win.
    console=False,       # GUI app — no console window.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
    version=version_file,
)

# ── Second EXE: headless CLI sharing the same Analysis ─────────────────────
# Runs the same backend (DownloadOrchestrator, PlaylistParser, …) with
# the cli.py entry point. console=True so users get stdout/stderr.
# Reusing ``pyz`` means there is no second copy of the Python runtime —
# both EXEs share every bundled module.

cli_a = Analysis(
    [str(ROOT / 'cli.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
cli_pyz = PYZ(cli_a.pure)

cli_exe = EXE(
    cli_pyz,
    cli_a.scripts,
    [],
    exclude_binaries=True,
    name='ytspot-cli',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,        # CLI needs a console window.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
    version=version_file,
)

# ── COLLECT (one-folder dist with both EXEs) ───────────────────────────────

coll = COLLECT(
    exe,
    cli_exe,
    a.binaries,
    a.datas,
    cli_a.binaries,
    cli_a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ytspot',
)
