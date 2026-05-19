# AUDIT_UNUSED_OR_DEAD_CODE

Branch: `audit/full-line-audit`. Symbols with no callers via AST or repo-wide `rg` search, classified by certainty. Not all dead-code candidates are bugs — some are intentional public APIs, signature scaffolding for future work, or stubs. Classification:

- `unused` — confirmed no callers (direct, dynamic, test, CLI, docs). Safe to remove.
- `dynamic` — used through a string-based bus (Qt signal, `getattr`, callback protocol); AST cannot see it.
- `inert_stub` — file/symbol exists for backward compatibility but always returns a no-op value.
- `signature_only` — parameter is threaded through call chain but never consumed.

## Confirmed `unused` (safe to remove)

| Symbol | File:line | Notes / proposed action |
|---|---|---|
| `AppConfig.window_geometry` (getter + setter) | `config.py:309-314` | Config migration 2 (`config_migrate.py:60`) removes the underlying key. The property always reads `""`. No callers. **Delete the property pair.** |
| `DownloadEngine.download_async` | `core/downloader.py:462-474` | Public-looking helper that spawns a daemon thread. No caller in repo (`rg "download_async\("` ⇒ 0 hits outside the def). All download paths go through `DownloadOrchestrator → engine.download(...)`. **Delete or keep as `# Public API: kept for direct script use` — recommend delete.** |
| `error_handler.run_preflight` and `PreflightResult` | `error_handler.py:312-355` | Well-designed startup-check function. `rg "run_preflight\("` ⇒ 0 callers. `main.py` does not call it. This is **a feature regression / missed UX**, not pure dead code — see `AUDIT_RELEASE_BLOCKERS.md` S2-3 to wire it up rather than delete it. |

## `signature_only` (parameter wired but never consumed)

| Symbol | File:line | Notes |
|---|---|---|
| `DownloadRequest.randomize_user_agent` | `core/downloader.py:177` | Explicit comment: `# rotate UA string per download (anti-ban) (kept for signature but unused)`. Passed from `download_controller.py:311` and `403` into `_build_base_opts(...randomize_user_agent=req.randomize_user_agent...)` (`utils/yt_dlp_opts.py:50`), where the parameter has the comment `# Kept for signature compatibility, but unused`. The config key `randomize_user_agent` (`config.py:101,482-487`) is exposed in settings. **The whole pipe is inert.** Either implement the feature (rotate UA in yt-dlp opts) or remove the config key + parameter. Defer to v1.1 — touches user-facing settings. |

## `inert_stub`

| Symbol | File:line | Notes |
|---|---|---|
| `utils/impersonate.py` (`CURL_CFFI_AVAILABLE`, `ImpersonateTarget`) | `utils/impersonate.py:5-6` | Module docstring literally says "Dummy file for backward compatibility". Always returns `False / None`. **Used** by `core/playlist_parser.py:48` (`from utils.impersonate import ...`). Since the stub returns `False`/`None`, the `_CURL_CFFI_AVAILABLE` branch in `playlist_parser` is always dead. **Recommend** (v1.1): either delete the stub + the dead branch in `playlist_parser`, or actually install `curl_cffi` and use it. Not S0/S1. |

## `dynamic` (no direct call, but reachable through Qt / callback protocol)

These are *not* dead — they're invoked through string-based dispatch and confirmed live by the receiving side.

- `_SignalAdapter.on_track_progress / on_track_speed / on_track_status / on_track_finished / on_track_error / on_overall_progress / on_metrics / on_status_message / on_job_count_changed / on_batch_finished / on_track_thumbnail` (`ui/workers/download_worker.py:60-91`) — called by `DownloadOrchestrator._safe_cb` via `getattr(self._cb, method)`. Each method confirmed reachable.
- `TerminalCallbacks.on_*` (`cli.py:60-99`) — same pattern, dispatched by `DownloadOrchestrator._safe_cb` when CLI runs.
- All Qt `Signal` definitions in `ui/controllers/*.py`, `ui/workers/*.py`, `ui/panels/*.py`, `ui/dialogs/*.py` — each connected at least once in the consumer panel/window. Cross-checked via `rg "<signal_name>\.connect"`.
- All `i18n` translation keys in `ui/i18n.py` — invoked through `t("key")` at runtime. AST cannot resolve string-keyed lookup. 80+ keys, all confirmed present in EN and HE.

## Suspected but not confirmed (need a fuller cross-ref pass)

These appear unreferenced in the main code paths I read; flagged for a future symbol pass:

- `MetadataController.cancel_apply` (`ui/controllers/metadata_controller.py:490`) — no caller visible in `MetadataEditorPanel` slices read so far. Confirm in Phase 4 full read.
- `core/replay_gain.analyse_and_embed` — called from `downloader._run_final_pipeline` (line 997) only when `req.replay_gain=True`. The config default is `False` and no UI toggle was seen in `settings_panel` quick scan. Off by default ≠ dead, but no UI to enable it would make it effectively unreachable. Verify in Phase 3 action-map.
- `core/lyrics_embedder.embed_lyrics` — same pattern as ReplayGain. Off by default; confirm UI toggle exists.
- `utils/network_probe.py` — only contains a constant `_PROBE_URL` and (presumably) a function. Did not full-read. Verify.

## Disposition

| Bucket | Count |
|---|---|
| `unused` (recommend delete) | 3 (window_geometry, download_async, optional run_preflight delete) |
| `signature_only` (delete or implement) | 1 (randomize_user_agent pipe) |
| `inert_stub` (refactor or implement) | 1 (`impersonate.py`) |
| `dynamic` (verified live) | ~30+ Qt signals + callback methods + 80+ i18n keys |
| `needs verification` | 4 (cancel_apply, lyrics, replay_gain, network_probe) |

None of the confirmed dead symbols are S0/S1. Deferred to a single `chore: remove dead code` commit after S0/S1 fixes land.
