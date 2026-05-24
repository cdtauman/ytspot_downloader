"""
ui/direction.py
Layout-direction helpers for surgical LTR within an RTL app.

The application's global layout direction follows the user's language
(``Qt.RightToLeft`` for Hebrew, ``Qt.LeftToRight`` for English) via
``apply_app_direction`` below. These helpers let individual widgets that
hold technical content (URLs, file paths, codec values, etc.) opt out
of the global direction so their content stays readable.

See :mod:`ui.i18n` for the central language coordinator that calls
``apply_app_direction``.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QWidget


def force_ltr(widget: QWidget) -> None:
    """Force LTR on a widget and all its descendants.

    Use for: containers, ComboBoxes with Latin values (codec/quality),
    tables or rows where technical content dominates.
    """
    widget.setLayoutDirection(Qt.LayoutDirection.LeftToRight)


def force_ltr_input(line_edit: QLineEdit) -> None:
    """Force LTR + left alignment on a single-line text input.

    Use for: URL fields, output path fields, proxy URL fields,
    API token fields, file-path text fields.

    Alignment must be set explicitly because under an RTL parent the
    default ``AlignLeading`` evaluates to right-aligned, which would
    leave the cursor and text on the wrong side.
    """
    line_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
    line_edit.setAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )


def force_ltr_label(label: QLabel) -> None:
    """Force LTR + left alignment on a QLabel showing a path/URL/technical string."""
    label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
    label.setAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )


def apply_app_direction(app: QApplication, lang: str) -> None:
    """Apply the app-wide layout direction for ``lang``.

    Called by :func:`ui.i18n.apply_language`. Hebrew uses RTL; everything
    else defaults to LTR.
    """
    direction = (
        Qt.LayoutDirection.RightToLeft
        if lang == "he"
        else Qt.LayoutDirection.LeftToRight
    )
    app.setLayoutDirection(direction)
