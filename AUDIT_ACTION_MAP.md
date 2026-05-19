# AUDIT_ACTION_MAP

Branch: `audit/full-line-audit`. Compact end-to-end map of every user-facing action (per the audit protocol's 55-item list). For each action: **UI entry** → **controller** → **worker** → **core** → **config keys** → **tests** → **release risk** (links to `AUDIT_RELEASE_BLOCKERS.md`).

Risk legend: `OK` = no concern; `S0/S1/S2/S3` = severity from blockers doc.

## Startup / settings / chrome

| # | Action | UI entry | Controller / Worker | Core / Util | Config keys | Tests | Risk |
|---|---|---|---|---|---|---|---|
| 1 | App startup | `main.py:main()` | — | `AppConfig`, `ServiceContainer.create_default` | all | — | OK (no preflight call → S2-3) |
| 2 | First-run / config load | implicit | — | `AppConfig._load`, `config_migrate.migrate` | persisted JSON | `test_core.py` | OK |
| 3 | Language selection | Settings | — | `i18n.set_language`, `app.setLayoutDirection` | `language` | — | OK |
| 4 | RTL/LTR | `main.py:67-69` | — | Qt | `language` | — | OK |
| 5 | Theme / accent / accessibility | Settings | `ThemeManager` | `theme_manager.py` | `theme`, `accent_color`, `accessibility_mode` | — | OK |
| 6 | Settings save/load | `SettingsPanel.*` | — | `AppConfig.save` | all | — | OK |

## Search

| # | Action | UI entry | Controller / Worker | Core | Config keys | Tests | Risk |
|---|---|---|---|---|---|---|---|
| 7 | YouTube search | `SearchPanel._on_search` | `SearchController` → `SearchWorker._run_youtube` | `SearchEngine.search_youtube_categorized` | `youtube_max_results`, `cookies_file` | `test_p0_gates` (excluded in CI) | S1 (S1-3 floor>cap) |
| 8 | YouTube Music search | same | `SearchWorker._run_ytmusic` | `SearchEngine.search_youtube_music` → `_YTMusicBackend.search_all` | `youtube_max_results` (shared) | `test_p0_gates` | S1 (S1-3, S1-4) |
| 9 | Spotify search | same | `SearchWorker._run_spotify` | `SearchEngine.search_spotify(_categorized)` (httpx → proxy) | `spotify_max_results`, `proxy_server_url`, `spotify_client_id/secret`, `spotify_app_api_key` | minimal | S1 (S1-3) |
| 10 | Combined ("both") search | same | `SearchWorker._run_youtube` + `_run_spotify` | both | both | minimal | S1 (S1-3) |
| 11 | Search result filtering | `SearchPanel._apply_filter` | — | per-kind section visibility | — | — | OK |
| 12 | Add to queue | `SearchResultCard.add_to_queue` | `AppWindow._on_add_to_queue` | builds TrackMeta → QueuePanel | — | — | OK |
| 13 | Drill down (album/playlist/artist/channel) | `SearchResultCard.browse_requested` | `AppWindow._on_drill_down` → `FetchController` | `PlaylistParser.parse` | `cookies_file` | partial | OK |

## URL / batch / scrape

| # | Action | UI entry | Controller / Worker | Core | Config keys | Tests | Risk |
|---|---|---|---|---|---|---|---|
| 14 | Single URL paste | `URLBar` | `FetchController.fetch_url` → `FetchWorker` | `PlaylistParser.parse` | `cookies_file` | partial | OK |
| 15 | Multi URL paste | `URLBar` | `FetchController` → `BatchImporter.extract_urls` | `batch_importer.py` | — | `test_core.py` | OK |
| 16 | Batch import from file | `URLBar` ⋯ Batch | `FetchController.import_batch` | `BatchImporter.parse_file` | `batch_import_dir` | `test_core.py` | OK |
| 17 | Page scrape (Spider) | `URLBar` ⋯ Spider | `FetchController.scrape` → `ScraperWorker` | `PageScraper.scrape` (3-phase: yt-dlp / BS4 / regex) | `cookies_file` | none | S3 (generic-extractor coverage) |
| 18 | Universal extraction (stream sniff) | `URLBar` Spider on generic page | implicit | `universal_extractor.find_best_stream_with_title` (Playwright) | — | none | S2 (Playwright dependency) |

## Format / quality / output

| # | Action | UI entry | Controller / Worker | Core | Config keys | Tests | Risk |
|---|---|---|---|---|---|---|---|
| 19 | Audio/video format | `OptionsBar._fmt_combo` | — | `MediaType` enum | `media_format` | — | OK |
| 20 | Quality | `OptionsBar._quality_combo` | — | `AudioQuality`/`VideoQuality` enums | `audio_quality`, `video_quality` | — | OK |
| 21 | Audio codec | `OptionsBar._codec_combo` | — | yt-dlp opts | `audio_format` | — | OK |
| 22 | Output dir | `OptionsBar` text + browse | `DownloadController.start_batch` line 245 | `Path.mkdir` | `output_dir` | none | **S1-2** (typed text ignored) |
| 23 | Clipboard monitor | `OptionsBar._clip_switch` | `ClipboardWorker` | — | `clipboard_monitor` | none | OK |

## Queue / download lifecycle

| # | Action | UI entry | Controller / Worker | Core | Config keys | Tests | Risk |
|---|---|---|---|---|---|---|---|
| 24 | Queue add/remove/select | `QueuePanel` | — | TrackCard state | — | none | OK |
| 25 | Download selected | `QueuePanel` ⋯ Download | `DownloadController.start_batch` → `DownloadWorker.run` → `DownloadOrchestrator.run_batch` | `DownloadEngine.download` | many | `test_orchestrator` | **S0-4, S1-1, S1-7, S1-8** |
| 26 | Pause track | `TrackCard.pause` | `DownloadController.pause_track` | engine cancel + .part | `paused_items` | none | OK |
| 27 | Resume track | `TrackCard.resume` | `DownloadController.resume_track` | new `DownloadWorker(max_workers=1)` w/ `resumable=True` | `paused_items` | none | OK |
| 28 | Global pause / cancel | `StatusBar.cancel` | `DownloadController.global_pause / cancel_all` | engine.cancel_all | — | `test_orchestrator` | OK |
| 29 | Auto-resume queue | `AppWindow` start-up | reads `cfg.queue_state`, `cfg.paused_items` | `queue_persistence` | `queue_state`, `paused_items` | `test_queue_persistence` | OK |

## Duplicates / filename / org

| # | Action | UI entry | Controller / Worker | Core | Config keys | Tests | Risk |
|---|---|---|---|---|---|---|---|
| 30 | Duplicate detection pre-download | implicit in `start_batch` | `DownloadController.start_batch:248-274` | `duplicate_checker.find_duplicate` | `duplicate_action` | partial | **S0-4** (stems never match), **S1-8** |
| 31 | Filename generation | implicit | `downloader._build_ydl_opts` | `_sanitize_filename`, `_sanitize_folder_name` | `playlist_subfolders`, `playlist_index_prefix` | none for filename collisions | **S0-4, S1-8** |
| 32 | Folder organization | implicit | `download_controller._get_dynamic_folder` lines 572-610 | hardcoded HE strings | `playlist_subfolders` | none | S3-3 (Hebrew names regardless of language) |

## Post-processing / enrichment

| # | Action | UI entry | Controller / Worker | Core | Config keys | Tests | Risk |
|---|---|---|---|---|---|---|---|
| 33 | Metadata embed | always | engine | yt-dlp `FFmpegMetadata` | `embed_metadata` | none | OK |
| 34 | Thumbnail embed | always | engine | yt-dlp `EmbedThumbnail` or `thumbnail_cropper.embed_custom_thumbnail` | `embed_thumbnail` | none | OK |
| 35 | Thumbnail crop/pad | post | engine | `core/thumbnail_cropper.py` | `square_thumbnails`, `expand_thumbnails` | none | OK |
| 36 | SponsorBlock | post | engine | yt-dlp SB postprocessor | `sponsorblock_enabled`, `sponsorblock_categories` | none | OK |
| 37 | Lyrics embed | post | engine | `core/lyrics_embedder.py` | `lyrics_enabled` (default off) | none | OK (off by default; verify UI toggle) |
| 38 | ReplayGain | post | engine | `core/replay_gain.py` | `replay_gain_enabled` (off) | none | OK (off by default) |
| 39 | MusicBrainz enrichment | post | engine | `core/musicbrainz_enricher.py` | `musicbrainz_enabled` (default on!) | none | **S1-11** (UA URL wrong) |

## History / DB

| # | Action | UI entry | Controller / Worker | Core | Config keys | Tests | Risk |
|---|---|---|---|---|---|---|---|
| 40 | History DB write | post-download | `DownloadOrchestrator._persist_record` line 361-378 | `HistoryDB.insert` | `history_db_path` | `test_history_db_resilience` | **S1-1** (hardcoded `platform="youtube"`) |
| 41 | History search/export/delete | `HistoryPanel` | — | `HistoryDB.search / export_csv / delete / clear_all` | `history_db_path` | `test_history_db_resilience` | OK |

## Converter

| # | Action | UI entry | Controller / Worker | Core | Config keys | Tests | Risk |
|---|---|---|---|---|---|---|---|
| 42 | Converter panel | `ConverterPanel` | — | ffmpeg via subprocess | — | none | S2 (no automated tests; quick manual smoke recommended) |

## Tag editor

| # | Action | UI entry | Controller / Worker | Core | Config keys | Tests | Risk |
|---|---|---|---|---|---|---|---|
| 43 | Tag editor scan | `MetadataEditorPanel` | `MetadataController.scan` → `MetadataScanWorker` | `metadata_processor.scan_folder` | `magic_auto_ops`, `tag_clean_*` | none | OK |
| 44 | Tag editor preview/apply | same | `MetadataController.apply_changes` → `MetadataApplyWorker` | `metadata_processor` write functions | tag_clean_* | none | OK (backup created — verified safe) |
| 45 | Tag backup/restore | apply path | `MetadataController.apply_changes:223-225` writes JSON | `~/.ytspot/tag_backups/` | — | none | S2-9 (no restore UI) |
| 46 | Physical filename rename | tag editor | `MetadataController.clean_filename` | regex sanitisation | tag_clean_filename_* | none | OK |
| 47 | Duplicate file scan | tag editor → `find_duplicates` | `MetadataController.find_duplicates` → `DuplicateDetectorWorker` | md5/size hash | — | none | OK |
| 48 | Duplicate file delete | `DuplicateFilesDialog` | `MetadataController.delete_duplicate_files` | `send2trash.send2trash` (fallback `unlink`) | — | none | OK (double-confirm + Recycle Bin verified) |

## Channel scrape

| # | Action | UI entry | Controller / Worker | Core | Config keys | Tests | Risk |
|---|---|---|---|---|---|---|---|
| 49 | YouTube channel tab discovery | URL paste → channel | `ChannelFlowController.discover` | `core/channel_tab_discoverer.py` | `cookies_file` | none | OK |
| 50 | Tab selection dialog | `TabSelectDialog` | `ChannelFlowController.scan` → `ChannelScrapeWorker` | `core/scraper.py` | — | none | OK |

## Updates / CLI / packaging

| # | Action | UI entry | Controller / Worker | Core | Config keys | Tests | Risk |
|---|---|---|---|---|---|---|---|
| 51 | Update checker | `AppWindow:443` startup | `UpdateWorker.run` | `UpdateChecker.check` | `check_updates` | none | **S0-1** (wrong default owner) |
| 52 | CLI | `cli.main` | `TerminalCallbacks` → `DownloadOrchestrator.run_batch` | same as GUI download | `cookies_file`, `output_dir` | partial | **S1-7** (parallel limit wrong), S2-7 (no `--version`/`--doctor`) |
| 53 | Tests / CI | `.github/workflows/tests.yml` | — | pytest | — | self | **S1-10** (P0 excluded; no Windows; missing 3.10) |
| 54 | Packaging / release | `pyproject.toml` | setuptools | — | — | none | OK (version aligned) |
| 55 | Privacy/security/legal wording | UI strings + README | — | i18n / docs | — | none | **S1-5, S1-6** (bypass/Anti-Ban wording) |

## Coverage by status

- **OK**: 33/55 actions
- **S0 risk**: 2 actions (download lifecycle, update checker)
- **S1 risk**: 12 actions (search 4×, output_dir, history platform, max_parallel CLI, .gitignore tests, wording, MB UA, ytmusic restore, etc.)
- **S2 risk**: 4 actions (Universal/scrape coverage, tag-restore UI, converter tests, polish)
- **S3 risk**: 2 actions (hardcoded HE folder names, scrape generality)
- **2 actions need verification**: lyrics_enabled UI toggle, replay_gain_enabled UI toggle (config keys exist; visual presence in Settings panel not confirmed)
