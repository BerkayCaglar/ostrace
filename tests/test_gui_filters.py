# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Filters as values: how they read, how they are stored, and which are kept.

None of this needs a window. It is the half of "recent filters" where the rules
live -- what counts as the same filter, what is not worth remembering, and what
happens to a stored line a future version wrote.
"""

from __future__ import annotations

import pytest

from ostrace.gui.filters import RECENT_KEPT, Filter, SavedFilter, forget, remember, save
from ostrace.model import Level, Record
from ostrace.storage.capture import open_capture
from tests.helpers import ERRORS


@pytest.fixture(scope="module")
def capture_rows() -> list[Record]:
    """The records of the errors fixture, gaps left out.

    Module-scoped: three thousand records read once, and nothing here mutates
    them.
    """
    return [row for row in open_capture(ERRORS).items() if isinstance(row, Record)]


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

    def test_an_excluded_term_does_not_read_as_an_included_one(self) -> None:
        """Two entries reading `process dasd` where one shows dasd and the
        other shows everything but is a menu that cannot be used."""
        excluding = Filter(process="dasd", process_exclude=True)

        assert Filter(process="dasd").summary != excluding.summary


class TestTheTextForm:
    """The spelling in `docs/formats/filter-text-form.md`, which is written
    before anything reads it so that a future reader has a specification rather
    than an implementation to copy."""

    def test_a_pattern_is_marked_by_its_key_not_by_a_prefix_on_its_value(self) -> None:
        """The research proposed `search:~timeout`, which cannot express a
        literal search for a string starting with `~`. That is not a theoretical
        value: `~` appears in the committed fixtures, once as the banner
        `~~~~~ PCS Cache ~~~~~`, which is exactly what somebody would paste into
        the search box."""
        literal = Filter(search="~~~~~ PCS Cache ~~~~~").as_text()
        pattern = Filter(search="tim.*out", regex=True).as_text()

        assert literal.startswith("search:")
        assert pattern == "regex:tim.*out"

    def test_the_level_is_written_so_that_it_can_be_read_back(self) -> None:
        """`Level.USER_ACTION.title` is `User Action`, and the space is the one
        character the term separator claims. The enum name has no space and
        `Level.parse` already accepts it."""
        text = Filter(minimum_level=Level.USER_ACTION).as_text()

        assert text == "level:user_action"
        assert Level.parse(text.removeprefix("level:")) is Level.USER_ACTION

    @pytest.mark.parametrize(
        ("value", "written"),
        [
            ("dasd", "process:dasd"),
            ("two words", 'process:"two words"'),
            ('a "quoted" one', 'process:"a \\"quoted\\" one"'),
            ("back\\slash", 'process:"back\\\\slash"'),
        ],
    )
    def test_a_value_is_quoted_only_when_it_has_to_be(self, value: str, written: str) -> None:
        """Quoting everything would be unambiguous and unreadable, and the
        point of this form is that somebody reads it in an issue."""
        assert Filter(process=value).as_text() == written

    def test_an_exclusion_is_a_sign_on_the_key(self) -> None:
        """Not on the value: a leading `-` inside a value would need an escape
        rule, and process names really do contain hyphens."""
        assert Filter(process="dasd", process_exclude=True).as_text() == "-process:dasd"

    def test_a_filter_that_narrows_nothing_writes_nothing(self) -> None:
        """The form is a list of terms and an empty filter has none. The window
        answers this by disabling Copy Filter rather than by putting an empty
        clipboard in front of somebody."""
        assert Filter().as_text() == ""
        assert Filter(process_exclude=True, subsystem_exclude=True).as_text() == ""

    def test_the_terms_come_in_one_order(self) -> None:
        """Two people looking at the same filter paste the same line, or the
        form is not a way of comparing two filters."""
        whole = Filter(
            minimum_level=Level.ERROR,
            process="dasd",
            subsystem="com.apple.network",
            subsystem_exclude=True,
            search="timeout",
        )

        assert whole.as_text() == (
            "level:error process:dasd -subsystem:com.apple.network search:timeout"
        )


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
            Filter(process="dasd", process_exclude=True),
            Filter(subsystem="com.apple.network", subsystem_exclude=True),
        ],
    )
    def test_it_survives_the_round_trip(self, original: Filter) -> None:
        assert Filter.from_stored(original.as_stored()) == original

    def test_a_line_written_before_exclusions_existed_still_reads(self) -> None:
        """Exactly what 0.1.2 wrote. Requiring the two new keys would empty the
        recent list of everyone upgrading, on the release that improved it --
        and they would read that as the feature having broken."""
        older = (
            '{"minimum_level": 60, "process": "dasd", "subsystem": "", '
            '"search": "", "regex": false}'
        )

        assert Filter.from_stored(older) == Filter(minimum_level=Level.ERROR, process="dasd")

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


class TestExcluding:
    """Against the real capture, because which records an exclusion drops is a
    question about what the device emitted. A synthetic stand-in would agree
    with whatever the implementation happened to do."""

    def test_a_subsystem_term_keeps_that_subsystem_and_no_other(
        self, capture_rows: list[Record]
    ) -> None:
        """Not about exclusion, and here because exclusion is what revealed the
        gap: inverting this comparison broke nothing in the sweep tier and
        nothing in the 393 gui tests. The term had no test that would notice it
        matching the wrong records."""
        shown = [
            row for row in capture_rows if Filter(subsystem="com.apple.mobilebackup").matches(row)
        ]

        assert len(shown) == 647
        assert all(row.subsystem == "com.apple.mobilebackup" for row in shown)

    def test_a_term_and_its_exclusion_partition_the_capture(
        self, capture_rows: list[Record]
    ) -> None:
        """Every record is on exactly one side. An exclusion that merely dropped
        the matches would also drop the records the term cannot speak about,
        which is how a filter quietly loses rows."""
        kept = [row for row in capture_rows if Filter(process="backupd").matches(row)]
        rest = [
            row
            for row in capture_rows
            if Filter(process="backupd", process_exclude=True).matches(row)
        ]

        assert len(kept) == 663
        assert len(kept) + len(rest) == len(capture_rows)
        assert not {id(row) for row in kept} & {id(row) for row in rest}

    def test_a_record_with_no_subsystem_survives_an_excluded_one(
        self, capture_rows: list[Record]
    ) -> None:
        """546 of these 3,000 carry no subsystem at all. Somebody excluding a
        noisy subsystem asked to see everything else, and a record that has none
        is everything else -- dropping it would be the exclusion quietly
        narrowing instead of widening."""
        without = [row for row in capture_rows if not row.subsystem]
        shown = [
            row
            for row in capture_rows
            if Filter(subsystem="com.apple.mobilebackup", subsystem_exclude=True).matches(row)
        ]

        assert len(without) == 546
        assert all(row in shown for row in without)

    def test_the_flag_alone_narrows_nothing(self, capture_rows: list[Record]) -> None:
        """`≠` over an empty field is a toggle somebody flipped and then cleared
        the field of. It has nothing to exclude, so it excludes nothing -- and
        the bar still reads as empty, which is what tells the window "the device
        is quiet" from "your filter hides everything"."""
        flagged = Filter(process_exclude=True, subsystem_exclude=True)

        assert flagged.is_empty
        assert all(flagged.matches(row) for row in capture_rows)


