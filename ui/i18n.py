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
