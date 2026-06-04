# -*- mode: python ; coding: utf-8 -*-
"""Cross-platform PyInstaller spec for YTSpot Downloader.

Windows
-------
Builds a one-folder distribution at ``dist/ytspot/`` containing
``ytspot.exe`` (GUI) + ``ytspot-cli.exe`` plus every Qt/PySide6/
qfluentwidgets resource needed to run on a clean Windows machine.
Driven by ``scripts/build_windows.ps1`` (regenerates
``packaging/version_info.txt`` first).

macOS
-----
Builds ``dist/YTSpot.app`` (a windowed .app bundle) with the headless
CLI binary alongside the GUI inside ``Contents/MacOS``. Driven by
``scripts/build_macos.sh`` (which then wraps the .app in a DMG).
Targets the host architecture (arm64 on Apple Silicon runners).

Both platforms
--------------
Staged FFmpeg binaries in ``packaging/ffmpeg/`` are bundled when
present, and Playwright Chromium (~300-400 MB) is bundled for fully
offline execution.
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

# ── Platform ───────────────────────────────────────────────────────────────
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

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

# Bundled Playwright Chromium browser (~300-400 MB).
# Windows ONLY: Chromium on Windows is a flat folder of DLLs/EXEs that
# PyInstaller can collect and codesign without issues.
#
# macOS: Chromium is a full nested .app bundle (Google Chrome for Testing.app)
# inside our bundle. PyInstaller 6.x tries to re-codesign every collected
# binary, which fails on nested .app bundles with
# "bundle format unrecognized, invalid, or unsuitable".
# Solution: don't embed Chromium in the macOS bundle. Instead, main.py/cli.py
# on macOS will NOT override PLAYWRIGHT_BROWSERS_PATH, so Playwright falls back
# to the user's ~/Library/Caches/ms-playwright. The macOS workflow installs
# Chromium there with `playwright install chromium` so it's always present.
if IS_WIN:
    _local_app_data = os.environ.get('LOCALAPPDATA') or os.path.join(
        os.environ.get('USERPROFILE', ''), 'AppData', 'Local'
    )
    ms_playwright_dir = Path(_local_app_data) / 'ms-playwright'
    if ms_playwright_dir.exists():
        for p_dir in ms_playwright_dir.iterdir():
            if p_dir.is_dir() and p_dir.name != '.links':
                datas.append((str(p_dir), f"ms-playwright/{p_dir.name}"))
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

# Bundled FFmpeg / ffprobe (LGPL build). Stage them in
# packaging/ffmpeg/ before invoking PyInstaller; if the folder is
# absent we ship without them and the user gets the preflight warning
# at startup. Binary names differ by platform (no .exe on macOS).
# utils.paths.get_bundled_ffmpeg_dir() knows every place PyInstaller
# may drop them inside a .app bundle.
FFMPEG_DIR = HERE / 'ffmpeg'
_ffmpeg_names = ('ffmpeg.exe', 'ffprobe.exe') if IS_WIN else ('ffmpeg', 'ffprobe')
binaries: list[tuple[str, str]] = []
if FFMPEG_DIR.exists():
    for name in _ffmpeg_names:
        src = FFMPEG_DIR / name
        if src.exists():
            # Place the binaries inside the app folder so the runtime
            # can locate them next to the executable.
            binaries.append((str(src), '.'))

# Application icon — generated once by packaging/generate_icon.py and
# committed. Windows uses .ico, macOS uses .icns.
ICON = HERE / ('ytspot.ico' if IS_WIN else 'ytspot.icns')
icon_path = str(ICON) if ICON.exists() else None

# Generated VS_VERSIONINFO (Windows-only). The build script writes this
# file just before PyInstaller runs; it is meaningless on macOS.
VERSION_FILE = HERE / 'version_info.txt'
version_file = str(VERSION_FILE) if (IS_WIN and VERSION_FILE.exists()) else None

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

# ── COLLECT (one-folder dist with both executables) ────────────────────────
# Windows  → dist/ytspot/   (ytspot.exe + ytspot-cli.exe)
# macOS    → dist/ytspot/   then wrapped into dist/YTSpot.app by BUNDLE
#
# Note: On macOS, we use codesign_identity=None to skip code-signing binaries
# (which would fail on Playwright Chromium bundles that are already complex).
# We'll ad-hoc sign the final .app bundle after PyInstaller finishes instead.

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
    codesign_identity=None if IS_MAC else None,  # Skip signing Playwright et al.
)

# ── BUNDLE (macOS .app) ────────────────────────────────────────────────────
# Wrap the collected folder into a proper .app. The CLI binary travels
# inside Contents/MacOS so power users can still invoke
# ``YTSpot.app/Contents/MacOS/ytspot-cli``.
if IS_MAC:
    app = BUNDLE(
        coll,
        name='YTSpot.app',
        icon=icon_path,
        bundle_identifier='com.taumansoftware.ytspot',
        version=__version__,
        info_plist={
            'CFBundleName': PRODUCT_NAME,
            'CFBundleDisplayName': PRODUCT_NAME,
            'CFBundleShortVersionString': __version__,
            'CFBundleVersion': __version__,
            'NSHighResolutionCapable': True,
            # The app uses Qt's own dark/light handling, so allow the
            # system appearance instead of forcing legacy Aqua.
            'NSRequiresAquaSystemAppearance': False,
            # Minimum supported macOS (Big Sur — first Apple Silicon OS).
            'LSMinimumSystemVersion': '11.0',
            # No special hardware/entitlement claims; this is a plain
            # GUI download utility.
            'LSApplicationCategoryType': 'public.app-category.utilities',
        },
    )