class TestNamingOne:
    """The expensive half, for the handful somebody comes back to for weeks."""

    def test_a_new_name_goes_on_the_end(self) -> None:
        one = SavedFilter("errors", Filter(minimum_level=Level.ERROR))
        two = SavedFilter("backupd", Filter(process="backupd"))

        assert save(save([], one), two) == [one, two]

    def test_saving_over_a_name_replaces_it_where_it_was(self) -> None:
        """Correcting a filter is the common case, and a list that reordered
        itself under the user each time would make the menu a different shape
        after every correction."""
        first = SavedFilter("watchdog", Filter(process="watchdogd"))
        other = SavedFilter("errors", Filter(minimum_level=Level.ERROR))
        corrected = SavedFilter("watchdog", Filter(process="watchdogd", minimum_level=Level.FAULT))

        assert save([first, other], corrected) == [corrected, other]

    @pytest.mark.parametrize("spelling", ["watchdog", "Watchdog", "  watchdog  "])
    def test_a_name_is_the_same_name_however_it_is_typed(self, spelling: str) -> None:
        """Two entries a menu shows identically are two nobody can choose
        between, and the second would silently shadow the first."""
        first = SavedFilter("watchdog", Filter(process="watchdogd"))
        again = SavedFilter(spelling, Filter(process="wd"))

        assert len(save([first], again)) == 1
        assert forget([first], spelling) == []

    def test_forgetting_one_that_is_not_there_changes_nothing(self) -> None:
        one = SavedFilter("errors", Filter(minimum_level=Level.ERROR))

        assert forget([one], "nothing of the sort") == [one]

    @pytest.mark.parametrize(
        "original",
        [
            SavedFilter("errors", Filter(minimum_level=Level.ERROR)),
            SavedFilter("not backupd", Filter(process="backupd", process_exclude=True)),
            SavedFilter("üç nokta", Filter(search="tim.*out", regex=True)),
        ],
    )
    def test_it_survives_the_round_trip(self, original: SavedFilter) -> None:
        assert SavedFilter.from_stored(original.as_stored()) == original

    @pytest.mark.parametrize(
        "line",
        [
            "",
            "not json",
            "{}",
            '["a", "list"]',
            '{"name": "errors"}',
            '{"filter": {"minimum_level": 60}}',
            (
                '{"name": "", "filter": {"minimum_level": 60, "process": "", '
                '"subsystem": "", "search": "", "regex": false}}'
            ),
            (
                '{"name": "   ", "filter": {"minimum_level": 60, "process": "", '
                '"subsystem": "", "search": "", "regex": false}}'
            ),
        ],
    )
    def test_what_cannot_be_read_is_dropped_rather_than_raised(self, line: str) -> None:
        """Including the blank name: the menu offers a saved filter *by* name,
        so an unnamed one is a row nobody can tell from the row above it."""
        assert SavedFilter.from_stored(line) is None

    def test_a_name_is_not_a_term(self) -> None:
        """`Filter` equality decides whether the model rescans, so it must not
        move when only a name does."""
        terms = Filter(minimum_level=Level.ERROR)

        assert SavedFilter("one", terms) != SavedFilter("two", terms)
        assert SavedFilter("one", terms).terms == SavedFilter("two", terms).terms


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
