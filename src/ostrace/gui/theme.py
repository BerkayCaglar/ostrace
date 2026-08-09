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
from string import Template
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QToolTip

from ostrace.model import Level

if TYPE_CHECKING:
    from PySide6.QtGui import QStyleHints
    from PySide6.QtWidgets import QApplication

__all__ = [
    "MARK_ACCENT",
    "MARK_TINT",
    "TOKENS",
    "Scheme",
    "Severity",
    "apply_theme",
    "contrast_ratio",
    "mark_accent",
    "mark_tint",
    "palette_for",
    "resolve_scheme",
    "scheme_for",
    "selection_row",
    "severity_for",
    "stylesheet_for",
    "token",
]

#: Qt's own preference for Windows 11, and the only widely-styled option that
#: renders dark correctly. It is also what makes Windows a faithful preview of
#: macOS, which for a project with no Mac is worth more than native chrome.
STYLE = "Fusion"


class Scheme(StrEnum):
    """Which of the two palettes to build."""

    LIGHT = "light"
    DARK = "dark"


#: Every colour this application draws, named by the job it does rather than by
#: the widget it lands on. One table per scheme, written out rather than derived
#: from one another: a dark theme is not a light theme with the lightness
#: inverted, and pretending otherwise is how dark modes end up with grey-on-grey
#: text.
#:
#: Everything below -- the palette, the severity colours, the mark, the
#: stylesheet -- reads from here and from nowhere else. That is what makes the
#: contrast tests worth running: a colour that bypassed this table would be a
#: colour they do not check.
TOKENS: dict[Scheme, dict[str, str]] = {
    Scheme.LIGHT: {
        "surface": "#f1f2f4",
        "surface-raised": "#ffffff",
        "surface-alt": "#f7f8fa",
        "surface-sunken": "#e7e9ed",
        "hover": "#eceff4",
        "border": "#d6d9df",
        "border-strong": "#b3b8c2",
        "control-border": "#7e8590",
        "text-primary": "#14161a",
        "text-secondary": "#474e59",
        "text-muted": "#5f6773",
        "text-disabled": "#a3a9b4",
        "accent": "#1f5fd0",
        "highlight": "#1f5fd0",
        "highlight-text": "#ffffff",
        "selection": "#dbe6fa",
        "mark": "#fff3cf",
        "mark-accent": "#7a5400",
        "gap-band": "#f9e2de",
        "gap-rail": "#a5291c",
        "level-debug": "#5f6773",
        "level-info": "#474e59",
        "level-notice": "#14161a",
        "level-user-action": "#1f5fd0",
        "level-error": "#b02a1f",
        "level-fault": "#8c1d18",
    },
    Scheme.DARK: {
        "surface": "#15171c",
        "surface-raised": "#1b1e24",
        "surface-alt": "#1f232a",
        "surface-sunken": "#101216",
        "hover": "#23282f",
        "border": "#2e333c",
        "border-strong": "#0f1116",
        "control-border": "#6b7381",
        "text-primary": "#e7eaf0",
        "text-secondary": "#b4bbc7",
        "text-muted": "#99a2b0",
        "text-disabled": "#606874",
        "accent": "#5b9bff",
        "highlight": "#2b62bd",
        "highlight-text": "#ffffff",
        "selection": "#22304a",
        "mark": "#332a12",
        "mark-accent": "#e0a83c",
        "gap-band": "#3a2220",
        "gap-rail": "#ff8a7a",
        "level-debug": "#99a2b0",
        "level-info": "#b4bbc7",
        "level-notice": "#e7eaf0",
        "level-user-action": "#5b9bff",
        "level-error": "#ff8a7a",
        "level-fault": "#ffab9d",
    },
}

