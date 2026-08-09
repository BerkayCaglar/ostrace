# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The theme, which is the one part of the GUI that CI can fully verify.

Colour is the classic thing nobody tests and everybody breaks, and here it is
unusually testable: `palette_for` is a pure function of a scheme, so the
offscreen lane can assert the actual numbers on all three operating systems
without a display, a platform theme or a font.

That matters because the alternative check is only half available.
``setColorScheme()`` is a no-op under the offscreen plugin, so nothing here can
make the *platform* change its mind. What a switch does once it arrives is
testable -- `colorSchemeChanged` carries the new value, so emitting it by hand
drives the same path the platform does, which is where
``test_gui_wiring.TestTheThemeSwitchReachesTheRecords`` picks this up. What
remains unreachable in CI is only the platform's own delivery of that signal.
"""

from __future__ import annotations

import re

import pytest

from ostrace.model import Level

pytest.importorskip("PySide6", reason="the gui extra is not installed")

from PySide6.QtGui import QPalette

from ostrace.gui.theme import (
    TOKENS,
    Scheme,
    apply_theme,
    contrast_ratio,
    mark_tint,
    palette_for,
    selection_row,
    severity_for,
    stylesheet_for,
)

pytestmark = pytest.mark.gui

#: WCAG 2.1 AA for body text. Severity foregrounds are body text: they are the
#: message, not decoration around it.
AA = 4.5


@pytest.mark.parametrize("scheme", list(Scheme))
@pytest.mark.parametrize("level", list(Level))
def test_every_severity_is_legible_on_its_own_background(scheme: Scheme, level: Level) -> None:
    """A colour tweak that drops below AA fails here rather than in the field.

    Checked against the tint where a level has one, because that is what is
    actually behind the text, and against ``Base`` where it does not.
    """
    severity = severity_for(level, scheme)
    background = severity.tint or palette_for(scheme).base().color()
    ratio = contrast_ratio(severity.foreground, background)
    assert ratio >= AA, f"{level.name} on {scheme}: {ratio:.2f}:1"


@pytest.mark.parametrize("scheme", list(Scheme))
def test_selected_rows_stay_legible(scheme: Scheme) -> None:
    """Selection replaces the background, so it gets the same check.

    A severity colour that is legible on Base and invisible on Highlight makes
    the selected row -- the one the user is looking at -- the unreadable one.
    """
    palette = palette_for(scheme)
    ratio = contrast_ratio(palette.highlightedText().color(), palette.highlight().color())
    assert ratio >= AA, f"{scheme}: {ratio:.2f}:1"


@pytest.mark.parametrize("scheme", list(Scheme))
@pytest.mark.parametrize("level", list(Level))
def test_every_severity_stays_legible_on_a_marked_row(scheme: Scheme, level: Level) -> None:
    """A mark replaces the row background, so it gets the same check.

    A mark that makes an Error unreadable is worse than no mark: it hides the
    line the user cared enough about to annotate.
    """
    ratio = contrast_ratio(severity_for(level, scheme).foreground, mark_tint(scheme))
    assert ratio >= AA, f"{level.name} on a mark in {scheme}: {ratio:.2f}:1"


@pytest.mark.parametrize("scheme", list(Scheme))
def test_a_mark_cannot_be_mistaken_for_a_selection(scheme: Scheme) -> None:
    """The first version borrowed an accent colour and produced a marked row
    identical to a selected one -- so the user could not tell what they had
    marked from what they had merely clicked."""
    assert mark_tint(scheme) != palette_for(scheme).highlight().color()
    assert contrast_ratio(mark_tint(scheme), palette_for(scheme).highlight().color()) > 2.0


def test_the_two_schemes_are_actually_different() -> None:
    """Guards against a copy-paste that leaves dark mode light."""
    light = palette_for(Scheme.LIGHT)
    dark = palette_for(Scheme.DARK)
    for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base, QPalette.ColorRole.Text):
        assert light.color(role) != dark.color(role)


def test_dark_is_dark_and_light_is_light() -> None:
    """The names are load-bearing: the screenshot job selects by them."""
    light = palette_for(Scheme.LIGHT).base().color()
    dark = palette_for(Scheme.DARK).base().color()
    assert light.lightnessF() > dark.lightnessF()


@pytest.mark.parametrize("scheme", list(Scheme))
def test_disabled_text_is_dimmer_than_enabled_text(scheme: Scheme) -> None:
    """Left at Qt's default, dark mode renders disabled text *brighter*."""
    palette = palette_for(scheme)
    enabled = contrast_ratio(
        palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Text),
        palette.base().color(),
    )
    disabled = contrast_ratio(
        palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text),
        palette.base().color(),
    )
    assert disabled < enabled


@pytest.mark.parametrize("scheme", list(Scheme))
def test_the_urgent_levels_carry_a_glyph(scheme: Scheme) -> None:
    """Colour is never the only cue.

    A screenshot printed in black and white, pasted into a plain-text issue, or
    read by someone who cannot separate the hues still has to say which lines
    are the bad ones.
    """
    assert severity_for(Level.ERROR, scheme).glyph
    assert severity_for(Level.FAULT, scheme).glyph
    assert not severity_for(Level.INFO, scheme).glyph


