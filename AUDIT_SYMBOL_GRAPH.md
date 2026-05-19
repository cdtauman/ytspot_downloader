# AUDIT_SYMBOL_GRAPH

Branch: `audit/full-line-audit`. Built by `tools/audit/symbol_scan.py` (AST extractor) over all 99 tracked `.py` files, cross-referenced with repo-wide `rg` for callers (direct calls, Qt `signal.connect`, decorator/dynamic uses, CLI entry points, test references).

The full per-symbol TSV is at `tools/audit/_symbols.tsv` (2,985 rows). This document summarises the graph and flags symbols of audit interest.

## Counts

| Kind | Count |
|---|---|
| `class` | 161 |
| `method` | 1,084 |
| `func` (module-level) | 186 |
| `const` (module-level) | 249 |
| `classvar` | 204 |
| `from` (imports) | 945 |
| `import` (imports) | 155 |
| **Total symbol rows** | **2,985** |

## Top 10 files by symbol count

| Symbols | File |
|---|---|
| 201 | `ui/panels/metadata_editor_panel.py` |
| 137 | `ui/app_window.py` |
| 132 | `config.py` |
| 77 | `ui/panels/settings_panel.py` |
| 72 | `core/downloader.py` |
| 71 | `ui/components/track_card.py` |
| 67 | `tests/test_core.py` |
| 66 | `core/search_engine.py` |
| 66 | `ui/panels/converter_panel.py` |
| 66 | `ui/panels/queue_panel.py` |

## Module entry-points (declared in `pyproject.toml`)

- `ytspot = "main:main"` → `main.main()` (`main.py:30`)
- `ytspot-cli = "cli:main"` → `cli.main()` (`cli.py:198`)

Plus `__main__` smoke-test blocks (not packaged as entry points):

- `cli.py:330`, `main.py:95` — real entry points (used)
- `core/playlist_parser.py`, `core/update_checker.py`, `core/search_engine.py`, `core/batch_importer.py`, `core/history_db.py`, `ui/components/update_banner.py` — module self-tests; not reached in normal app flow.

## Public APIs that cross module boundaries (key bus stops)

- `config.AppConfig` — used by every controller, worker, panel, service.
- `core.services.ServiceContainer.create_default` — single factory; called from `main.py:61`.
- `core.downloader.DownloadEngine.download(req)` — used by `DownloadOrchestrator._download_one` and (by design) any CLI-style caller.
- `core.download_orchestrator.DownloadOrchestrator.run_batch` — invoked by `ui/workers/download_worker.run` and by `cli.main`.
- `core.playlist_parser.PlaylistParser.parse` — entry to URL resolution; used by `fetch_controller`, `cli.py`, tests.
- `core.search_engine.SearchEngine.search_youtube(_categorized|_music)`, `.search_spotify(_categorized)` — invoked by `ui/workers/search_worker.SearchWorker.run`.
- `core.history_db.HistoryDB.insert / fetch_all / search / export_csv / delete / clear_all` — used by `download_orchestrator`, `ui/panels/history_panel`.
- `core.update_checker.UpdateChecker.check` — invoked by `ui/workers/update_worker.run`.
- `error_handler.classify_error` — used by `download_orchestrator`, `download_controller`, workers.
- `ui.i18n.t(key, **kwargs)` — used by every panel, dialog, controller for translated strings.

## Qt signal/slot bus (high-traffic signals)

| Emitter (file:line) | Signal | Connected by |
|---|---|---|
| `DownloadController.batch_started / batch_finished / show_error_dialog / show_success_bar / cancel_visible / downloading_changed / status_update / metrics_update / overall_progress / job_count_changed / browser_lock_warning / track_thumbnail` | various | `AppWindow._connect_download_signals` |
| `DownloadWorker.track_progress / track_speed / track_status / track_finished / metrics / status_msg / job_error / all_finished / track_thumbnail / overall_progress / job_count_changed` | per-track | `DownloadController.start_batch` |
| `SearchPanel.add_to_queue_requested / drill_down_requested / search_requested` | UI | `AppWindow` |
| `SearchWorker.result_ready / status_msg / finished / error` | per-result | `AppWindow.on_search_started` (creates worker), connects to SearchPanel.add_result |
| `MetadataController.scan_started / track_discovered / scan_complete / auto_rules_applied / tags_modified / apply_started / apply_progress / apply_file_done / apply_complete / apply_error / status_update / duplicate_scan_progress / duplicate_scan_complete / duplicate_scan_error / duplicate_delete_complete` | tag editor | `MetadataEditorPanel.connect_controller` |
| `UpdateWorker.update_available` | one-shot | `AppWindow._on_update_available` (shows `UpdateBanner`) |
| `OfflineMonitor.online_changed` | network | `AppWindow._on_offline_changed` (shows `OfflineBanner`) |
| `ClipboardWorker.url_detected` | clipboard | `AppWindow._on_clipboard_url` |

All Qt signal connections discovered by `rg "\.(connect|emit)\("`. Signals not in any `.connect(...)` call are flagged in the dead-code doc.

## Notable dynamic / non-AST dispatch

- `core/services.py` — direct attribute access (`svc.config`, `svc.db`, `svc.engine`); not callable via `getattr`.
- `core/download_orchestrator.py:_safe_cb` — `getattr(self._cb, method, None)` then call. Method names are strings (`"on_track_progress"`, etc.). Adds names to the call graph that AST alone misses.
- `ui/workers/download_worker._SignalAdapter` — implements the callbacks protocol by forwarding to Qt signals; methods discovered only by string lookup.
- `ui/i18n.t(key)` — string-keyed translation lookup. 80+ keys. Coverage is exercised at runtime; no AST cross-ref.
- `core/playlist_parser.py:48` — imports `ImpersonateTarget, CURL_CFFI_AVAILABLE` from `utils/impersonate.py`. The latter is a 6-line stub that always returns `None`/`False`. The import is "live" (AST sees it) but the values are inert.
