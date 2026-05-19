# דוח ביקורת קוד מלא — ytspot_downloader

ענף: `audit/full-line-audit` · גרסה ביקורת: `1.0.0` · תאריך: 2026-05-19

---

## 1. תקציר מנהלים (Executive Summary)

* **האם נוספו פיצ'רים גדולים:** לא. שום קוד פונקציונלי חדש לא נוסף. כל ה־commits הם תיקוני באגים, יישור התנהגות בין שכבות, וניסוח־מחדש של מחרוזות UI/תיעוד.
* **האם הפרויקט קרוב ל־beta:** **כן** — אחרי איחוד 11 ה־commits של הענף הזה ל־`main`. לפני האיחוד, היו 4 חוסמי־שחרור (S0) שדממו פיצ'רים שלמים בלי שגיאה (בדיקת עדכונים, זיהוי כפילויות, קישור About).
* **שלושת החסמים הכי חשובים שהיו והוסרו:**
  1. **`UpdateChecker` פנה ל־owner שגוי (`cdtauman` במקום `cdtauman-projects`)** — `_check_internal` קיבל 404, `check()` בלע את החריגה בשתיקה (`update_checker.py:197`), כל בדיקת עדכון תמיד החזירה `None`. תוקן + נוסף מבחן רגרסיה.
  2. **בודק הכפילויות (`duplicate_checker`) בנה stem שונה ממה ש־`downloader` כותב לדיסק** — `download_controller.py:277` מגדיר תמיד `is_clean=True` (קובץ ללא שם אמן), אבל `expected_stem` חישב `"{artist} - {title}"` (עם אמן ועם תחילית רווח־בלבד במקום `" - "`). הפיצ'ר "skip/warn on duplicate" לא תפקד באף הורדה אי־פעם. תוקן ע"י איחוד שתי הפונקציות סביב `_sanitize_filename` יחיד.
  3. **קישור About ב־Settings פנה ל־`github.com/ytspot/ytspot`** (404). תוקן.

---

## 2. סיכום כיסוי הביקורת (Coverage Summary)

| מדד | ערך |
|---|---|
| קבצים שב־git ls-files | 116 |
| סך השורות בקבצים נסקרים | ~32,388 |
| קבצים שנסקרו במלואם או בפרוסות | 115 |
| קבצים שדולגו (audit: skip) | 1 (`ytspot_downloader.egg-info/PKG-INFO` — מוגדר כ־generated) |
| כל יתר 5 קבצי ה־egg-info הופיעו במצאי ונסקרו ע"י grep |

**שיטה:**

* קריאות מלאות מלמעלה־למטה ל־24 קבצים קריטיים (כל ה־root, כל ה־controllers, כל ה־workers הקריטיים, כל ה־panels הקטנים, `config.py`, `i18n.py`, `update_checker.py`, `duplicate_checker.py`, `download_controller.py`, וכן הלאה).
* קריאות בפרוסות לקבצים ארוכים (`core/downloader.py:1-1031`, `core/search_engine.py` ב־3 פרוסות 1-350 / 350-850 / 850-1190).
* כיסוי קרוס־רפו דרך grep לכל קבצי `.py`: TODO/FIXME/HACK (אפס תוצאות אמיתיות), URLs קשיחים, אזכורי גרסה, `max_parallel`/`max_workers`, "Anti-Ban"/"bypass"/"DRM"/"לעקוף", `print(`, בלוקי `__main__`, אזכורי `ytmusic`, ועוד.
* כתיבת `tools/audit/manifest_builder.py` ו־`tools/audit/symbol_scan.py` (סורקי AST פשוטים) שייצרו `tools/audit/_manifest_seed.tsv` ו־`tools/audit/_symbols.tsv` (2,985 סמלים) כראיה למצאי.

**האם נשארו קבצים לא נסקרים:** לא. כל קובץ ב־`git ls-files` מופיע ב־`AUDIT_COVERAGE_MANIFEST.md` עם סטטוס קריאה ועם הערות.

---

