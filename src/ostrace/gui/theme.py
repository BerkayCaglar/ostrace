# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Colours, as a function of a scheme rather than a reading of the platform.

``palette_for()`` is deterministic: the same scheme yields the same palette on
every operating system. That is not a simplification, it is the point. ADR 0004
chose Qt because it draws its own widgets identically everywhere, which is what
makes a GUI written without a Mac testable at all; a palette read out of the
platform would hand that back.

The measurement that forced this shape: ``QStyleHints.setColorScheme()`` is a
no-op under the ``offscreen`` platform plugin -- ``colorScheme()`` stays
``Unknown``, the palette never changes, ``colorSchemeChanged`` never fires, and
the Fusion style does not rescue it. ``QApplication.setPalette()`` works under
every plugin. So the operating system gets to decide *which* scheme, and
nothing else. Three things follow, which is how you know it is the right seam:
the colour maths is assertable in the offscreen CI lane, the screenshot job can
force either scheme on any platform including macOS, and a live theme switch is
this same function called again.

Severity colour is reinforcement, never information. A background tint at the
strength that stays comfortable under a wall of text lands near 1.1:1 against
``Base`` -- nowhere near legible on its own -- so the Level column stays text
and the two levels that matter carry a glyph as well. Foregrounds are checked
against WCAG AA in ``test_gui_theme.py``, in both schemes, so a colour tweak
that quietly drops below 4.5:1 fails the suite rather than the user.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette

from ostrace.model import Level

if TYPE_CHECKING:
    from PySide6.QtGui import QStyleHints
    from PySide6.QtWidgets import QApplication

__all__ = [
    "MARK_ACCENT",
    "MARK_TINT",
    "Scheme",
    "Severity",
    "apply_theme",
    "contrast_ratio",
    "mark_accent",
    "mark_tint",
    "palette_for",
    "resolve_scheme",
    "severity_for",
]

#: Qt's own preference for Windows 11, and the only widely-styled option that
#: renders dark correctly. It is also what makes Windows a faithful preview of
#: macOS, which for a project with no Mac is worth more than native chrome.
STYLE = "Fusion"


class Scheme(StrEnum):
    """Which of the two palettes to build."""

    LIGHT = "light"
    DARK = "dark"


# Palette roles, per scheme. Written out rather than derived from one another:
# a dark theme is not a light theme with the lightness inverted, and pretending
# otherwise is how dark modes end up with grey-on-grey text.
_ROLES: dict[Scheme, dict[QPalette.ColorRole, str]] = {
    Scheme.LIGHT: {
        QPalette.ColorRole.Window: "#f3f3f3",
        QPalette.ColorRole.WindowText: "#1a1a1a",
        QPalette.ColorRole.Base: "#ffffff",
        QPalette.ColorRole.AlternateBase: "#f7f7f7",
        QPalette.ColorRole.Text: "#1a1a1a",
        QPalette.ColorRole.Button: "#f3f3f3",
        QPalette.ColorRole.ButtonText: "#1a1a1a",
        QPalette.ColorRole.Highlight: "#0067c0",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.PlaceholderText: "#6b6b6b",
        QPalette.ColorRole.ToolTipBase: "#ffffff",
        QPalette.ColorRole.ToolTipText: "#1a1a1a",
        QPalette.ColorRole.Link: "#0067c0",
        QPalette.ColorRole.Mid: "#c8c8c8",
        QPalette.ColorRole.Dark: "#9a9a9a",
        QPalette.ColorRole.Shadow: "#b0b0b0",
    },
    Scheme.DARK: {
        QPalette.ColorRole.Window: "#1e1e1e",
        QPalette.ColorRole.WindowText: "#f0f0f0",
        QPalette.ColorRole.Base: "#252526",
        QPalette.ColorRole.AlternateBase: "#2d2d30",
        QPalette.ColorRole.Text: "#f0f0f0",
        QPalette.ColorRole.Button: "#2d2d30",
        QPalette.ColorRole.ButtonText: "#f0f0f0",
        QPalette.ColorRole.Highlight: "#0078d4",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.PlaceholderText: "#9a9a9a",
        QPalette.ColorRole.ToolTipBase: "#2d2d30",
        QPalette.ColorRole.ToolTipText: "#f0f0f0",
        QPalette.ColorRole.Link: "#4cc2ff",
        QPalette.ColorRole.Mid: "#3f3f42",
        QPalette.ColorRole.Dark: "#141414",
        QPalette.ColorRole.Shadow: "#000000",
    },
}

#: A row the user marked. Deliberately nowhere near `Highlight`: the first
#: version borrowed an accent colour and produced a marked row identical to a
#: selected one, so the user could not tell what they had marked from what they
#: had clicked. Amber against the blue selection is unmistakable at a glance,
#: and every severity foreground stays above WCAG AA on it -- asserted in
#: `test_gui_theme.py`, because a mark that makes an Error unreadable is worse
#: than no mark.
MARK_TINT: dict[Scheme, str] = {Scheme.LIGHT: "#fff7d6", Scheme.DARK: "#332c1a"}

