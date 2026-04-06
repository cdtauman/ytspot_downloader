"""
MIGRATION_GUIDE_module_consolidation.md
========================================
Phase 2 Task 3: Move downloader.py and playlist_parser.py into core/

Steps
-----

1. MOVE the files:
       mv  downloader.py       core/downloader.py
       mv  playlist_parser.py  core/playlist_parser.py

2. PLACE the shims at the OLD locations:
       cp  downloader_shim.py      downloader.py
       cp  playlist_parser_shim.py playlist_parser.py

3. UPDATE internal imports inside the moved files:
   In core/downloader.py, the existing imports are fine — it only imports
   from utils/ which is unchanged.

   In core/playlist_parser.py, the existing imports are fine — it imports
   from utils/ (unchanged).

4. UPDATE core/__init__.py if it exists — add:
       from core.downloader import DownloadEngine, DownloadRequest  # etc.
       from core.playlist_parser import PlaylistParser, classify_url  # etc.

5. VERIFY nothing breaks:
       python -c "from downloader import DownloadEngine; print('OK')"
       python -c "from core.downloader import DownloadEngine; print('OK')"
       python -c "from playlist_parser import classify_url; print('OK')"
       python -c "from core.playlist_parser import classify_url; print('OK')"
       pytest tests/ -v

6. GRADUALLY migrate imports in other files:
   Over time, change:
       from downloader import ...
   to:
       from core.downloader import ...

   The shim ensures both work simultaneously, so this can be done
   incrementally without a big-bang refactor.

Files that import from downloader.py (search for "from downloader import"):
   - ui/workers/download_worker.py
   - ui/app_window.py
   - core/download_orchestrator.py
   - core/services.py
   - test_integration.py

Files that import from playlist_parser.py (search for "from playlist_parser import"):
   - ui/workers/fetch_worker.py
   - ui/app_window.py
   - core/batch_importer.py
   - core/search_engine.py
   - core/playlist_sync.py
   - test_integration.py

Why shims instead of sed-replacing all imports at once:
   - Zero risk of breaking working code
   - External users/forks that import the old paths still work
   - Can be removed in a future major version bump
"""