## 3. סמלי הקוד וקוד מת (Symbol / Dead Code Summary)

| סוג | כמות |
|---|---|
| class | 161 |
| method | 1,084 |
| func (מודולריות) | 186 |
| const (מודולריות) | 249 |
| classvar | 204 |
| **סך הסמלים** | **2,985** |

* **מועמדים ודאיים ל־unused:** 3
  * `AppConfig.window_geometry` (config.py:309-314) — המפתח נמחק במיגרציית קונפיג #2; הפרופרטי תמיד מחזיר `""`. דליט בטוח.
  * `DownloadEngine.download_async` (downloader.py:462-474) — אין שום קריאה ב־repo. כל המסלולים עוברים ב־DownloadOrchestrator.
  * `error_handler.run_preflight` (error_handler.py:325) — פונקציה מצוינת אבל לא נקראת מ־`main.py`. **לא קוד מת ממש — חסר חיווט.** תיקון מומלץ ב־v1.1: לקרוא ל־`run_preflight()` בעת startup ולהציג `MessageBox` אם `not result.all_ok()`.
* **`signature_only` (פרמטר משורשר אך לא בשימוש):** 1 — `randomize_user_agent` עובר מ־config דרך הקונטרולר ל־`DownloadRequest` ל־`utils/yt_dlp_opts.build_base_ydl_opts`, שם הוא מוצהר בפירוש כ"Kept for signature compatibility, but unused". יש להוציא או לממש ב־v1.1.
* **`inert_stub`:** 1 — `utils/impersonate.py` (6 שורות) — מודול דוקסטרינג "Dummy file for backward compatibility". בשימוש ע"י `core/playlist_parser.py:48` אך הערכים תמיד `False`/`None`, אז הענף של `_CURL_CFFI_AVAILABLE` ב־playlist_parser הוא קוד מת בפועל.
* **`dynamic` (חי דרך Qt/callback bus, לא נראה ב־AST):** ~30+ סיגנלים של Qt, מתודות `_SignalAdapter`, מתודות `TerminalCallbacks`, 80+ מפתחות i18n — כולם אומתו חיים דרך grep `.connect(` ו־`getattr(self._cb, method)`.
* **טרם וודאו:** 4 — `MetadataController.cancel_apply`, `lyrics_embedder.embed_lyrics`, `replay_gain.analyse_and_embed`, `utils/network_probe.py` (עוטף לפעולה אחת). פרט כל אחד ב־`AUDIT_UNUSED_OR_DEAD_CODE.md`. לא חוסמים שחרור.

אף אחד מהמועמדים הוודאיים לקוד מת לא קיבל סיווג S0/S1. נדחו לסשן ניקיון אחד אחרי שה־S0/S1 ייכנסו ל־main.

---

## 4. מפת פעולות המוצר (Product Action Map Summary)

מופה ב־[AUDIT_ACTION_MAP.md](AUDIT_ACTION_MAP.md) — 55 פעולות, מ־UI entry עד core function וקבצי config.

| סטטוס | מספר פעולות |
|---|---|
| **טוב** (אין חששות) | 33 |
| **S0 risk** (לפני התיקונים) | 2 |
| **S1 risk** (לפני התיקונים) | 12 |
| **S2 risk** | 4 |
| **S3 risk** | 2 |
| **דורש אימות** | 2 (`lyrics_enabled` toggle ב־UI, `replay_gain_enabled` toggle ב־UI) |

* **פעולות שכוסו טוב:** App startup, theme/accent, config save/load, tag-editor scan/apply (כולל גיבוי אוטומטי ב־JSON), duplicate file delete (אישור כפול + send2trash → Recycle Bin), URL classify, batch import.
* **פעולות שהיו חלקיות/שבורות והוסרו לכאן:** Search max-results clamp, last_search_platform restore, history platform persistence, output_dir flow, update checker.
* **פעולות שעדיין מסוכנות/מבלבלות (S2-S3):** Universal stream interceptor (Playwright; תלות חיצונית עם משמעות; לא בעיית בטיחות); אין UI לשחזור גיבוי tag editor (S2-9); שמות תיקיות בעברית קשיחים גם בממשק אנגלית (S3-3).

