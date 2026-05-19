# AUDIT_COVERAGE_MANIFEST

Branch: `audit/full-line-audit` · Generated as part of the full line-level audit of `cdtauman-projects/ytspot_downloader`.

## Summary

| Metric | Value |
|---|---|
| Tracked files (`git ls-files`) | 116 |
| Total lines across tracked files | ~32,388 |
| Files audited | 115 |
| Files skipped (`audit: skip`) | 1 (egg-info PKG-INFO — generated; remaining egg-info `.txt` files still listed) |
| Languages | Python (99 files, ~28.4k lines), Markdown (4 docs, ~1.6k), YAML/INI/TOML (5 files), batch (1) |

Helper scripts under `tools/audit/` produced the seed manifest (`_manifest_seed.tsv`) and AST symbol scrape (`_symbols.tsv` — Phase 2). All Python files were also covered by repository-wide grep passes (TODO/FIXME/HACK, hardcoded URLs, version strings, `max_parallel`/`max_workers`, "Anti-Ban"/"bypass"/"DRM"/"לעקוף", `print(`, `__main__` blocks, `ytmusic`).

## Cross-cutting observations (apply repo-wide)

- **No TODO / FIXME / HACK markers in any Python file** — the only `grep` hits on `XXX` are `TXXX` (mutagen ID3 frame). The codebase has been actively cleaned; absence of debt markers is a polish signal.
- **Hardcoded GitHub repo URLs use 3 different (wrong) owners**: `cdtauman` (`core/update_checker.py:169`, `README.md:399`, `ui/workers/update_worker.py:53`), `ytspot/ytspot` (`ui/panels/settings_panel.py:570`), `your-username/ytspot-downloader` (`ui/components/update_banner.py:261,269`), `ytspot` (`core/musicbrainz_enricher.py:30`). The actual `git remote` is `cdtauman-projects/ytspot_downloader`.
- **Version is consistent**: `pyproject.toml:7 = "1.0.0"`, `core/update_checker.py:51 = "1.0.0"`, `main.py:48 = "1.0.0"`. The `version="2.0.0"` (`update_checker.py:387`) and `version="2.1.0"` (`update_banner.py:260`) are confined to `if __name__ == "__main__":` demo blocks.
- **"Anti-Ban" wording** is in 4 file-level docstrings (`config.py:2,8,98,469`), 1 inline comment (`download_orchestrator.py:196`), and 4 README sections (`README.md:296,304` + others). User-facing UI strings additionally use **"bypass"** in `ui/i18n.py:82,231,310,459` and `ui/panels/settings_panel.py:490`.
- **`spotify_app_api_key`** has a **default real-looking 64-char hex string** baked into `config.py:96`. Treated as a public proxy-API token, not a private credential — flagged for confirmation.

## Inventory table (all 116 tracked files)

Notation: `Lines` = newline count; `Audit` = `yes`/`skip`; `Read` = `full` (whole file in context), `slices` (selected ranges), `grep` (covered only by repo-wide grep passes); `Risk` = `S0`/`S1`/`S2`/`S3`/`-`. `-` = no release-blocking finding in this file; doesn't imply zero defects.

### Root + entry points

