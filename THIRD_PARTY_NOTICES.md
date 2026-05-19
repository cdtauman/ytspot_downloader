# Third-Party Notices

YTSpot Downloader is distributed as a Windows binary that bundles or
links to several open-source projects. This file lists each one, its
license, and any commercial-distribution considerations the project
maintainer should review with legal counsel before shipping a paid
release.

This file is **informational**. It is not legal advice. Two of the
dependencies (Mutagen, PySide6-Fluent-Widgets) carry copyleft licenses
that may require either dynamic linking, source disclosure, or a
commercial-license purchase depending on how the EXE is distributed.
Items marked **REVIEW REQUIRED** are flagged for that reason.

Version reference: YTSpot Downloader `1.0.0` (see [`version.py`](version.py)).

---

## Bundled binaries (shipped inside the Windows installer)

### FFmpeg / ffprobe — LGPL v2.1 or later

Used by yt-dlp (as a post-processor for format conversion, audio
extraction, thumbnail embedding, SponsorBlock chapter removal) and by
`core/hls_downloader.py` (direct HLS / DASH download).

The Windows EXE bundles the **LGPL-licensed** FFmpeg build only.
The release build script (`scripts/build_windows.ps1 -RequireBundledFfmpeg`)
fails unless the maintainer has staged `ffmpeg.exe` and `ffprobe.exe`
manually. It does not auto-download FFmpeg, so a wrong license cannot
ship by accident.

| Field | Value |
|---|---|
| Project | FFmpeg |
| License | LGPL v2.1 or later (some optional components are GPL — they are NOT included in the LGPL build) |
| Source | https://ffmpeg.org/ |
| LGPL compliance | The full LGPL text is reproduced below. The bundled binaries are unmodified; users can replace them with their own LGPL build by overwriting `ffmpeg.exe` / `ffprobe.exe` in the install folder. |
| Action required | Distribute the unmodified LGPL build, ship the LGPL v2.1 text in the installer (Inno Setup `LicenseFile` already includes this notices file). |

Get the LGPL build from a trusted mirror, e.g. the BtbN
[FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds) project (look
for a `*-lgpl*-shared` artifact). The gyan.dev "essentials" build is
GPL and must NOT be used for a commercial release.

---

## Runtime Python dependencies

Each row lists the upstream license and whether commercial review is
needed. "Bundled" means PyInstaller copies the package's compiled
code into the EXE; the legal effect of bundling vs. importing varies
by license.

| Dependency | License | Bundled by EXE | Note |
|---|---|---|---|
| yt-dlp[default] | Unlicense (public domain) | yes | Permissive, no obligations. |
| yt-dlp-ejs | Unlicense | yes | Same. |
| ffmpeg-python | Apache 2.0 | yes | Pure-Python bindings; only the bundled FFmpeg binary has the LGPL/GPL concern. |
| moviepy | MIT | yes | |
| pyloudnorm | MIT | yes | |
| soundfile | BSD-3-Clause | yes | |
| **mutagen** | **GPL v2.0 or later** | yes | **REVIEW REQUIRED** — strong copyleft. The Python ecosystem commonly treats `import` as runtime use rather than linking, but a paid closed-source distribution should confirm with legal counsel. Alternative: vendorise a smaller MIT-licensed tag library (e.g. `tinytag` for reads, custom writes). |
| syncedlyrics | MIT | yes | Disabled by default. |
| **PySide6** | **LGPL v3** (with Qt commercial alternative) | yes | LGPL is satisfied by Qt's dynamic-link model + the LGPL v3 text in this file. PySide6 wheels are distributed under LGPL v3. No commercial Qt license is required for this usage. |
| **PySide6-Fluent-Widgets** | **GPL v3 / Commercial dual-license** | yes | **REVIEW REQUIRED** — the community version is GPL v3. The author sells a commercial license at https://qfluentwidgets.com/pages/pro. For a commercial closed-source EXE distribution either (a) acquire the commercial license, (b) release the entire YTSpot source under GPL v3, or (c) replace the dependency with a permissive Qt theme. |
| PySideSix-Frameless-Window | LGPL v3 | yes, transitively via PySide6-Fluent-Widgets | Transitive dependency of Fluent Widgets; not imported directly by this app. Treat like other LGPL v3 Qt-adjacent components: ship the LGPL v3 text and preserve user replaceability of the installed files. |
| requests | Apache 2.0 | yes | |
| httpx | BSD-3-Clause | yes | |
| beautifulsoup4 | MIT | yes | |
| lxml | BSD-3-Clause | yes | Includes libxml2 / libxslt (MIT / similar). |
| ytmusicapi | MIT | yes | |
| Pillow | HPND (MIT-style) | yes | |
| python-dotenv | BSD-3-Clause | yes | |
| certifi | MPL 2.0 | yes | File-level copyleft; satisfied by shipping unmodified. |
| keyboard | MIT | yes | Optional — graceful fallback when missing. |
| playwright | Apache 2.0 | yes | Python bindings only. Browser binaries are NOT bundled (~300 MB). User installs them via `scripts/install_playwright.ps1`. |
| Playwright Chromium browsers | BSD-3-Clause (Chromium) + several others | no (installed separately) | When the user runs `playwright install chromium`, the browser is downloaded from Microsoft's CDN under Chromium's license. YTSpot does not redistribute it. |

