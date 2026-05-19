# Release Checklist — YTSpot Downloader Windows EXE

This is the manual smoke-test that must pass on a **clean Windows machine
without Python installed** before publishing a release. Automated tests
(`pytest`) catch regressions inside the codebase; only this checklist
catches packaging, bundling, and installer regressions.

## Pre-release

- [ ] `version.__version__` bumped (and the test in `tests/test_p0_gates.py::TestVersionConsistency` passes).
- [ ] `pyproject.toml` `version` matches.
- [ ] CHANGELOG / release notes drafted.
- [ ] `THIRD_PARTY_NOTICES.md` reviewed; the **REVIEW REQUIRED** items (Mutagen, PySide6-Fluent-Widgets) all resolved.
- [ ] LGPL FFmpeg + ffprobe placed in `packaging/ffmpeg/` (NOT the gyan.dev essentials GPL build).
- [ ] `git status` clean; no `.env`, secrets, local IDE files staged.
- [ ] `git ls-files | grep -E "(egg-info|\.pyc|build/|dist/)"` returns empty.

## Build

Run from the repo root in PowerShell:

```powershell
# Full build with bundled FFmpeg + tests + portable ZIP + checksums
pwsh scripts\build_windows.ps1

# Build the installer EXE on top of the portable folder
iscc packaging\ytspot.iss
```

Expected outputs in `dist/`:

- [ ] `dist/ytspot/ytspot.exe` (GUI)
- [ ] `dist/ytspot/ytspot-cli.exe` (CLI)
- [ ] `dist/ytspot/ffmpeg.exe`, `dist/ytspot/ffprobe.exe`
- [ ] `dist/ytspot-<version>-windows-portable.zip`
- [ ] `dist/ytspot-<version>-windows-setup.exe` (Inno Setup output)
- [ ] `dist/SHA256SUMS.txt`

## Clean-machine smoke test

Provision a fresh Windows 10/11 VM (no Python, no FFmpeg, no Playwright).
Copy `dist/ytspot-<version>-windows-portable.zip` to the VM.

### Cold launch

- [ ] Unzip the portable build; double-click `ytspot.exe`. App launches; main window is visible within ~5 seconds; no missing-DLL pop-ups.
- [ ] CLI smoke: in a console, `ytspot-cli.exe --version` prints `ytspot-cli <version>` and exits 0.
- [ ] CLI doctor: `ytspot-cli.exe --doctor` reports `FFmpeg: OK` (bundled), `Network: OK`, `Output directory: OK`, `Playwright: NOT INSTALLED` (expected — informational), and exits 0.
- [ ] EXE metadata: right-click `ytspot.exe` → Properties → Details: ProductName = "YTSpot Downloader", FileVersion = `<version>`, CompanyName = "Tauman Software", LegalCopyright present.
- [ ] App icon visible in Explorer thumbnail and in the taskbar.

### Functional smoke

Test each path end-to-end. Use a short, public domain test URL where possible.

- [ ] **YouTube single track**: paste a short YouTube URL → Fetch Info → Download Selected. File appears in `~/Downloads/YTSpot/` with embedded title/artist/thumbnail metadata.
- [ ] **YouTube playlist**: paste a short playlist URL → tracks load into queue → select all → download. Files land in a per-playlist subfolder.
- [ ] **YouTube Music search**: open Search tab → select platform "YouTube Music" → type a query → results appear in TRACK / ALBUM / ARTIST / PLAYLIST sections → click "Add to queue" → track downloads.
- [ ] **Spotify resolve**: paste a Spotify track URL → fetch info → track resolved to YouTube → download succeeds. (Requires Spotify proxy URL configured in Settings, or graceful "proxy not configured" error.)
- [ ] **Metadata embedding**: open a downloaded MP3 in Windows Media Player / VLC — title, artist, album, year, thumbnail all visible.
- [ ] **Duplicate detection**: re-download the same track. With `duplicate_action = "warn"` (default) a confirmation dialog appears; with `"skip"` the second download is silently skipped (verify history shows only one record).
- [ ] **History panel**: open History tab → see the previous downloads with the correct platform badge (youtube / ytmusic / spotify, not all "youtube").
- [ ] **Settings persistence**: change theme, language, output folder, max parallel → close app → reopen → settings preserved.
- [ ] **Hebrew RTL UI**: Settings → Language → Hebrew → restart app. Layout switches to right-to-left; navigation labels and all error messages are in Hebrew.
- [ ] **Update checker**: launch and wait ~10 seconds. The update worker queries `api.github.com/repos/cdtauman-projects/ytspot_downloader/releases/latest`. No banner = up-to-date (correct). A banner = the bumped version is older than the published release (also correct; resync `version.py`).