| Path | Type | Lines | Read | Risk | Notes |
|---|---|---|---|---|---|
| `main.py` | python-app | 96 | full | – | QApplication bootstrap. Version set on line 48. Does **not** call `error_handler.run_preflight()`. |
| `cli.py` | python-app | 331 | full | S1 | `--parallel` help says "1–5" but config allows 6 (line 144); clamps `min(5, args.parallel)` line 300. No `--version`/`--doctor`. |
| `config.py` | python-app | 745 | full | S0/S1 | Source-of-truth for limits. `spotify_app_api_key` default = 64-char hex (line 96). `window_geometry` property at line 309-314 is dead (key removed by migration 2). `_DEFAULTS` mostly clean and typed. |
| `config_migrate.py` | python-app | 133 | full | – | Migration framework. CURRENT_VERSION=2. Removes `window_geometry`. |
| `error_handler.py` | python-app | 355 | full | – | Solid: `classify_error`, `probe_connectivity`, `check_ffmpeg`, `run_preflight`. `run_preflight()` exists but is **never called** anywhere → S2 dead code / missed UX. |
| `pyproject.toml` | packaging | 54 | full | – | Version 1.0.0. Scripts `ytspot`, `ytspot-cli`. No `[project.urls]` section. |
| `requirements.txt` | packaging | 32 | full | – | Matches pyproject. |
| `pytest.ini` | config | 6 | full | – | Clean. |
| `.gitignore` | config | 14 | full | S1 | **BROKEN**: lines 2-7 contain mangled whitespace/RTL chars (`my_venv/`, `v e n v /`, ` . i d e a /`). Missing: `*.egg-info/`, `*.pyc`, `dist/`, `build/`, `.env`, `*.log`. |
| `install_playwright.bat` | script | 18 | grep | – | Windows installer for Playwright Chromium. |
| `README.md` | docs | 641 | slices | S1 | "Anti-Ban Strategy" section (line 296), "DRM" wording (line 631), wrong owner URL (line 399). User-facing on GitHub. |
| `PROJECT_STRUCTURE.md` | docs | 208 | slices | S2 | Mentions "bypass cookies/HTML" (line 141). Internal doc, but public on GitHub. |
| `SPOTIFY_PROXY_API.md` | docs | 288 | slices | – | Spotify proxy API contract — clean. |
| `user_guide_hebrew.md` | docs | 516 | slices | S1 | "Anti-Ban Delay" + "לעקוף את החסימה" (lines 309, 350). Hebrew user-facing. |
| `.claude/settings.local.json` | other | 12 | full | S2 | IDE local settings — **shouldn't be tracked**. |

### `core/` (29 files, 10,390 lines)

| Path | Lines | Read | Risk | Notes |
|---|---|---|---|---|
| `core/batch_importer.py` | 520 | grep + slice | – | Multi-URL importer; deduplication; URL extraction. Big `__main__` demo block. |
| `core/channel_tab_discoverer.py` | 238 | grep + slice | – | Discovers YouTube channel tabs. |
| `core/cookie_wizard.py` | 101 | grep + slice | – | Playwright-based cookie-grabber. Default URL https://www.youtube.com. |
| `core/download_orchestrator.py` | 390 | full | S1 | Line 99 docstring says "1–5" but code clamps to 6 (line 112). Line 374 `_persist_record` hardcodes `platform="youtube"` — **history is mis-tagged for ytmusic/spotify downloads**. |
| `core/downloader.py` | 1030 | full | S0 | `_sanitize_filename` (line 263) and `duplicate_checker._sanitize` differ on truncation (200 chars vs none). `is_solo`/`clean_filename` produce title-only filenames that collide. Hebrew "לעקוף" (line 238). Title-cleanup regex preserves Remix/Live/Acoustic/Edit ✓. |
| `core/duplicate_checker.py` | 128 | full | S0 | `expected_stem()` builds `"{artist} - {title}"` but downloader always writes clean-filename `"{title}"` (no artist). Checker is **silently broken** for every download. |
| `core/duplicate_detector.py` | 169 | full | – | Cross-tab dedup (channel scraper). Pure data; clean. |
| `core/history_db.py` | 643 | grep + slice | – | SQLite history. `__main__` block has placeholder URLs. |
| `core/hls_downloader.py` | 193 | grep | – | HLS/DASH download via ffmpeg. |
| `core/listing_scraper.py` | 320 | grep | – | Listing pagination. |
| `core/lyrics_embedder.py` | 168 | grep | – | Lyrics fetch + embed (off by default). |
| `core/metadata_models.py` | 178 | grep | – | TrackMeta + tag dataclasses. |
| `core/metadata_processor.py` | 533 | grep + slice | TBD | Tag editor scan / apply / backup / restore. Need full Phase 4 read for safety. |
| `core/musicbrainz_enricher.py` | 266 | grep + slice | S1 | Line 30 User-Agent URL `https://github.com/ytspot` — wrong owner; MB enforces accurate UA. |
| `core/offline_monitor.py` | 117 | grep | – | Network probe loop. |
| `core/parallel_enricher.py` | 220 | grep | – | ThreadPoolExecutor wrapper for enrichment. |
| `core/playlist_parser.py` | 866 | grep + slice | – | yt-dlp playlist resolver. `SourcePlatform` enum + `classify_url`. Critical for tests/cli. |
| `core/playlist_sync.py` | 142 | grep | – | Spotify → local sync. |
| `core/progress_estimator.py` | 227 | grep | – | Speed/ETA calc. Tested. |
| `core/queue_persistence.py` | 195 | grep | – | TrackMeta JSON serialiser. Tested. |
| `core/replay_gain.py` | 206 | grep | – | rsgain/pyloudnorm. Off by default. |
| `core/retry_policy.py` | 171 | full | – | Solid retry-with-backoff. Tested. |
| `core/scraper.py` | 626 | grep + slice | – | BeautifulSoup channel/playlist scraper. |
| `core/search_engine.py` | 1189 | slices (1-350, 350-850, 850-1190) | S1 | **F3**: per-category floors (`song_limit=max(N//3,8)`, `playlist_limit=max(N//5,5)`, etc.) mean configured `max_results` is a floor, not a cap — the "Max …" label lies. YTM `search_all` floor = 22 items even when user sets `max_results=10`. |
| `core/services.py` | 86 | full | – | DI container. Clean. |
| `core/spotify_match_scorer.py` | 345 | grep | – | Fuzzy Spotify→local matcher. Tested. |
| `core/thumbnail_cropper.py` | 315 | grep | – | Pillow square/pad. |
| `core/universal_extractor.py` | 396 | grep | – | Playwright stream sniffer. |
| `core/update_checker.py` | 412 | full | S0 | Line 169 `repo_owner="cdtauman"` ← wrong default. Lines 310-412 are `__main__` smoke test (not prod). |