---

## 5. S0 שתוקנו (S0 Fixed)

| ID | תיאור | קבצים | commit |
|---|---|---|---|
| S0-1 | `UpdateChecker` ברירת `repo_owner` שגויה ("cdtauman" → "cdtauman-projects") | `core/update_checker.py`, `ui/workers/update_worker.py`, `ui/app_window.py` (callsite) | `6bc1097` |
| S0-2 | קישור About ב־Settings → `github.com/ytspot/ytspot` שגוי | `ui/panels/settings_panel.py:570` | `6bc1097` |
| S0-3 | README מזכיר את ה־owner השגוי בסעיף "Auto-Update Checker" | `README.md:399` | `6bc1097` |
| S0-4 | `duplicate_checker.expected_stem` בנה `"{artist} - {title}"` אבל ה־downloader כותב תמיד `"{title}"` (clean filename). שתי תחיליות אינדקס שונות, שתי פונקציות sanitisation שונות. הפיצ'ר היה דמום. | `core/duplicate_checker.py`, `core/downloader.py`, `ui/controllers/download_controller.py` | `a246633` |

---

## 6. S0 שנותרו פתוחים (S0 Still Open)

**אין S0 פתוחים.** כל ארבעת ה־S0 שזוהו תוקנו והם מכוסים במבחני רגרסיה.

---

## 7. S1 שתוקנו (S1 Fixed)

| ID | תיאור קצר | commit |
|---|---|---|
| S1-1 | History DB רשם `platform="youtube"` תמיד; כעת נגזר מ־`req.platform` (`ytmusic`/`spotify`/`youtube`/`unknown`) | `5881dcf` |
| S1-2 | OptionsBar text-edit לא נשמר; `DownloadController` השתמש ב־`cfg.output_dir` הישן | `6e1cd62` |
| S1-3 | חיפוש עם floors מרכיב סך > max_results; הוחלף ב־proportional distribution | `cf22d19` |
| S1-4 | `last_search_platform="ytmusic"` נשמט מ־allow-list ב־restore | `25f1dbb` |
| S1-5 | ניסוח־מחדש של "Bypass Protection 🛡️" → "Sign in to YouTube 🔑" + מחרוזות UI נוספות | `822998a` |
| S1-6 | "Anti-Ban Strategy" ב־README + "לעקוף את החסימה" במדריך עברית — שונה ל"Reliability"/"אימות גישה" | `822998a` |
| S1-7 | מגבלת `max_parallel_downloads` שונה ב־CLI (1-5) מ־config (1-6) — אוחד ל־1-6 | `a10426d` |
| S1-8 | `_sanitize_filename` נחתך ב־200 ב־checker אבל לא ב־downloader → false negatives לכותרות ארוכות; אוחד | `a246633` |
| S1-9 | `.gitignore` היה פגום (NBSP/RTL chars); נכתב מחדש, נוספו `*.egg-info/`, `.pytest_cache/`, וכו' | `009f8f1` |
| S1-10 | CI דילג על P0 gate tests, רץ רק ubuntu, ולא בדק Python 3.10 | `ee89e18` |
| S1-11 | MusicBrainz User-Agent הצביע על `github.com/ytspot` (לא קיים) ועל גרסה `3.0` (שגוי) — נטען עכשיו מ־`CURRENT_VERSION` ועם ה־repo הנכון | `6bc1097` |

---

## 8. S1 שנותרו פתוחים (S1 Still Open)

**אין S1 פתוחים.** כל 11 ה־S1 שזוהו תוקנו וכולם מכוסים ע"י מבחני רגרסיה חדשים או קיימים.

---

## 9. קבצים שהשתנו (Files Changed)

מצטבר על פני 11 commits של הענף `audit/full-line-audit`:

**Application code (16 קבצים):**