### Error & edge cases

- [ ] **Missing FFmpeg behaviour**: rename or delete `ffmpeg.exe` from the install folder. Relaunch. Preflight MessageBox warns about missing FFmpeg in English (or Hebrew if the language is set). The app still launches; downloads fail with a clear "FFmpeg not found" error rather than a yt-dlp stack trace.
- [ ] **No internet**: disconnect the VM from the network → relaunch. Preflight warns about no internet. App still opens. Manual download attempts fail with a clear "No internet connection" message.
- [ ] **Unwritable output directory**: in Settings, set output to `C:\Windows\System32\YTSpot` (or any folder the current user lacks write access to). Try to download. Preflight + the controller's writability check refuse with a "Cannot Write to Output Folder" MessageBox naming the offending path.
- [ ] **Invalid cookies file**: set `cookies_file` in `%APPDATA%\.ytspot\config.json` to a non-existent path. Relaunch. Preflight warns about invalid cookies. App still works for non-authenticated URLs.
- [ ] **Sign-in / Cookies wizard without Playwright**: click the "Sign in to YouTube 🔑" button. Clean MessageBox in Hebrew (or English) explains that Playwright Chromium is needed and points to `scripts/install_playwright.ps1`. **No crash.**

### Playwright install

- [ ] In the install folder, run `scripts/install_playwright.ps1`. Chromium downloads (~300 MB) to `%USERPROFILE%\AppData\Local\ms-playwright\`.
- [ ] Re-run `ytspot-cli.exe --doctor` → `Playwright: OK`.
- [ ] In the GUI, paste a Spotify artist URL → discography loads (uses Playwright scraper).
- [ ] Click "Sign in to YouTube 🔑" → headed Chromium opens → close it → app captures cookies.

## Installer smoke

- [ ] Run `dist/ytspot-<version>-windows-setup.exe` on a fresh VM. Installer launches in either English or Hebrew (the user can pick on first page).
- [ ] License page shows `THIRD_PARTY_NOTICES.md` content.
- [ ] Install to `%LOCALAPPDATA%\Programs\YTSpot Downloader` (lowest-privileges install).
- [ ] Start menu shortcut for YTSpot Downloader; one for `(CLI)`; one for `Install Playwright`; one for Uninstall.
- [ ] (Optional task) `Install Playwright Chromium (~300 MB)` runs after install when ticked.
- [ ] Launch from Start menu; app runs with the same bundled FFmpeg and EXE metadata as the portable build.
- [ ] Uninstall via `Settings → Apps`: every installed file under `{app}` is removed. `%APPDATA%\.ytspot\config.json` and the user's downloads SURVIVE the uninstall (verify by reinstalling and confirming history and settings restore).

## Antivirus / SmartScreen

- [ ] First-run on a fresh Windows install — does SmartScreen block the unsigned installer? If yes, document the "More info → Run anyway" step in the README, and plan to sign the EXE with an EV certificate for v1.1.
- [ ] Scan `dist/ytspot/ytspot.exe` with the user's preferred AV (Defender / Avast / etc.). Investigate any flag — PyInstaller binaries occasionally trip heuristic scanners. If a false positive is consistent, submit the EXE to the vendor for whitelisting.
- [ ] Confirm no `UPX` compression was used (build script sets `upx=False` precisely to avoid AV heuristics).

## Pre-publish

- [ ] `dist/SHA256SUMS.txt` checksums recorded in the release notes.
- [ ] Tag the release: `git tag v<version>` and push.
- [ ] Upload `ytspot-<version>-windows-portable.zip`, `ytspot-<version>-windows-setup.exe`, and `SHA256SUMS.txt` to GitHub Releases.
- [ ] Update banner test: bump `version.__version__` locally to `0.9.0`, run the app, confirm the update banner appears with the new release. Revert the version bump and rebuild.

## Post-publish

- [ ] Verify update checker now sees the new release on a clean install of the previous version.
- [ ] Watch GitHub issues for 24h for crash reports, install failures, or false-positive AV reports.
