"""
ui/i18n.py
Localization helper for the app.

This is intentionally lightweight: translation lookup by key plus a
small API to coordinate language + layout direction at startup or when
the user changes it in Settings.

Public API:
    t(key, **kwargs)                  — translate a key with optional formatting
    set_language(lang)                — update active language code (no side effects)
    current_language()                — read active language code
    apply_language(app, lang)         — single entry point used at startup and
                                        when the user picks a different language;
                                        updates translation state, app-wide layout
                                        direction, and emits language_changed
    request_language_restart(app, lang) — restart the app process with the new
                                          language so every widget rebuilds in it
    language_manager()                — singleton QObject exposing the
                                        ``language_changed(str)`` signal that
                                        widgets can connect to for future
                                        live-retranslation work
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Dict, Optional, Set

_current: str = "en"
_log = logging.getLogger("ui.i18n")
_warned_keys: Set[str] = set()

TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "en": {
        # ── Navigation ──────────────────────────────────────────────────────────
        "app_name": "YTSpot Downloader",
        "queue": "Queue",
        "search": "Search",
        "history": "History",
        "settings": "Settings",
        "tag_editor": "Tag Editor",
        "converter": "Converter",

        # ── Download bar ────────────────────────────────────────────────────────
        "no_tracks_selected": "No tracks selected",
        "download_selected": "⬇  Download Selected",
        "download_downloading": "⬇  Downloading…",
        "selected_of_total": "{selected} of {total} track{plural} selected",

        # ── Error dialogs ───────────────────────────────────────────────────────
        "ffmpeg_missing_title": "⚠️ FFmpeg Not Found",
        "ffmpeg_missing_detail": (
            "FFmpeg is required to download audio files but is not installed.\n\n"
            "Downloads will fail unless you install FFmpeg.\n\n"
            "Windows:  choco install ffmpeg  (or scoop install ffmpeg)\n"
            "macOS:    brew install ffmpeg\n"
            "Linux:    sudo apt install ffmpeg"
        ),

        "unsupported_url_title": "Invalid URL",
        "unsupported_url_detail": (
            "Please enter a valid http:// or https:// URL.\n\n"
            "YouTube, YouTube Music, and Spotify are fully supported.\n"
            "Thousands of additional sites are supported via yt-dlp.\n\n"
            "Example:\n  • youtube.com/watch?v=…"
        ),
        "unsupported_generic_title": "Unsupported Site / Listing Page",
        "unsupported_generic_detail": (
            "yt-dlp does not natively support this URL, or it is a listing page.\n\n"
            "Try using the Spider tool (🕷) in the URL bar to scan the page for embedded media links instead."
        ),

        "no_internet_title": "No Internet Connection",
        "no_internet_detail": "Cannot reach the internet.\n\nPlease check your network connection and try again.",

        "cannot_write_output_title": "Cannot Write to Output Folder",
        "cannot_write_output_detail": "The folder cannot be created:\n{path}\n\nError: {exc}",

        # ── Status bar ──────────────────────────────────────────────────────────
        "ready": "Ready.",
        "cancel": "Cancel",
        "fetching_status": "🔍  Fetching…",
        "fetch_cancelled": "🚫  Fetch cancelled.",
        "starting_downloads": "⬇  Starting {n} download{plural}…",
        "download_progress_count": "⬇  Downloading {current} / {total}…",
        "cancelling": "🚫  Cancelling…",
        "tracks_loaded": "✅  {n} track{plural} loaded  ·  {summary}",
        "added_to_queue": "✅  Added to queue: {title}",
        "clipboard_url_detected": "📋  Clipboard URL detected — press  Fetch Info  to load.",
        "search_error": "❌  Search: {message}",
        "scraper_error": "❌  Scraper: {message}",
        
        # ── Browser sign-in (authentication for restricted content) ────────────
        "bot_bypass_title": "Sign-in Required",
        "bot_bypass_instructions": (
            "YouTube or the target server is asking for verification before serving this URL. "
            "Please solve any CAPTCHAs and, if needed, sign in to your account below to confirm "
            "your age or access members-only content. Once the video page loads successfully, "
            "click 'Save Cookies' to continue downloading."
        ),
        "bot_bypass_save": "Save Cookies",
        "bypass_bot_btn": "Sign in to YouTube 🔑",

        # ── URL bar ─────────────────────────────────────────────────────────────
        "fetching_button": "Fetching…",
        "fetch_info_button": "Fetch Info",
        "paste_tooltip": "Paste from clipboard",
        "batch_import_tooltip": "Batch import URLs from a .txt file",
        "scrape_tooltip": "Scan this page for embedded media links",
        "clipboard_on_tooltip": "Clipboard monitor is ON — auto-detecting media URLs",
        "clipboard_off_tooltip": "Clipboard monitor is OFF — enable in Settings",
        "url_placeholder": "Paste a YouTube or Spotify URL, or type a search query…",

        # ── Batch import ────────────────────────────────────────────────────────
        "batch_import_failed": "Batch Import Failed",
        "no_urls_found": "⚠  No supported URLs found in {filename}",
        "batch_multi_loaded": "📄  {count} URLs imported. First URL loaded — press Fetch Info to begin.",

        # ── Scraper ─────────────────────────────────────────────────────────────
        "scrape_multi_found": "🕷  {count} media link(s) found. First URL loaded — press Fetch Info to begin.",

        # ── Settings panel ──────────────────────────────────────────────────────
        "appearance": "Appearance",
        "theme": "Theme",
        "switch_theme": "Switch Theme",
        "theme_tooltip": "Cycles through: 🌙 Dark  →  ☀️ Light  →  ⚫ OLED",
        "language": "Language",
        "select_language": "Select UI language",

        "downloads_group": "Downloads",
        "embed_thumbnail": "Embed Thumbnail",
        "embed_thumbnail_desc": "Write cover art into the downloaded file's metadata (ID3 / MP4 atoms)",
        "embed_metadata": "Embed Metadata",
        "embed_metadata_desc": "Write title, artist, album, and year tags into the file",

        "features": "Features",
        "clipboard_monitor": "Clipboard Monitor",
        "clipboard_monitor_desc": (
            "Auto-detect YouTube / Spotify URLs copied to the clipboard "
            "and populate the URL bar automatically"
        ),
        "check_updates": "Check for Updates on Launch",
        "check_updates_desc": (
            "Silently query GitHub Releases and show a banner "
            "when a newer version is available"
        ),

        "search_group": "Search",
        "max_search_results": "Max Search Results (Legacy)",
        "max_search_results_desc": "Maximum number of results to fetch per search query (1 – 50)",
        "max_youtube_results": "Max YouTube Results",
        "max_youtube_results_desc": "Maximum number of results to fetch for YouTube searches (1 – 100)",
        "max_spotify_results": "Max Spotify Results",
        "max_spotify_results_desc": "Maximum number of results to fetch for Spotify searches (1 – 100)",
        "spotify_proxy": "Spotify Proxy Server URL",
        "spotify_proxy_desc": "URL to your Spotify proxy server (e.g. http://localhost:8000)",

        "spotify_group": "Spotify",
        "spotify_proxy_api_key": "App API Key",
        "spotify_proxy_api_key_desc": "Security token for your proxy server (X-App-Token)",

        "authentication": "Authentication",
        "cookies_file": "Cookies File",
        "cookies_file_unset": "Not set — click Browse to select a cookies.txt file",
        "cookies_tooltip": (
            "Export cookies from your browser using the\n"
            "'Get cookies.txt LOCALLY' extension, then select\n"
            "the file here for age-gated or private content."
        ),
        "browse": "Browse…",
        "clear_cookies": "Clear",
        "clear_cookies_title": "Clear Cookies File",
        "clear_cookies_desc": "Remove the currently configured cookies file path",

        "about": "About",
        "open_github": "Open on GitHub",
        "open_github_desc": "Version {version}  ·  MIT Licence",
        "feedback": "Feedback & Bug Reports",
        "feedback_desc": "Open an issue on GitHub",
        "report_issue": "Report Issue",

        # ── History panel ───────────────────────────────────────────────────────
        "search_history_placeholder": "Search history by title or artist…",
        "export_csv": "Export CSV",
        "clear_history": "Clear History",
        "records_count": "{n} record{plural}",
        "col_date": "Date",
        "col_title_artist": "Title / Artist",
        "col_platform": "Platform",
        "col_type": "Type",
        "col_duration": "Duration",
        "col_size": "Size",
        "col_actions": "Actions",
        "history_empty_hint": (
            "Your download history will appear here.\n"
            "Completed downloads are logged automatically."
        ),
        "export_dialog_title": "Export history as CSV",
        "export_complete": "Export Complete",
        "export_complete_msg": "Exported {count} record(s) to:\n{path}",
        "export_failed": "Export Failed",
        "export_failed_msg": "Could not write CSV file:\n{error}",
        "clear_history_title": "Clear Download History",
        "clear_history_confirm": "This will permanently delete all history records.\n\nAre you sure?",

        # ── Search panel ────────────────────────────────────────────────────────
        "search_placeholder": "Search for tracks, albums, artists…",
        "searching": "Searching…",
        "no_results": "No results found.",
        "results_count": "{n} result{plural}",
        "clear_results": "Clear results",
        "search_empty_hint": (
            "Search for music, videos, or playlists.\n"
            "Select a platform and type your query above."
        ),
        "platform_youtube": "YouTube",
        "platform_ytmusic": "YouTube Music",
        "platform_spotify": "Spotify",
        "platform_both": "Both",

        "search_filter_all": "All",
        "search_filter_tracks": "Tracks",
        "search_filter_albums": "Albums",
        "search_filter_artists": "Artists",
        "search_filter_playlists": "Playlists",
        "search_filter_channels": "Channels",

        # ── Queue panel ─────────────────────────────────────────────────────────
        "no_tracks_loaded": "No tracks loaded",
        "select_deselect_all": "Select / Deselect All",
        "clear_completed": "Clear completed",
        "clear_selected": "Clear selected",
        "clear_all": "Clear all",
        "clear_options": "Clear...",
        "pause_all": "Pause All",
        "resume_all": "Resume All",
        "sel_of_n": "{sel} / {n} selected",
        "queue_empty_hint": (
            "Paste a YouTube or Spotify URL above\n"
            "and press  Fetch Info  to load tracks."
        ),

        # ── Update banner ───────────────────────────────────────────────────────
        "update_available": "🎉  Update available",
        "view_release": "View Release",
        "download_btn": "Download",
        "dismiss_tooltip": "Dismiss",

        # ── Browser cookies ─────────────────────────────────────────────────────
        "browser_cookies":      "Browser Cookies Source",
        "browser_cookies_desc": "Read cookies from your browser to authenticate access to age-restricted or members-only content",
        "disabled":             "Disabled",

        # ── Release types ───────────────────────────────────────────────────────
        "release_album":        "Album",
        "release_single":       "Single",
        "release_ep":           "EP",
        "release_playlist":     "Playlist",
        "release_compilation":  "Compilation",
        "tracks":               "tracks",
        "items":                "items",

        # ── System tray ─────────────────────────────────────────────────────────
        "tray_tooltip": "YTSpot Downloader",
        "tray_open": "Open",
        "tray_cancel_all": "Cancel All Downloads",
        "tray_quit": "Quit",
        "tray_all_done": "All downloads complete!",

        # ── Auth / cookie wizard ────────────────────────────────────────────────
        "auth_wizard_open_btn": "🔑 Open Sign-in Wizard (recommended)",
        "auth_wizard_close_btn": "Close",
        "auth_wizard_manual_btn": "🔧 Manual fix in browser",
        "playwright_required_title": "Playwright Chromium Required",
        "auth_wizard_title": "Site Sign-in Wizard",
        "auth_wizard_url_prompt": "Enter the URL you want to sign into:",
        "auth_wizard_browser_info": (
            "A browser window will now open.\n\n"
            "1. Sign in to your account at: {url}\n"
            "2. After signing in, simply close the browser window.\n\n"
            "The software will save your sign-in details automatically."
        ),
        "auth_wizard_success_title": "Sign-in successful",
        "auth_wizard_success_msg": "Sign-in details saved. You may now resume downloading.",
        "auth_wizard_aborted_title": "Wizard closed without saving",
        "auth_wizard_aborted_msg": "No cookies were saved. The wizard may have been closed before sign-in.",
        "browser_locked_title": "{browser} is open",
        "browser_locked_msg": (
            "{browser} is currently open.\n\n"
            "Windows does not allow apps to access cookies while the browser is running.\n"
            "Close all browser windows and try again."
        ),
        "browser_locked_retry_btn": "Closed, retry",
        "cancel_btn": "Cancel",

        # ── Track card tooltips ─────────────────────────────────────────────────
        "card_remove_tooltip": "Remove from queue",
        "card_pause_tooltip": "Pause download",
        "card_resume_tooltip": "Resume download",

        # ── Options bar labels ──────────────────────────────────────────────────
        "options_format_label": "Format:",
        "options_quality_label": "Quality:",
        "options_codec_label": "Codec:",
        "options_save_label": "Save to:",
        "options_clipboard_label": "Clipboard:",

        # ── Converter panel ─────────────────────────────────────────────────────
        "converter_cancel_btn": "⏹  Cancel",
        "converter_convert_all_btn": "Convert All",

        # ── Duplicate files dialog ──────────────────────────────────────────────
        "duplicates_manage_title": "🔍 Manage Duplicate Files",
        "duplicates_strategy_size": "by file size (fast)",
        "duplicates_strategy_md5": "by MD5 content (precise)",
        "duplicates_header": (
            "Found <b>{n_files}</b> duplicate files in <b>{n_groups}</b> "
            "groups (strategy: {strat}) | scan time: {elapsed:.1f}s"
        ),
        "duplicates_hint": "☑ Checked = keep file    ☐ Unchecked = delete file",
        "duplicates_keep_all_btn": "✅ Keep all",
        "duplicates_keep_all_tooltip": "Mark all files in every group for keep",
        "duplicates_group_label": "Group {n}  —  {count} duplicate files",
        "duplicates_apply_btn": "🗑 Delete & clean up",
        "duplicates_nothing_title": "Nothing to delete",
        "duplicates_nothing_msg": (
            "All files are marked for keeping.\n"
            "Uncheck files you want to delete."
        ),
        "duplicates_confirm_title": "Final delete confirmation",
        "duplicates_confirm_msg": (
            "Warning: this will permanently delete the {n} marked files from disk.\n\n"
            "Are you sure?"
        ),
        "duplicates_confirm_yes": "Yes, delete",
        "duplicates_confirm_no": "No, go back",

        # ── Conflict resolution dialog ──────────────────────────────────────────
        "conflict_sources_count": "{n} sources",
        "conflict_dialog_title": "Manage Duplicates",
        "conflict_dialog_subtitle": "Manage Duplicates — {n} overlapping videos",
        "conflict_videos_header": "📹 Videos / Shorts / Streams",
        "conflict_playlists_header": "📋 Playlists",
        "conflict_explanation": (
            "The following videos were found in more than one source. "
            "Check ✓ the copies you want to download.\n"
            "Different copies will be saved to different folders."
        ),
        "conflict_ok_btn": "Confirm — download all checked",
        "conflict_keep_videos_btn": "✓ Keep in Videos",
        "conflict_keep_playlists_btn": "✓ Keep in Playlists",
        "conflict_keep_both_btn": "✓ Keep both",
        "conflict_clear_all_btn": "✗ Clear all",

        # ── Restart prompt ──────────────────────────────────────────────────────
        "restart_required_title": "Restart required",
        "restart_required_msg": (
            "The language change will take effect after a restart.\n"
            "Restart now?"
        ),
        "restart_now_btn": "Restart now",
        "restart_later_btn": "Later",

        # ── Tray notifications ──────────────────────────────────────────────────
        "tray_minimized_title": "YTSpot Downloader",
        "tray_minimized_message": "Running in the background. Double-click the tray icon to restore.",

        # ── Converter panel (extended) ──────────────────────────────────────────
        "converter_header_title": "🔄  Local File Converter",
        "converter_subtitle": (
            "Convert audio files already on your disk to a different format. "
            "Drag files here or use the Add button — no internet connection needed."
        ),
        "converter_drop_hint": "⬆  Drop audio files here or click Add Files",
        "converter_add_files": "Add Files",
        "converter_clear_all": "Clear All",
        "converter_output_format": "Output Format:",
        "converter_bitrate": "Bitrate:",
        "converter_same_folder": "Same folder as source",
        "converter_output_folder": "Output Folder",
        "converter_select_output_dialog": "Select Output Folder",
        "converter_select_files_dialog": "Select Audio Files",
        "converter_audio_files_filter": "Audio Files",
        "converter_all_files_filter": "All Files",

        # ── Settings panel (extended) ───────────────────────────────────────────
        "clear": "Clear",
        "select_cookies_file": "Select Cookies File",
        "accessibility_mode": "Accessibility Mode",
        "accessibility_mode_desc": "High-contrast colours and enhanced keyboard navigation (restart recommended)",
        "concurrent_downloads": "Concurrent Downloads",
        "concurrent_downloads_desc": "Number of tracks downloaded simultaneously (1 – 5)",
        "playlist_behaviour": "Playlist Behaviour",
        "playlist_subfolders": "Playlist Sub-folders",
        "playlist_subfolders_desc": "Create a named subfolder for each playlist download",
        "track_index_prefix": "Track Index Prefix",
        "track_index_prefix_desc": "Prefix filenames with 01-, 02- … to preserve playlist order",
        "duplicate_detection": "Duplicate Detection",
        "duplicate_detection_desc": "Action when the output file already exists",
        "duplicate_skip": "Skip silently",
        "duplicate_warn": "Show warning dialog",
        "duplicate_overwrite": "Always overwrite",
        "system_integration": "System Integration",
        "minimise_to_tray": "Minimise to System Tray",
        "minimise_to_tray_desc": "Keep app running in the background when window is closed",
        "global_hotkeys": "Global Hotkeys",
        "global_hotkeys_desc": "Register system-wide keyboard shortcuts (requires restart)",
        "advanced_audio_processing": "⚙  Advanced Audio Processing",
        "sponsorblock_title": "SponsorBlock – Remove Non-Music Segments",
        "sponsorblock_desc": "Automatically cut sponsor reads, intros, and outros from YouTube music videos using the SponsorBlock API",
        "musicbrainz_title": "MusicBrainz Metadata Enrichment",
        "musicbrainz_desc": "After downloading, query MusicBrainz for genre, label, ISRC, release year, and country",
        "lyrics_title": "Lyrics Downloader  [Advanced]",
        "lyrics_desc": "Fetch lyrics automatically and embed them into the file's metadata tags (requires: pip install syncedlyrics)",
        "replay_gain_title": "Replay Gain Analysis  [Advanced]",
        "replay_gain_desc": "Analyse loudness and embed REPLAYGAIN_TRACK_GAIN tags for normalised playback volume across tracks (requires: rsgain or pip install pyloudnorm soundfile)",
        "square_thumbnails_title": "Square Thumbnail Crop  [Advanced]",
        "square_thumbnails_desc": "Crop the embedded 16:9 YouTube thumbnail to a 1:1 square before embedding — ideal for standard music players (requires: pip install Pillow)",
        "youtube_proxy_title": "YouTube Proxy",
        "youtube_proxy_desc": "HTTP/HTTPS/SOCKS proxy for YouTube downloads (e.g. http://127.0.0.1:7890). Leave empty for direct connection.",
        "accent_color": "Accent Color",
        "expand_square_to_rectangle_title": "Expand square thumbnails to rectangle for video (MP4)",
        "expand_square_to_rectangle_desc": (
            "When downloading a video file with a square thumbnail at the source (like Spotify), "
            "the image will be expanded to a 16:9 rectangle by creating an elegant blurred background."
        ),
        "external_login_title": "External Site Login (Cookies)",
        "external_login_desc": "Sign in to YouTube or any other site directly from the app to save access details and resolve verification challenges.",
        "external_login_now_btn": "Sign in now",

        # ── Channel import (tab selection dialog) ───────────────────────────────
        "import_channel_title": "Import YouTube Channel",
        "import_channel_discovering": "Discovering available tabs…",
        "import_channel_cancel": "Cancel",
        "import_channel_scan_selected": "Scan selected tabs",
        "import_channel_items_count": "{n:,} items",
        "import_channel_error_prefix": "Error discovering tabs: {error}",
        "import_channel_scan_complete": "Scan complete — {n:,} items",
        "import_channel_with_name": "Import: {name}",
        "import_channel_tabs_found": "Found {n} tabs — choose what to scan:",
        "import_channel_scanning_selected": "Scanning selected tabs…",
        "import_channel_scanning_tab": "Scanning: {tab}…",
        "import_channel_expanding_playlists": "Expanding playlists: {current}/{total}",
        "import_channel_scrape_error": "Scrape error: {msg}",

        # ── Search result card ──────────────────────────────────────────────────
        "search_card_add_btn": "＋  Add",
        "search_card_browse_btn": "Browse  →",

        # ── Tag Editor: dialogs / headers ───────────────────────────────────────
        "meta_auto_settings_title": "Auto-Order Settings",
        "meta_clean_settings_title": "Clean-up Settings (aggressive)",
        "meta_auto_header": "Choose which actions the 'Auto-Order' button will perform:",
        "meta_auto_album_note": "(Album from folder name is always active)",
        "meta_clean_title_group": "Title clean-up (Title)",
        "meta_clean_filename_group": "Physical filename clean-up (Filename)",

        # ── Tag Editor: auto-order operations ───────────────────────────────────
        "meta_op_title_strip_label": "Copy filename to title (without number)",
        "meta_op_title_strip_desc": "Takes the existing filename and copies it into the 'title' field, removing leading numbers (e.g. '01 song' becomes 'song').",
        "meta_op_title_full_label": "Copy filename to title (including number)",
        "meta_op_title_full_desc": "Takes the existing filename and copies it into the 'title' field exactly as it is.",
        "meta_op_normalize_spaces_label": "Remove double spaces and underscores from title",
        "meta_op_normalize_spaces_desc": "Scans the title, replaces underscores (_) with spaces, and removes double or extra spaces.",
        "meta_op_track_num_label": "Extract track number from filename",
        "meta_op_track_num_desc": "Looks for a number at the start of the filename (e.g. '03') and saves it as the track number.",
        "meta_op_split_at_label": "Split filename into 'artist' and 'title'",
        "meta_op_split_at_desc": "Detects a hyphen (-) in the filename. The part before becomes 'artist', the part after becomes 'title'.",
        "meta_op_album_artist_label": "Copy 'artist' to 'album artist'",
        "meta_op_album_artist_desc": "Copies each track's 'artist' into the 'album artist' field too (important for correct album sorting in players).",
        "meta_op_strip_junk_label": "Clean junk words from title",
        "meta_op_strip_junk_desc": "Removes common YouTube additions from the title like '(Official Video)', '[HD]', or 'Lyrics'.",
        "meta_op_clear_comments_label": "Clear 'comments' tag",
        "meta_op_clear_comments_desc": "Completely clears whatever is in the song's comments field.",
        "meta_op_clear_track_num_label": "Clear 'track number' tag",
        "meta_op_clear_track_num_desc": "Completely clears the song's track number.",
        "meta_op_clear_year_label": "Clear 'year' tag",
        "meta_op_clear_year_desc": "Clears the release year from the tags.",
        "meta_op_clear_genre_label": "Clear 'genre' tag",
        "meta_op_clear_genre_desc": "Clears the music style (genre) from the tags.",
        "meta_op_clean_filename_label": "Clean physical filename",
        "meta_op_clean_filename_desc": "Cleans the filename itself: removes underscores, strips anything inside parentheses () or [], and normalizes double spaces.",
        "meta_op_strip_filename_numbering_label": "Remove numbering from physical filename",
        "meta_op_strip_filename_numbering_desc": "Removes leading numbering from the physical filename (like '01-', '01 -', or '01_').",

        # ── Tag Editor: buttons / labels ────────────────────────────────────────
        "meta_cancel": "Cancel",
        "meta_ok": "OK",
        "meta_save_ok": "Save",
        "meta_browse_folder": "📁 Choose Folder",
        "meta_no_folder_selected": "No folder selected",
        "meta_include_subdirs": "Include subfolders",
        "meta_auto_btn": "🪄 Auto-Order",
        "meta_apply_changes": "✅ Apply Changes",
        "meta_revert_changes": "↩ Revert Changes",
        "meta_find_duplicates": "🔍 Find Duplicates",
        "meta_no_folder_scanned": "No folder scanned",
        "meta_files_folders_header": "📂 Files and Folders",
        "meta_auto_cfg_tooltip": "Configure what Auto-Order will perform",
        "meta_dupes_tooltip": "Scan the folder for duplicate music files",
        "meta_clean_cfg_tooltip": "Clean-up settings",

        # ── Tag Editor: inspector ──────────────────────────────────────────────
        "meta_select_files_prompt": "Select files\nor a folder\nto edit",
        "meta_all_checked_files": "All checked files",
        "meta_apply_artist_group": "Apply Artist",
        "meta_artist_placeholder": "Artist name…",
        "meta_apply_artist_btn": "✅ Apply Artist to Selected",
        "meta_apply_album_group": "Apply Album",
        "meta_album_placeholder": "Album name…",
        "meta_apply_album_btn": "✅ Apply Album to Selected",
        "meta_tracks_selected_count": "{n} tracks selected",
        "meta_edit_tags_group": "Edit Tags",
        "meta_mixed_placeholder": "empty / mixed",
        "meta_field_title": "Title:",
        "meta_field_artist": "Artist:",
        "meta_field_album": "Album:",
        "meta_field_album_artist": "Album Artist:",
        "meta_field_track": "Track:",
        "meta_apply_to_selection": "✅ Apply to Selection",
        "meta_rename_group": "Rename File",
        "meta_rename_note": "Rename the physical file to match the new title",
        "meta_rename_btn": "📝 Rename file to match title",
        "meta_actions_on_selected": "Actions on Selected",

        # ── Tag Editor: clean-up checkboxes ────────────────────────────────────
        "meta_clean_brackets": "Clean brackets with junk (like [HD] etc.)",
        "meta_clean_english_junk": "Clean English junk words (Official, Audio, 4K, Prod...)",
        "meta_clean_hebrew_junk": "Clean Hebrew junk words (cover, remix, live performance...)",
        "meta_clean_punctuation": "Fix spacing, extra hyphens, and pipe separators (|)",
        "meta_clean_filename_brackets": "Smart bracket removal (delete junk, keep feat. etc.)",
        "meta_clean_filename_brackets_tooltip": "If off, blindly removes all brackets including their content.",
        "meta_clean_filename_domains": "Clean download-site residue (y2mate, yt1s, SPOTIFY-DL...)",
        "meta_clean_filename_emojis": "Clean problematic emojis and special characters (!@#$)",
        "meta_clean_filename_spaces": "Fix hyphens and double spaces ( - - )",

        # ── Tag Editor: status / progress / errors ─────────────────────────────
        "meta_choose_music_folder": "Choose Music Folder",
        "meta_scanning": "Scanning…",
        "meta_searching_duplicates": "Searching for duplicates…",
        "meta_searching_duplicates_progress": "Searching for duplicates… {done}/{total}  ({eta})",
        "meta_writing_tags_progress": "Writing tags… {done}/{total}",
        "meta_done_success_base": "Done: {success} succeeded",
        "meta_done_failed_suffix": ", {fail} failed",
        "meta_done_skipped_suffix": ", {skip} skipped",
        "meta_done_summary_title": "Success",
        "meta_done_with_errors_title": "Completed with errors",
        "meta_no_duplicates_found": "No duplicates found ({elapsed:.1f}s)",
        "meta_duplicate_search_error": "Duplicate search error: {msg}",
        "meta_files_deleted": "Deleted {success} duplicate files{note}",
        "meta_files_deleted_errors_suffix": " ({fail} errors)",
        "meta_files_count": "{n} files",
        "meta_folders_count": "{n} folders",
        "meta_changes_proposed": "{n} changes proposed",
        "meta_warnings_count": "{n} warnings",
        "meta_total_files": "{total} files",
        "meta_showing_filtered": "Showing {checked} checked of {total}",
        "meta_n_files_checked": "{n} files checked",
        "meta_tracks_selected_summary": "{n} track{plural} selected",

        # ── Tag Editor: context menu / dialogs ─────────────────────────────────
        "meta_add_folder": "📁 Add folder",
        "meta_rename_menu": "✏️ Rename",
        "meta_delete_menu": "🗑️ Delete",
        "meta_new_folder_dialog_title": "Add Folder",
        "meta_new_folder_prompt": "New folder name:",
        "meta_new_folder_default": "New folder",
        "meta_invalid_folder_name": "Invalid folder name.",
        "meta_folder_exists": "A folder with this name already exists.",
        "meta_create_folder_failed": "Failed to create folder:\n{error}",
        "meta_rename_dialog_title": "Rename",
        "meta_rename_prompt": "Enter new name:",
        "meta_target_name_exists": "Target name already exists in this folder.",
        "meta_rename_failed": "Failed to rename:\n{error}",
        "meta_delete_file_title": "Delete File",
        "meta_delete_folder_title": "Delete Folder",
        "meta_delete_confirm": "Are you sure you want to permanently delete:\n{name}?",
        "meta_delete_recursive_note": "\n(All files inside the folder will be deleted too)",
        "meta_delete_failed": "Failed to delete:\n{error}",
        "meta_move_target_exists": "Target already exists:\n{name}",
        "meta_move_failed": "Failed to move file:\n{error}",
        "meta_error_title": "Error",

        # ── Downloader hints (authentication / browser / cookies / 403) ────────
        "downloader_auth_required_hint": (
            "💡 YouTube requires authentication (Google account) to continue downloading.\n\n"
            "You have two options:\n"
            "1. Quick sign-in: click 'Login Fix' to sign in to your Google account directly from the app (simplest).\n"
            "2. Export cookies: use the 'Get cookies.txt LOCALLY' browser extension to export a text file and configure it in Settings.\n"
            "Extension link: https://chromewebstore.google.com/detail/get-cookiestxt-locally/ccmgnabidkenghhcidlkgeimdbgefecl\n"
        ),
        "downloader_chrome_locked_hint": (
            "💡 Tip: Chrome is locked or encrypted. Close the browser completely and try again.\n"
            "If that doesn't help, use the 'Login Fix (simple)' button to read Chrome's encrypted cookie file."
        ),
        "downloader_node_missing_hint": (
            "💡 Tip: A JavaScript runtime is missing (needed to solve YouTube's 'puzzles').\n"
            "Run the following commands in your terminal:\n"
        ),
        "downloader_po_token_hint": (
            "💡 Tip: YouTube requires an extra verification component (PO Token) or account sign-in.\n"
            "You may need to refresh your cookies file via the 'Sign-in Wizard' or use the 'Manual fix in browser' button to warm up the Token."
        ),
        "downloader_403_hint": "💡 Tip: Access error (403). You may need to refresh your cookies file or change your IP address.",

        # ── Cookie validator ────────────────────────────────────────────────────
        "cookies_file_not_found": "Cookies file not found: {path}",
        "cookies_read_error": "Error reading cookies file: {exc}",
        "cookies_empty_or_invalid": "Cookies file is empty or invalid.",
        "cookies_all_expired": (
            "⚠️ All cookies have expired! You may receive 403 errors.\n"
            "Re-sign-in via the 'Sign-in Wizard' is recommended."
        ),

        # ── Playwright check ────────────────────────────────────────────────────
        "playwright_missing_message": (
            "{feature} requires Playwright Chromium, which is not installed.\n\n"
            "Run the following from the YTSpot install folder to enable it:\n"
            "    scripts/install_playwright.ps1\n\n"
            "Or from a Python install:\n"
            "    python -m playwright install chromium\n\n"
            "All other features continue to work normally."
        ),

        # ── Channel flow status ─────────────────────────────────────────────────
        "channel_discovering_tabs": "Discovering tabs…",
        "channel_import_cancelled": "Channel import cancelled.",
        "channel_items_found": "Found {n:,} items — checking for duplicates…",
        "channel_duplicates_found": "Found {n} duplicates — waiting for user decision…",
        "channel_adding_to_queue": "Adding {n:,} items to queue…",

        # ── Duplicate detector worker ───────────────────────────────────────────
        "dup_calculating": "Calculating…",

        # ── Metadata table headers & row statuses ──────────────────────────────
        "mt_col_filename":     "Filename",
        "mt_col_title":        "Title",
        "mt_col_title_new":    "Title (new)",
        "mt_col_artist":       "Artist",
        "mt_col_artist_new":   "Artist (new)",
        "mt_col_album":        "Album",
        "mt_col_album_new":    "Album (new)",
        "mt_col_track":        "Track",
        "mt_col_track_new":    "Track (new)",
        "mt_col_status":       "Status",
        "mt_col_filename_new": "Filename (new)",
        "mt_col_genre":        "Genre",
        "mt_col_genre_new":    "Genre (new)",
        "mt_col_comment":      "Comments",
        "mt_col_comment_new":  "Comments (new)",
        "mt_status_changed":     "Changed",
        "mt_status_done":        "✓ Done",
        "mt_status_error":       "✗ Error",
        "mt_status_unsupported": "Unsupported",

        # ── Metadata controller status messages ────────────────────────────────
        "md_scanning_folder": "Scanning: {folder}…",
        "md_auto_changes_proposed": "Auto-Order: {n} changes proposed",
        "md_auto_no_changes": "Auto-Order: all files are already organised",
        "md_artist_applied": "Artist '{artist}' applied to {n} file(s)",
        "md_album_applied": "Album '{album}' applied to {n} file(s)",
        "md_no_changes_to_apply": "No changes to apply to the selected files",
        "md_writing_tags_to_n": "Writing tags to {n} file(s)…",
        "md_album_artist_copied": "Album artist copied from artist ({n} file(s))",
        "md_artist_title_split_done": "Artist-title split completed ({n} file(s))",
        "md_year_cleared": "Year cleared",
        "md_genre_cleared": "Genre cleared",
        "md_track_num_cleared": "Track number cleared",
        "md_spaces_normalised": "Spaces normalised in {n} title(s)",
        "md_clean_settings_empty": "Clean-up settings are empty — no changes made",
        "md_junk_removed": "Junk removed from {n} title(s)",
        "md_filename_cleaned": "Physical filename cleaned for {n} file(s)",
        "md_filename_numbering_removed": "Numbering removed from filenames for {n} file(s)",
        "md_searching_duplicates_in": "Searching for duplicates in {folder}…",
        "md_duplicates_deleted": "Deleted {success} duplicate file(s){note}",
        "md_duplicates_deleted_errors_suffix": ", {fail} errors",
        "md_all_changes_reverted": "All changes reverted",
        "md_scan_done": "Scanned {n} files in {folders} folder(s)",
        "md_scan_error": "Scan error: {msg}",
        "md_writing_tags_progress": "Writing tags… {done}/{total}",
        "md_apply_done": "Done — {success} succeeded, {fail} failed, {skip} skipped{bp_note}",
        "md_apply_done_backup_note": " (backup: {name})",
        "md_duplicates_found_summary": "Found {n_files} duplicates in {n_groups} groups ({strat}, {elapsed:.1f}s)",
        "md_strategy_size": "file size",
        "md_strategy_md5": "MD5",

        # ── Folder names (channel output structure) ─────────────────────────────
        "folder_videos": "Videos",
        "folder_shorts": "Shorts",
        "folder_live": "Live Streams",
        "folder_playlists": "Playlists",
        "folder_releases": "Releases",
        "folder_podcasts": "Podcasts",
        "folder_singles_eps": "Singles & EPs",
        "folder_singles_eps_variants": "Singles & EP Releases",
        "folder_albums": "Albums",
        "folder_live_performances": "Live Performances",

        # ── About ───────────────────────────────────────────────────────────────
        "about_app": "About",
    },

    "he": {
        # ── Navigation ──────────────────────────────────────────────────────────
        "app_name": "YTSpot מנהל הורדות",
        "queue": "תור",
        "search": "חיפוש",
        "history": "היסטוריה",
        "settings": "הגדרות",
        "tag_editor": "עורך תגיות",
        "converter": "ממיר",

        # ── Download bar ────────────────────────────────────────────────────────
        "no_tracks_selected": "לא נבחרו שירים",
        "download_selected": "⬇  הורד פריטים שנבחרו",
        "download_downloading": "⬇  מוריד…",
        "selected_of_total": "נבחרו {selected} מתוך {total}",

        # ── Error dialogs ───────────────────────────────────────────────────────
        "ffmpeg_missing_title": "⚠️ FFmpeg לא נמצא",
        "ffmpeg_missing_detail": (
            "FFmpeg נדרש להורדת קבצי סאונד אך לא מותקן.\n\n"
            "ההורדות ייכשלו אם לא תתקין את FFmpeg.\n\n"
            "Windows:  choco install ffmpeg  (או scoop install ffmpeg)\n"
            "macOS:    brew install ffmpeg\n"
            "Linux:    sudo apt install ffmpeg"
        ),

        "unsupported_url_title": "כתובת URL לא תקינה",
        "unsupported_url_detail": (
            "אנא הזן כתובת http:// או https:// תקינה.\n\n"
            "YouTube, YouTube Music ו-Spotify נתמכים במלואם.\n"
            "אלפי אתרים נוספים נתמכים דרך yt-dlp.\n\n"
            "דוגמה:\n  • youtube.com/watch?v=…"
        ),
        "unsupported_generic_title": "אתר לא נתמך / דף רשימה",
        "unsupported_generic_detail": (
            "yt-dlp אינו תומך בכתובת זו באופן טבעי, או שמדובר בדף רשימה.\n\n"
            "נסה להשתמש בכלי העכביש (🕷) בשורת הכתובת כדי לסרוק את הדף לחיפוש קישורי מדיה מוטמעים."
        ),

        "no_internet_title": "אין חיבור לאינטרנט",
        "no_internet_detail": "לא ניתן להגיע לאינטרנט.\n\nאנא בדוק את החיבור ונסה שוב.",

        "cannot_write_output_title": "לא ניתן לכתוב לתיקיית הפלט",
        "cannot_write_output_detail": "לא ניתן ליצור את התיקייה:\n{path}\n\nשגיאה: {exc}",

        # ── Status bar ──────────────────────────────────────────────────────────
        "ready": "מוכן.",
        "cancel": "ביטול",
        "fetching_status": "🔍  טוען…",
        "fetch_cancelled": "🚫  הטעינה בוטלה.",
        "starting_downloads": "⬇  מתחיל הורדה של {n} פריטים…",
        "download_progress_count": "⬇  מוריד {current} מתוך {total}…",
        "cancelling": "🚫  מבטל…",
        "tracks_loaded": "✅  {n} פריטים נטענו  ·  {summary}",
        "added_to_queue": "✅  נוסף לתור: {title}",
        "clipboard_url_detected": "📋  קישור זוהה בלוח — לחץ על  הצג מידע  לטעינה.",
        "search_error": "❌  שגיאת חיפוש: {message}",
        "scraper_error": "❌  שגיאת סריקה: {message}",
        
        # ── Browser sign-in (authentication for restricted content) ────────────
        "bot_bypass_title": "נדרשת התחברות",
        "bot_bypass_instructions": (
            "השרת מבקש אימות לפני הגישה לכתובת זו. "
            "פתור אתגר רובוטים (CAPTCHA) במידת הצורך, והתחבר לחשבונך למטה כדי לאמת "
            "גיל או לגשת לתוכן שמיועד רק לחברים. "
            "כאשר דף הסרטון ייטען בהצלחה, לחץ על 'שמור קובצי עוגיות' להמשך ההורדה."
        ),
        "bot_bypass_save": "שמור עוגיות",
        "bypass_bot_btn": "התחבר ליוטיוב 🔑",

        # ── URL bar ─────────────────────────────────────────────────────────────
        "fetching_button": "טוען…",
        "fetch_info_button": "הצג מידע",
        "paste_tooltip": "הדבק מהלוח",
        "batch_import_tooltip": "ייבא כתובות URL מקובץ .txt",
        "scrape_tooltip": "סרוק דף זה למציאת קישורי מדיה",
        "clipboard_on_tooltip": "ניטור הלוח פעיל — זיהוי אוטומטי של קישורי מדיה",
        "clipboard_off_tooltip": "ניטור הלוח כבוי — הפעל בהגדרות",
        "url_placeholder": "הדבק קישור YouTube או Spotify, או כתוב שאילתת חיפוש…",

        # ── Batch import ────────────────────────────────────────────────────────
        "batch_import_failed": "ייבוא אצווה נכשל",
        "no_urls_found": "⚠  לא נמצאו קישורים נתמכים בקובץ {filename}",
        "batch_multi_loaded": "📄  {count} קישורים יובאו. הקישור הראשון נטען — לחץ הצג מידע להתחיל.",

        # ── Scraper ─────────────────────────────────────────────────────────────
        "scrape_multi_found": "🕷  נמצאו {count} קישורי מדיה. הקישור הראשון נטען — לחץ הצג מידע להתחיל.",

        # ── Settings panel ──────────────────────────────────────────────────────
        "appearance": "מראה",
        "theme": "ערכת נושא",
        "switch_theme": "החלף ערכת נושא",
        "theme_tooltip": "מחזור בין: 🌙 כהה  →  ☀️ בהיר  →  ⚫ OLED",
        "language": "שפה",
        "select_language": "בחר שפת ממשק",

        "downloads_group": "הורדות",
        "embed_thumbnail": "הטמע תמונה ממוזערת",
        "embed_thumbnail_desc": "כתוב עטיפה לתוך מטא-דאטה של הקובץ (ID3 / MP4)",
        "embed_metadata": "הטמע מטא-דאטה",
        "embed_metadata_desc": "כתוב כותרת, אמן, אלבום ושנה לתוך הקובץ",

        "features": "תכונות",
        "clipboard_monitor": "ניטור לוח",
        "clipboard_monitor_desc": (
            "זיהוי אוטומטי של קישורי YouTube / Spotify שהועתקו ללוח "
            "ומילוי שורת ה-URL באופן אוטומטי"
        ),
        "check_updates": "בדוק עדכונים בהפעלה",
        "check_updates_desc": (
            "שאל את GitHub Releases בשקט והצג באנר "
            "כשגרסה חדשה זמינה"
        ),

        "search_group": "חיפוש",
        "max_search_results": "מקסימום תוצאות חיפוש (ישן)",
        "max_search_results_desc": "מספר מקסימלי של תוצאות לשאילתת חיפוש (1 – 50)",
        "max_youtube_results": "מקסימום תוצאות YouTube",
        "max_youtube_results_desc": "מספר מקסימלי של תוצאות לחיפושי YouTube (1 – 100)",
        "max_spotify_results": "מקסימום תוצאות Spotify",
        "max_spotify_results_desc": "מספר מקסימלי של תוצאות לחיפושי Spotify (1 – 100)",
        "spotify_proxy": "כתובת שרת פרוקסי ל-Spotify",
        "spotify_proxy_desc": "כתובת ה-URL של שרת הפרוקסי ל-Spotify (למשל http://localhost:8000)",

        "spotify_group": "Spotify",
        "spotify_proxy_api_key": "מפתח API לאפליקציה (App API Key)",
        "spotify_proxy_api_key_desc": "טוקן אבטחה לשרת הפרוקסי (נשלח כ-X-App-Token)",

        "authentication": "אימות",
        "cookies_file": "קובץ עוגיות",
        "cookies_file_unset": "לא הוגדר — לחץ עיון לבחירת קובץ cookies.txt",
        "cookies_tooltip": (
            "ייצא עוגיות מהדפדפן שלך עם התוסף\n"
            "'Get cookies.txt LOCALLY', ובחר\n"
            "את הקובץ כאן לתוכן מוגבל גיל."
        ),
        "browse": "עיון…",
        "clear_cookies": "נקה",
        "clear_cookies_title": "נקה קובץ עוגיות",
        "clear_cookies_desc": "הסר את נתיב קובץ העוגיות המוגדר",

        "about": "אודות",
        "open_github": "פתח ב-GitHub",
        "open_github_desc": "גרסה {version}  ·  רישיון MIT",
        "feedback": "משוב ודיווח על באגים",
        "feedback_desc": "פתח בעיה ב-GitHub",
        "report_issue": "דווח על בעיה",

        # ── History panel ───────────────────────────────────────────────────────
        "search_history_placeholder": "חפש בהיסטוריה לפי כותרת או אמן…",
        "export_csv": "ייצא CSV",
        "clear_history": "נקה היסטוריה",
        "records_count": "{n} רשומות",
        "col_date": "תאריך",
        "col_title_artist": "כותרת / אמן",
        "col_platform": "פלטפורמה",
        "col_type": "סוג",
        "col_duration": "משך",
        "col_size": "גודל",
        "col_actions": "פעולות",
        "history_empty_hint": (
            "היסטוריית ההורדות תופיע כאן.\n"
            "הורדות שהושלמו נרשמות אוטומטית."
        ),
        "export_dialog_title": "ייצא היסטוריה כ-CSV",
        "export_complete": "הייצוא הושלם",
        "export_complete_msg": "יוצאו {count} רשומות אל:\n{path}",
        "export_failed": "הייצוא נכשל",
        "export_failed_msg": "לא ניתן לכתוב קובץ CSV:\n{error}",
        "clear_history_title": "נקה היסטוריית הורדות",
        "clear_history_confirm": "פעולה זו תמחק לצמיתות את כל הרשומות.\n\nהאם אתה בטוח?",

        # ── Search panel ────────────────────────────────────────────────────────
        "search_placeholder": "חפש שירים, אלבומים, אמנים…",
        "searching": "מחפש…",
        "no_results": "לא נמצאו תוצאות.",
        "results_count": "{n} תוצאות",
        "clear_results": "נקה תוצאות",
        "search_empty_hint": (
            "חפש מוזיקה, סרטונים או פלייליסטים.\n"
            "בחר פלטפורמה והקלד שאילתה למעלה."
        ),
        "platform_youtube": "YouTube",
        "platform_ytmusic": "YouTube Music",
        "platform_spotify": "Spotify",
        "platform_both": "הכל",

        "search_filter_all": "הכל",
        "search_filter_tracks": "שירים",
        "search_filter_albums": "אלבומים",
        "search_filter_artists": "אמנים",
        "search_filter_playlists": "פלייליסטים",
        "search_filter_channels": "ערוצים",

        # ── Queue panel ─────────────────────────────────────────────────────────
        "no_tracks_loaded": "אין פריטים בתור",
        "select_deselect_all": "בחר / בטל בחירה הכל",
        "clear_completed": "נקה שהושלמו",
        "clear_selected": "נקה שנבחרו",
        "clear_all": "נקה הכל",
        "clear_options": "נקה...",
        "pause_all": "השהה הכל",
        "resume_all": "המשך הכל",
        "sel_of_n": "{sel} / {n} נבחרו",
        "queue_empty_hint": (
            "הדבק קישור YouTube או Spotify למעלה\n"
            "ולחץ  הצג מידע  לטעינת פריטים."
        ),

        # ── Update banner ───────────────────────────────────────────────────────
        "update_available": "🎉  עדכון זמין",
        "view_release": "צפה בגרסה",
        "download_btn": "הורד",
        "dismiss_tooltip": "סגור",

        # ── Browser cookies ─────────────────────────────────────────────────────
        "browser_cookies":      "מקור עוגיות דפדפן",
        "browser_cookies_desc": "קרא קובצי עוגיות מהדפדפן שלך כדי לאמת גישה לתוכן המוגבל בגיל או שמיועד רק לחברים",
        "disabled":             "מושבת",

        # ── Release types ───────────────────────────────────────────────────────
        "release_album":        "אלבום",
        "release_single":       "סינגל",
        "release_ep":           "EP",
        "release_playlist":     "פלייליסט",
        "release_compilation":  "אוסף",
        "tracks":               "שירים",
        "items":                "פריטים",

        # ── System tray ─────────────────────────────────────────────────────────
        "tray_tooltip": "YTSpot Downloader",
        "tray_open": "פתח",
        "tray_cancel_all": "בטל את כל ההורדות",
        "tray_quit": "יציאה",
        "tray_all_done": "כל ההורדות הושלמו!",

        # ── Auth / cookie wizard ────────────────────────────────────────────────
        "auth_wizard_open_btn": "🔑 פתח אשף התחברות (מומלץ)",
        "auth_wizard_close_btn": "סגור",
        "auth_wizard_manual_btn": "🔧 תיקון ידני בדפדפן",
        "playwright_required_title": "נדרש Playwright Chromium",
        "auth_wizard_title": "אשף התחברות לאתרים",
        "auth_wizard_url_prompt": "הזן את כתובת האתר שברצונך להתחבר אליו:",
        "auth_wizard_browser_info": (
            "כעת ייפתח חלון דפדפן.\n\n"
            "1. התחבר לחשבון שלך באתר: {url}\n"
            "2. לאחר ההתחברות, פשוט סגור את חלון הדפדפן.\n\n"
            "התוכנה תשמור את פרטי ההתחברות באופן אוטומטי."
        ),
        "auth_wizard_success_title": "ההתחברות הצליחה",
        "auth_wizard_success_msg": "פרטי ההתחברות לאתר נשמרו. ניתן להתחיל להוריד מחדש.",
        "auth_wizard_aborted_title": "האשף נסגר ללא שמירה",
        "auth_wizard_aborted_msg": "לא נשמרו cookies. ייתכן שהאשף נסגר לפני ההתחברות.",
        "browser_locked_title": "{browser} פתוח",
        "browser_locked_msg": (
            "דפדפן {browser} פתוח כרגע.\n\n"
            "ווינדוס לא מאפשר לתוכנה לגשת ל-Cookies בזמן שהדפדפן פתוח.\n"
            "כדי שההורדה תעבוד, עליך לסגור את כל חלונות הדפדפן ולנסות שוב."
        ),
        "browser_locked_retry_btn": "סגרתי, נסה שוב",
        "cancel_btn": "ביטול",

        # ── Track card tooltips ─────────────────────────────────────────────────
        "card_remove_tooltip": "הסר מהתור",
        "card_pause_tooltip": "השהה הורדה",
        "card_resume_tooltip": "המשך הורדה",

        # ── Options bar labels ──────────────────────────────────────────────────
        "options_format_label": "פורמט:",
        "options_quality_label": "איכות:",
        "options_codec_label": "קודק:",
        "options_save_label": "שמור אל:",
        "options_clipboard_label": "לוח גזירה:",

        # ── Converter panel ─────────────────────────────────────────────────────
        "converter_cancel_btn": "⏹  ביטול",
        "converter_convert_all_btn": "המר הכל",

        # ── Duplicate files dialog ──────────────────────────────────────────────
        "duplicates_manage_title": "🔍 ניהול קבצים כפולים",
        "duplicates_strategy_size": "לפי גודל קובץ (מהיר)",
        "duplicates_strategy_md5": "לפי תוכן MD5 (מדויק)",
        "duplicates_header": (
            "נמצאו <b>{n_files}</b> קבצים כפולים ב-<b>{n_groups}</b> "
            "קבוצות (אסטרטגיה: {strat}) | זמן סריקה: {elapsed:.1f}s"
        ),
        "duplicates_hint": "☑ מסומן = שמור קובץ    ☐ לא מסומן = מחק קובץ",
        "duplicates_keep_all_btn": "✅ שמור את כולם",
        "duplicates_keep_all_tooltip": "סמן את כל הקבצים בכל הקבוצות לשמירה",
        "duplicates_group_label": "קבוצה {n}  —  {count} קבצים כפולים",
        "duplicates_apply_btn": "🗑 בצע מחיקה וניקוי",
        "duplicates_nothing_title": "אין מה למחוק",
        "duplicates_nothing_msg": (
            "כל הקבצים מסומנים לשמירה.\n"
            "בטל סימון של קבצים שברצונך למחוק."
        ),
        "duplicates_confirm_title": "אישור מחיקה סופי",
        "duplicates_confirm_msg": (
            "אזהרה: פעולה זו תמחק לצמיתות {n} קבצים מסומנים מהדיסק.\n\n"
            "האם אתה בטוח?"
        ),
        "duplicates_confirm_yes": "כן, מחק",
        "duplicates_confirm_no": "לא, חזור",

        # ── Conflict resolution dialog ──────────────────────────────────────────
        "conflict_sources_count": "{n} מקורות",
        "conflict_dialog_title": "ניהול כפילויות",
        "conflict_dialog_subtitle": "ניהול כפילויות — {n} סרטונים חופפים",
        "conflict_videos_header": "📹 סרטונים / קצרים / שידורים",
        "conflict_playlists_header": "📋 פלייליסטים",
        "conflict_explanation": (
            "הסרטונים הבאים נמצאו ביותר ממקור אחד. "
            "סמן ✓ את העותקים שברצונך להוריד.\n"
            "עותקים שונים יישמרו לתיקיות שונות."
        ),
        "conflict_ok_btn": "אישור — הורד הכל שסומן",
        "conflict_keep_videos_btn": "✓ שמור בסרטונים",
        "conflict_keep_playlists_btn": "✓ שמור בפלייליסטים",
        "conflict_keep_both_btn": "✓ שמור שניהם",
        "conflict_clear_all_btn": "✗ נקה הכל",

        # ── Restart prompt ──────────────────────────────────────────────────────
        "restart_required_title": "נדרשת הפעלה מחדש",
        "restart_required_msg": (
            "שינוי השפה ייכנס לתוקף לאחר הפעלה מחדש.\n"
            "להפעיל מחדש כעת?"
        ),
        "restart_now_btn": "הפעל מחדש",
        "restart_later_btn": "מאוחר יותר",

        # ── Tray notifications ──────────────────────────────────────────────────
        "tray_minimized_title": "YTSpot מנהל הורדות",
        "tray_minimized_message": "פועל ברקע. לחץ פעמיים על אייקון המגש כדי לשחזר.",

        # ── Converter panel (extended) ──────────────────────────────────────────
        "converter_header_title": "🔄  ממיר קבצים מקומי",
        "converter_subtitle": (
            "המר קבצי שמע שכבר נמצאים בדיסק לפורמט אחר. "
            "גרור קבצים לכאן או השתמש בכפתור הוספה — לא נדרש חיבור לאינטרנט."
        ),
        "converter_drop_hint": "⬆  גרור קבצי שמע לכאן או לחץ על הוסף קבצים",
        "converter_add_files": "הוסף קבצים",
        "converter_clear_all": "נקה הכל",
        "converter_output_format": "פורמט פלט:",
        "converter_bitrate": "קצב סיביות:",
        "converter_same_folder": "אותה תיקייה כמו המקור",
        "converter_output_folder": "תיקיית פלט",
        "converter_select_output_dialog": "בחר תיקיית פלט",
        "converter_select_files_dialog": "בחר קבצי שמע",
        "converter_audio_files_filter": "קבצי שמע",
        "converter_all_files_filter": "כל הקבצים",

        # ── Settings panel (extended) ───────────────────────────────────────────
        "clear": "נקה",
        "select_cookies_file": "בחר קובץ Cookies",
        "accessibility_mode": "מצב נגישות",
        "accessibility_mode_desc": "צבעים בניגודיות גבוהה וניווט מקלדת משופר (מומלץ להפעיל מחדש)",
        "concurrent_downloads": "הורדות מקבילות",
        "concurrent_downloads_desc": "מספר השירים שיורדים במקביל (1 – 5)",
        "playlist_behaviour": "התנהגות פלייליסט",
        "playlist_subfolders": "תת-תיקיות פלייליסט",
        "playlist_subfolders_desc": "צור תת-תיקייה בעלת שם לכל הורדת פלייליסט",
        "track_index_prefix": "תחילית מספור רצועה",
        "track_index_prefix_desc": "הוסף לקבצים את הקידומת 01-, 02- … כדי לשמור את סדר הפלייליסט",
        "duplicate_detection": "זיהוי כפילויות",
        "duplicate_detection_desc": "פעולה כאשר קובץ הפלט כבר קיים",
        "duplicate_skip": "דלג בשקט",
        "duplicate_warn": "הצג דיאלוג אזהרה",
        "duplicate_overwrite": "תמיד שכתב",
        "system_integration": "אינטגרציה עם המערכת",
        "minimise_to_tray": "מזער למגש המערכת",
        "minimise_to_tray_desc": "השאר את האפליקציה פועלת ברקע כאשר החלון נסגר",
        "global_hotkeys": "קיצורי מקלדת גלובליים",
        "global_hotkeys_desc": "הירשם לקיצורי מקלדת ברמת המערכת (נדרש הפעלה מחדש)",
        "advanced_audio_processing": "⚙  עיבוד שמע מתקדם",
        "sponsorblock_title": "SponsorBlock – הסר קטעים שאינם מוזיקה",
        "sponsorblock_desc": "חתוך אוטומטית קריינויות חסות, פתיחים וסיומות מסרטוני מוזיקה ביוטיוב באמצעות SponsorBlock API",
        "musicbrainz_title": "העשרת מטא-דאטה מ-MusicBrainz",
        "musicbrainz_desc": "לאחר ההורדה, שאל את MusicBrainz לקבלת ז'אנר, לייבל, ISRC, שנת הוצאה ומדינה",
        "lyrics_title": "מוריד מילות שיר  [מתקדם]",
        "lyrics_desc": "הורד מילות שיר אוטומטית והטמע אותן בתגיות הקובץ (נדרש: pip install syncedlyrics)",
        "replay_gain_title": "ניתוח Replay Gain  [מתקדם]",
        "replay_gain_desc": "נתח עוצמת קול והטמע תגיות REPLAYGAIN_TRACK_GAIN לעוצמת השמעה אחידה בין רצועות (נדרש: rsgain או pip install pyloudnorm soundfile)",
        "square_thumbnails_title": "חיתוך תמונה ממוזערת לריבוע  [מתקדם]",
        "square_thumbnails_desc": "חתוך את התמונה הממוזערת של יוטיוב מ-16:9 לריבוע 1:1 לפני הטמעה — אידיאלי לנגני מוזיקה רגילים (נדרש: pip install Pillow)",
        "youtube_proxy_title": "פרוקסי YouTube",
        "youtube_proxy_desc": "פרוקסי HTTP/HTTPS/SOCKS להורדות YouTube (למשל http://127.0.0.1:7890). השאר ריק להתחברות ישירה.",
        "accent_color": "צבע הדגשה",
        "expand_square_to_rectangle_title": "הרחב תמונות מרובעות למלבן עבור וידאו (MP4)",
        "expand_square_to_rectangle_desc": (
            "כאשר מורידים קובץ וידאו עם תמונה מרובעת במקור (כמו ספוטיפיי), "
            "התמונה תורחב למלבן 16:9 על ידי יצירת רקע מטושטש ואלגנטי."
        ),
        "external_login_title": "התחברות לאתר חיצוני (קוקיז)",
        "external_login_desc": "התחבר ליוטיוב או לכל אתר אחר ישירות מהתוכנה כדי לשמור פרטי גישה ולפתור בקשות אימות.",
        "external_login_now_btn": "התחבר עכשיו",

        # ── Channel import (tab selection dialog) ───────────────────────────────
        "import_channel_title": "ייבוא ערוץ יוטיוב",
        "import_channel_discovering": "מגלה טאבים זמינים…",
        "import_channel_cancel": "ביטול",
        "import_channel_scan_selected": "סרוק טאבים נבחרים",
        "import_channel_items_count": "{n:,} פריטים",
        "import_channel_error_prefix": "שגיאה בגילוי טאבים: {error}",
        "import_channel_scan_complete": "סריקה הושלמה — {n:,} פריטים",
        "import_channel_with_name": "ייבוא: {name}",
        "import_channel_tabs_found": "נמצאו {n} טאבים — בחר מה לסרוק:",
        "import_channel_scanning_selected": "סורק טאבים נבחרים…",
        "import_channel_scanning_tab": "סורק: {tab}…",
        "import_channel_expanding_playlists": "מרחיב פלייליסטים: {current}/{total}",
        "import_channel_scrape_error": "שגיאת סריקה: {msg}",

        # ── Search result card ──────────────────────────────────────────────────
        "search_card_add_btn": "＋  הוסף",
        "search_card_browse_btn": "עיון  →",

        # ── Tag Editor: dialogs / headers ───────────────────────────────────────
        "meta_auto_settings_title": "הגדרות סדר אוטומטי",
        "meta_clean_settings_title": "הגדרות ניקוי (אגרסיביות)",
        "meta_auto_header": "בחר אילו פעולות יבצע כפתור 'סדר אוטומטי':",
        "meta_auto_album_note": "(אלבום משם תיקייה תמיד פעיל)",
        "meta_clean_title_group": "ניקוי כותרת (Title)",
        "meta_clean_filename_group": "ניקוי שם קובץ פיזי (Filename)",

        # ── Tag Editor: auto-order operations ───────────────────────────────────
        "meta_op_title_strip_label": "העתק שם קובץ לכותרת (ללא מספר)",
        "meta_op_title_strip_desc": "לוקח את שם הקובץ הקיים ומעתיק אותו לתוך שדה 'כותרת', תוך הסרת מספרים בתחילת השם (למשל '01 שיר' יהפוך ל-'שיר').",
        "meta_op_title_full_label": "העתק שם קובץ לכותרת (כולל מספר)",
        "meta_op_title_full_desc": "לוקח את שם הקובץ הקיים ומעתיק אותו לתוך שדה 'כותרת' בדיוק כפי שהוא.",
        "meta_op_normalize_spaces_label": "מחק רווחים כפולים וקווים תחתונים מהכותרת",
        "meta_op_normalize_spaces_desc": "סורק את הכותרת, מחליף קווים תחתונים (_) ברווחים, ומוחק רווחים כפולים או מיותרים מהכותרת.",
        "meta_op_track_num_label": "חלץ מספר רצועה משם הקובץ",
        "meta_op_track_num_desc": "מחפש מספר בתחילת שם הקובץ (למשל '03') ושומר אותו בתור מספר הרצועה.",
        "meta_op_split_at_label": "פצל שם קובץ ל'אמן' ו'כותרת'",
        "meta_op_split_at_desc": "מזהה מקף (-) בשם הקובץ. מה שלפני המקף הופך ל'אמן', ומה שאחריו ל'כותרת'.",
        "meta_op_album_artist_label": "העתק 'אמן' ל'אמן אלבום'",
        "meta_op_album_artist_desc": "מעתיק את שם ה'אמן' של כל שיר ושם אותו גם בשדה 'אמן אלבום' (חשוב לסידור נכון של אלבומים בנגנים).",
        "meta_op_strip_junk_label": "נקה מילים מיותרות מהכותרת",
        "meta_op_strip_junk_desc": "מנקה מהכותרת תוספות שכיחות מיוטיוב כמו '(Official Video)', '[HD]', או 'Lyrics'.",
        "meta_op_clear_comments_label": "מחק תוכן מתגית 'הערות'",
        "meta_op_clear_comments_desc": "מוחק לחלוטין את כל מה שכתוב בשדה ההערות של השיר.",
        "meta_op_clear_track_num_label": "מחק תוכן מתגית 'מספר רצועה'",
        "meta_op_clear_track_num_desc": "מוחק לחלוטין את מספר הרצועה של השיר.",
        "meta_op_clear_year_label": "מחק תוכן מתגית 'שנה'",
        "meta_op_clear_year_desc": "מוחק את שנת ההוצאה מהתגיות.",
        "meta_op_clear_genre_label": "מחק תוכן מתגית 'ז'אנר'",
        "meta_op_clear_genre_desc": "מוחק את סגנון המוזיקה (ז'אנר) מהתגיות.",
        "meta_op_clean_filename_label": "נקה שם קובץ פיזי",
        "meta_op_clean_filename_desc": "מנקה את שם הקובץ עצמו: מסיר קווים תחתונים, מוחק כל מה שבתוך סוגריים () או [], ומסדר רווחים כפולים.",
        "meta_op_strip_filename_numbering_label": "הסר מספור משם הקובץ הפיזי",
        "meta_op_strip_filename_numbering_desc": "מוחק משם הקובץ הפיזי מספור בתחילתו (כמו '01-', '01 -', או '01_').",

        # ── Tag Editor: buttons / labels ────────────────────────────────────────
        "meta_cancel": "ביטול",
        "meta_ok": "אישור",
        "meta_save_ok": "אישור שמירה",
        "meta_browse_folder": "📁 בחר תיקייה",
        "meta_no_folder_selected": "לא נבחרה תיקייה",
        "meta_include_subdirs": "כלול תתי-תיקיות",
        "meta_auto_btn": "🪄 סדר אוטומטי",
        "meta_apply_changes": "✅ החל שינויים",
        "meta_revert_changes": "↩ בטל שינויים",
        "meta_find_duplicates": "🔍 חפש כפילויות",
        "meta_no_folder_scanned": "לא נסרקה תיקייה",
        "meta_files_folders_header": "📂 קבצים ותיקיות",
        "meta_auto_cfg_tooltip": "הגדר מה סדר אוטומטי יבצע",
        "meta_dupes_tooltip": "סרוק את התיקייה לאיתור קבצי מוזיקה כפולים",
        "meta_clean_cfg_tooltip": "הגדרות ניקוי",

        # ── Tag Editor: inspector ──────────────────────────────────────────────
        "meta_select_files_prompt": "בחר קבצים\nאו תיקייה\nלעריכה",
        "meta_all_checked_files": "כל הקבצים המסומנים",
        "meta_apply_artist_group": "החל אמן",
        "meta_artist_placeholder": "שם האמן…",
        "meta_apply_artist_btn": "✅ החל אמן על המסומנים",
        "meta_apply_album_group": "החל אלבום",
        "meta_album_placeholder": "שם האלבום…",
        "meta_apply_album_btn": "✅ החל אלבום על המסומנים",
        "meta_tracks_selected_count": "{n} שירים נבחרו",
        "meta_edit_tags_group": "עריכת תגיות",
        "meta_mixed_placeholder": "ריק / מעורב",
        "meta_field_title": "כותרת:",
        "meta_field_artist": "אמן:",
        "meta_field_album": "אלבום:",
        "meta_field_album_artist": "אמן אלבום:",
        "meta_field_track": "רצועה:",
        "meta_apply_to_selection": "✅ החל על הבחירה",
        "meta_rename_group": "שינוי שם קובץ",
        "meta_rename_note": "שנה את שם הקובץ הפיזי לפי הכותרת החדשה",
        "meta_rename_btn": "📝 שנה שם קובץ לפי כותרת",
        "meta_actions_on_selected": "פעולות על המסומנים",

        # ── Tag Editor: clean-up checkboxes ────────────────────────────────────
        "meta_clean_brackets": "נקה סוגריים עם זבל (כמו [HD] וכו')",
        "meta_clean_english_junk": "נקה מילות זבל באנגלית (Official, Audio, 4K, Prod...)",
        "meta_clean_hebrew_junk": "נקה מילות זבל בעברית (קאבר, רמיקס, הופעה חיה...)",
        "meta_clean_punctuation": "תקן רווחים, מקפים מיותרים וקווים מפרידים (|)",
        "meta_clean_filename_brackets": "מחיקת סוגריים חכמה (למחוק זבל, להשאיר feat. וכו')",
        "meta_clean_filename_brackets_tooltip": "אם כבוי, ימחק בצורה 'עיוורת' את כל הסוגריים כולל התוכן שלהם.",
        "meta_clean_filename_domains": "נקה שאריות אתרי הורדות (y2mate, yt1s, SPOTIFY-DL...)",
        "meta_clean_filename_emojis": "נקה אימוג'י וסימנים מיוחדים בעייתיים (!@#$)",
        "meta_clean_filename_spaces": "תקן מקפים ורווחים כפולים ( - - )",

        # ── Tag Editor: status / progress / errors ─────────────────────────────
        "meta_choose_music_folder": "בחר תיקיית מוזיקה",
        "meta_scanning": "סורק…",
        "meta_searching_duplicates": "מחפש כפילויות…",
        "meta_searching_duplicates_progress": "מחפש כפילויות… {done}/{total}  ({eta})",
        "meta_writing_tags_progress": "כותב תגיות… {done}/{total}",
        "meta_done_success_base": "הושלם: {success} הצליחו",
        "meta_done_failed_suffix": ", {fail} נכשלו",
        "meta_done_skipped_suffix": ", {skip} דולגו",
        "meta_done_summary_title": "הצלחה",
        "meta_done_with_errors_title": "הושלם עם שגיאות",
        "meta_no_duplicates_found": "לא נמצאו כפילויות ({elapsed:.1f}s)",
        "meta_duplicate_search_error": "שגיאה בחיפוש כפילויות: {msg}",
        "meta_files_deleted": "נמחקו {success} קבצים כפולים{note}",
        "meta_files_deleted_errors_suffix": " ({fail} שגיאות)",
        "meta_files_count": "{n} קבצים",
        "meta_folders_count": "{n} תיקיות",
        "meta_changes_proposed": "{n} שינויים מוצעים",
        "meta_warnings_count": "{n} אזהרות",
        "meta_total_files": "{total} קבצים",
        "meta_showing_filtered": "מציג {checked} מסומנים מתוך {total}",
        "meta_n_files_checked": "{n} קבצים מסומנים",
        "meta_tracks_selected_summary": "נבחרו {n} שירים",

        # ── Tag Editor: context menu / dialogs ─────────────────────────────────
        "meta_add_folder": "📁 הוסף תיקייה",
        "meta_rename_menu": "✏️ שנה שם",
        "meta_delete_menu": "🗑️ מחק",
        "meta_new_folder_dialog_title": "הוסף תיקייה",
        "meta_new_folder_prompt": "שם התיקייה החדשה:",
        "meta_new_folder_default": "תיקייה חדשה",
        "meta_invalid_folder_name": "שם התיקייה אינו חוקי.",
        "meta_folder_exists": "תיקייה בשם הזה כבר קיימת.",
        "meta_create_folder_failed": "כשל ביצירת התיקייה:\n{error}",
        "meta_rename_dialog_title": "שנה שם",
        "meta_rename_prompt": "הכנס שם חדש:",
        "meta_target_name_exists": "שם היעד כבר קיים בתיקייה זו.",
        "meta_rename_failed": "כשל בשינוי השם:\n{error}",
        "meta_delete_file_title": "מחיקת קובץ",
        "meta_delete_folder_title": "מחיקת תיקייה",
        "meta_delete_confirm": "האם אתה בטוח שברצונך למחוק לצמיתות את:\n{name}?",
        "meta_delete_recursive_note": "\n(כל הקבצים בתוך התיקייה יימחקו גם הם)",
        "meta_delete_failed": "כשל במחיקה:\n{error}",
        "meta_move_target_exists": "היעד כבר קיים:\n{name}",
        "meta_move_failed": "כשל בהעברת הקובץ:\n{error}",
        "meta_error_title": "שגיאה",

        # ── Downloader hints (authentication / browser / cookies / 403) ────────
        "downloader_auth_required_hint": (
            "💡 יוטיוב דורש אימות (חשבון גוגל) כדי להמשיך בהורדה.\n\n"
            "יש לך שתי אפשרויות:\n"
            "1. התחברות מהירה: לחץ על 'תיקון התחברות' כדי להתחבר לחשבון גוגל ישירות מהתוכנה (הכי פשוט).\n"
            "2. ייצוא קוקיז: השתמש בתוסף 'Get cookies.txt LOCALLY' לדפדפן כדי לייצא קובץ טקסט ולהגדיר אותו בהגדרות.\n"
            "קישור לתוסף: https://chromewebstore.google.com/detail/get-cookiestxt-locally/ccmgnabidkenghhcidlkgeimdbgefecl\n"
        ),
        "downloader_chrome_locked_hint": (
            "💡 טיפ: דפדפן Chrome נעול או מוצפן. סגור את הדפדפן לגמרי ונסה שוב.\n"
            "אם זה לא עוזר, השתמש בלחצן 'תיקון התחברות (פשוט)' כדי לקרוא את קובצי העוגיות המוצפנים של כרום."
        ),
        "downloader_node_missing_hint": (
            "💡 טיפ: חסר רכיב להרצת JavaScript (נחוץ לפתרון ה'חידות' של יוטיוב).\n"
            "יש להריץ בטרמינל את הפקודות הבאות:\n"
        ),
        "downloader_po_token_hint": (
            "💡 טיפ: יוטיוב דורש רכיב אימות נוסף (PO Token) או התחברות לחשבון.\n"
            "ייתכן שתצטרך לעדכן את קובץ ה-Cookies שלך דרך 'אשף ההתחברות' או להשתמש בלחצן 'תיקון ידני בדפדפן' כדי לחמם את ה-Token."
        ),
        "downloader_403_hint": "💡 טיפ: שגיאת גישה (403). ייתכן שצריך לעדכן את קובץ ה-Cookies או להחליף כתובת IP.",

        # ── Cookie validator ────────────────────────────────────────────────────
        "cookies_file_not_found": "קובץ Cookies לא נמצא: {path}",
        "cookies_read_error": "שגיאה בקריאת קובץ Cookies: {exc}",
        "cookies_empty_or_invalid": "קובץ Cookies ריק או לא תקין.",
        "cookies_all_expired": (
            "⚠️ כל ה-Cookies פגו תוקף! ייתכן שתקבל שגיאת 403.\n"
            "מומלץ להתחבר מחדש דרך 'אשף ההתחברות'."
        ),

        # ── Playwright check ────────────────────────────────────────────────────
        "playwright_missing_message": (
            "הפיצ'ר \"{feature}\" דורש את Playwright Chromium שאינו מותקן.\n\n"
            "להפעלה, הרץ מתוך תיקיית ההתקנה של YTSpot:\n"
            "    scripts/install_playwright.ps1\n\n"
            "או מתוך התקנת Python:\n"
            "    python -m playwright install chromium\n\n"
            "שאר הפעולות בתוכנה ימשיכו לעבוד כרגיל."
        ),

        # ── Channel flow status ─────────────────────────────────────────────────
        "channel_discovering_tabs": "מגלה טאבים…",
        "channel_import_cancelled": "ייבוא ערוץ בוטל.",
        "channel_items_found": "נמצאו {n:,} פריטים — בודק כפילויות…",
        "channel_duplicates_found": "נמצאו {n} כפילויות — ממתין להחלטת המשתמש…",
        "channel_adding_to_queue": "מוסיף {n:,} פריטים לתור…",

        # ── Duplicate detector worker ───────────────────────────────────────────
        "dup_calculating": "מחשב…",

        # ── Metadata table headers & row statuses ──────────────────────────────
        "mt_col_filename":     "שם קובץ",
        "mt_col_title":        "כותרת",
        "mt_col_title_new":    "כותרת (חדש)",
        "mt_col_artist":       "אמן",
        "mt_col_artist_new":   "אמן (חדש)",
        "mt_col_album":        "אלבום",
        "mt_col_album_new":    "אלבום (חדש)",
        "mt_col_track":        "רצועה",
        "mt_col_track_new":    "רצועה (חדש)",
        "mt_col_status":       "סטטוס",
        "mt_col_filename_new": "שם קובץ חדש",
        "mt_col_genre":        "ז'אנר",
        "mt_col_genre_new":    "ז'אנר (חדש)",
        "mt_col_comment":      "הערות",
        "mt_col_comment_new":  "הערות (חדש)",
        "mt_status_changed":     "שונה",
        "mt_status_done":        "✓ הושלם",
        "mt_status_error":       "✗ שגיאה",
        "mt_status_unsupported": "לא נתמך",

        # ── Metadata controller status messages ────────────────────────────────
        "md_scanning_folder": "סורק: {folder}…",
        "md_auto_changes_proposed": "סדר אוטומטי: {n} שינויים הוצעו",
        "md_auto_no_changes": "סדר אוטומטי: כל הקבצים כבר מסודרים",
        "md_artist_applied": "אמן '{artist}' הוחל על {n} קבצים",
        "md_album_applied": "אלבום '{album}' הוחל על {n} קבצים",
        "md_no_changes_to_apply": "אין שינויים להחלה בקבצים הנבחרים",
        "md_writing_tags_to_n": "כותב תגיות ל-{n} קבצים…",
        "md_album_artist_copied": "אמן אלבום הועתק מ-אמן ({n} קבצים)",
        "md_artist_title_split_done": "פיצול אמן-כותרת הושלם ({n} קבצים)",
        "md_year_cleared": "שנה נוקתה",
        "md_genre_cleared": "ז'אנר נוקה",
        "md_track_num_cleared": "מספר רצועה נוקה",
        "md_spaces_normalised": "נוקה רווחים ב-{n} כותרות",
        "md_clean_settings_empty": "הגדרות הניקוי ריקות - לא בוצע שינוי",
        "md_junk_removed": "זבל הוסר מ-{n} כותרות",
        "md_filename_cleaned": "שם קובץ פיזי נוקה עבור {n} קבצים",
        "md_filename_numbering_removed": "מספור הוסר משם הקובץ עבור {n} קבצים",
        "md_searching_duplicates_in": "מחפש כפילויות ב-{folder}…",
        "md_duplicates_deleted": "נמחקו {success} קבצים כפולים{note}",
        "md_duplicates_deleted_errors_suffix": ", {fail} שגיאות",
        "md_all_changes_reverted": "כל השינויים בוטלו",
        "md_scan_done": "נסרקו {n} קבצים ב-{folders} תיקיות",
        "md_scan_error": "שגיאה בסריקה: {msg}",
        "md_writing_tags_progress": "כותב תגיות… {done}/{total}",
        "md_apply_done": "הושלם — {success} הצליחו, {fail} נכשלו, {skip} דולגו{bp_note}",
        "md_apply_done_backup_note": " (גיבוי: {name})",
        "md_duplicates_found_summary": "נמצאו {n_files} כפילויות ב-{n_groups} קבוצות ({strat}, {elapsed:.1f}s)",
        "md_strategy_size": "גודל קובץ",
        "md_strategy_md5": "MD5",

        # ── Folder names (channel output structure) ─────────────────────────────
        "folder_videos": "סרטונים",
        "folder_shorts": "קצרים",
        "folder_live": "שידורים חיים",
        "folder_playlists": "פלייליסטים",
        "folder_releases": "פריטי תוכן",
        "folder_podcasts": "פודקאסטים",
        "folder_singles_eps": "סינגלים ו-EP",
        "folder_singles_eps_variants": "סינגלים וגרסאות EP",
        "folder_albums": "אלבומים",
        "folder_live_performances": "הופעות חיות",

        # ── About ───────────────────────────────────────────────────────────────
        "about_app": "אודות",
    },
}


def set_language(lang: str) -> None:
    """Set the active language code (falls back to English).

    This only updates the in-memory translation state. Use
    :func:`apply_language` instead when you also need to update the
    application's layout direction and notify language-aware widgets.
    """
    global _current
    if lang not in TRANSLATIONS:
        lang = "en"
    _current = lang


def current_language() -> str:
    return _current


def _warn_missing(key: str, lang: str, also_missing_in_en: bool = False) -> None:
    """Log a translation key that's not present in the active language.

    Each (key, lang) pair is logged at most once per session to avoid
    flooding the log from paint events. Uses DEBUG level so it's silent
    in normal use but visible when devs raise the log level.
    """
    marker = (key, lang)
    if marker in _warned_keys:
        return
    _warned_keys.add(marker)
    if also_missing_in_en:
        _log.debug("i18n: key %r missing in %r and in English fallback", key, lang)
    else:
        _log.debug("i18n: key %r missing in %r (using English fallback)", key, lang)


def t(key: str, **kwargs) -> str:
    """Translate `key` using the active language and format with kwargs."""
    d = TRANSLATIONS.get(_current, TRANSLATIONS["en"])
    if key in d:
        s = d[key]
    elif key in TRANSLATIONS["en"]:
        s = TRANSLATIONS["en"][key]
        if _current != "en":
            _warn_missing(key, _current)
    else:
        _warn_missing(key, _current, also_missing_in_en=True)
        s = key
    try:
        return s.format(**kwargs)
    except Exception:
        return s


# ─── Language coordinator ────────────────────────────────────────────────────
#
# The LanguageManager singleton exposes a ``language_changed(str)`` Qt signal
# that widgets can connect to in order to live-update their text when the
# user changes language. Today the application uses restart-based language
# switching (see ``request_language_restart`` below), so no widget connects
# to the signal — but the plumbing is in place so a future live-retranslate
# phase can wire each widget's ``_retranslate()`` method without an
# architectural change.

_language_manager: Optional["LanguageManager"] = None


def language_manager() -> "LanguageManager":
    """Return the singleton LanguageManager, creating it on first call.

    Requires a QApplication to exist. Import-deferred so plain ``import ui.i18n``
    does not pull in Qt symbols.
    """
    global _language_manager
    if _language_manager is None:
        # Local import: keeps Qt out of the import path for non-UI consumers.
        from PySide6.QtCore import QObject, Signal

        class LanguageManager(QObject):
            language_changed = Signal(str)

        _language_manager = LanguageManager()
    return _language_manager


def apply_language(app, lang: str) -> None:
    """Apply ``lang`` as the active language + layout direction in one call.

    Use at startup (after QApplication is constructed) and whenever the user
    changes language in Settings. ``app`` must be a ``QApplication`` instance.
    """
    set_language(lang)
    # Local imports keep this module importable without Qt for tooling.
    from ui.direction import apply_app_direction
    apply_app_direction(app, _current)
    language_manager().language_changed.emit(_current)


# Map the Hebrew category labels used internally (matching YouTube's Hebrew UI)
# to translation keys. Used by ``localized_folder_name`` to produce the correct
# folder-name string when writing scraped channel content to disk.
_FOLDER_KEY_MAP: Dict[str, str] = {
    "סרטונים":              "folder_videos",
    "קצרים":                "folder_shorts",
    "שידורים חיים":         "folder_live",
    "פלייליסטים":           "folder_playlists",
    "פריטי תוכן":           "folder_releases",
    "פודקאסטים":            "folder_podcasts",
    "סינגלים ו-EP":         "folder_singles_eps",
    "סינגלים וגרסאות EP":   "folder_singles_eps_variants",
    "אלבומים":              "folder_albums",
    "הופעות חיות":          "folder_live_performances",
}


def localized_folder_name(category: str) -> str:
    """Translate an internal Hebrew category label to the current language.

    Internal scraping/identification code uses Hebrew labels because they
    match YouTube's Hebrew UI. When those labels are written out as folder
    names, they should be in the user's selected language. Returns the
    original ``category`` unchanged if no mapping is registered.
    """
    key = _FOLDER_KEY_MAP.get(category)
    return t(key) if key else category


def request_language_restart(app, lang: str) -> None:
    """Persist ``lang`` to in-memory state then restart the app process.

    The new process re-reads ``cfg.language`` at startup and renders the
    entire UI cleanly in the new language with the correct RTL direction
    from frame one — no partial-refresh edge cases.
    """
    apply_language(app, lang)
    from PySide6.QtCore import QProcess

    program = sys.executable
    # Re-launch with the same argv. When frozen (PyInstaller), sys.argv[0]
    # is the bundled executable; sys.executable points to the same binary,
    # so passing sys.argv[1:] as arguments preserves any user-supplied flags.
    arguments = sys.argv[1:] if getattr(sys, "frozen", False) else list(sys.argv)
    workdir = os.getcwd()
    QProcess.startDetached(program, arguments, workdir)
    app.quit()