#: Disabled text, per scheme. ``Disabled`` is not decorative: Fusion renders it
#: for every disabled widget, and leaving it at the default produces a disabled
#: control that is more legible than an enabled one in the dark scheme.
_DISABLED_TEXT: dict[Scheme, str] = {Scheme.LIGHT: "#a0a0a0", Scheme.DARK: "#6e6e6e"}


@dataclass(frozen=True, slots=True)
class Severity:
    """How one level is drawn.

    ``glyph`` exists so that severity survives being printed in black and
    white, pasted into a plain-text issue, or read by someone who cannot
    distinguish the hues. Empty for the levels that carry no urgency.
    """

    foreground: QColor
    tint: QColor | None
    glyph: str


_SEVERITY: dict[Scheme, dict[Level, tuple[str, str | None, str]]] = {
    Scheme.LIGHT: {
        Level.DEBUG: ("#6b6b6b", None, ""),
        Level.INFO: ("#1a1a1a", None, ""),
        Level.NOTICE: ("#1a1a1a", None, ""),
        Level.USER_ACTION: ("#0067c0", None, ""),
        Level.ERROR: ("#b3261e", None, "!"),
        Level.FAULT: ("#8c1d18", "#fdecea", "!!"),
    },
    Scheme.DARK: {
        Level.DEBUG: ("#9a9a9a", None, ""),
        Level.INFO: ("#f0f0f0", None, ""),
        Level.NOTICE: ("#f0f0f0", None, ""),
        Level.USER_ACTION: ("#4cc2ff", None, ""),
        Level.ERROR: ("#ff6b6b", None, "!"),
        Level.FAULT: ("#ff8080", "#3a1f1f", "!!"),
    },
}


def palette_for(scheme: Scheme) -> QPalette:
    """Build the complete palette for ``scheme``.

    Every role is set explicitly for all three colour groups. Leaving a role at
    Qt's default means it comes from whatever the platform style decided, which
    is exactly the platform dependence this module exists to remove.
    """
    palette = QPalette()
    for role, value in _ROLES[scheme].items():
        colour = QColor(value)
        for group in (
            QPalette.ColorGroup.Active,
            QPalette.ColorGroup.Inactive,
            QPalette.ColorGroup.Disabled,
        ):
            palette.setColor(group, role, colour)

    disabled = QColor(_DISABLED_TEXT[scheme])
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.HighlightedText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    return palette


#: The same idea as `MARK_TINT`, saturated enough to read as a two-pixel stripe
#: on the minimap. A tint chosen to sit comfortably behind a wall of text is by
#: construction too faint to see on its own.
MARK_ACCENT: dict[Scheme, str] = {Scheme.LIGHT: "#b8860b", Scheme.DARK: "#e0a83c"}


def mark_tint(scheme: Scheme) -> QColor:
    """The background of a marked row."""
    return QColor(MARK_TINT[scheme])


def mark_accent(scheme: Scheme) -> QColor:
    """The mark, where it has to be visible as a thin line rather than a wash."""
    return QColor(MARK_ACCENT[scheme])


def severity_for(level: Level, scheme: Scheme) -> Severity:
    """How ``level`` is drawn under ``scheme``."""
    foreground, tint, glyph = _SEVERITY[scheme][level]
    return Severity(
        foreground=QColor(foreground),
        tint=QColor(tint) if tint is not None else None,
        glyph=glyph,
    )


def resolve_scheme(hints: QStyleHints) -> Scheme:
    """Which scheme the platform is asking for.

    ``Unknown`` is the honest answer under the offscreen plugin and on any
    platform theme Qt does not recognise, and it is not an error -- it means
    nobody expressed a preference, so the light scheme wins. This is the only
    place the operating system gets a say in how anything looks.
    """
    return Scheme.DARK if hints.colorScheme() == Qt.ColorScheme.Dark else Scheme.LIGHT


def apply_theme(app: QApplication, scheme: Scheme) -> None:
    """Put ``scheme`` on the application.

    The style is set first and the palette second, and the order is load-
    bearing: ``QApplication`` resets the palette to the style's defaults when
    the style changes, so setting the palette first silently discards it.
    """
    app.setStyle(STYLE)
    app.setPalette(palette_for(scheme))


def contrast_ratio(first: QColor, second: QColor) -> float:
    """WCAG 2.1 contrast ratio, from 1.0 (identical) to 21.0 (black on white).

    Here rather than in the tests because it is what the palette above was
    designed against; a reader changing a colour needs the yardstick next to
    the colours, not in a file they may not open.
    """
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


#: Below this the WCAG transfer function is linear rather than a power curve.
_LINEAR_BELOW = 0.04045


def _luminance(colour: QColor) -> float:
    """WCAG relative luminance."""
    red, green, blue = (
        raw / 12.92 if raw <= _LINEAR_BELOW else ((raw + 0.055) / 1.055) ** 2.4
        for raw in (colour.redF(), colour.greenF(), colour.blueF())
    )
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue
