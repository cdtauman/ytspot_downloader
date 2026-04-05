"""
ui/panels/settings_panel.py  –  Settings sub-interface
=======================================================
A full-height scrollable settings panel using QFluentWidgets' native
SettingCard family, giving it the same look as the Windows 11 Settings app.

This module provides SettingsPanel as a standalone QScrollArea subclass
that can be registered directly with FluentWindow.addSubInterface().

It replaces the inline _build_settings_interface() method in app_window.py.
To use it, import and instantiate it in AppWindow._build_panels(), then
pass it to addSubInterface() in AppWindow._register_navigation().

Signals emitted upward
----------------------
theme_changed(str)
    Emitted when the user clicks the theme cycle button.
    Payload is the new theme name ("dark" | "light" | "oled").

clipboard_monitor_changed(bool)
    Emitted when the clipboard monitor switch is toggled.
    AppWindow starts or stops ClipboardWorker in response.

settings_saved()
    Emitted after any setting card change that writes to AppConfig.
    AppWindow can use this to sync dependent UI elements (OptionsBar, etc.).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QScrollArea,
    QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    ComboBoxSettingCard, ExpandLayout,
    FluentIcon, HyperlinkCard,
    OptionsConfigItem, OptionsValidator,
    PushSettingCard, SettingCardGroup,
    SwitchSettingCard,
)

from config import AppConfig
from core.update_checker import CURRENT_VERSION
from ui.i18n import t
from ui.theme_manager import ACCENT_COLOR, ThemeManager


# ── Design tokens ──────────────────────────────────────────────────────────────
_BG      = "#111114"
_SURFACE = "#1c1c21"
_BORDER  = "#313139"
_TEXT    = "#f2f2f5"
_TEXT_2  = "#94949e"


# ──────────────────────────────────────────────────────────────────────────────
# SettingsPanel
# ──────────────────────────────────────────────────────────────────────────────

class SettingsPanel(QScrollArea):
    """
    Full settings sub-interface for FluentWindow.

    Parameters
    ----------
    config  : AppConfig  – live config instance; written on every card change.
    theme   : ThemeManager – owned by AppWindow; used to apply theme changes.
    parent  : Optional Qt parent.
    """

    theme_changed              = Signal(str)    # new theme name
    clipboard_monitor_changed  = Signal(bool)   # new toggle state
    settings_saved             = Signal()       # any setting changed

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

    # ── Public API ─────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """
        Re-read all values from AppConfig and update card displays.
        Call this after an external config change (e.g., after OptionsBar saves).
        """
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
        except Exception:
            pass

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.setObjectName("settingsPage")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(f"""
            QScrollArea {{ background: {_BG}; border: none; }}
            QScrollBar:vertical {{
                background: {_BG};
                width: 6px;
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: {_BORDER};
                border-radius: 3px;
                min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{ background: #3e3e47; }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

        # ── Inner content widget ──────────────────────────────────────────────
        content = QWidget()
        content.setStyleSheet(f"background: {_BG};")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(36, 28, 36, 40)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ── 1. Appearance ─────────────────────────────────────────────────────
        appearance_grp = SettingCardGroup(t("appearance"), content)

        self._theme_card = PushSettingCard(
            text=t("switch_theme"),
            icon=FluentIcon.BRUSH,
            title=t("theme"),
            content=self._theme.theme_display_label(),
            parent=appearance_grp,
        )
        self._theme_card.setToolTip(t("theme_tooltip"))
        self._theme_card.clicked.connect(self._on_cycle_theme)
        appearance_grp.addSettingCard(self._theme_card)

        # Language selection
        self._lang_card = _LanguageSettingCard(
            icon=FluentIcon.GLOBE,
            title=t("language"),
            content=t("select_language"),
            value=self._cfg.language,
            options=(
                ("en", "English"),
                ("he", "עברית"),
            ),
            parent=appearance_grp,
        )
        self._lang_card.value_changed.connect(self._on_language_change)
        appearance_grp.addSettingCard(self._lang_card)

        layout.addWidget(appearance_grp)

        # ── 2. Downloads ──────────────────────────────────────────────────────
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

        layout.addWidget(downloads_grp)

        # ── 3. Features ───────────────────────────────────────────────────────
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
            lambda v: (setattr(self._cfg, "cookies_browser", v), self.settings_saved.emit())
        )
        features_grp.addSettingCard(self._browser_card)

        layout.addWidget(features_grp)

        # ── 4. Search ─────────────────────────────────────────────────────────
        search_grp = SettingCardGroup(t("search_group"), content)

        self._results_card = _SpinnerSettingCard(
            icon=FluentIcon.SEARCH,
            title=t("max_search_results"),
            content=t("max_search_results_desc"),
            value=self._cfg.search_max_results,
            min_val=1,
            max_val=50,
            parent=search_grp,
        )
        self._results_card.value_changed.connect(
            lambda v: self._persist("search_max_results", v)
        )
        search_grp.addSettingCard(self._results_card)

        layout.addWidget(search_grp)

        # ── 5. Authentication ─────────────────────────────────────────────────
        auth_grp = SettingCardGroup(t("authentication"), content)

        cookies_val = self._cfg.cookies_file
        self._cookies_card = PushSettingCard(
            text=t("browse"),
            icon=FluentIcon.CERTIFICATE,
            title=t("cookies_file"),
            content=(
                cookies_val if cookies_val
                else t("cookies_file_unset")
            ),
            parent=auth_grp,
        )
        self._cookies_card.setToolTip(t("cookies_tooltip"))
        self._cookies_card.clicked.connect(self._on_browse_cookies)
        auth_grp.addSettingCard(self._cookies_card)

        clear_cookies_card = PushSettingCard(
            text=t("clear_cookies"),
            icon=FluentIcon.DELETE,
            title=t("clear_cookies_title"),
            content=t("clear_cookies_desc"),
            parent=auth_grp,
        )
        clear_cookies_card.clicked.connect(self._on_clear_cookies)
        auth_grp.addSettingCard(clear_cookies_card)

        layout.addWidget(auth_grp)

        # ── 6. About ──────────────────────────────────────────────────────────
        about_grp = SettingCardGroup(t("about"), content)

        about_grp.addSettingCard(
            HyperlinkCard(
                url="https://github.com/your-username/ytspot-downloader",
                text=t("open_github"),
                icon=FluentIcon.LINK,
                title="YTSpot Downloader",
                content=t("open_github_desc", version=CURRENT_VERSION),
                parent=about_grp,
            )
        )

        about_grp.addSettingCard(
            HyperlinkCard(
                url="https://github.com/your-username/ytspot-downloader/issues",
                text=t("report_issue"),
                icon=FluentIcon.FEEDBACK,
                title=t("feedback"),
                content=t("feedback_desc"),
                parent=about_grp,
            )
        )

        layout.addWidget(about_grp)
        layout.addStretch()

        self.setWidget(content)

    # ── Slots ──────────────────────────────────────────────────────────────────

    def _on_cycle_theme(self) -> None:
        new_theme = self._theme.cycle()
        self._theme_card.setContent(self._theme.theme_display_label())
        self._persist("theme", new_theme)
        self.theme_changed.emit(new_theme)

    def _on_clipboard_toggle(self, checked: bool) -> None:
        self._persist("clipboard_monitor", checked)
        self.clipboard_monitor_changed.emit(checked)

    def _on_browse_cookies(self) -> None:
        start = self._cfg.cookies_file or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select cookies.txt",
            start,
            "Text files (*.txt);;All files (*.*)",
        )
        if path:
            self._persist("cookies_file", path)
            self._cookies_card.setContent(path)

    def _on_clear_cookies(self) -> None:
        self._persist("cookies_file", "")
        self._cookies_card.setContent(t("cookies_file_unset"))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _persist(self, key: str, value) -> None:
        """Write a single key to AppConfig and save."""
        self._cfg.set(key, value)
        self._cfg.save()
        self.settings_saved.emit()

    def _on_language_change(self, lang_code: str) -> None:
        """Persist language choice and emit saved signal."""
        self._persist("language", lang_code)


# ──────────────────────────────────────────────────────────────────────────────
# _SpinnerSettingCard  –  a SettingCard with +/- integer controls
# ──────────────────────────────────────────────────────────────────────────────

class _SpinnerSettingCard(QFrame):
    """
    A minimal SettingCard-style widget with ToolButtons to increment /
    decrement an integer value, matching the visual style of the other cards.

    Signals
    -------
    value_changed(int)  Emitted when the value changes.
    """

    from PySide6.QtCore import Signal as _S
    value_changed = _S(int)

    def __init__(
        self,
        icon,
        title:   str,
        content: str,
        value:   int,
        min_val: int,
        max_val: int,
        parent:  QWidget = None,
    ) -> None:
        super().__init__(parent)
        self._value   = value
        self._min_val = min_val
        self._max_val = max_val
        self._build(icon, title, content)

    def _build(self, icon, title: str, content: str) -> None:
        from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout
        from qfluentwidgets import IconWidget, ToolButton

        self.setFixedHeight(76)
        self.setStyleSheet(f"""
            _SpinnerSettingCard {{
                background: {_SURFACE};
                border: 1px solid {_BORDER};
                border-radius: 8px;
            }}
        """)

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(12)

        # Icon
        icon_lbl = IconWidget(icon, self)
        icon_lbl.setFixedSize(20, 20)
        row.addWidget(icon_lbl)

        # Text
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.setContentsMargins(0, 0, 0, 0)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 13px; background: transparent;"
        )
        sub_lbl = QLabel(content)
        sub_lbl.setWordWrap(True)
        sub_lbl.setStyleSheet(
            f"color: {_TEXT_2}; font-size: 11px; background: transparent;"
        )
        text_col.addWidget(title_lbl)
        text_col.addWidget(sub_lbl)
        row.addLayout(text_col, stretch=1)

        # Spinner controls
        self._minus_btn = ToolButton()
        self._minus_btn.setText("−")
        self._minus_btn.setFixedSize(30, 30)
        self._minus_btn.clicked.connect(self._decrement)

        self._value_lbl = QLabel(str(self._value))
        self._value_lbl.setFixedWidth(36)
        self._value_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._value_lbl.setStyleSheet(
            f"color: {ACCENT_COLOR}; font-size: 14px;"
            " font-weight: bold; background: transparent;"
        )

        self._plus_btn = ToolButton()
        self._plus_btn.setText("+")
        self._plus_btn.setFixedSize(30, 30)
        self._plus_btn.clicked.connect(self._increment)

        row.addWidget(self._minus_btn)
        row.addWidget(self._value_lbl)
        row.addWidget(self._plus_btn)

    def _increment(self) -> None:
        if self._value < self._max_val:
            self._value += 1
            self._value_lbl.setText(str(self._value))
            self.value_changed.emit(self._value)

    def _decrement(self) -> None:
        if self._value > self._min_val:
            self._value -= 1
            self._value_lbl.setText(str(self._value))
            self.value_changed.emit(self._value)