@pytest.mark.parametrize("scheme", list(Scheme))
def test_error_and_fault_are_distinguishable_from_each_other(scheme: Scheme) -> None:
    """Two red rows that look identical are one row twice."""
    error = severity_for(Level.ERROR, scheme)
    fault = severity_for(Level.FAULT, scheme)
    assert error.glyph != fault.glyph
    assert (error.tint is None) != (fault.tint is None)


def test_palette_for_is_deterministic() -> None:
    """Same scheme, same colours -- on every operating system.

    This is what makes a GUI written without a Mac testable: the palette is
    ours, so what CI asserts here is what a Mac user sees.
    """
    first = palette_for(Scheme.DARK)
    second = palette_for(Scheme.DARK)
    for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base, QPalette.ColorRole.Highlight):
        assert first.color(role) == second.color(role)


def test_apply_theme_sets_the_style_before_the_palette(qt_app: object) -> None:
    """Order matters: a style change resets the palette to the style's own.

    Applying them the other way round leaves the application looking themed
    right up until anything triggers a restyle, at which point the colours
    silently revert.
    """
    from PySide6.QtWidgets import QApplication

    assert isinstance(qt_app, QApplication)
    apply_theme(qt_app, Scheme.DARK)
    assert qt_app.palette().base().color() == palette_for(Scheme.DARK).base().color()
    apply_theme(qt_app, Scheme.LIGHT)
    assert qt_app.palette().base().color() == palette_for(Scheme.LIGHT).base().color()


def test_the_theme_reaches_tooltips(qt_app: object) -> None:
    """`QToolTip` keeps its own palette, which the application's does not reach.

    So the two tooltip roles this module sets arrived nowhere and tooltips
    stayed on the platform's colours in both schemes -- Windows' `#ffffe1`,
    which under the dark theme is a bright yellow card on a dark window. Qt 6
    removed the class-specific `setPalette` overload that used to cover it, and
    nothing replaced the call.
    """
    from PySide6.QtWidgets import QApplication, QToolTip

    assert isinstance(qt_app, QApplication)
    for scheme in (Scheme.DARK, Scheme.LIGHT):
        apply_theme(qt_app, scheme)
        intended = palette_for(scheme)
        for role in (QPalette.ColorRole.ToolTipBase, QPalette.ColorRole.ToolTipText):
            assert QToolTip.palette().color(role) == intended.color(role), role.name


@pytest.mark.parametrize("scheme", list(Scheme))
@pytest.mark.parametrize("level", list(Level))
def test_every_severity_stays_legible_on_the_selected_row(scheme: Scheme, level: Level) -> None:
    """The table's selection is a wash, not the saturated application highlight.

    Which is only safe if the severity colours survive being drawn on it -- and
    they have to survive, because `SeverityDelegate` deliberately keeps them
    there rather than letting the style substitute `HighlightedText`. A log is
    read by scanning, and a selection that deletes the severity of the one row
    the user clicked deletes it exactly where they were looking.
    """
    ratio = contrast_ratio(severity_for(level, scheme).foreground, selection_row(scheme))
    assert ratio >= AA, f"{level.name} on the selected row in {scheme}: {ratio:.2f}:1"


@pytest.mark.parametrize("scheme", list(Scheme))
def test_the_stylesheet_resolves_every_token_it_names(scheme: Scheme) -> None:
    """`Template.substitute` raises on a name that is not a token.

    Which is the point of using it: QSS is made of braces, so an f-string would
    need every brace doubled, and a mis-spelled colour in a stylesheet fails
    silently -- Qt discards the rule and everything after it with no warning.
    """
    sheet = stylesheet_for(scheme)
    assert "$" not in sheet, "a token was left unsubstituted"
    # This scheme's colours, and not the other scheme's: a sheet built once and
    # cached would leave every styled widget behind on a theme switch.
    assert TOKENS[scheme]["surface"] in sheet
    other = Scheme.DARK if scheme is Scheme.LIGHT else Scheme.LIGHT
    assert TOKENS[other]["surface"] not in sheet


@pytest.mark.parametrize("scheme", list(Scheme))
def test_the_stylesheet_never_touches_the_table(scheme: Scheme) -> None:
    """Two measured rules, both of which fail silently if broken.

    A stylesheet giving `QTableView` a box model makes its viewport
    non-blittable: every scroll notch then repaints the whole viewport rather
    than the two percent that moved, measured at **1.6 ms to 30.8 ms** on the
    real model at 200,000 rows -- about 32 frames per second while a capture is
    streaming, and nothing in the code looks wrong.

    A `::item` rule carrying a background, border or colour silently discards
    the model's own `BackgroundRole` and `ForegroundRole`, which is where every
    severity colour and the mark tint come from.

    So the table is styled through the palette and the sheet leaves it alone.
    """
    sheet = stylesheet_for(scheme)
    assert "QTableView" not in sheet
    assert "QAbstractScrollArea" not in sheet
    # `QComboBox QAbstractItemView` is the documented way to reach a combo's
    # popup and is not an item view with model colours to lose. A bare one
    # would also catch the log table.
    assert re.findall(r"(?<!QComboBox )QAbstractItemView", sheet) == []
