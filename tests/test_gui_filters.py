# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Filters as values: how they read, how they are stored, and which are kept.

None of this needs a window. It is the half of "recent filters" where the rules
live -- what counts as the same filter, what is not worth remembering, and what
happens to a stored line a future version wrote.
"""

from __future__ import annotations

import pytest

from ostrace.gui.filters import RECENT_KEPT, Filter, remember
from ostrace.model import Level


class TestHowAFilterReads:
    """One line per entry, for a menu of ten."""

    def test_it_names_only_the_terms_that_are_set(self) -> None:
        """Ten entries each carrying four fields, most of them empty, is a
        list nobody reads."""
        assert Filter(process="dasd").summary == "process dasd"

    def test_the_level_is_written_as_the_threshold_it_is(self) -> None:
        """`Error and above`, not `Error`. It is the single most misread thing
        about this filter, and a summary that said `Error` would confirm the
        misreading every time somebody opened the menu."""
        assert Filter(minimum_level=Level.ERROR).summary.startswith("Error+")

    def test_a_search_says_whether_it_is_a_pattern(self) -> None:
        """`timeout` and `timeout` are different filters when one is a regex,
        and two menu entries reading the same are two nobody can choose
        between."""
        text = Filter(search="tim.*out").summary
        pattern = Filter(search="tim.*out", regex=True).summary

        assert text != pattern
        assert "text" in text
        assert "regex" in pattern

    def test_everything_reads_as_everything(self) -> None:
        assert Filter().summary == "everything"

    def test_several_terms_are_all_named(self) -> None:
        summary = Filter(minimum_level=Level.ERROR, process="dasd", search="timeout").summary

        assert "Error+" in summary
        assert "dasd" in summary
        assert "timeout" in summary


class TestStoringOne:
    """Settings outlive the version that wrote them."""

    @pytest.mark.parametrize(
        "original",
        [
            Filter(),
            Filter(process="dasd"),
            Filter(minimum_level=Level.FAULT, subsystem="com.apple.network"),
            Filter(search="tim.*out", regex=True),
            Filter(minimum_level=Level.ERROR, process="97", subsystem="x", search="y", regex=False),
        ],
    )
    def test_it_survives_the_round_trip(self, original: Filter) -> None:
        assert Filter.from_stored(original.as_stored()) == original

    def test_the_compiled_pattern_is_rebuilt_rather_than_stored(self) -> None:
        """It is derived, and a regex object is not JSON. Equality ignores it,
        so the round-trip above would pass either way -- this is the assertion
        that the restored filter actually still filters."""
        restored = Filter.from_stored(Filter(search="tim.*out", regex=True).as_stored())

        assert restored is not None
        assert restored._pattern is not None

    @pytest.mark.parametrize(
        "line",
        [
            "",
            "not json",
            "{}",
            '{"minimum_level": 99}',
            (
                '{"minimum_level": "Error", "process": "", "subsystem": "", '
                '"search": "", "regex": false}'
            ),
            '["a", "list"]',
            "null",
        ],
    )
    def test_what_cannot_be_read_is_dropped_rather_than_raised(self, line: str) -> None:
        """A window that refuses to open because a remembered filter is
        malformed has turned a convenience into a way of losing the
        application."""
        assert Filter.from_stored(line) is None


class TestWhichAreKept:
    """Newest first, no duplicates, bounded."""

    def test_the_newest_is_first(self) -> None:
        recent = remember(remember([], Filter(process="a")), Filter(process="b"))

        assert [entry.process for entry in recent] == ["b", "a"]

    def test_using_one_again_moves_it_rather_than_copying_it(self) -> None:
        """A filter somebody comes back to twice is one entry they used twice.
        Copying it would push the other nine out with duplicates of one."""
        recent: list[Filter] = []
        for process in ("a", "b", "c", "a"):
            recent = remember(recent, Filter(process=process))

        assert [entry.process for entry in recent] == ["a", "c", "b"]

    def test_it_stops_at_the_cap(self) -> None:
        recent: list[Filter] = []
        for index in range(RECENT_KEPT * 2):
            recent = remember(recent, Filter(process=str(index)))

        assert len(recent) == RECENT_KEPT
        assert recent[0].process == str(RECENT_KEPT * 2 - 1)

    def test_showing_everything_is_not_worth_remembering(self) -> None:
        """It is the state you get by clearing the bar, so offering it as
        something to go back to is offering a way back to where you are."""
        assert remember([], Filter()) == []

    def test_it_does_not_touch_the_list_it_was_given(self) -> None:
        """The window holds one of these and compares before against after to
        decide whether to write settings."""
        original = [Filter(process="a")]

        remember(original, Filter(process="b"))

        assert original == [Filter(process="a")]