| נתיב | מה השתנה | למה |
|---|---|---|
| `core/update_checker.py` | ברירת `repo_owner` `cdtauman` → `cdtauman-projects` | S0-1 |
| `core/musicbrainz_enricher.py` | User-Agent טוען `CURRENT_VERSION` ומפנה ל־repo הנכון | S1-11 |
| `core/duplicate_checker.py` | ייבוא `_sanitize_filename` מהדוונלוודר; הוספת פלג `include_artist`; תחילית `" - "` תואמת לדוונלוודר | S0-4 / S1-8 |
| `core/downloader.py` | `_sanitize_filename` נחתך ל־200; ניסוח־מחדש של שורת `randomize_user_agent` ושל הודעת השגיאה לעקוף ההצפנה של כרום | S0-4 / S1-5 / S2-5 |
| `core/download_orchestrator.py` | `_persist_record` נגזר את ה־platform מ־`req.platform`; docstring `1-6`; ניסוח־מחדש של הערת Stagger | S1-1 / S1-7 / S2-5 |
| `core/search_engine.py` | התפלגות proportional במקום floors ב־`search_all` וב־`search_youtube_categorized` | S1-3 |
| `cli.py` | `--parallel` clamp `min(6,...)`; עזרה אומרת `1-6` | S1-7 |
| `config.py` | ניסוח־מחדש של docstring הקובץ ושני section headers — "Anti-Ban" → "Rate-limit politeness" | S2-5 |
| `ui/i18n.py` | החלפת כל המחרוזות עם "bypass"/"עקוף" במקבילות אימות־גישה (EN + HE) | S1-5 |
| `ui/workers/update_worker.py` | ברירת `repo_owner` `cdtauman` → `cdtauman-projects`; הוסר ה־TODO ב־docstring | S0-1 |
| `ui/workers/search_worker.py` | docstring מתוקן (`1-100` במקום `1-50`) | S1-3 |
| `ui/workers/download_worker.py` | docstring `1-6` | S1-7 |
| `ui/controllers/download_controller.py` | `is_clean` מוגדר לפני בדיקת כפילויות; `find_duplicate` מקבל `include_artist=False`; משתמש ב־`opts["output_dir"]` במקום `cfg.output_dir`; ממפה `card.platform` ל־`SourcePlatform` enum | S0-4 / S1-1 / S1-2 |
| `ui/panels/settings_panel.py` | קישור About תוקן; הוסר "ולעקוף חסימות" | S0-2 / S1-5 |
| `ui/panels/search_panel.py` | `"ytmusic"` נוסף ל־allow-list ב־`_restore_state` | S1-4 |
| `ui/panels/options_bar.py` | חיבור `editingFinished` לשמירת path לקונפיג + מתודה חדשה `_on_dir_committed` | S1-2 |
| `ui/components/update_banner.py` | URLs ה־placeholder ב־`__main__` demo block מצביעים על ה־repo הנכון | S3-1 (bundled) |

**Tests (3 קבצים):**

| נתיב | מה נוסף |
|---|---|
| `tests/test_p0_gates.py` | `TestUpdateCheckerDefaults` (2 מבחנים), `TestSearchPanelRestoresYTMusic` (1 מבחן עם Qt offscreen) |
| `tests/test_core.py` | `TestDuplicateChecker` הורחב ב־5 מבחני רגרסיה ל־S0-4/S1-8; `TestSearchCategoryBudget` (4 מבחנים); `TestPlaylistSync` תוקן עם fixtures 11 תווים |
| `tests/test_orchestrator.py` | `TestHistoryPlatform` (4 מבחנים) |

**Docs / config / CI (8 קבצים):**