### `ui/` (44 files, 14,509 lines)

#### Top-level + theme/i18n

| Path | Lines | Read | Risk | Notes |
|---|---|---|---|---|
| `ui/app_window.py` | 1179 | grep + slice | S0 | Line 443 `self._update_worker = UpdateWorker(parent=self)` — uses default broken owner. Line 723 hardcoded `https://www.youtube.com`. |
| `ui/i18n.py` | 493 | full | S1 | Lines 82/310 `bypass_bot_btn` = "Bypass Protection 🛡️"/"עקוף הגנה 🛡️". Lines 231/459 `browser_cookies_desc` says "bypass bot checks and age gates" / "לעקיפת זיהוי רובוטים". |
| `ui/theme_manager.py` | 838 | grep | – | Theme/accent management. Large but isolated. |

#### Panels

| Path | Lines | Read | Risk | Notes |
|---|---|---|---|---|
| `ui/panels/__init__.py` | 34 | grep | – | Package init / re-exports. |
| `ui/panels/converter_panel.py` | 520 | grep | – | Local file converter. |
| `ui/panels/history_panel.py` | 364 | grep | – | History browse + CSV export. |
| `ui/panels/metadata_editor_panel.py` | 1917 | grep + slice | TBD | Largest file. Tag editor table. Needs Phase-4 safety read. |
| `ui/panels/options_bar.py` | 287 | full | S1 | Line 100: `get_options()` returns `"output_dir"` = UI text. Line 273-282: `_on_browse` saves to config; text edits do **not** save. Combined with `download_controller.py:245`, this means typing into the field is verified writable but the actual download writes to `cfg.output_dir`. |
| `ui/panels/queue_panel.py` | 525 | grep | – | Drag-drop queue. |
| `ui/panels/search_panel.py` | 449 | full | S1 | **F8**: Line 396 `if platform in ("youtube", "spotify", "both"):` — **`"ytmusic"` missing** from restore allow-list. Last-platform "ytmusic" is dropped on restart. |
| `ui/panels/settings_panel.py` | 894 | grep + slice | S0 | Line 570 hardcoded GitHub URL `https://github.com/ytspot/ytspot` (About link). Line 490 Hebrew "ולעקוף חסימות". |
| `ui/panels/status_bar.py` | 204 | grep | – | Status bar with cancel. |
| `ui/panels/url_bar.py` | 241 | grep | – | URL input + paste/batch/scrape. |

#### Controllers

| Path | Lines | Read | Risk | Notes |
|---|---|---|---|---|
| `ui/controllers/__init__.py` | 1 | full | – | Empty. |
| `ui/controllers/channel_flow_controller.py` | 227 | grep | – | Channel scrape flow. |
| `ui/controllers/download_controller.py` | 610 | full | S0/S1 | **F2 confirmed**: line 245 uses `cfg.output_dir` not `opts["output_dir"]`. **F7 confirmed**: line 277 `is_clean = True` always — every download uses clean (no-artist) filename, breaking duplicate_checker's `{artist} - {title}` stem. Hardcoded Hebrew subfolder names (lines 198-210, 593-596). |
| `ui/controllers/fetch_controller.py` | 149 | grep | – | Playlist fetch + batch import. |
| `ui/controllers/metadata_controller.py` | 548 | grep + slice | TBD | Tag-editor session lifecycle. Needs Phase-4 safety read. |
| `ui/controllers/search_controller.py` | 94 | grep | – | Search dispatch. |