---

## Public-API endpoints used at runtime

These are network services queried by the app. Their terms of service
apply to the end-user, not the YTSpot binary, but maintainers should
be aware:

| Endpoint | Purpose | Notes |
|---|---|---|
| `https://api.github.com/repos/cdtauman-projects/ytspot_downloader/releases/latest` | Update checker | Rate-limited to 60 req/hour for unauthenticated clients; called once at startup. |
| `https://musicbrainz.org/ws/2/...` | MusicBrainz tag enrichment | Public API; the User-Agent identifies the app per MB policy. Throttled to 1 req/sec by the client. |
| YouTube web + ytmusic web | Search / playlist / channel scraping | Subject to YouTube's Terms of Service. The user is responsible for downloading only content they have the rights to access. |
| `https://open.spotify.com/...` + optional self-hosted proxy | Spotify metadata resolution | Spotify metadata is fetched read-only; downloads use yt-dlp against the matched YouTube source, not the Spotify DRM stream. The user must comply with Spotify's Terms of Service for any data they collect. |

---

## License-text appendix

The full text of the licenses referenced above is available from the
canonical sources:

- **LGPL v2.1**: https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt
- **LGPL v3**:   https://www.gnu.org/licenses/lgpl-3.0.txt
- **GPL v2**:    https://www.gnu.org/licenses/old-licenses/gpl-2.0.txt
- **GPL v3**:    https://www.gnu.org/licenses/gpl-3.0.txt
- **Apache 2.0**: https://www.apache.org/licenses/LICENSE-2.0.txt
- **MIT**:        https://opensource.org/licenses/MIT
- **BSD-3-Clause**: https://opensource.org/licenses/BSD-3-Clause
- **MPL 2.0**:    https://www.mozilla.org/en-US/MPL/2.0/
- **HPND**:       https://opensource.org/licenses/HPND
- **Unlicense**:  https://unlicense.org/

For an LGPL-compliant offline distribution, copy the LGPL v2.1 text
into the installer's `LicenseFile`. Inno Setup currently uses this
file as the license; consider concatenating the LGPL text into a
single `LICENSES.md` before final release.

---

## Pre-release checklist for the project maintainer

Before publishing the first paid release, confirm each of the
following with counsel:

- [ ] FFmpeg binaries bundled are confirmed LGPL (NOT gyan.dev essentials GPL).
- [ ] LGPL v2.1 / LGPL v3 license texts are accessible to the end user (bundle into installer or link from the About dialog).
- [ ] Mutagen GPL obligations addressed: either commercial license, source-release, or replacement library.
- [ ] PySide6-Fluent-Widgets commercial license acquired OR app open-sourced under GPL v3.
- [ ] User-facing terms of service / EULA drafted for the EXE distribution.
- [ ] Privacy notice covers: clipboard monitor (optional), cookies file reading, history database location.