# Which token fills which Qt role. `Highlight` stays fully saturated because it
# is what menus, combo popups and text selection use, where a wash would read as
# nothing happening. The *table row* selection is a separate token -- see
# `selection_row` -- because a log is read by scanning and a saturated bar
# across it destroys the severity colours it is drawn over.
_ROLES: dict[QPalette.ColorRole, str] = {
    QPalette.ColorRole.Window: "surface",
    QPalette.ColorRole.WindowText: "text-primary",
    QPalette.ColorRole.Base: "surface-raised",
    QPalette.ColorRole.AlternateBase: "surface-alt",
    QPalette.ColorRole.Text: "text-primary",
    QPalette.ColorRole.Button: "surface",
    QPalette.ColorRole.ButtonText: "text-primary",
    QPalette.ColorRole.Highlight: "highlight",
    QPalette.ColorRole.HighlightedText: "highlight-text",
    QPalette.ColorRole.PlaceholderText: "text-muted",
    QPalette.ColorRole.ToolTipBase: "surface-raised",
    QPalette.ColorRole.ToolTipText: "text-primary",
    QPalette.ColorRole.Link: "accent",
    QPalette.ColorRole.Accent: "accent",
    QPalette.ColorRole.Mid: "border",
    QPalette.ColorRole.Dark: "border-strong",
    QPalette.ColorRole.Shadow: "border-strong",
}

#: A row the user marked. Deliberately nowhere near `Highlight`: the first
#: version borrowed an accent colour and produced a marked row identical to a
#: selected one, so the user could not tell what they had marked from what they
#: had clicked. Amber against the blue selection is unmistakable at a glance,
#: and every severity foreground stays above WCAG AA on it -- asserted in
#: `test_gui_theme.py`, because a mark that makes an Error unreadable is worse
#: than no mark.
MARK_TINT: dict[Scheme, str] = {scheme: values["mark"] for scheme, values in TOKENS.items()}


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


#: Level -> (foreground token, tint token or ``None``, glyph). One table for
#: both schemes, since which token a level uses does not change between them --
#: only what the token resolves to does.
_SEVERITY: dict[Level, tuple[str, str | None, str]] = {
    Level.DEBUG: ("level-debug", None, ""),
    Level.INFO: ("level-info", None, ""),
    Level.NOTICE: ("level-notice", None, ""),
    Level.USER_ACTION: ("level-user-action", None, ""),
    Level.ERROR: ("level-error", None, "!"),
    Level.FAULT: ("level-fault", "gap-band", "!!"),
}


def palette_for(scheme: Scheme) -> QPalette:
    """Build the complete palette for ``scheme``.

    Every role is set explicitly for all three colour groups. Leaving a role at
    Qt's default means it comes from whatever the platform style decided, which
    is exactly the platform dependence this module exists to remove.
    """
    palette = QPalette()
    for role, name in _ROLES.items():
        colour = token(name, scheme)
        for group in (
            QPalette.ColorGroup.Active,
            QPalette.ColorGroup.Inactive,
            QPalette.ColorGroup.Disabled,
        ):
            palette.setColor(group, role, colour)

    # `Disabled` is not decorative: Fusion renders it for every disabled widget,
    # and leaving it at Qt's default produces a disabled control that is more
    # legible than an enabled one in the dark scheme.
    disabled = token("text-disabled", scheme)
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
MARK_ACCENT: dict[Scheme, str] = {
    scheme: values["mark-accent"] for scheme, values in TOKENS.items()
}


def token(name: str, scheme: Scheme) -> QColor:
    """One colour, by the name of the job it does.

    Raises rather than returning a default: a typo that resolved to grey would
    ship a grey nobody chose and no test would notice.
    """
    return QColor(TOKENS[scheme][name])


def mark_tint(scheme: Scheme) -> QColor:
    """The background of a marked row."""
    return token("mark", scheme)


def mark_accent(scheme: Scheme) -> QColor:
    """The mark, where it has to be visible as a thin line rather than a wash."""
    return token("mark-accent", scheme)