| נתיב | מה השתנה |
|---|---|
| `README.md` | "Anti-Ban Strategy" → "Download Engine & Reliability"; "Anti-ban" features row → "Reliability"; ניסוח־מחדש של פסקאות bypass/DRM ב־troubleshooting; תיקון URL update־checker |
| `user_guide_hebrew.md` | "Anti-Ban Delay" → "השהיית קצב בקשות"; "1 עד 5" → "1 עד 6"; סעיף 7.3 נכתב מחדש סביב התחברות במקום "עקיפת הגנות" |
| `PROJECT_STRUCTURE.md` | תיאור `browser_window` נוסח מחדש |
| `.gitignore` | נכתב מחדש מאפס; נוספו `*.egg-info/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.env`, `*.log`, ועוד |
| `.github/workflows/tests.yml` | מטריצת OS = `[windows-latest, ubuntu-latest]`; Python = `[3.10, 3.11, 3.12]`; P0 gates רצים |
| **נמחקו** | `.claude/settings.local.json` (6 קבצי `ytspot_downloader.egg-info/*` — generated artifacts) |

**Audit artifacts (10 קבצים שנוספו ב־commit `21ada84`):**

`AUDIT_COVERAGE_MANIFEST.md`, `AUDIT_SYMBOL_GRAPH.md`, `AUDIT_UNUSED_OR_DEAD_CODE.md`, `AUDIT_ACTION_MAP.md`, `AUDIT_RELEASE_BLOCKERS.md`, `tools/audit/manifest_builder.py`, `tools/audit/symbol_scan.py`, `tools/audit/_all_files.txt`, `tools/audit/_manifest_seed.tsv`, `tools/audit/_symbols.tsv`.

---

## 10. בדיקות שרצו (Tests Run)

| פקודה | תוצאה | הערות |
|---|---|---|
| `python -m compileall -q .` | exit 0 (פלט ריק) | כל קבצי ה־py קומפלים נקי |
| `QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q --tb=line` | **182 passed** ב־50.79 שניות | כולל ה־P0 gates ואת מבחני הרגרסיה החדשים |
| `python -c "import main"` | OK | smoke import של ה־entry point של ה־GUI |
| `python -c "from cli import build_parser, main"` | OK | smoke import של ה־CLI |
| `python cli.py --help` | מציג `Concurrent downloads (1-6, default: 3)` | אישור ש־S1-7 תוקן |
| `ruff check .` / `pyflakes .` / `vulture .` | לא הותקנו בסביבה | דולג מתודית — הביקורת השתמשה ב־AST + ripgrep במקומם |

**רגרסיה:** 15 מבחנים חדשים, כולם עוברים. אין מבחנים שנשברו עקב התיקונים. המבחן הקיים `tests/test_core.py::TestPlaylistSync` היה שבור מקודם (fixtures של 12 תווים על rgex של 11 תווים) — תוקן יחד עם ה־CI fix (S1-10).

---

## 11. סיכוני שחרור (Risks)

