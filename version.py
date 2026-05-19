"""Single source of truth for the YTSpot Downloader application version.

Every module that needs to surface a version string should import from
here. The packaging build script also reads `__version__` directly so
the EXE VS_VERSIONINFO and Inno Setup metadata stay in sync.

A drift guard lives in ``tests/test_p0_gates.py::TestVersionConsistency``
that fails if any of the following diverge:
  * ``version.__version__``
  * ``pyproject.toml`` [project] version
  * ``core.update_checker.CURRENT_VERSION``
  * the Qt application version set in ``main.py``

Bump this single constant when cutting a new release. The audit branch
adds a `release.bump_version` helper script in v1.1.
"""

from __future__ import annotations

__version__: str = "1.0.0"

# Convenience tuple form for code that needs to compare versions
# numerically without parsing the string.
VERSION_INFO: tuple[int, int, int] = (1, 0, 0)

# Stable name used in product metadata (EXE description, Qt
# setApplicationName, MusicBrainz User-Agent, etc.).
PRODUCT_NAME: str = "YTSpot Downloader"

# Vendor / publisher string for Windows EXE metadata and Inno Setup.
COMPANY_NAME: str = "Tauman Software"

# Copyright line used in the EXE version-info block. Year is updated
# alongside __version__ on each release.
COPYRIGHT: str = "Copyright (c) 2026 Tauman Software"