def selection_row(scheme: Scheme) -> QColor:
    """The background of the selected row *in the log table only*.

    Not `Highlight`, which stays saturated for menus and text selection where a
    wash would read as nothing having happened. A log is read by scanning, and a
    saturated bar drawn across one row destroys the severity colours it covers:
    that is the whole signal the table exists to carry, deleted on the one row
    the user is looking at. Every severity foreground stays above AA on this,
    which is what makes the softer fill safe rather than merely quieter.
    """
    return token("selection", scheme)


def severity_for(level: Level, scheme: Scheme) -> Severity:
    """How ``level`` is drawn under ``scheme``."""
    foreground, tint, glyph = _SEVERITY[level]
    return Severity(
        foreground=token(foreground, scheme),
        tint=token(tint, scheme) if tint is not None else None,
        glyph=glyph,
    )


def scheme_for(colour_scheme: Qt.ColorScheme) -> Scheme:
    """Which scheme one of Qt's answers means.

    ``Unknown`` is the honest answer under the offscreen plugin and on any
    platform theme Qt does not recognise, and it is not an error -- it means
    nobody expressed a preference, so the light scheme wins.

    Separate from :func:`resolve_scheme` because ``colorSchemeChanged`` carries
    the new value as its argument, and a slot that re-read the hints instead
    would be untestable: the offscreen plugin's ``setColorScheme`` is a no-op,
    so the hints never move and the signal could only ever be observed doing
    nothing.
    """
    return Scheme.DARK if colour_scheme == Qt.ColorScheme.Dark else Scheme.LIGHT


def resolve_scheme(hints: QStyleHints) -> Scheme:
    """Which scheme the platform is asking for.

    This is the only place the operating system gets a say in how anything
    looks.
    """
    return scheme_for(hints.colorScheme())