#### Workers

| Path | Lines | Read | Risk | Notes |
|---|---|---|---|---|
| `ui/workers/__init__.py` | 37 | grep | – | Package init / re-exports. |
| `ui/workers/channel_scrape_worker.py` | 243 | grep | – | Channel video enumeration. |
| `ui/workers/clipboard_worker.py` | 140 | grep | – | Clipboard monitor. |
| `ui/workers/download_worker.py` | 175 | full | S1 | Line 107 docstring "1–5" — wrong, should be 1-6. Thin QThread shell. |
| `ui/workers/duplicate_detector_worker.py` | 286 | grep | – | Duplicate file scan worker. |
| `ui/workers/fetch_worker.py` | 145 | grep | – | Playlist resolver. |
| `ui/workers/metadata_worker.py` | 165 | grep | – | Tag scan. |
| `ui/workers/offline_monitor.py` | 70 | grep | – | Online/offline state. |
| `ui/workers/scraper_worker.py` | 117 | grep | – | PageScraper wrapper. |
| `ui/workers/search_worker.py` | 214 | full | S1 | Line 53 docstring says "1-50" but code clamps to 1-100 (line 85-86). |
| `ui/workers/thumbnail_worker.py` | 109 | grep | – | Parallel thumbnail fetcher. |
| `ui/workers/update_worker.py` | 84 | full | S0 | Lines 53-54 default `repo_owner="cdtauman"`. Lines 36-37 docstring contains an explicit "Replace with your actual GitHub username before release" TODO. |

#### Components + Dialogs + Models

| Path | Lines | Read | Risk | Notes |
|---|---|---|---|---|
| `ui/components/__init__.py` | 28 | grep | – | |
| `ui/components/browser_window.py` | 182 | grep + slice | S2 | Temp filenames `ytspot_bypass_*.txt` (lines 136-138) — internal. Uses i18n bot_bypass_* keys. |
| `ui/components/history_row.py` | 264 | grep | – | History row card. |
| `ui/components/offline_banner.py` | 81 | grep | – | |
| `ui/components/search_result_card.py` | 317 | grep | – | |
| `ui/components/track_card.py` | 528 | grep | – | Queue item card. |
| `ui/components/update_banner.py` | 292 | grep + slice | S3 | Lines 261/269 placeholder URLs — confirmed inside `if __name__ == "__main__":` demo (not prod). |
| `ui/dialogs/__init__.py` | 0 | full | – | Empty. |
| `ui/dialogs/conflict_resolution_dialog.py` | 320 | grep | – | Cross-tab merge dialog. |
| `ui/dialogs/duplicate_files_dialog.py` | 383 | grep | TBD | Duplicate file delete UX — needs Phase-4 destructive-action audit. |
| `ui/dialogs/tab_select_dialog.py` | 369 | grep | – | Channel tab picker. |
| `ui/models/__init__.py` | 1 | full | – | |
| `ui/models/metadata_table_model.py` | 385 | grep | – | Qt model for tag editor table. |

### `utils/` (11 files, 1,792 lines)

| Path | Lines | Read | Risk | Notes |
|---|---|---|---|---|
| `utils/artwork_cleaner.py` | 50 | grep | – | Strip Google `=w120-h120` thumbnail params. |
| `utils/cookie_validator.py` | 74 | grep | – | Check cookies.txt freshness. |
| `utils/impersonate.py` | 6 | grep | – | Tiny module (6 lines) — possibly dead. Phase 2. |
| `utils/logger.py` | 75 | grep | – | SilentLogger wrapper. |
| `utils/logging_config.py` | 139 | grep | – | setup_logging used by main/cli. |
| `utils/network_probe.py` | 22 | grep | – | dns.google probe. |
| `utils/paths.py` | 40 | grep | – | get_app_cookies_path etc. |
| `utils/spotify_resolver.py` | 847 | grep + slice | – | Spotify→track resolver (largest util). Hardcoded `accounts.spotify.com/api/token`. |
| `utils/time_format.py` | 52 | grep | – | seconds_to_str helper. |
| `utils/yt_dlp_opts.py` | 145 | grep | – | Shared yt-dlp options builder. |
| `utils/ytm_scraper.py` | 342 | grep | – | YT Music HTTP scraper. Hardcoded public YTM web-client API key (`AIzaSyC9XL3...`) — public, not a secret. |

