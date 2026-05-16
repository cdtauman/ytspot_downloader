"""
ui/dialogs/conflict_resolution_dialog.py  –  Two-Column Merge (Option 4)
=========================================================================
Shown when ChannelScrapeWorker finds videos that appear in more than one
scraped source (e.g. the same video is in "סרטונים" AND inside a playlist).

Layout
------
Left column  — non-playlist appearances (סרטונים, קצרים, שידורים, …)
Right column — playlist appearances (פלייליסטים / [Playlist Name])

Each row has a checkbox so the user can decide per-occurrence whether to
keep it in the download batch.

Toolbar shortcuts:
  [✓ הכל בסרטונים]  [✓ הכל בפלייליסטים]  [✓ שניהם]  [✗ נקה הכל]

After exec() returns Accepted, read .decisions: list[DuplicateDecision].
Non-duplicate videos are NOT shown here — they pass through unchanged.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QWidget, QFrame, QCheckBox,
    QSizePolicy, QSplitter,
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, PrimaryPushButton, PushButton,
    SubtitleLabel, TitleLabel,
)

from core.duplicate_detector import (
    DuplicateGroup, DuplicateDecision, VideoInfo, _appearance_key,
)
from ui.theme_manager import get_colors, ACCENT_COLOR, WARNING_COLOR, SUCCESS_COLOR


# ── Appearance row ─────────────────────────────────────────────────────────────

class _AppearanceRow(QFrame):
    """One checkbox row representing a single occurrence of a duplicate video."""

    def __init__(self, video: VideoInfo, parent=None) -> None:
        super().__init__(parent)
        self._video = video
        self._build()

    @property
    def video(self) -> VideoInfo:
        return self._video

    @property
    def is_checked(self) -> bool:
        return self._checkbox.isChecked()

    def set_checked(self, v: bool) -> None:
        self._checkbox.setChecked(v)

    def _build(self) -> None:
        c = get_colors()
        self.setStyleSheet(f"""
            _AppearanceRow {{
                background: {c.surface};
                border: 1px solid {c.border};
                border-radius: 8px;
            }}
        """)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(8)

        self._checkbox = QCheckBox()
        self._checkbox.setChecked(True)
        self._checkbox.setStyleSheet(f"accent-color: {ACCENT_COLOR};")

        # Location label: "סרטונים" or "פלייליסטים: שירי בוקר (3)"
        if self._video.playlist_name:
            loc_text = f"{self._video.tab_name}: {self._video.playlist_name}"
            if self._video.playlist_index:
                loc_text += f"  (#{self._video.playlist_index})"
        else:
            loc_text = self._video.tab_name

        loc_lbl = CaptionLabel(loc_text)
        loc_lbl.setStyleSheet(f"color: {c.text_secondary}; background: transparent;")
        loc_lbl.setWordWrap(True)

        lay.addWidget(self._checkbox)
        lay.addWidget(loc_lbl, 1)


# ── Duplicate card (one per video ID) ─────────────────────────────────────────

class _DuplicateCard(QFrame):
    """Shows one duplicate group: title + all its appearances in two columns."""

    def __init__(self, group: DuplicateGroup, parent=None) -> None:
        super().__init__(parent)
        self._group = group
        self._rows:  list[_AppearanceRow] = []
        self._build()

    @property
    def group(self) -> DuplicateGroup:
        return self._group

    def build_decision(self) -> DuplicateDecision:
        keep_keys = {
            _appearance_key(row.video)
            for row in self._rows
            if row.is_checked
        }
        return DuplicateDecision(video_id=self._group.video_id, keep_keys=keep_keys)

    def check_all(self, side: str, value: bool) -> None:
        """side = "playlist" | "non_playlist" | "all" """
        for row in self._rows:
            if side == "all":
                row.set_checked(value)
            elif side == "playlist" and row.video.tab_type == "playlist_item":
                row.set_checked(value)
            elif side == "non_playlist" and row.video.tab_type != "playlist_item":
                row.set_checked(value)

    def _build(self) -> None:
        c = get_colors()
        self.setStyleSheet(f"""
            _DuplicateCard {{
                background: {c.surface2};
                border: 1px solid {c.border};
                border-radius: 10px;
            }}
        """)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(6)

        # Title row
        title_row = QHBoxLayout()
        warn_lbl = QLabel("⚠")
        warn_lbl.setStyleSheet(f"color: {WARNING_COLOR}; font-size: 14px; background: transparent;")
        title_lbl = BodyLabel(self._group.title)
        title_lbl.setStyleSheet(f"color: {c.text_primary}; font-weight: 600; background: transparent;")
        title_lbl.setWordWrap(True)
        count_lbl = CaptionLabel(f"{len(self._group.appearances)} מקורות")
        count_lbl.setStyleSheet(f"color: {c.text_tertiary}; background: transparent;")
        title_row.addWidget(warn_lbl)
        title_row.addWidget(title_lbl, 1)
        title_row.addWidget(count_lbl)
        outer.addLayout(title_row)

        # Two-column layout
        cols = QHBoxLayout()
        cols.setSpacing(8)

        left_col  = self._make_column("📹 סרטונים / קצרים / שידורים", "non_playlist")
        right_col = self._make_column("📋 פלייליסטים", "playlist")
        cols.addLayout(left_col, 1)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.VLine)
        div.setStyleSheet(f"color: {c.border};")
        cols.addWidget(div)

        cols.addLayout(right_col, 1)
        outer.addLayout(cols)

    def _make_column(self, header: str, side: str) -> QVBoxLayout:
        c = get_colors()
        col = QVBoxLayout()
        col.setSpacing(4)

        hdr = CaptionLabel(header)
        hdr.setStyleSheet(f"color: {c.text_tertiary}; background: transparent; font-size: 10px;")
        col.addWidget(hdr)

        is_playlist = (side == "playlist")
        has_any = False
        for appearance in self._group.appearances:
            is_pl_item = (appearance.tab_type == "playlist_item")
            if is_pl_item != is_playlist:
                continue
            row = _AppearanceRow(appearance)
            self._rows.append(row)
            col.addWidget(row)
            has_any = True

        if not has_any:
            empty = CaptionLabel("—")
            empty.setStyleSheet(f"color: {c.text_tertiary}; background: transparent;")
            col.addWidget(empty)

        col.addStretch()
        return col


# ── Main dialog ────────────────────────────────────────────────────────────────

class ConflictResolutionDialog(QDialog):
    """
    Two-Column Merge dialog for duplicate video resolution.

    After exec() returns Accepted, read .decisions: list[DuplicateDecision].
    """

    def __init__(
        self,
        groups:  list[DuplicateGroup],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._groups = groups
        self._cards:  list[_DuplicateCard] = []

        # Public output
        self.decisions: list[DuplicateDecision] = []

        self._build()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        c = get_colors()
        self.setWindowTitle("ניהול כפילויות")
        self.setMinimumSize(640, 500)
        self.setModal(True)
        self.setStyleSheet(f"background: {c.bg};")

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        # Header
        hdr = QHBoxLayout()
        icon_lbl = QLabel("📁")
        icon_lbl.setStyleSheet("font-size: 22px;")
        title_lbl = SubtitleLabel(f"ניהול כפילויות — {len(self._groups)} סרטונים חופפים")
        title_lbl.setStyleSheet(f"color: {c.text_primary};")
        hdr.addWidget(icon_lbl)
        hdr.addWidget(title_lbl, 1)
        root.addLayout(hdr)

        desc = CaptionLabel(
            "הסרטונים הבאים נמצאו ביותר ממקור אחד. סמן ✓ את העותקים שאתה רוצה להוריד.\n"
            "עותקים שונים יישמרו בתיקיות שונות."
        )
        desc.setStyleSheet(f"color: {c.text_secondary};")
        desc.setWordWrap(True)
        root.addWidget(desc)

        # Toolbar
        root.addLayout(self._build_toolbar())

        # Scrollable list of duplicate cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"QScrollArea {{ background: transparent; border: none; }}")

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        list_lay = QVBoxLayout(container)
        list_lay.setSpacing(8)
        list_lay.setContentsMargins(0, 0, 4, 0)

        for group in self._groups:
            card = _DuplicateCard(group)
            self._cards.append(card)
            list_lay.addWidget(card)
        list_lay.addStretch()

        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        # Bottom buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = PushButton("ביטול")
        ok_btn = PrimaryPushButton("אישור — הורד הכל שסומן")
        cancel_btn.clicked.connect(self.reject)
        ok_btn.clicked.connect(self._on_ok)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        root.addLayout(btn_row)

    def _build_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)

        def _btn(label: str, action) -> PushButton:
            b = PushButton(label)
            b.clicked.connect(action)
            b.setFixedHeight(28)
            return b

        row.addWidget(_btn("✓ שמור בסרטונים",    lambda: self._apply_all("non_playlist", True)))
        row.addWidget(_btn("✓ שמור בפלייליסטים", lambda: self._apply_all("playlist", True)))
        row.addWidget(_btn("✓ שמור שניהם",        lambda: self._apply_all("all", True)))
        row.addWidget(_btn("✗ נקה הכל",           lambda: self._apply_all("all", False)))
        row.addStretch()
        return row

    # ── Actions ────────────────────────────────────────────────────────────────

    def _apply_all(self, side: str, value: bool) -> None:
        for card in self._cards:
            card.check_all(side, value)

    def _on_ok(self) -> None:
        self.decisions = [card.build_decision() for card in self._cards]
        self.accept()