#: Chrome, and only chrome. Every rule here is on a widget the *style* draws;
#: nothing addresses ``QTableView`` or ``QTableView::item``, and that is a
#: correctness rule rather than a preference:
#:
#: * A stylesheet giving ``QTableView`` a box model -- a background or a border
#:   -- makes its viewport non-blittable, so every scroll notch repaints the
#:   whole viewport instead of the sliver that moved. Measured on the real model
#:   at 200,000 rows: **1.6 ms to 30.8 ms, 12.4x**, a ceiling of about 32 frames
#:   per second while a capture is streaming. The table's colours come from the
#:   palette instead, which costs nothing -- verified against this sheet on a
#:   60,000-row capture off a device: **0.3% of the viewport repainted per
#:   notch either way**, 1.71 ms without it and 1.26 ms with it.
#:
#:   Measure that with ``processEvents``, never ``repaint()``: forcing a repaint
#:   is precisely what defeats the blit, so the first version of the benchmark
#:   reported 100% of the viewport in both arms and would have called the trap
#:   safe.
#: * A ``::item`` rule carrying ``background``, ``border``, ``border-radius`` or
#:   ``color`` silently deletes the model's own ``BackgroundRole`` and
#:   ``ForegroundRole``: the severity colours and the mark tint would disappear
#:   with nothing in the code looking wrong.
#:
#: Written as a `string.Template` rather than an f-string or ``.format``,
#: because QSS is made of braces: one unescaped brace kills the rest of the
#: sheet with no warning from Qt. ``substitute`` also raises on a name that is
#: not a token, so a typo fails in CI rather than rendering as nothing.
_STYLESHEET = Template("""
QToolBar { background: $surface; border: 0; border-bottom: 1px solid $border;
           padding: 6px 8px; spacing: 4px; }
QToolBar::separator { background: $border; width: 1px; margin: 0 8px; }
QToolButton { border: none; border-radius: 4px; padding: 4px 8px;
              color: $text_secondary; }
QToolButton:hover { background: $hover; color: $text_primary; }
QToolButton:pressed { background: $surface_sunken; color: $text_primary; }
QToolButton:checked { background: $selection; color: $accent; }
QToolButton:disabled { color: $text_disabled; }

QLineEdit { background: $surface_raised; border: 1px solid $control_border;
            border-radius: 4px; padding: 2px 8px; color: $text_primary;
            selection-background-color: $highlight;
            selection-color: $highlight_text; }
QLineEdit:focus { border: 1px solid $accent; }
QLineEdit:disabled { background: $surface; color: $text_disabled; }

QComboBox { background: $surface_raised; border: 1px solid $control_border;
            border-radius: 4px; padding: 2px 8px; color: $text_primary; }
QComboBox:focus { border: 1px solid $accent; }
QComboBox::drop-down { border: 0; width: 18px; }
QComboBox QAbstractItemView { background: $surface_raised; border: 1px solid $border;
                              selection-background-color: $highlight;
                              selection-color: $highlight_text; }

QHeaderView::section { background: $surface; color: $text_secondary;
                       border: 0; border-right: 1px solid $border;
                       border-bottom: 1px solid $border; padding: 0 8px; }
QHeaderView::section:hover { background: $hover; }

QScrollBar:vertical { background: $surface_sunken; width: 10px; margin: 0; border: 0; }
QScrollBar::handle:vertical { background: $border_strong; border-radius: 3px;
                              min-height: 24px; margin: 2px; }
QScrollBar:horizontal { background: $surface_sunken; height: 10px; margin: 0; border: 0; }
QScrollBar::handle:horizontal { background: $border_strong; border-radius: 3px;
                                min-width: 24px; margin: 2px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; border: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QSplitter::handle { background: $border; }

/* Fusion draws a sunken frame around every permanent status-bar widget, which
   is the single most dated thing in the window it is left on. */
QStatusBar { background: $surface; border-top: 1px solid $border; color: $text_muted; }
QStatusBar::item { border: 0; }

QMenuBar { background: $surface; color: $text_primary; border-bottom: 1px solid $border; }
QMenuBar::item { padding: 4px 10px; background: transparent; }
QMenuBar::item:selected { background: $hover; }
QMenu { background: $surface_raised; border: 1px solid $border; padding: 4px; }
QMenu::item { padding: 5px 24px 5px 12px; border-radius: 3px; }
QMenu::item:selected { background: $highlight; color: $highlight_text; }
QMenu::item:disabled { color: $text_disabled; }
QMenu::separator { height: 1px; background: $border; margin: 4px 8px; }

QToolTip { background: $surface_raised; color: $text_primary;
           border: 1px solid $border; padding: 4px 6px; }
""")


def stylesheet_for(scheme: Scheme) -> str:
    """The chrome stylesheet, with this scheme's tokens substituted in."""
    return _STYLESHEET.substitute(
        {name.replace("-", "_"): value for name, value in TOKENS[scheme].items()}
    )


def apply_theme(app: QApplication, scheme: Scheme) -> None:
    """Put ``scheme`` on the application.

    The style is set first and the palette second, and the order is load-
    bearing: ``QApplication`` resets the palette to the style's defaults when
    the style changes, so setting the palette first silently discards it.

    ``QToolTip`` keeps a palette of its own that the application's does not
    reach, so the ``ToolTipBase`` and ``ToolTipText`` roles set two functions up
    arrived nowhere: tooltips stayed on the platform's own colours in both
    schemes -- measured as Windows' ``#ffffe1`` under the dark theme as well as
    the light one. Qt 6 removed the class-specific ``setPalette`` overload that
    used to cover this, and ``QToolTip.setPalette`` is what replaced it.
    """
    palette = palette_for(scheme)
    app.setStyle(STYLE)
    app.setPalette(palette)
    QToolTip.setPalette(palette)
    # After the palette, and rebuilt rather than reused: the sheet carries
    # literal colours, so a switch that only moved the palette would leave every
    # styled widget in the previous scheme.
    app.setStyleSheet(stylesheet_for(scheme))


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