class _LanguageSettingCard(QFrame):
    """A simple setting card that shows a combo box for language selection."""

    from PySide6.QtCore import Signal as _S
    value_changed = _S(str)

    def __init__(
        self,
        icon,
        title: str,
        content: str,
        value: str,
        options: tuple,
        parent: QWidget = None,
    ) -> None:
        super().__init__(parent)
        self._value = value
        self._options = list(options)
        self._build(icon, title, content)

    def _build(self, icon, title: str, content: str) -> None:
        from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QComboBox
        from qfluentwidgets import IconWidget

        self.setFixedHeight(76)
        self.setStyleSheet(f"""
            _LanguageSettingCard {{
                background: {_SURFACE};
                border: 1px solid {_BORDER};
                border-radius: 8px;
            }}
        """)

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(12)

        # Icon
        icon_lbl = IconWidget(icon, self)
        icon_lbl.setFixedSize(20, 20)
        row.addWidget(icon_lbl)

        # Text
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.setContentsMargins(0, 0, 0, 0)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 13px; background: transparent;"
        )
        sub_lbl = QLabel(content)
        sub_lbl.setStyleSheet(
            f"color: {_TEXT_2}; font-size: 11px; background: transparent;"
        )
        text_col.addWidget(title_lbl)
        text_col.addWidget(sub_lbl)
        row.addLayout(text_col, stretch=1)

        # Combo
        self._combo = QComboBox(self)
        for code, text in self._options:
            self._combo.addItem(text, userData=code)

        # Set initial value
        self.setValue(self._value)
        self._combo.currentIndexChanged.connect(self._on_index_changed)
        row.addWidget(self._combo)

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
        # fallback: set first option
        if self._combo.count() > 0:
            self._combo.setCurrentIndex(0)
