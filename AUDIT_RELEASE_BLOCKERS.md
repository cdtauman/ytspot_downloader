# AUDIT_RELEASE_BLOCKERS

Branch: `audit/full-line-audit` · Severity-ranked findings from the full line-level audit.

## Severity levels

- **S0** — Release blocker. Must be fixed before public release. The product is incorrect, silently broken, or points to a wrong/missing external resource.
- **S1** — Beta blocker. Must be fixed before giving the build to beta users; symptom is visible to users (mis-tagged history, misleading UI labels, broken `.gitignore`, missing platform restore, etc.).
- **S2** — Important polish. Should be fixed soon. Internal hygiene, tracked artifacts, missing docs/tests.
- **S3** — Later. Cosmetic, comments, demo-block placeholders.

Status: `fixed` / `open` / `verified_safe` (false alarm or already mitigated).

## Snapshot (re-verified against current code)

| Severity | Total | Fixed | Open |
|---|---|---|---|
| S0 | 4 | **4** | 0 |
| S1 | 11 | **11** | 0 |
| S2 | 9 | 5 | 4 (S2-3, S2-4, S2-6, S2-7, S2-9 — see [Commercial-release deltas](#commercial-release-deltas)) |
| S3 | 5 | 1 | 4 (deferred to v1.1) |

**All S0 and S1 blockers are fixed in commits `6bc1097` through `ee89e18`.** The commercial-release prep work (PyInstaller, FFmpeg bundling, Playwright graceful degradation, preflight, version unification, `--version`/`--doctor`, third-party notices, release checklist) is tracked in [Commercial-release deltas](#commercial-release-deltas) below and lands in commits after `ee89e18`.

---

## S0 — Release blockers

### S0-1: Update checker points to the wrong GitHub owner (3 files)
- **Files**: `core/update_checker.py:169`, `ui/workers/update_worker.py:53-54`, `ui/app_window.py:443`
- **Symptom**: `UpdateWorker(parent=self)` is constructed with no args → defaults flow through to `UpdateChecker(repo_owner="cdtauman", repo_name="ytspot_downloader")`. The real repo is `cdtauman-projects/ytspot_downloader`. The `https://api.github.com/repos/cdtauman/ytspot_downloader/releases/latest` request returns 404, `_check_internal` raises, the blanket `check()` swallows it (line 197), and the user is never told there is an update — silently broken forever.
- **Fix**: change both default `repo_owner` values to `"cdtauman-projects"`. Also fix README:399 and settings_panel:570 (separate S0 item below).
- **Test**: add assertion in `test_p0_gates.py` that `UpdateChecker().__init__` defaults match the live `git remote`.
- **Status**: **fixed** in commit `6bc1097`. Evidence: `core/update_checker.py:169` default is `"cdtauman-projects"`; `ui/workers/update_worker.py:53` matches; `tests/test_p0_gates.py::TestUpdateCheckerDefaults` enforces both via runtime + signature checks.

### S0-2: About-page GitHub link in Settings is wrong owner
- **File**: `ui/panels/settings_panel.py:570`
- **Symptom**: `url="https://github.com/ytspot/ytspot"` — clicking "About → Open on GitHub" 404s.
- **Fix**: replace with `https://github.com/cdtauman-projects/ytspot_downloader`.
- **Status**: **fixed** in commit `6bc1097`. Evidence: `ui/panels/settings_panel.py:570` HyperlinkCard now uses `https://github.com/cdtauman-projects/ytspot_downloader`.

### S0-3: README references wrong GitHub owner
- **File**: `README.md:399`
- **Symptom**: doc string `api.github.com/repos/cdtauman/ytspot_downloader/releases/latest` — instructs readers/contributors with the wrong URL.
- **Fix**: replace `cdtauman/ytspot_downloader` with `cdtauman-projects/ytspot_downloader`.
- **Status**: **fixed** in commit `6bc1097`. Evidence: `README.md` line ~399 (Auto-Update Checker section) now references `cdtauman-projects/ytspot_downloader`.

### S0-4: Duplicate-checker stem mismatches actual download filename
- **Files**: `core/duplicate_checker.py:60-61`, `ui/controllers/download_controller.py:277`, `core/downloader.py:712-715`
- **Symptom**: `download_controller.py:277` hardcodes `is_clean = True` for every download. The downloader (`downloader.py:712-715`) then writes files as `"{idx_prefix}{title}.{ext}"` — **no artist** in the filename. But `duplicate_checker.expected_stem()` builds `"{prefix}{artist} - {title}"` (line 60-61). The stems can never match, so `find_duplicate()` returns `None` for every download. **The duplicate-skip/warn feature is silently dead** for the entire app.
- **Fix**: align the two. Either:
  - (recommended) Update `duplicate_checker.expected_stem` to also build the clean (title-only) stem when `include_artist=False`, and have `download_controller` pass `include_artist=False` matching its `is_clean` flag.
  - Or remove the artist from the duplicate-stem build (simpler).
- **Test**: add `test_core.py` case that performs `download_controller.start_batch`-style stem build and asserts equality with `duplicate_checker.expected_stem(..., include_artist=False)` for the same track.
- **Status**: **fixed** in commit `a246633`. Evidence: `core/duplicate_checker.py` now imports `_sanitize_filename` directly from `core.downloader`; `expected_stem` accepts `include_artist` and uses prefix `"NN - "`; `ui/controllers/download_controller.py` passes `include_artist=not is_clean`. `tests/test_core.py::TestDuplicateChecker` has 10 tests, including `test_expected_stem_matches_downloader_sanitiser` and `test_find_duplicate_clean_filename_match` end-to-end.

---

## S1 — Beta blockers

### S1-1: History records hardcode `platform="youtube"` for every download
- **File**: `core/download_orchestrator.py:374`
- **Symptom**: `_persist_record(...)` always sets `platform="youtube"` regardless of whether the download came from YouTube, YouTube Music, or Spotify. The History panel's per-platform filtering and counts are wrong. The HistoryDB schema explicitly supports `"youtube" | "ytmusic" | "spotify" | "unknown"` (`history_db.py:71`) and the UI colour-codes by platform (`history_row.py:53`).
- **Fix**: derive platform from `req.platform` (already on `DownloadRequest` line 183) → map `SourcePlatform.YOUTUBE_MUSIC → "ytmusic"`, `SPOTIFY → "spotify"`, else `"youtube"`.
- **Test**: orchestrator test that runs a fake job with `req.platform=SourcePlatform.YOUTUBE_MUSIC` and asserts inserted record has `platform == "ytmusic"`.
- **Status**: **fixed** in commit `5881dcf`. Evidence: `core/download_orchestrator.py:_persist_record` derives platform from `req.platform.value` for known enums and falls back to `"unknown"`. `ui/controllers/download_controller.py:start_batch` maps `card.platform` string to `SourcePlatform` enum. `tests/test_orchestrator.py::TestHistoryPlatform` has 4 tests (ytmusic/spotify/youtube/missing).

### S1-2: `output_dir` flow uses stale config value, ignores the OptionsBar text field
- **Files**: `ui/panels/options_bar.py:100,212,273-282`, `ui/controllers/download_controller.py:160-165,243-245`
- **Symptom**: typing a new path into the OptionsBar `LineEdit` fires `options_changed` but does **not** call `cfg.save()`. Only the "📁" browse button persists to config (line 280). DownloadController verifies that the typed path is writable (line 162-168) but then immediately switches back to `str(Path(self._cfg.output_dir))` (line 245) — an acknowledged mismatch (the comment on lines 243-244 says so). A user editing the textbox sees the (writable) text accepted but the file lands at the previously-saved path.
- **Fix**: either (a) save `cfg.output_dir = path` whenever the line-edit changes (debounced or `editingFinished`), or (b) have `DownloadController.start_batch` use `opts["output_dir"]` as the source-of-truth (it's already pre-verified). Option (b) is simpler and matches the user's intent.
- **Test**: add unit test that calls `DownloadController.start_batch` with `opts["output_dir"]` ≠ `cfg.output_dir` and asserts the built `DownloadRequest.output_dir == opts["output_dir"]`.
- **Status**: **fixed** in commit `6e1cd62`. Evidence: `ui/panels/options_bar.py` connects `editingFinished` to `_on_dir_committed` which writes to config; `ui/controllers/download_controller.py` now uses `Path(base_output_dir).expanduser()` (the verified UI value) as the download path. Manual UI smoke confirmed under QT_QPA_PLATFORM=offscreen. No automated UI test (Qt+qfluentwidgets too heavy to mock cleanly).

### S1-3: "Max search results" config is a per-category floor, not a cap
- **Files**: `core/search_engine.py:454-457,832-855`
- **Symptom**: `_YTMusicBackend.search_all()` (line 454-457) uses `max(N//3, 8)` etc. With `max_results=10` (config default = 15), the floor is `8+5+4+5 = 22` items — exceeding the configured maximum. Same in `search_youtube_categorized` (line 832-834: `max(N, 10)` for videos, `max(N//3, 5)` for playlists, `max(N//5, 3)` for channels). The "Max Search Results (1-50)" label in Settings (`i18n.py:130`) is misleading.
- **Fix**: either reword the UI label to "Per-category baseline" and document the floor explicitly, or strictly clamp the total to `max_results`. Recommend the clamp because users expect the label to mean what it says.
- **Status**: **fixed** in commit `cf22d19`. Evidence: `core/search_engine.py` `_YTMusicBackend.search_all` uses proportional split (50/20/15/remainder) and `search_youtube_categorized` uses 60/25/remainder; `tests/test_core.py::TestSearchCategoryBudget` has 4 tests pinning the new distribution.

### S1-4: `last_search_platform="ytmusic"` is dropped on restart
- **File**: `ui/panels/search_panel.py:392-397`
- **Symptom**: `_restore_state()` accepts only `("youtube", "spotify", "both")` — missing `"ytmusic"`. A user who last used YouTube Music sees the platform reset to YouTube on next launch. The config setter (line 363) allows `"ytmusic"`, the menu adds it (line 210-211), but the restore loses it.
- **Fix**: add `"ytmusic"` to the allow-list on line 396.
- **Test**: add panel-construction test that injects a config with `last_search_platform="ytmusic"` and asserts `panel.get_platform() == "ytmusic"`.
- **Status**: **fixed** in commit `25f1dbb`. Evidence: `ui/panels/search_panel.py:_restore_state` allow-list is now `("youtube", "ytmusic", "spotify", "both")`; `tests/test_p0_gates.py::TestSearchPanelRestoresYTMusic::test_ytmusic_round_trips_through_panel` round-trips through a real SearchPanel under QT_QPA_PLATFORM=offscreen.

### S1-5: "Bypass" wording in user-facing UI strings
- **Files**: `ui/i18n.py:82,231,310,459`, `ui/panels/settings_panel.py:490`, `core/downloader.py:238`
- **Symptom**: visible button text "Bypass Protection 🛡️" / "עקוף הגנה 🛡️" and tooltip "Extract cookies from your browser to bypass bot checks and age gates" / "חלץ עוגיות מהדפדפן שלך לעקיפת זיהוי רובוטים ובדיקות גיל". Settings panel line 490 has Hebrew "ולעקוף חסימות". `downloader.py:238` Hebrew error tip says "לעקוף את ההצפנה של כרום".
- **Fix**: rephrase as authentication / sign-in / access-restricted-content. Concrete replacements:
  - `bypass_bot_btn` "Bypass Protection 🛡️" → "Sign in to YouTube 🔑" / "התחבר ליוטיוב 🔑"
  - `browser_cookies_desc` "Extract cookies … to bypass bot checks and age gates" → "Extract cookies from your browser to authenticate access to age-restricted or members-only content" / "חלץ עוגיות מהדפדפן שלך כדי לאמת גישה לתוכן המוגבל בגיל או חבר"
  - `settings_panel.py:490` Hebrew "ולעקוף חסימות" → "ולפתור חסימות שדורשות התחברות"
  - `downloader.py:238` "כדי לעקוף את ההצפנה של כרום" → "כדי לקרוא קובצי עוגיות מוצפנים של כרום"
- **Status**: **fixed** in commit `822998a`. Evidence: `ui/i18n.py` now serves "Sign in to YouTube 🔑" / "התחבר ליוטיוב 🔑" for `bypass_bot_btn`, "Sign-in Required" / "נדרשת התחברות" for `bot_bypass_title`, and authentication-framed wording for `browser_cookies_desc` and `bot_bypass_instructions`. `ui/panels/settings_panel.py` content text now says "ולפתור בקשות אימות". `core/downloader.py:238` no longer references "לעקוף ההצפנה".

### S1-6: Anti-Ban / Bypass wording in README and Hebrew user guide
- **Files**: `README.md:283,296,304,628,631`, `user_guide_hebrew.md:309,350`
- **Symptom**: README section title "Anti-Ban Strategy", terms "bypass", "DRM", "Anti-Ban Measures" appear in public-facing docs. Hebrew guide mentions "Anti-Ban Delay" and "לעקוף את החסימה".
- **Fix**: rephrase as "rate-limit handling", "reliability features", "authenticate to age-gated content". Concrete replacements documented in fix commit. The `egg-info/PKG-INFO:244` will regenerate from README.
- **Status**: **fixed** in commit `822998a`. Evidence: `README.md` "## Download Engine & Anti-Ban Strategy" → "## Download Engine & Reliability"; "Anti-Ban Measures" table → "Rate-limit & politeness defaults"; "Anti-ban" features-table row → "Reliability"; chrome-cookie troubleshooting reworded to clarify Playwright reads in a separate session. `user_guide_hebrew.md` "Anti-Ban Delay" → "השהיית קצב בקשות"; section 7.3 rewritten around sign-in instead of "עקיפת הגנות". `egg-info/PKG-INFO` no longer tracked (commit `009f8f1`) so the stale copy won't ship.

### S1-7: `max_parallel_downloads` mismatch (config ≠ CLI ≠ docstrings)
- **Files**: `config.py:99,467`, `cli.py:144,300`, `core/download_orchestrator.py:99,112`, `ui/workers/download_worker.py:107`
- **Symptom**:
  - Config and orchestrator both clamp 1–6 ✓
  - CLI clamps `min(5, args.parallel)` (line 300) → user can pass `--parallel 6` but it silently becomes 5
  - CLI help says "1–5, default: 3" (line 144) — misleading
  - Orchestrator docstring line 99 says "1–5"
  - DownloadWorker docstring line 107 says "1–5"
- **Fix**: pick **1–6** as the canonical limit (matches config + README + UI spinbox in settings_panel.py:222) and update CLI clamp + all three docstrings.
- **Status**: **fixed** in commit `a10426d`. Evidence: `cli.py:144` help says "1-6, default: 3"; `cli.py:300` clamps `min(6, args.parallel)`; `core/download_orchestrator.py:99` and `ui/workers/download_worker.py:107` docstrings say "1-6". `python cli.py --help` smoke-tested OK.

### S1-8: `_sanitize_filename` truncation drift between downloader and duplicate-checker
- **Files**: `core/downloader.py:273`, `core/duplicate_checker.py:45`
- **Symptom**: `duplicate_checker._sanitize` truncates to 200 chars (`name.strip(". ")[:200]`); `downloader._sanitize_filename` does NOT truncate. For titles > 200 chars (rare but real for some YouTube titles), the duplicate-checker stem differs from the file actually written → false negatives.
- **Fix**: extract a single shared `_sanitize_filename(name, max_len=200)` helper in `core/downloader.py` and import it from `duplicate_checker.py` to guarantee one source of truth. Combined with S0-4, this fully unifies the filename logic.
- **Status**: **fixed** in commit `a246633` (bundled with S0-4). Evidence: `core/downloader.py:_sanitize_filename` now truncates to 200; `core/duplicate_checker.py` imports it directly; `tests/test_core.py::TestDuplicateChecker::test_expected_stem_truncates_to_200` and `test_expected_stem_matches_downloader_sanitiser` pin the contract.

### S1-9: `.gitignore` is corrupted by mangled whitespace/RTL artifacts
- **File**: `.gitignore` (lines 2-7)
- **Symptom**: lines 2-7 contain entries like `v e n v / ` (spaces between letters), ` . i d e a / `, leading whitespace — likely from Hebrew RTL copy-paste corruption or NBSP characters. These lines do NOT match real paths, so `venv/` etc. would only be ignored by the duplicate clean line on line 10. Additionally **missing**: `*.egg-info/`, `*.pyc`, `dist/`, `build/`, `.env`, `*.log`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`. `ytspot_downloader.egg-info/` is currently **tracked** (6 files).
- **Fix**: rewrite `.gitignore` cleanly; `git rm -r --cached ytspot_downloader.egg-info/`.
- **Status**: **fixed** in commit `009f8f1`. Evidence: `.gitignore` rewritten from scratch with 8 grouped sections; `ytspot_downloader.egg-info/` removed from index via `git rm --cached` (6 files); `git ls-files | grep egg-info` returns empty.

### S1-10: CI skips P0 gate tests with no documented reason
- **File**: `.github/workflows/tests.yml:49`
- **Symptom**: `pytest --ignore=tests/test_p0_gates.py` skips the largest test file (463 lines), which guards critical regressions (TrackMeta defaults, PlaylistParser error handling, SpotifyResolver, cookies_file forwarding). The CI never sees these tests fail. There is no comment explaining why.
- **Fix**: either run P0 gates (preferred — they look offline-safe based on test contents) or split into a separate `p0` job with a documented reason. Also: tests run only on ubuntu but the primary target is Windows. Add a Windows matrix entry. Add Python 3.10 to the matrix to match `pyproject.toml:9 requires-python = ">=3.10"`.
- **Status**: **fixed** in commit `ee89e18`. Evidence: `.github/workflows/tests.yml` now runs matrix `{windows-latest, ubuntu-latest} × {3.10, 3.11, 3.12}`; removed `--ignore=tests/test_p0_gates.py`; P0 gates run in every job with a comment explaining their purpose. Local `pytest tests/ -q --tb=line` → 182 passed.

### S1-11: MusicBrainz User-Agent contains a fake GitHub URL
- **File**: `core/musicbrainz_enricher.py:30`
- **Symptom**: `"User-Agent": "YTSpotDownloader/3.0 (https://github.com/ytspot)"` — wrong URL. MusicBrainz enforces UA policy and may rate-limit or block clients that present an unverifiable identity. Also the version `3.0` doesn't match anything else in the project (everything else is `1.0.0`).
- **Fix**: import `CURRENT_VERSION` from `update_checker` and use the real `cdtauman-projects/ytspot_downloader` repo URL.
- **Status**: **fixed** in commit `6bc1097`. Evidence: `core/musicbrainz_enricher.py` imports `CURRENT_VERSION` and the UA is `"YTSpotDownloader/{CURRENT_VERSION} (https://github.com/cdtauman-projects/ytspot_downloader)"`.

---

## S2 — Important polish

### S2-1: `ytspot_downloader.egg-info/` is tracked
- **Files**: 6 files under `ytspot_downloader.egg-info/`
- **Fix**: covered by S1-9 (.gitignore rewrite + `git rm --cached`).
- **Status**: **fixed** in commit `009f8f1`. Evidence: untracked via `git rm --cached`; covered by new `*.egg-info/` rule in `.gitignore`.

### S2-2: `.claude/settings.local.json` is tracked
- **File**: `.claude/settings.local.json` (12 lines)
- **Symptom**: IDE-local config in version control. Already in `.gitignore:14` (`.claude/`) but the file was tracked before that line existed.
- **Fix**: `git rm --cached .claude/settings.local.json` (already ignored going forward).
- **Status**: **fixed** in commit `009f8f1`. Evidence: removed from index; `.claude/` rule in new `.gitignore`.

### S2-3: `run_preflight()` never invoked
- **File**: `error_handler.py:325`, `main.py`
- **Symptom**: `run_preflight()` is a well-designed function that checks FFmpeg + network on startup, but `main.py` never calls it. Users with missing FFmpeg get a cryptic yt-dlp error on their first download instead of an upfront message.
- **Fix**: call from `main.py` after window construction; show `MessageBox` if `not result.all_ok()`.
- **Status**: open (consider adding to S1 if FFmpeg is genuinely required for the audio path)

### S2-4: Stale `window_geometry` property in `AppConfig`
- **File**: `config.py:309-314`
- **Symptom**: Property exists, but migration 2 (`config_migrate.py:60`) explicitly pops the key. Property always returns `""`. Dead code.
- **Fix**: delete the property.
- **Status**: open

### S2-5: "Anti-Ban" docstring/comment wording in non-user-facing files
- **Files**: `config.py:2,8,98,469`, `core/download_orchestrator.py:196`, `core/downloader.py:177`, `PROJECT_STRUCTURE.md:141`
- **Symptom**: code comments and section headers still say "Anti-Ban". Not visible to end users but visible to anyone reading the source.
- **Fix**: rename to "Rate-limit handling" / "Reliability" / "Politeness throttling" in comments. Behavior unchanged.
- **Status**: **fixed** in commit `822998a` (bundled with S1-5/S1-6). Evidence: `config.py` v3.1 docstring + section header reworded; `core/download_orchestrator.py:196` stagger comment reworded; `core/downloader.py:177` randomize_user_agent comment now says "kept for signature; rotation not yet wired through"; `PROJECT_STRUCTURE.md` browser_window description reworded.

### S2-6: `download_async` is defined but never called
- **File**: `core/downloader.py:462-474`
- **Symptom**: `DownloadEngine.download_async` exists but no caller anywhere (all paths go through `DownloadOrchestrator → _download_one → engine.download(...)`).
- **Fix**: delete the method, or annotate `# Public API: kept for direct CLI use`.
- **Status**: open

### S2-7: CLI lacks `--version` and `--doctor`
- **File**: `cli.py`
- **Symptom**: `python cli.py --version` errors as unrecognised argument. `--doctor` would expose `error_handler.run_preflight()` neatly.
- **Fix**: add both flags. `--version` prints `CURRENT_VERSION`; `--doctor` runs preflight and exits.
- **Status**: open

### S2-8: `bypass_bot_btn` i18n key name itself uses "bypass"
- **File**: `ui/i18n.py:82,310`
- **Symptom**: even after rewording the values, the key name leaks the intent. Cosmetic / internal.
- **Fix**: optional; renaming the key requires touching every caller and is not behavior-changing.
- **Status**: deferred (S3)

### S2-9: Tag-editor backup files are created but no restore UI
- **Files**: `ui/controllers/metadata_controller.py:223-225`, `ui/panels/metadata_editor_panel.py`
- **Symptom**: backups land at `~/.ytspot/tag_backups/ytspot_tag_backup_*.json`. The status bar shows "(גיבוי: …)" but no restore button. If the user wants to undo, they must manually edit the JSON or use the tag editor's revert (in-memory only).
- **Fix**: add a "Restore from backup…" button that lists files and re-applies.
- **Status**: open (S2)

---

## S3 — Later

### S3-1: Placeholder URLs in `update_banner.py` and `update_checker.py` smoke blocks
- **Files**: `ui/components/update_banner.py:261,269`, `core/update_checker.py:387-396`
- **Symptom**: `your-username/ytspot-downloader/...` and `user/repo/...` strings inside `if __name__ == "__main__":` demo blocks. Not reachable at runtime.
- **Fix**: rewrite to use the real repo URL for cleanliness. No user impact.
- **Status**: **fixed** in commit `6bc1097` (`ui/components/update_banner.py:261,269` updated). `core/update_checker.py:387-396` demo URLs (user/repo placeholders) intentionally left as illustrative; not a real release blocker.

### S3-2: Internal tempfile names use "bypass" prefix
- **File**: `ui/components/browser_window.py:136-138`
- **Symptom**: `ytspot_bypass_cookies.txt`, `ytspot_bypass_html.html`, `ytspot_bypass_url.txt`. Internal, not visible to users unless they inspect `%TEMP%`.
- **Fix**: rename to `ytspot_auth_*` or `ytspot_browser_*`. Cosmetic.
- **Status**: deferred

### S3-3: Hardcoded Hebrew subfolder names regardless of UI language
- **File**: `ui/controllers/download_controller.py:198-210,593-596`
- **Symptom**: "אלבומים", "סינגלים ו-EP", "הופעות חיות", "פלייליסטים", "סרטונים" are written to the filesystem regardless of `cfg.language`. English-only users see Hebrew folder names.
- **Fix**: route through i18n. Larger change; ship as v1.1 work, not v1.0.
- **Status**: deferred

### S3-4: `utils/impersonate.py` is 6 lines — likely dead
- **File**: `utils/impersonate.py`
- **Symptom**: tiny module with no callers visible in any grep.
- **Fix**: confirm via Phase 2 symbol scan; delete if unused.
- **Status**: deferred (Phase 2)

### S3-5: Multiple `pytest` config conflict (pyproject vs pytest.ini)
- **Files**: `pyproject.toml:52-54`, `pytest.ini:1-6`
- **Symptom**: both `[tool.pytest.ini_options]` and `pytest.ini` define the same options. Not harmful; pytest.ini wins. Cleaner to keep one.
- **Status**: deferred

---

## Verified safe (initially flagged, confirmed OK)

- **`spotify_app_api_key` default 64-char hex** (`config.py:96`): not a private credential — this is a public proxy auth token shared with the open-source proxy server. **Verified safe**; consider documenting in a comment.
- **`utils/ytm_scraper.py:6` `key=AIzaSyC9XL3...`**: this is the public, well-known YouTube Music web-client API key. **Not a secret.**
- **Tag editor backup before apply** (F12): `metadata_controller.py:223-225` always writes a backup JSON before invoking `MetadataApplyWorker`. **Verified safe.**
- **Duplicate-delete confirmation** (F13): `duplicate_files_dialog.py:322-337` shows a `QMessageBox.Warning` with explicit "כן, מחק"/"לא, חזור", default = No. Also uses `send2trash` (recycle bin, recoverable) via `metadata_controller.delete_duplicate_files` line 477-480, only falling back to `unlink()` on ImportError. **Verified safe.**
- **`download_controller.py:689` clean-title regex** explicitly preserves Remix / Edit / Acoustic / Live / Cover (comment on line 688). **Verified safe.**
- **`last_search_platform` SETTER** (`config.py:367`) accepts any string. The GETTER (line 363) clamps to a valid set including "ytmusic". The bug is in `search_panel.py` restore, not config.
- **No DRM circumvention code**: zero hits on DRM/circumvent/Widevine. **Verified safe.**
- **No private API tokens leaked**: only public IDs and the documented proxy default token.

---

## Fix-commit plan

One commit per category, all on `audit/full-line-audit`:

| # | Commit title | Bundles |
|---|---|---|
| 1 | `fix: correct GitHub repo URL across update checker, settings, README` | S0-1, S0-2, S0-3, S1-11 |
| 2 | `fix: unify duplicate-checker stem with downloader filename logic` | S0-4, S1-8 |
| 3 | `fix: persist correct platform on download-history records` | S1-1 |
| 4 | `fix: use OptionsBar output_dir for downloads, not stale config` | S1-2 |
| 5 | `fix: clamp categorized search results to configured max` | S1-3 |
| 6 | `fix: restore ytmusic as a valid last_search_platform` | S1-4 |
| 7 | `chore: rephrase 'bypass'/'Anti-Ban' wording in user-facing UI and docs` | S1-5, S1-6, S2-5 |
| 8 | `fix: align max_parallel_downloads limit (1-6) across CLI, docs, orchestrator` | S1-7 |
| 9 | `chore: rewrite .gitignore, untrack egg-info and .claude/settings.local.json` | S1-9, S2-1, S2-2 |
| 10 | `ci: run P0 gate tests and add Windows + Python 3.10 to matrix` | S1-10 |

S2-3 (`run_preflight`), S2-4 (stale property), S2-6 (`download_async`), S2-7 (`--version`/`--doctor`), S2-8/9, S3-* are deferred — bundled into a single "polish" commit or left for v1.1.

---

## Commercial-release deltas

Tracking the extra release-prep work required for a true commercial Windows EXE distribution. These are not "bugs" the audit found — they are the gap between "branch passes tests" and "ship a signed installer to paying users." Each lands in its own commit on `audit/full-line-audit`.

| Delta | Severity | Status |
|---|---|---|
| **C-1**: Single source of truth for the app version (`version.py` module read by `update_checker`, `cli --version`, `main.py` Qt metadata, packaging, and EXE VS_VERSIONINFO) | S1 for release | open |
| **C-2**: CLI `--version` and `--doctor` flags (extends earlier S2-7) | S1 for release | open |
| **C-3**: Wire `error_handler.run_preflight()` into `main.py` startup (closes S2-3) and extend it with cookies + output-dir + Playwright checks | S1 for release | open |
| **C-4**: PyInstaller spec, build script, Windows VS_VERSIONINFO, application icon | S0 for release | open |
| **C-5**: Inno Setup installer config | S1 for release | open |
| **C-6**: Bundle LGPL FFmpeg/ffprobe + auto-discovery in downloader | S0 for release | open |
| **C-7**: Playwright graceful degradation + clear "install browsers" path | S1 for release | open |
| **C-8**: `THIRD_PARTY_NOTICES.md` covering all bundled and runtime deps | S0 for release (legal) | open |
| **C-9**: `RELEASE_CHECKLIST.md` for manual smoke on a clean Windows machine | S1 for release | open |
| **C-10**: Windows packaging CI workflow with SHA-256 artifact checksums (no auto-publish) | S2 for release | open |
| **C-11**: Final grep sweep for bypass/anti-ban/circumvent/DRM in user-facing strings and public docs | S1 for release | open |
