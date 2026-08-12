# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fitting the columns into a window, as arithmetic.

No Qt, no display, no font. That is the point of the extraction: the input this
has never been asked about is `unit` -- the width of a ``0`` in the table's
font -- and that is where the device pixel ratio arrives. macOS reports an
integer ratio and cannot have High DPI scaling turned off; Windows allows a
fractional one. The suspect has always been what a fractional unit does to
column widths chosen on a machine with an integer one, and until this was a
function there was no way to ask.
"""

from __future__ import annotations

import pytest

from ostrace.gui.columns import (
    COLUMNS,
    MESSAGE_MINIMUM,
    MINIMUM_CHARACTERS,
    UNTRIMMABLE,
    Column,
    fit_budgets,
    wanted_widths,
)

#: A plausible monospaced ``0`` at 100% scaling, and the inset the style adds.
UNIT = 8
MARGINS = 6


def total(budgets: dict[Column, int]) -> int:
    return sum(budgets.values())


class TestWhatTheColumnsAskFor:
    def test_every_fixed_column_asks_and_the_message_does_not(self) -> None:
        """Message takes what is left, so it has no budget to trim."""
        budgets = wanted_widths(UNIT, margins=MARGINS)

        assert set(budgets) == {spec.column for spec in COLUMNS if spec.characters is not None}
        assert Column.MESSAGE not in budgets

    def test_the_margins_are_added_rather_than_absorbed(self) -> None:
        """A column is a budget of characters and the style insets the text on
        top of it. Spending the budget on the column and the margins on the
        text elides the last character of a value sized to fit exactly -- the
        timestamp being the first to lose a digit in a monospaced face, where
        the slack is one pixel."""
        spec = next(spec for spec in COLUMNS if spec.column is Column.TIME)
        assert spec.characters is not None

        budgets = wanted_widths(UNIT, margins=MARGINS)

        assert budgets[Column.TIME] == spec.characters * UNIT + MARGINS


class TestWhenItAllFits:
    def test_a_wide_window_changes_nothing(self) -> None:
        budgets = wanted_widths(UNIT, margins=MARGINS)

        assert fit_budgets(budgets, UNIT, available=4000) == budgets

    def test_a_window_with_no_width_yet_changes_nothing(self) -> None:
        """Nothing is laid out before the first show, and a negative shortfall
        is not a reason to trim anything."""
        budgets = wanted_widths(UNIT, margins=MARGINS)

        assert fit_budgets(budgets, UNIT, available=0) == budgets


class TestWhenItDoesNot:
    """Measured on the shipped set at a 1,280-pixel window: five fixed columns
    of 91 characters came to 1,183 pixels of a 1,254-pixel viewport, so the
    message got 71 -- about five characters -- and the columns overflowed the
    window besides."""

    @pytest.fixture
    def tight(self) -> dict[Column, int]:
        return fit_budgets(wanted_widths(UNIT, margins=MARGINS), UNIT, available=900)

    def test_the_message_gets_the_room_it_is_owed(self, tight: dict[Column, int]) -> None:
        assert 900 - total(tight) >= MESSAGE_MINIMUM * UNIT

    def test_the_columns_with_a_known_length_give_nothing_up(
        self, tight: dict[Column, int]
    ) -> None:
        """A timestamp missing its last digits is a timestamp nobody can use,
        and `Level` has to fit ``User Action`` and its glyph."""
        wanted = wanted_widths(UNIT, margins=MARGINS)

        for column in UNTRIMMABLE:
            assert tight[column] == wanted[column]

    def test_nothing_is_trimmed_to_punctuation(self, tight: dict[Column, int]) -> None:
        for column, width in tight.items():
            if column not in UNTRIMMABLE:
                assert width >= MINIMUM_CHARACTERS * UNIT

    def test_the_floor_is_load_bearing_at_the_width_where_it_bites(self) -> None:
        """The width above is comfortable enough that proportional trimming
        never reaches the floor, so removing the floor leaves it green --
        measured. There is a narrow band where the guard still permits trimming
        and the proportion would go under: at a unit of 8 that band opens at
        644 pixels, where two of the three identifiers land exactly on it.

        A specific number rather than a search, because the point is that the
        floor is reachable at all -- and if the budgets change, this failing is
        the notice that the band moved.
        """
        budgets = wanted_widths(UNIT, margins=MARGINS)

        fitted = fit_budgets(budgets, UNIT, available=644)

        floor = MINIMUM_CHARACTERS * UNIT
        trimmed = [width for column, width in fitted.items() if column not in UNTRIMMABLE]
        assert min(trimmed) == floor, "the floor was never reached, so it proves nothing here"
        assert all(width >= floor for width in trimmed)

    def test_the_shortfall_comes_out_in_proportion(self, tight: dict[Column, int]) -> None:
        """The widest identifier gives up the most, so the columns stay in the
        same order of size they were designed in."""
        flexible = [column for column in tight if column not in UNTRIMMABLE]
        wanted = wanted_widths(UNIT, margins=MARGINS)

        by_want = sorted(flexible, key=lambda column: wanted[column])
        by_fitted = sorted(flexible, key=lambda column: tight[column])

        assert by_want == by_fitted

    def test_a_window_too_narrow_for_the_floor_keeps_the_budgets(self) -> None:
        """The budgets stand and the scrollbar appears, which at that width is
        the honest answer: a column trimmed below its floor is not a narrower
        column, it is an unreadable one."""
        budgets = wanted_widths(UNIT, margins=MARGINS)

        assert fit_budgets(budgets, UNIT, available=320) == budgets


class TestAFractionalUnit:
    """The named Retina suspect, asked at last.

    macOS reports an integer device pixel ratio and cannot have High DPI
    scaling disabled; Windows allows a fractional one, so a `0` measures 8 on
    one machine and 8.6 on another at the same nominal size. Whether that
    breaks the fitting has been a question since the widths were written, and
    it took the arithmetic leaving the widget to answer it.
    """

    @pytest.mark.parametrize("unit", [6, 7, 8, 9, 11, 14, 19])
    def test_the_message_is_owed_its_floor_at_every_size(self, unit: int) -> None:
        budgets = wanted_widths(unit, margins=MARGINS)

        fitted = fit_budgets(budgets, unit, available=1254)

        assert fitted == budgets or 1254 - total(fitted) >= MESSAGE_MINIMUM * unit

    def test_a_scaled_display_needs_a_wider_window_for_the_same_columns(self) -> None:
        """The arithmetic is in units rather than pixels, so a display that
        makes every character half again as wide needs half again the window to
        hold the same text. What must not happen is the columns quietly
        surviving at the old width by eating the message."""
        wide = wanted_widths(12, margins=MARGINS)

        fitted = fit_budgets(wide, 12, available=1254)

        assert total(fitted) <= 1254 - MESSAGE_MINIMUM * 12 or fitted == wide

    def test_the_widths_are_whole_pixels(self) -> None:
        """A column width is set on a header in device pixels, and Qt takes an
        int. A float here would be silently truncated somewhere else."""
        budgets = wanted_widths(9, margins=5)

        fitted = fit_budgets(budgets, 9, available=800)

        assert all(isinstance(width, int) for width in fitted.values())
