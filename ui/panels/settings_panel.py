"""
ui/panels/settings_panel.py  –  Settings sub-interface  (v3)
=============================================================
Changelog v3
------------
New setting groups added (all backward-compatible – no removed cards):
  * Accent Color picker (swatch row under Appearance)
  * Accessibility Mode toggle
  * Advanced Audio group:
      - SponsorBlock toggle
      - Lyrics Downloader toggle (Advanced, default OFF)
      - Replay Gain toggle (Advanced, default OFF)
      - Square Thumbnails toggle (Advanced, default OFF)
      - MusicBrainz enrichment toggle
  * Playlist Behaviour group:
      - Playlist sub-folders toggle
      - Track index prefix toggle
      - Duplicate action selector (skip / warn / overwrite)
  * System Integration group:
      - Tray on close toggle
      - Global hotkeys toggle
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QBoxLayout, QFileDialog, QFrame, QHBoxLayout, QLabel, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    ComboBoxSettingCard, ExpandLayout,
    FluentIcon, HyperlinkCard,
    OptionsConfigItem, OptionsValidator,
    PushButton, PushSettingCard, SettingCardGroup,
    SwitchSettingCard,
)

from config import AppConfig
from core.update_checker import CURRENT_VERSION
from ui.direction import force_ltr_input
from ui.i18n import t
from ui.theme_manager import ACCENT_COLOR, ACCENT_PALETTE, ThemeManager, get_colors


# ──────────────────────────────────────────────────────────────────────────────
# SettingsPanel
# ──────────────────────────────────────────────────────────────────────────────

class SettingsPanel(QScrollArea):
    """
    Full settings sub-interface for FluentWindow.

    Signals
    -------
    theme_changed(str)             – new theme name
    accent_changed(str)            – new accent hex
    clipboard_monitor_changed(bool)
    accessibility_changed(bool)    – NEW
    settings_saved()
    """

    theme_changed              = Signal(str)
    accent_changed             = Signal(str)
    clipboard_monitor_changed  = Signal(bool)
    accessibility_changed      = Signal(bool)
    login_fix_requested        = Signal()  # NEW
    settings_saved             = Signal()

    def __init__(
        self,
        config: AppConfig,
        theme:  ThemeManager,
        parent: QWidget = None,
    ) -> None:
        super().__init__(parent)
        self._cfg   = config
        self._theme = theme
        self._build()

        tm = ThemeManager.instance()
        if tm is not None:
            tm.theme_changed.connect(self._apply_theme)

    # ── Public API ─────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        self._thumb_card.setChecked(self._cfg.embed_thumbnail)
        self._meta_card.setChecked(self._cfg.embed_metadata)
        self._clip_card.setChecked(self._cfg.clipboard_monitor)
        self._update_card.setChecked(self._cfg.check_updates)
        self._theme_card.setContent(self._theme.theme_display_label())
        try:
            self._lang_card.setValue(self._cfg.language)
        except Exception:
            pass
        cookies = self._cfg.cookies_file
        self._cookies_card.setContent(
            cookies if cookies else t("cookies_file_unset")
        )
        try:
            self._browser_card.setValue(self._cfg.cookies_browser)
            self._youtube_results_card.setValue(self._cfg.youtube_max_results)
            self._spotify_results_card.setValue(self._cfg.spotify_max_results)
            self._spotify_proxy_card.setText(self._cfg.proxy_server_url)
            self._spotify_proxy_token_card.setText(self._cfg.spotify_app_api_key)
            self._youtube_proxy_card.setText(self._cfg.get("youtube_proxy_url", ""))
        except Exception:
            pass
        QTimer.singleShot(0, self._adjust_layouts)

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.setObjectName("settingsPage")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._scroll_content = QWidget()
        content = self._scroll_content
        self._apply_theme()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(36, 28, 36, 40)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ── 1. Appearance ──────────────────────────────────────────────────────
        appearance_grp = SettingCardGroup(t("appearance"), content)

        self._theme_card = PushSettingCard(
            text=self._theme.next_theme_label(),
            icon=FluentIcon.BRUSH,
            title=t("switch_theme"),
            content=self._theme.theme_display_label(),
            parent=appearance_grp,
        )
        self._theme_card.clicked.connect(self._on_theme_click)
        appearance_grp.addSettingCard(self._theme_card)

        # Accent color swatch row
        accent_card = _AccentPickerCard(
            current_accent=self._cfg.accent_color,
            parent=appearance_grp,
        )
        accent_card.accent_changed.connect(self._on_accent_change)
        appearance_grp.addSettingCard(accent_card)

        self._lang_card = _LanguageSettingCard(
            icon=FluentIcon.LANGUAGE,
            title=t("language"),
            content=t("select_language"),
            value=self._cfg.language,
            options=(("en", "English"), ("he", "עברית")),
            parent=appearance_grp,
        )
        self._lang_card.value_changed.connect(self._on_language_change)
        appearance_grp.addSettingCard(self._lang_card)

        # Accessibility mode
        self._a11y_card = SwitchSettingCard(
            icon=FluentIcon.PEOPLE,
            title=t("accessibility_mode"),
            content=t("accessibility_mode_desc"),
            parent=appearance_grp,
        )
        self._a11y_card.setChecked(self._cfg.accessibility_mode)
        self._a11y_card.checkedChanged.connect(self._on_accessibility_toggle)
        appearance_grp.addSettingCard(self._a11y_card)

        layout.addWidget(appearance_grp)

        # ── 2. Downloads ───────────────────────────────────────────────────────
        downloads_grp = SettingCardGroup(t("downloads_group"), content)

        self._thumb_card = SwitchSettingCard(
            icon=FluentIcon.PHOTO,
            title=t("embed_thumbnail"),
            content=t("embed_thumbnail_desc"),
            parent=downloads_grp,
        )
        self._thumb_card.setChecked(self._cfg.embed_thumbnail)
        self._thumb_card.checkedChanged.connect(
            lambda v: self._persist("embed_thumbnail", v)
        )
        downloads_grp.addSettingCard(self._thumb_card)

        self._meta_card = SwitchSettingCard(
            icon=FluentIcon.TAG,
            title=t("embed_metadata"),
            content=t("embed_metadata_desc"),
            parent=downloads_grp,
        )
        self._meta_card.setChecked(self._cfg.embed_metadata)
        self._meta_card.checkedChanged.connect(
            lambda v: self._persist("embed_metadata", v)
        )
        downloads_grp.addSettingCard(self._meta_card)

        self._parallel_card = _SpinnerSettingCard(
            icon=FluentIcon.SPEED_HIGH,
            title=t("concurrent_downloads"),
            content=t("concurrent_downloads_desc"),
            value=self._cfg.max_parallel_downloads,
            min_val=1,
            max_val=5,
            parent=downloads_grp,
        )
        self._parallel_card.value_changed.connect(
            lambda v: self._persist("max_parallel_downloads", v)
        )
        downloads_grp.addSettingCard(self._parallel_card)

        layout.addWidget(downloads_grp)

        # ── 3. Playlist Behaviour ──────────────────────────────────────────────
        playlist_grp = SettingCardGroup(t("playlist_behaviour"), content)

        self._subfolder_card = SwitchSettingCard(
            icon=FluentIcon.FOLDER,
            title=t("playlist_subfolders"),
            content=t("playlist_subfolders_desc"),
            parent=playlist_grp,
        )
        self._subfolder_card.setChecked(self._cfg.playlist_subfolders)
        self._subfolder_card.checkedChanged.connect(
            lambda v: self._persist("playlist_subfolders", v)
        )
        playlist_grp.addSettingCard(self._subfolder_card)

        self._index_card = SwitchSettingCard(
            icon=FluentIcon.LABEL,
            title=t("track_index_prefix"),
            content=t("track_index_prefix_desc"),
            parent=playlist_grp,
        )
        self._index_card.setChecked(self._cfg.playlist_index_prefix)
        self._index_card.checkedChanged.connect(
            lambda v: self._persist("playlist_index_prefix", v)
        )
        playlist_grp.addSettingCard(self._index_card)

        self._dup_card = _LanguageSettingCard(
            icon=FluentIcon.COPY,
            title=t("duplicate_detection"),
            content=t("duplicate_detection_desc"),
            value=self._cfg.duplicate_action,
            options=(
                ("skip",      t("duplicate_skip")),
                ("warn",      t("duplicate_warn")),
                ("overwrite", t("duplicate_overwrite")),
            ),
            parent=playlist_grp,
        )
        self._dup_card.value_changed.connect(
            lambda v: self._persist("duplicate_action", v)
        )
        playlist_grp.addSettingCard(self._dup_card)

        layout.addWidget(playlist_grp)

        # ── 4. Features ────────────────────────────────────────────────────────
        features_grp = SettingCardGroup(t("features"), content)

        self._clip_card = SwitchSettingCard(
            icon=FluentIcon.COPY,
            title=t("clipboard_monitor"),
            content=t("clipboard_monitor_desc"),
            parent=features_grp,
        )
        self._clip_card.setChecked(self._cfg.clipboard_monitor)
        self._clip_card.checkedChanged.connect(self._on_clipboard_toggle)
        features_grp.addSettingCard(self._clip_card)

        self._update_card = SwitchSettingCard(
            icon=FluentIcon.UPDATE,
            title=t("check_updates"),
            content=t("check_updates_desc"),
            parent=features_grp,
        )
        self._update_card.setChecked(self._cfg.check_updates)
        self._update_card.checkedChanged.connect(
            lambda v: self._persist("check_updates", v)
        )
        features_grp.addSettingCard(self._update_card)

        self._browser_card = _LanguageSettingCard(
            icon=FluentIcon.VPN,
            title=t("browser_cookies"),
            content=t("browser_cookies_desc"),
            value=self._cfg.cookies_browser,
            options=(
                ("",        t("disabled")),
                ("chrome",  "Google Chrome"),
                ("firefox", "Mozilla Firefox"),
                ("edge",    "Microsoft Edge"),
                ("brave",   "Brave"),
                ("safari",  "Safari"),
            ),
            parent=features_grp,
        )
        self._browser_card.value_changed.connect(
            lambda v: self._persist("cookies_browser", v)
        )
        features_grp.addSettingCard(self._browser_card)

        layout.addWidget(features_grp)

        # ── 5. System Integration ──────────────────────────────────────────────
        system_grp = SettingCardGroup(t("system_integration"), content)

        self._tray_card = SwitchSettingCard(
            icon=FluentIcon.MINIMIZE,
            title=t("minimise_to_tray"),
            content=t("minimise_to_tray_desc"),
            parent=system_grp,
        )
        self._tray_card.setChecked(self._cfg.tray_on_close)
        self._tray_card.checkedChanged.connect(
            lambda v: self._persist("tray_on_close", v)
        )
        system_grp.addSettingCard(self._tray_card)

        self._hotkeys_card = SwitchSettingCard(
            icon=FluentIcon.COMMAND_PROMPT,
            title=t("global_hotkeys"),
            content=t("global_hotkeys_desc"),
            parent=system_grp,
        )
        self._hotkeys_card.setChecked(self._cfg.global_hotkeys_enabled)
        self._hotkeys_card.checkedChanged.connect(
            lambda v: self._persist("global_hotkeys_enabled", v)
        )
        system_grp.addSettingCard(self._hotkeys_card)

        layout.addWidget(system_grp)

        # ── 6. Advanced Audio Processing ───────────────────────────────────────
        advanced_grp = SettingCardGroup(t("advanced_audio_processing"), content)

        # SponsorBlock
        self._sb_card = SwitchSettingCard(
            icon=FluentIcon.REMOVE,
            title=t("sponsorblock_title"),
            content=t("sponsorblock_desc"),
            parent=advanced_grp,
        )
        self._sb_card.setChecked(self._cfg.sponsorblock_enabled)
        self._sb_card.checkedChanged.connect(
            lambda v: self._persist("sponsorblock_enabled", v)
        )
        advanced_grp.addSettingCard(self._sb_card)

        # MusicBrainz
        self._mb_card = SwitchSettingCard(
            icon=FluentIcon.SEARCH,
            title=t("musicbrainz_title"),
            content=t("musicbrainz_desc"),
            parent=advanced_grp,
        )
        self._mb_card.setChecked(self._cfg.musicbrainz_enabled)
        self._mb_card.checkedChanged.connect(
            lambda v: self._persist("musicbrainz_enabled", v)
        )
        advanced_grp.addSettingCard(self._mb_card)

        # Lyrics (disabled by default)
        self._lyrics_card = SwitchSettingCard(
            icon=FluentIcon.DOCUMENT,
            title=t("lyrics_title"),
            content=t("lyrics_desc"),
            parent=advanced_grp,
        )
        self._lyrics_card.setChecked(self._cfg.lyrics_enabled)
        self._lyrics_card.checkedChanged.connect(
            lambda v: self._persist("lyrics_enabled", v)
        )
        advanced_grp.addSettingCard(self._lyrics_card)

        # Replay Gain (disabled by default)
        self._rg_card = SwitchSettingCard(
            icon=FluentIcon.VOLUME,
            title=t("replay_gain_title"),
            content=t("replay_gain_desc"),
            parent=advanced_grp,
        )
        self._rg_card.setChecked(self._cfg.replay_gain_enabled)
        self._rg_card.checkedChanged.connect(
            lambda v: self._persist("replay_gain_enabled", v)
        )
        advanced_grp.addSettingCard(self._rg_card)

        # Square Thumbnails (disabled by default)
        self._sq_card = SwitchSettingCard(
            icon=FluentIcon.PHOTO,
            title=t("square_thumbnails_title"),
            content=t("square_thumbnails_desc"),
            parent=advanced_grp,
        )
        self._sq_card.setChecked(self._cfg.square_thumbnails)
        self._sq_card.checkedChanged.connect(
            lambda v: self._persist("square_thumbnails", v)
        )
        advanced_grp.addSettingCard(self._sq_card)

        # Expand Thumbnails (disabled by default)
        self._expand_card = SwitchSettingCard(
            icon=FluentIcon.PHOTO,
            title=t("expand_square_to_rectangle_title"),
            content=t("expand_square_to_rectangle_desc"),
            parent=advanced_grp,
        )
        self._expand_card.setChecked(self._cfg.expand_thumbnails)
        self._expand_card.checkedChanged.connect(
            lambda v: self._persist("expand_thumbnails", v)
        )
        advanced_grp.addSettingCard(self._expand_card)

        layout.addWidget(advanced_grp)

        # ── 7. Authentication / Cookies ────────────────────────────────────────
        auth_grp = SettingCardGroup(t("authentication"), content)

        self._cookies_card = PushSettingCard(
            text=t("browse"),
            icon=FluentIcon.CERTIFICATE,
            title=t("cookies_file"),
            content=(
                self._cfg.cookies_file
                if self._cfg.cookies_file
                else t("cookies_file_unset")
            ),
            parent=auth_grp,
        )
        self._cookies_card.clicked.connect(self._on_browse_cookies)
        auth_grp.addSettingCard(self._cookies_card)

        self._clear_cookies_card = PushSettingCard(
            text=t("clear"),
            icon=FluentIcon.DELETE,
            title=t("clear_cookies"),
            content=t("clear_cookies_desc"),
            parent=auth_grp,
        )
        self._clear_cookies_card.clicked.connect(self._on_clear_cookies)
        auth_grp.addSettingCard(self._clear_cookies_card)

        self._login_fix_card = PushSettingCard(
            text=t("external_login_now_btn"),
            icon=FluentIcon.PEOPLE,
            title=t("external_login_title"),
            content=t("external_login_desc"),
            parent=auth_grp,
        )
        self._login_fix_card.clicked.connect(self.login_fix_requested)
        auth_grp.addSettingCard(self._login_fix_card)

        layout.addWidget(auth_grp)

        # ── 8. Search settings ─────────────────────────────────────────────────
        search_grp = SettingCardGroup(t("search_group"), content)

        self._youtube_results_card = _SpinnerSettingCard(
            icon=FluentIcon.SEARCH,
            title=t("max_youtube_results"),
            content=t("max_youtube_results_desc"),
            value=self._cfg.youtube_max_results,
            min_val=1,
            max_val=100,
            parent=search_grp,
        )
        self._youtube_results_card.value_changed.connect(
            lambda v: self._persist("youtube_max_results", v)
        )
        search_grp.addSettingCard(self._youtube_results_card)

        self._spotify_results_card = _SpinnerSettingCard(
            icon=FluentIcon.SEARCH,
            title=t("max_spotify_results"),
            content=t("max_spotify_results_desc"),
            value=self._cfg.spotify_max_results,
            min_val=1,
            max_val=100,
            parent=search_grp,
        )
        self._spotify_results_card.value_changed.connect(
            lambda v: self._persist("spotify_max_results", v)
        )
        search_grp.addSettingCard(self._spotify_results_card)

        self._spotify_proxy_card = _TextSettingCard(
            icon=FluentIcon.GLOBE,
            title=t("spotify_proxy"),
            content=t("spotify_proxy_desc"),
            value=self._cfg.proxy_server_url,
            parent=search_grp,
        )
        self._spotify_proxy_card.value_changed.connect(
            lambda v: self._persist("proxy_server_url", v)
        )
        search_grp.addSettingCard(self._spotify_proxy_card)

        self._spotify_proxy_token_card = _TextSettingCard(
            icon=FluentIcon.VPN,
            title=t("spotify_proxy_api_key"),
            content=t("spotify_proxy_api_key_desc"),
            value=self._cfg.spotify_app_api_key,
            parent=search_grp,
        )
        self._spotify_proxy_token_card.value_changed.connect(
            lambda v: self._persist("spotify_app_api_key", v)
        )
        search_grp.addSettingCard(self._spotify_proxy_token_card)

        self._youtube_proxy_card = _TextSettingCard(
            icon=FluentIcon.VPN,
            title=t("youtube_proxy_title"),
            content=t("youtube_proxy_desc"),
            value=self._cfg.get("youtube_proxy_url", ""),
            parent=search_grp,
        )
        self._youtube_proxy_card.value_changed.connect(
            lambda v: self._persist("youtube_proxy_url", v)
        )
        search_grp.addSettingCard(self._youtube_proxy_card)

        layout.addWidget(search_grp)

        # ── 9. About ───────────────────────────────────────────────────────────
        about_grp = SettingCardGroup(t("about"), content)
        about_grp.addSettingCard(HyperlinkCard(
            url="https://github.com/cdtauman-projects/ytspot_downloader",
            text="GitHub",
            icon=FluentIcon.GITHUB,
            title=t("about_app"),
            content=f"YTSpot Downloader  v{CURRENT_VERSION}",
            parent=about_grp,
        ))
        layout.addWidget(about_grp)

        self.setWidget(content)

        # After all cards are built and parented, apply theme once more so the
        # force-restyler can actually find them via findChildren.
        self._apply_theme()
        QTimer.singleShot(0, self._adjust_layouts)

    def _apply_theme(self) -> None:
        c = get_colors()
        self.setStyleSheet(f"""
            QScrollArea {{ background: {c.bg}; border: none; }}
            QScrollBar:vertical {{
                background: {c.bg}; width: 6px; border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: {c.border}; border-radius: 3px; min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {c.surface2}; }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{ height: 0; }}
        """)
        if hasattr(self, "_scroll_content"):
            self._scroll_content.setStyleSheet(f"background: {c.bg};")

        # ── Aggressive walk: force every qfluentwidgets card to refresh ────
        # qfluentwidgets SettingCard.paintEvent reads isDarkTheme() at paint
        # time, but on a live theme switch the cached pixel buffer may not
        # invalidate. We also override the card stylesheet inline so it shows
        # the correct surface/border colors regardless of which QSS layer wins.
        self._force_restyle_fluent_cards(c)
        QTimer.singleShot(0, self._adjust_layouts)

    def _force_restyle_fluent_cards(self, c) -> None:
        """Walk all descendants and force-style every SettingCard variant."""
        from qfluentwidgets import (
            SettingCard as _SC,
            SettingCardGroup as _SCG,
        )

        # Custom card class names (also QFrame-based, our own classes)
        custom_card_names = {
            "_AccentPickerCard",
            "_SpinnerSettingCard",
            "_TextSettingCard",
            "_LanguageSettingCard",
        }

        card_qss = (
            f"background-color: {c.surface};"
            f" border: 1px solid {c.border};"
            f" border-radius: 8px;"
        )

        # 1. Force-style every qfluentwidgets SettingCard descendant
        for card in self.findChildren(_SC):
            # Set per-widget stylesheet (this wins over app-level QSS for the
            # widget AND its direct visible surface). qfluentwidgets' own
            # paintEvent still runs over this but with isDarkTheme() correctly
            # returning False in Light, it paints transparent-ish white,
            # which composites correctly over our explicit light surface.
            card.setStyleSheet(
                f"SettingCard, PushSettingCard, SwitchSettingCard,"
                f" ComboBoxSettingCard, HyperlinkCard, ExpandSettingCard,"
                f" RangeSettingCard, OptionsSettingCard, ColorSettingCard,"
                f" FolderListSettingCard, CustomColorSettingCard {{"
                f"  {card_qss}"
                f"}}"
                f" QLabel {{ background: transparent; color: {c.text_primary}; }}"
                f" QLabel#contentLabel {{ color: {c.text_secondary}; }}"
            )
            # Update palette as a belt-and-braces measure
            pal = card.palette()
            pal.setColor(QPalette.Window, QColor(c.surface))
            pal.setColor(QPalette.Base, QColor(c.surface))
            pal.setColor(QPalette.WindowText, QColor(c.text_primary))
            pal.setColor(QPalette.Text, QColor(c.text_primary))
            card.setPalette(pal)
            card.update()
            card.repaint()

        # 2. Force-style every SettingCardGroup title
        for grp in self.findChildren(_SCG):
            if hasattr(grp, "titleLabel") and grp.titleLabel is not None:
                grp.titleLabel.setStyleSheet(
                    f"color: {c.text_primary}; background: transparent;"
                    f" font-weight: 700; font-size: 15px; border: none;"
                )

        # 3. Force-style our custom cards (they have their own _restyle, but
        #    safety: also walk by class name in case _restyle was missed)
        for child in self.findChildren(QFrame):
            cls_name = type(child).__name__
            if cls_name in custom_card_names:
                if hasattr(child, "_restyle"):
                    try:
                        child._restyle()
                    except Exception:
                        pass
                child.update()
                child.repaint()

        # 4. Force a full visual refresh of the entire scroll content so
        #    cached pixel buffers from the previous theme are discarded.
        if hasattr(self, "_scroll_content"):
            self._scroll_content.update()
            self._scroll_content.repaint()

    def _apply_card_alignment(self, card, rtl: bool) -> None:
        """Apply layout direction, margins, and alignments to a card based on RTL state."""
        # Force LTR layout direction on the card container itself to prevent
        # double-mirroring of the horizontal QBoxLayout direction.
        card.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

        # 1. Defensively set horizontal layout direction and margins
        h_layout = getattr(card, "hBoxLayout", None)
        if h_layout is not None:
            try:
                if rtl:
                    h_layout.setDirection(QBoxLayout.Direction.RightToLeft)
                    h_layout.setContentsMargins(0, 0, 16, 0)
                else:
                    h_layout.setDirection(QBoxLayout.Direction.LeftToRight)
                    h_layout.setContentsMargins(16, 0, 0, 0)
            except Exception:
                pass

        # 2. Defensively set alignment of icon label
        icon_label = getattr(card, "iconLabel", None)
        if icon_label is not None:
            try:
                align_icon = (Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter) if rtl else (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                if h_layout is not None:
                    h_layout.setAlignment(icon_label, align_icon)
            except Exception:
                pass

        # 3. Defensively set alignment of internal vertical text layout
        v_layout = getattr(card, "vBoxLayout", None)
        if v_layout is not None:
            try:
                align_v = (Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter) if rtl else (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                v_layout.setAlignment(align_v)
            except Exception:
                pass

        # 4. Defensively set alignment of labels
        title_label = getattr(card, "titleLabel", None)
        if title_label is not None:
            try:
                align_text = (Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter) if rtl else (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                title_label.setAlignment(align_text)
            except Exception:
                pass

        content_label = getattr(card, "contentLabel", None)
        if content_label is not None:
            try:
                align_text = (Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter) if rtl else (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                content_label.setAlignment(align_text)
            except Exception:
                pass

        # Support custom card fallback attributes
        title_lbl_custom = getattr(card, "_title_lbl", None)
        if title_lbl_custom is not None:
            try:
                align_text = (Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter) if rtl else (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                title_lbl_custom.setAlignment(align_text)
            except Exception:
                pass

        sub_lbl_custom = getattr(card, "_sub_lbl", None)
        if sub_lbl_custom is not None:
            try:
                align_text = (Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter) if rtl else (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                sub_lbl_custom.setAlignment(align_text)
            except Exception:
                pass

        # Defensively set child QComboBox layout directions to RTL if needed
        from PySide6.QtWidgets import QComboBox
        for combo in card.findChildren(QComboBox):
            try:
                combo.setLayoutDirection(Qt.LayoutDirection.RightToLeft if rtl else Qt.LayoutDirection.LeftToRight)
            except Exception:
                pass

    def _adjust_layouts(self) -> None:
        """Walk all setting cards and apply proper RTL/LTR alignment rules."""
        is_hebrew = (self._cfg.language == "he")
        
        # 1. Walk and adjust all standard QFluentWidgets SettingCards
        from qfluentwidgets import SettingCard
        for card in self.findChildren(SettingCard):
            self._apply_card_alignment(card, is_hebrew)

        # 2. Walk and adjust custom cards
        custom_classes = (_LanguageSettingCard, _SpinnerSettingCard, _TextSettingCard, _AccentPickerCard)
        for cls in custom_classes:
            for card in self.findChildren(cls):
                self._apply_card_alignment(card, is_hebrew)

    # ── Handlers ───────────────────────────────────────────────────────────────

    def _on_theme_click(self) -> None:
        new_theme = self._theme.cycle()
        self._theme_card.setContent(self._theme.theme_display_label())
        self._theme_card.button.setText(self._theme.next_theme_label())
        self.theme_changed.emit(new_theme)
        self.settings_saved.emit()

    def _on_accent_change(self, hex_color: str) -> None:
        self._theme.set_accent(hex_color)
        self._persist("accent_color", hex_color)
        self.accent_changed.emit(hex_color)

    def _on_clipboard_toggle(self, checked: bool) -> None:
        self._persist("clipboard_monitor", checked)
        self.clipboard_monitor_changed.emit(checked)

    def _on_accessibility_toggle(self, checked: bool) -> None:
        self._persist("accessibility_mode", checked)
        self.accessibility_changed.emit(checked)

    def _on_browse_cookies(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, t("select_cookies_file"), "", "Cookies (*.txt);;All Files (*)"
        )
        if path:
            self._persist("cookies_file", path)
            self._cookies_card.setContent(path)

    def _on_clear_cookies(self) -> None:
        self._persist("cookies_file", "")
        self._cookies_card.setContent(t("cookies_file_unset"))

    def _on_language_change(self, lang_code: str) -> None:
        self._persist("language", lang_code)
        QTimer.singleShot(0, self._adjust_layouts)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _persist(self, key: str, value) -> None:
        self._cfg.set(key, value)
        self._cfg.save()
        self.settings_saved.emit()


# ──────────────────────────────────────────────────────────────────────────────
# _AccentPickerCard
# ──────────────────────────────────────────────────────────────────────────────

class _AccentPickerCard(QFrame):
    """A row of coloured circle swatches for picking the accent color."""

    from PySide6.QtCore import Signal as _S
    accent_changed = _S(str)   # emits hex string

    def __init__(self, current_accent: str, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._current = current_accent
        self._build()
        self._restyle()

        tm = ThemeManager.instance()
        if tm is not None:
            tm.theme_changed.connect(self._restyle)

    def _build(self) -> None:
        self.setFixedHeight(64)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(10)

        self._title_lbl = QLabel(t("accent_color"))
        row.addWidget(self._title_lbl)
        row.addStretch()

        for name, hex_color in ACCENT_PALETTE.items():
            btn = _SwatchButton(name, hex_color, selected=(hex_color == self._current))
            btn.clicked.connect(lambda _checked, h=hex_color: self._on_swatch(h))
            row.addWidget(btn)

    def _restyle(self) -> None:
        c = get_colors()
        self.setStyleSheet(f"""
            _AccentPickerCard {{
                background: {c.surface};
                border: 1px solid {c.border};
                border-radius: 8px;
            }}
        """)
        self._title_lbl.setStyleSheet(
            f"color: {c.text_primary}; font-size: 13px; background: transparent;"
        )

    def _on_swatch(self, hex_color: str) -> None:
        self._current = hex_color
        # Update selected state on all swatches
        for btn in self.findChildren(_SwatchButton):
            btn.set_selected(btn.hex_color == hex_color)
        self.accent_changed.emit(hex_color)


class _SwatchButton(PushButton):
    """A circular colour swatch button."""

    def __init__(self, name: str, hex_color: str, selected: bool = False) -> None:
        super().__init__()
        self.hex_color = hex_color
        self.setFixedSize(28, 28)
        self.setToolTip(name)
        self.set_selected(selected)

    def set_selected(self, selected: bool) -> None:
        border = "3px solid #ffffff" if selected else "2px solid transparent"
        self.setStyleSheet(f"""
            QPushButton {{
                background: {self.hex_color};
                border: {border};
                border-radius: 14px;
            }}
            QPushButton:hover {{
                border: 2px solid rgba(255,255,255,0.7);
            }}
        """)


# ──────────────────────────────────────────────────────────────────────────────
# _SpinnerSettingCard
# ──────────────────────────────────────────────────────────────────────────────

class _SpinnerSettingCard(QFrame):
    from PySide6.QtCore import Signal as _S
    value_changed = _S(int)

    def __init__(
        self, icon, title: str, content: str,
        value: int, min_val: int, max_val: int,
        parent: QWidget = None,
    ) -> None:
        super().__init__(parent)
        self._value   = value
        self._min_val = min_val
        self._max_val = max_val
        self._build(icon, title, content)
        self._restyle()

        tm = ThemeManager.instance()
        if tm is not None:
            tm.theme_changed.connect(self._restyle)

    def _build(self, icon, title: str, content: str) -> None:
        from qfluentwidgets import IconWidget, SpinBox

        self.setFixedHeight(76)
        row = QHBoxLayout(self)
        row.setSpacing(0)
        row.setContentsMargins(16, 0, 0, 0)

        self.hBoxLayout = row

        self.iconLabel = IconWidget(icon, self)
        self.iconLabel.setFixedSize(16, 16)
        row.addWidget(self.iconLabel)
        row.addSpacing(16)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.vBoxLayout = text_col

        self.titleLabel = QLabel(title)
        self.contentLabel = QLabel(content)
        self.contentLabel.setWordWrap(True)
        text_col.addWidget(self.titleLabel)
        text_col.addWidget(self.contentLabel)
        row.addLayout(text_col, stretch=1)

        row.addSpacing(16)

        self._spin_box = SpinBox(self)
        self._spin_box.setRange(self._min_val, self._max_val)
        self._spin_box.setValue(self._value)
        self._spin_box.setFixedWidth(120)
        self._spin_box.valueChanged.connect(self._on_spin_changed)
        row.addWidget(self._spin_box)

        row.addSpacing(16)

        self._title_lbl = self.titleLabel
        self._sub_lbl = self.contentLabel

    def _restyle(self) -> None:
        c = get_colors()
        self.setStyleSheet(f"""
            _SpinnerSettingCard {{
                background: {c.surface};
                border: 1px solid {c.border};
                border-radius: 8px;
            }}
        """)
        self._title_lbl.setStyleSheet(
            f"color: {c.text_primary}; font-size: 13px; background: transparent;"
        )
        self._sub_lbl.setStyleSheet(
            f"color: {c.text_secondary}; font-size: 11px; background: transparent;"
        )

    def _on_spin_changed(self, value: int) -> None:
        if value != self._value:
            self._value = value
            self.value_changed.emit(value)

    def setValue(self, value: int) -> None:
        self._value = value
        self._spin_box.setValue(value)


# ──────────────────────────────────────────────────────────────────────────────
# _TextSettingCard
# ──────────────────────────────────────────────────────────────────────────────

class _TextSettingCard(QFrame):
    from PySide6.QtCore import Signal as _S
    value_changed = _S(str)

    def __init__(
        self, icon, title: str, content: str, value: str,
        parent: QWidget = None,
    ) -> None:
        super().__init__(parent)
        self._value = value
        self._build(icon, title, content)
        self._restyle()

        tm = ThemeManager.instance()
        if tm is not None:
            tm.theme_changed.connect(self._restyle)

    def _build(self, icon, title: str, content: str) -> None:
        from PySide6.QtWidgets import QLineEdit
        from qfluentwidgets import IconWidget, LineEdit

        self.setFixedHeight(76)
        row = QHBoxLayout(self)
        row.setSpacing(0)
        row.setContentsMargins(16, 0, 0, 0)

        self.hBoxLayout = row

        self.iconLabel = IconWidget(icon, self)
        self.iconLabel.setFixedSize(16, 16)
        row.addWidget(self.iconLabel)
        row.addSpacing(16)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.vBoxLayout = text_col

        self.titleLabel = QLabel(title)
        self.contentLabel = QLabel(content)
        self.contentLabel.setWordWrap(True)
        text_col.addWidget(self.titleLabel)
        text_col.addWidget(self.contentLabel)
        row.addLayout(text_col, stretch=1)

        row.addSpacing(16)

        self._edit = LineEdit(self)
        self._edit.setText(self._value)
        self._edit.setFixedWidth(260)
        # All three _TextSettingCard instances hold technical values (proxy
        # URL, API token, server URL) that must read L→R even in Hebrew.
        force_ltr_input(self._edit)
        self._edit.editingFinished.connect(self._on_editing_finished)
        row.addWidget(self._edit)

        row.addSpacing(16)

        self._title_lbl = self.titleLabel
        self._sub_lbl = self.contentLabel

    def _restyle(self) -> None:
        c = get_colors()
        self.setStyleSheet(f"""
            _TextSettingCard {{
                background: {c.surface};
                border: 1px solid {c.border};
                border-radius: 8px;
            }}
        """)
        self._title_lbl.setStyleSheet(
            f"color: {c.text_primary}; font-size: 13px; background: transparent;"
        )
        self._sub_lbl.setStyleSheet(
            f"color: {c.text_secondary}; font-size: 11px; background: transparent;"
        )

    def _on_editing_finished(self) -> None:
        v = self._edit.text().strip()
        if v != self._value:
            self._value = v
            self.value_changed.emit(v)

    def setText(self, value: str) -> None:
        self._value = value
        self._edit.setText(value)


# ──────────────────────────────────────────────────────────────────────────────
# _LanguageSettingCard  (reused for any combo-selection cards)
# ──────────────────────────────────────────────────────────────────────────────

class _LanguageSettingCard(QFrame):
    from PySide6.QtCore import Signal as _S
    value_changed = _S(str)

    def __init__(
        self, icon, title: str, content: str,
        value: str, options: tuple,
        parent: QWidget = None,
    ) -> None:
        super().__init__(parent)
        self._value   = value
        self._options = list(options)
        self._build(icon, title, content)
        self._restyle()

        tm = ThemeManager.instance()
        if tm is not None:
            tm.theme_changed.connect(self._restyle)

    def _build(self, icon, title: str, content: str) -> None:
        from PySide6.QtWidgets import QComboBox
        from qfluentwidgets import IconWidget

        self.setFixedHeight(76)
        row = QHBoxLayout(self)
        row.setSpacing(0)
        row.setContentsMargins(16, 0, 0, 0)

        self.hBoxLayout = row

        self.iconLabel = IconWidget(icon, self)
        self.iconLabel.setFixedSize(16, 16)
        row.addWidget(self.iconLabel)
        row.addSpacing(16)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.vBoxLayout = text_col

        self.titleLabel = QLabel(title)
        self.contentLabel = QLabel(content)
        self.contentLabel.setWordWrap(True)
        text_col.addWidget(self.titleLabel)
        text_col.addWidget(self.contentLabel)
        row.addLayout(text_col, stretch=1)

        row.addSpacing(16)

        self._combo = QComboBox(self)
        for code, label in self._options:
            self._combo.addItem(label, userData=code)
        self.setValue(self._value)
        self._combo.currentIndexChanged.connect(self._on_index_changed)
        row.addWidget(self._combo)

        row.addSpacing(16)

        self._title_lbl = self.titleLabel
        self._sub_lbl = self.contentLabel

    def _restyle(self) -> None:
        c = get_colors()
        self.setStyleSheet(f"""
            _LanguageSettingCard {{
                background: {c.surface};
                border: 1px solid {c.border};
                border-radius: 8px;
            }}
        """)
        self._title_lbl.setStyleSheet(
            f"color: {c.text_primary}; font-size: 13px; background: transparent;"
        )
        self._sub_lbl.setStyleSheet(
            f"color: {c.text_secondary}; font-size: 11px; background: transparent;"
        )

    def _on_index_changed(self, index: int) -> None:
        code = self._combo.itemData(index)
        if code is None:
            return
        self._value = code
        self.value_changed.emit(code)

    def setValue(self, value: str) -> None:
        for i in range(self._combo.count()):
            if self._combo.itemData(i) == value:
                self._combo.setCurrentIndex(i)
                return
        if self._combo.count() > 0:
            self._combo.setCurrentIndex(0)