### `tests/` (10 files, 1,749 lines)

| Path | Lines | Read | Risk | Notes |
|---|---|---|---|---|
| `tests/__init__.py` | 0 | full | – | Empty. |
| `tests/test_core.py` | 424 | grep | – | AppConfig, HistoryDB, classify_url, classify_error, BatchImporter, duplicate_checker. |
| `tests/test_history_db_resilience.py` | 67 | grep | – | DB concurrency. |
| `tests/test_orchestrator.py` | 179 | grep | – | Orchestrator cancel/callbacks. |
| `tests/test_p0_gates.py` | 463 | grep | S1 | **Largest test file**, gates critical regressions — and CI **skips it** (`--ignore=tests/test_p0_gates.py`). |
| `tests/test_parallel_enricher.py` | 112 | grep | – | enrich_parallel. |
| `tests/test_progress_estimator.py` | 140 | grep | – | Speed/ETA. |
| `tests/test_queue_persistence.py` | 126 | grep | – | TrackMeta JSON. |
| `tests/test_retry_policy.py` | 107 | grep | – | Exponential backoff. |
| `tests/test_spotify_match_scorer.py` | 131 | grep | – | Fuzzy match. |

### `.github/` + CI

| Path | Lines | Read | Risk | Notes |
|---|---|---|---|---|
| `.github/workflows/tests.yml` | 52 | full | S1 | **ubuntu-latest only** (no Windows despite primary target). **Excludes test_p0_gates.py** with no reason. Tests Python 3.11/3.12 but pyproject requires `>=3.10`. No lint/coverage. |

### `ytspot_downloader.egg-info/` (tracked-by-mistake, 6 files, ~447 lines total)

| Path | Lines | Read | Risk | Notes |
|---|---|---|---|---|
| `ytspot_downloader.egg-info/PKG-INFO` | 330 | skip | S2 | Generated from README. Will auto-update; should not be tracked. |
| `ytspot_downloader.egg-info/SOURCES.txt` | 84 | grep | S2 | Generated file list. |
| `ytspot_downloader.egg-info/dependency_links.txt` | 1 | grep | S2 | Generated. |
| `ytspot_downloader.egg-info/entry_points.txt` | 3 | grep | S2 | Generated. Declares `ytspot`, `ytspot-cli`. |
| `ytspot_downloader.egg-info/requires.txt` | 26 | grep | S2 | Generated mirror of pyproject deps. |
| `ytspot_downloader.egg-info/top_level.txt` | 3 | grep | S2 | Generated. |

These six files are setuptools build artifacts and should be `.gitignore`d + `git rm`-ed.

## Phase 1 coverage proof

Per-file line ranges read (combined with repo-wide grep coverage of all `.py`):

- **Full reads (top→bottom, single Read call)**: `main.py:1-96`, `cli.py:1-331`, `config.py:1-745`, `config_migrate.py:1-133`, `error_handler.py:1-355`, `core/services.py:1-86`, `core/update_checker.py:1-412`, `core/duplicate_checker.py:1-128`, `core/duplicate_detector.py:1-169`, `core/retry_policy.py:1-171`, `core/downloader.py:1-1031`, `core/download_orchestrator.py:1-391`, `ui/panels/options_bar.py:1-287`, `ui/panels/search_panel.py:1-449`, `ui/workers/search_worker.py:1-214`, `ui/workers/download_worker.py:1-175`, `ui/workers/update_worker.py:1-84`, `ui/controllers/download_controller.py:1-611`, `ui/i18n.py:1-493`, `.gitignore:1-14`, `pyproject.toml:1-54`, `pytest.ini:1-6`, `requirements.txt:1-32`, `.github/workflows/tests.yml:1-52`.
- **Slice reads**: `core/search_engine.py:1-350,350-850,850-1190` (full coverage in slices).
- **Grep-only coverage**: every remaining `.py` file matched by the cross-cutting passes (TODO/FIXME/HACK absent; hardcoded URLs enumerated; "Anti-Ban"/"bypass"/"DRM"/"לעקוף" enumerated; `max_parallel`/`max_workers` enumerated; `__main__` blocks enumerated; `print(` enumerated; `ytmusic` references enumerated; version strings enumerated).
- Files marked `TBD` in the table need targeted slice reads during Phase 4 safety audit (`core/metadata_processor.py`, `ui/panels/metadata_editor_panel.py`, `ui/controllers/metadata_controller.py`, `ui/dialogs/duplicate_files_dialog.py`).
