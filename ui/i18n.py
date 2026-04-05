"""
ui/i18n.py
Simple localization helper for the app.

This is intentionally lightweight: translation lookup by key and a
small API to set the active language at startup or when the user
changes it in Settings.
"""
from __future__ import annotations

from typing import Dict

_current: str = "en"

TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "en": {
        # ── Navigation ──────────────────────────────────────────────────────────
        "app_name": "YTSpot Downloader",
        "queue": "Queue",
        "search": "Search",
        "history": "History",
        "settings": "Settings",

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
            "Most video sites are supported — YouTube, Vimeo, Dailymotion, Twitch, and thousands more via yt-dlp.\n\n"
            "Examples:\n  • youtube.com/watch?v=…\n  • vimeo.com/123456"
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
        "cancelling": "🚫  Cancelling…",
        "tracks_loaded": "✅  {n} track{plural} loaded  ·  {summary}",
        "added_to_queue": "✅  Added to queue: {title}",
        "clipboard_url_detected": "📋  Clipboard URL detected — press  Fetch Info  to load.",
        "search_error": "❌  Search: {message}",
        "scraper_error": "❌  Scraper: {message}",
        
        # ── Bot Bypass Browser ──────────────────────────────────────────────────
        "bot_bypass_title": "Bot Verification Required",
        "bot_bypass_instructions": (
            "YouTube or the target server has blocked this request. "
            "Please solve any CAPTCHAs, acknowledge warnings, or log in to verify your age below. "
            "Once the video page loads successfully, click 'Save Cookies' to continue downloading."
        ),
        "bot_bypass_save": "Save Cookies",
        "bypass_bot_btn": "Bypass Protection 🛡️",

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
        "max_search_results": "Max Search Results",
        "max_search_results_desc": "Maximum number of results to fetch per search query (1 – 50)",
        "spotify_proxy": "Spotify Proxy Server URL",
        "spotify_proxy_desc": "URL to your Spotify proxy server (e.g. http://localhost:8000)",

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
        "platform_spotify": "Spotify",
        "platform_both": "Both",

        # ── Queue panel ─────────────────────────────────────────────────────────
        "no_tracks_loaded": "No tracks loaded",
        "select_deselect_all": "Select / Deselect All",
        "clear_completed": "Clear completed",
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
        "browser_cookies_desc": "Extract cookies from your browser to bypass bot checks and age gates",
        "disabled":             "Disabled",
    },

    "he": {
        # ── Navigation ──────────────────────────────────────────────────────────
        "app_name": "YTSpot מנהל הורדות",
        "queue": "תור",
        "search": "חיפוש",
        "history": "היסטוריה",
        "settings": "הגדרות",

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
            "רוב אתרי הווידאו נתמכים — YouTube, Vimeo, Dailymotion, Twitch ואלפים נוספים דרך yt-dlp.\n\n"
            "דוגמאות:\n  • youtube.com/watch?v=…\n  • vimeo.com/123456"
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
        "cancelling": "🚫  מבטל…",
        "tracks_loaded": "✅  {n} פריטים נטענו  ·  {summary}",
        "added_to_queue": "✅  נוסף לתור: {title}",
        "clipboard_url_detected": "📋  קישור זוהה בלוח — לחץ על  הצג מידע  לטעינה.",
        "search_error": "❌  שגיאת חיפוש: {message}",
        "scraper_error": "❌  שגיאת סריקה: {message}",
        
        # ── Bot Bypass Browser ──────────────────────────────────────────────────
        "bot_bypass_title": "נדרש אימות אנושי",
        "bot_bypass_instructions": (
            "השרת חסם את הבקשה האוטומטית. "
            "אנא פתור אתגר רובוטים (CAPTCHA) או התחבר לחשבון שלך למטה כדי לאמת גיל. "
            "כאשר דף הסרטון ייטען בהצלחה ללא הודעות חסימה, לחץ על 'שמור קובצי עוגיות' להמשך ההורדה."
        ),
        "bot_bypass_save": "שמור עוגיות",
        "bypass_bot_btn": "עקוף הגנה 🛡️",

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
        "max_search_results": "מקסימום תוצאות חיפוש",
        "max_search_results_desc": "מספר מקסימלי של תוצאות לשאילתת חיפוש (1 – 50)",
        "spotify_proxy": "כתובת שרת פרוקסי ל-Spotify",
        "spotify_proxy_desc": "כתובת ה-URL של שרת הפרוקסי ל-Spotify (למשל http://localhost:8000)",

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
        "platform_spotify": "Spotify",
        "platform_both": "הכל",

        # ── Queue panel ─────────────────────────────────────────────────────────
        "no_tracks_loaded": "אין פריטים בתור",
        "select_deselect_all": "בחר / בטל בחירה הכל",
        "clear_completed": "נקה שהושלמו",
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
        "browser_cookies_desc": "חלץ עוגיות מהדפדפן שלך לעקיפת זיהוי רובוטים ובדיקות גיל",
        "disabled":             "מושבת",
    },
}


def set_language(lang: str) -> None:
    """Set the active language code (falls back to English)."""
    global _current
    if lang not in TRANSLATIONS:
        lang = "en"
    _current = lang


def current_language() -> str:
    return _current


def t(key: str, **kwargs) -> str:
    """Translate `key` using the active language and format with kwargs."""
    d = TRANSLATIONS.get(_current, TRANSLATIONS["en"])
    s = d.get(key, TRANSLATIONS["en"].get(key, key))
    try:
        return s.format(**kwargs)
    except Exception:
        return s