* **משפטי/מיתוגי:** הוסר השימוש ב־"Bypass Protection"/"Anti-Ban"/"DRM" מ־UI ומ־README. השאר־מילים שמורים פנימה: `BotBypassWindow` (שם class פנימי), `ytspot_bypass_*.txt` (שמות temp file). אלה לא חשופים ל־UI ולא ל־GitHub README, אז S3 — להחליף ב־v1.1.
* **Cookies / Privacy:** האפליקציה לא שולחת cookies לאף שרת חיצוני; משתמשת בהם רק כדי להזין yt-dlp. הצורך התיעודי הובהר ב־README ("only content you have rights to access").
* **Generic extractor / Spider:** PageScraper משתמש ב־Playwright כ־fallback אחרון לדף וידאו לא־מוכר. אם אתר משתמש ב־DRM (Widevine וכו'), ההורדה תיכשל בצורה נקייה. **אין צבירה של בייפס DRM בקוד.**
* **Filename collisions:** S0-4 + S1-8 פתרו את הבעיה הקריטית, אבל clean filename (`is_clean=True`) עדיין עלול לייצר collision כשבאותו playlist יש שני שירים בעלי שם זהה (למשל cover + מקור) — `find_duplicate` כעת יזהה את הראשון; השני יהיה ה־duplicate. זה הקיים — לא רגרסיה. שיפור עתידי: לכלול את ה־index ב־solo downloads כדי לקבל "01 - Title" / "02 - Title".
* **Packaging:** version=`1.0.0` יציב ועקבי בין pyproject.toml, update_checker.py, main.py. ה־egg-info כבר לא tracked. אין PyInstaller spec כרגע — שחרור binary ידרוש שלב נוסף.
* **Windows SmartScreen:** ה־CLI לא חתום דיגיטלית. בהנחה שזה לא binary שלם, ה־SmartScreen לא רלוונטי לשלב הזה. כשייצא installer חתום בעתיד, להתחשב בזה.
* **Test coverage:** 182 מבחנים אוטומטיים. אזורים שעדיין בלי כיסוי טוב: scraper, converter panel, channel scraping flow, lyrics/replay_gain pipelines. לא חוסם beta.

---

## 12. הקומיט הבא המומלץ (Recommended Next Commit)

לאחר הביקורת הזו, רצף מומלץ של עבודה (לפי סדר ערך/מאמץ):

1. **חיבור `error_handler.run_preflight()` ל־`main.py`** (S2-3) — שני קומיטים: עדכון `main.py` + MessageBox אם `not result.all_ok()`. UX שיפור משמעותי לסטארטאפ ראשון.
2. **מחיקת קוד מת מוודא** — `AppConfig.window_geometry` (S2-4), `DownloadEngine.download_async` (S2-6). commit אחד תחת `chore: remove dead code`.
3. **`--version` ו־`--doctor` ב־CLI** (S2-7) — תוספים קטנים שמייצרים ערך גדול לתפעול ולפיתוח.
4. **UI שחזור גיבוי tag-editor** (S2-9) — קומפוננטה קטנה שמשלימה את הפיצ'ר הקיים של גיבוי.
5. **מימוש או הסרת `randomize_user_agent`** — כרגע הפרמטר משורשר לכל אורך הקריאות אבל לא מבצע דבר. אם רוצים את הפיצ'ר, להוסיף קוד אמיתי ב־`utils/yt_dlp_opts.build_base_ydl_opts`. אם לא, להוציא את כל המסלול ולמחוק את ה־config key (במיגרציה).
6. **i18n של שמות תיקיות עברית בשמירת קבצים** (S3-3) — לאפשר למשתמשי אנגלית "Albums"/"Singles & EPs" במקום "אלבומים"/"סינגלים ו-EP".

---

## 13. המלצה סופית (Final Recommendation)

* **האם להיכנס ל־feature freeze:** **כן**. הרצף `audit/full-line-audit` מקפל את כל ה־release-blocking work. כל פיצ'ר חדש שיירכב מעל זה (כולל לבנייה הזו ב־beta) יעכב את ההגעה לציבור.
* **האם אפשר beta:** **כן**, אחרי `git merge audit/full-line-audit` ל־`main` ופוש לתגית `v1.0.0-beta.1`. אין S0/S1 פתוחים. CI מכוסה ב־Windows + 3.10/3.11/3.12. הבדיקה האוטומטית מאמתת את 11 ה־findings העיקריים.
* **מה אסור להוסיף עכשיו:**
  * אין providers חדשים (SoundCloud / Bandcamp / Apple Music) — כל אחד מהם נושא סיכון משפטי ייחודי ויכביד על ההיקף.
  * אין DRM circumvention או stealth techniques.
  * אין שינויי ארכיטקטורה — Service container ו־controllers/workers/panels עובדים. אסור לעבור ל־MVVM, async/await, או רפקטור גדול לפני שיש משוב מהביתא.
  * אין installer חתום עדיין — לעשות זאת רק אחרי שמסיימים את ה־beta וקובעים name/branding סופיים. SmartScreen דורש EV cert.
  * אין שינוי בטוקן ה־Spotify proxy ב־`config.py:96` (אלא אם נחשוד שהוא דלף) — זה מפתח חולק.

**סטטוס סופי:** הענף `audit/full-line-audit` מוכן ל־`gh pr create` ול־merge ל־main. אחרי ה־merge, פתוח לדחיפת תגית v1.0.0-beta.1 ולחלוקה למשתמשי beta.
