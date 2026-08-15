# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The second verb: marking rows in place rather than removing them.

The distinction the whole feature rests on is that a highlight changes *nothing*
about which rows exist — so most of what is asserted here is what did **not**
happen: no rescan, no reset, no lost selection, no filter touched.

Real fixture records where the assertion is about what device output contains,
synthetics where it is about the model's own bookkeeping.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from ostrace.model import Gap, Level
from ostrace.storage.spool import SpoolReader
from tests.helpers import MIXED, make_record

pytest.importorskip("PySide6", reason="the gui extra is not installed")

from PySide6.QtCore import Qt

from ostrace.gui.columns import Column
from ostrace.gui.filters import Filter, Highlight, merge_spans
from ostrace.gui.finding import Find
from ostrace.gui.markers import is_record
from ostrace.gui.models import RecordModel
from ostrace.gui.theme import mark_accent
from ostrace.gui.widgets.log_table import _TICK_WIDTH, LogTable
from ostrace.gui.widgets.status_bar import HITS
from ostrace.gui.windows.main import MainWindow

if TYPE_CHECKING:
    from ostrace.gui.markers import Row

pytestmark = pytest.mark.gui


@pytest.fixture
def rows() -> list[Row]:
    return list(SpoolReader(MIXED).items())


@pytest.fixture
def model(rows: list[Row]) -> RecordModel:
    built = RecordModel()
    built.extend_from(rows)
    return built


@pytest.fixture
def window(qt_app: object) -> MainWindow:
    del qt_app
    return MainWindow()


# -- the value ---------------------------------------------------------------


def test_a_half_typed_pattern_raises_rather_than_matching_nothing() -> None:
    """The same rule `Filter` follows, for the same reason: a view that empties
    itself while somebody types is indistinguishable from a dead device."""
    with pytest.raises(ValueError, match="invalid regular expression"):
        Highlight(text="[com", regex=True)


def test_a_literal_term_is_escaped_rather_than_compiled() -> None:
    """``[com`` is a usable literal and an unusable pattern, and which one it is
    depends only on the toggle beside the field."""
    assert Highlight(text="[com").hits("a [common case")


def test_two_highlights_with_the_same_terms_are_the_same_value() -> None:
    """What lets the model refuse to do any work when nothing changed. The
    compiled pattern is excluded from equality, or two identical terms would
    compare unequal because they hold two different `re.Pattern` objects."""
    assert Highlight(text="dasd") == Highlight(text="dasd")
    assert Highlight(text="dasd") != Highlight(text="dasd", regex=True)


def test_zero_width_matches_are_not_drawn() -> None:
    """``a*`` matches the empty string between every pair of characters, and a
    wash of nothing at every position paints the row solid."""
    assert Highlight(text="a*", regex=True).spans("bbb") == []


def test_overlapping_spans_are_merged_before_they_are_drawn() -> None:
    """A wash is translucent, so painting the same pixels twice comes out darker
    than the colour that was measured against the contrast floor."""
    assert list(merge_spans([(0, 5), (12, 14)], [(3, 8)])) == [(0, 8), (12, 14)]


def test_one_empty_side_is_handed_back_untouched() -> None:
    """The ordinary case, and it runs per visible cell per repaint: only one of
    the two fields is usually filled in, and joining and sorting there would be
    two allocations to arrive at the list that came in."""
    spans = [(0, 3)]
    assert merge_spans(spans, []) is spans
    assert merge_spans([], spans) is spans


def test_searching_err_while_highlighting_error_overlaps_on_every_hit() -> None:
    """Not a corner case: it is what somebody narrowing and then looking within
    the narrowing actually types."""
    text = "the error was fatal"
    merged = merge_spans(Filter(search="err").spans(text), Highlight(text="error").spans(text))
    assert list(merged) == [(4, 9)]


# -- the model ---------------------------------------------------------------


def test_the_hit_count_is_over_the_rows_on_screen(model: RecordModel) -> None:
    """One set, three readings of it: the count, the gutter and the chevrons."""
    model.set_highlight(Highlight(text="error"))
    counted = sum(1 for row in range(model.rowCount()) if model.highlight_hit(row))
    assert model.highlight_hits == counted
    assert counted > 0


def test_a_narrowing_filter_takes_rows_away_from_the_highlight(
    model: RecordModel,
) -> None:
    """The count is an aggregate over the rows shown, so it has to move when the
    filter moves them. Reading it over the retained rows instead would be a
    fourth answer disagreeing with the other three."""
    model.set_highlight(Highlight(text="error"))
    everything = model.highlight_hits
    model.set_filter(Filter(minimum_level=Level.FAULT))
    assert model.highlight_hits < everything
    assert model.highlight_hits == sum(
        1 for row in range(model.rowCount()) if model.highlight_hit(row)
    )


def test_setting_the_highlight_does_not_rescan(model: RecordModel) -> None:
    """The point of keeping it off `Filter`.

    A reset would invalidate every index and throw away the reader's selection
    and scroll position on each character typed into a field that removes
    nothing at all.
    """
    resets = 0

    def count() -> None:
        nonlocal resets
        resets += 1

    model.modelAboutToBeReset.connect(count)
    before = model.rowCount()
    model.set_highlight(Highlight(text="error"))
    assert resets == 0
    assert model.rowCount() == before


def test_an_identical_highlight_is_not_a_change(model: RecordModel) -> None:
    repaints = 0

    def count() -> None:
        nonlocal repaints
        repaints += 1

    model.set_highlight(Highlight(text="error"))
    model.dataChanged.connect(count)
    model.set_highlight(Highlight(text="error"))
    assert repaints == 0


def test_arriving_records_are_tested_against_the_standing_highlight() -> None:
    """A live capture has to keep the count true without re-testing everything
    already there."""
    model = RecordModel()
    model.set_highlight(Highlight(text="watchdog"))
    assert model.highlight_hits == 0
    model.append([make_record(0, message="watchdog fired"), make_record(1, message="quiet")])
    assert model.highlight_hits == 1


def test_a_gap_can_be_a_hit() -> None:
    """Markers count, for the reason `row_at_time` gives about them: a term that
    could match every row except the one explaining a silence would skip the
    answer somebody is hunting for.

    A synthetic `Gap`, and legitimately so: the assertion is about whether the
    model's own choke point lets a marker be tested at all, not about how device
    output is interpreted. Neither committed fixture holds a gap.
    """
    model = RecordModel()
    moment = make_record(0).timestamp
    model.append(
        [
            make_record(0, message="quiet"),
            Gap(start=moment, end=moment + timedelta(seconds=8), reason="the cable was pulled"),
        ]
    )
    model.set_highlight(Highlight(text="cable"))
    assert model.highlight_hits == 1
    assert model.highlight_hit(1)


def test_hits_are_rebased_by_a_trim_exactly_as_marks_are() -> None:
    """A hit that outlived its record would light a row somebody else's message
    now occupies."""
    model = RecordModel(row_cap=100)
    model.set_highlight(Highlight(text="keepme"))
    model.append([make_record(i, message=f"keepme {i}") for i in range(400)])
    # Every retained record still carries the term, and the eviction notice at
    # the top does not.
    assert model.highlight_hits == model.rowCount() - 1
    for row in range(model.rowCount()):
        assert model.highlight_hit(row) is is_record(model.row_at(row))


def test_clearing_the_model_drops_the_hits_and_keeps_the_term() -> None:
    """The hits are positions in rows that no longer exist; the term is a
    question the user asked and nobody has withdrawn."""
    model = RecordModel()
    model.set_highlight(Highlight(text="watchdog"))
    model.append([make_record(0, message="watchdog fired")])
    model.clear()
    assert model.highlight_hits == 0
    assert model.highlight == Highlight(text="watchdog")


# -- stepping ----------------------------------------------------------------


def test_the_chevrons_can_be_pointed_at_the_highlight(model: RecordModel) -> None:
    """The research asked for `F3`/`n`. Both were already bound to the target
    picker by the time this could be built, so the hits became one more target
    rather than a second pair of keys stepping past the first."""
    model.set_highlight(Highlight(text="error"))
    found = model.find(Find.HIGHLIGHT, start=0)
    assert found is not None
    assert model.highlight_hit(found)


def test_stepping_finds_nothing_when_nothing_is_highlighted(model: RecordModel) -> None:
    assert model.find(Find.HIGHLIGHT, start=0) is None


def test_every_find_kind_has_a_label() -> None:
    """`_FIND_LABELS` raises for a member with no entry, so adding a target and
    naming it are one edit. Asserted so the raise is not the first anybody hears
    of it."""
    for kind in Find:
        assert kind.label


# -- the window --------------------------------------------------------------


def test_typing_a_highlight_does_not_apply_a_filter(window: MainWindow) -> None:
    """The two verbs are separate all the way to the window: they are debounced
    apart, so a keystroke in one cannot postpone the other."""
    window.model.append([make_record(i, message="watchdog") for i in range(3)])
    shown = window.model.rowCount()
    window.filter_bar._highlight.setText("watchdog")
    window._apply_highlight()
    assert window.model.rowCount() == shown
    assert window.model.filter == Filter()
    assert window.model.highlight == Highlight(text="watchdog")


def test_the_status_bar_says_how_many_rows_carry_the_term(window: MainWindow) -> None:
    window.model.append([make_record(0, message="watchdog"), make_record(1, message="quiet")])
    window.filter_bar._highlight.setText("watchdog")
    window._apply_highlight()
    assert window.status.hits_text == HITS.format(count=1)


def test_the_hit_readout_speaks_at_zero_and_is_silent_with_no_term(
    window: MainWindow,
) -> None:
    """The gap count's rule rather than `set_shown`'s. "Highlighted, no hits" is
    the answer to *does this ever happen*, and a readout that vanished instead
    could not be told from a field somebody had not finished typing into."""
    window.model.append([make_record(0, message="quiet")])
    window.filter_bar._highlight.setText("watchdog")
    window._apply_highlight()
    assert window.status.hits_text == HITS.format(count=0)

    window.filter_bar.clear_highlight()
    window._apply_highlight()
    assert window.status.hits_text == ""


def test_the_gutter_appears_only_while_a_term_is_set(window: MainWindow) -> None:
    """Five pixels off every window forever, for a strip that says nothing until
    somebody types, is the cost this project refused for the minimap time axis.

    `isHidden` rather than `isVisible`: an unshown widget and a hidden one
    answer `isVisible` identically.
    """
    assert window.table.gutter.isHidden()
    window.filter_bar._highlight.setText("watchdog")
    window._apply_highlight()
    assert not window.table.gutter.isHidden()
    window.filter_bar.clear_highlight()
    window._apply_highlight()
    assert window.table.gutter.isHidden()


def test_the_gutter_draws_a_tick_on_every_hit_row_and_nowhere_else(
    qt_app: object,
) -> None:
    """A pixel, not a visibility flag.

    The visibility assertion above passes just as happily against a strip that
    paints nothing, and a timing run reporting 0.001 ms was the first hint that
    it might be doing exactly that. This is the second bug class in this project
    that only a picture could reveal, so the picture is taken: ten alternating
    hits over twenty rows come to ten ticks of `_TICK_WIDTH` by the row height,
    and the arithmetic is asserted rather than the count of coloured pixels
    being taken on trust.
    """
    del qt_app
    table = LogTable()
    model = RecordModel()
    table.setModel(model)
    model.append([make_record(i, message="watchdog" if i % 2 else "quiet") for i in range(20)])
    marked = Highlight(text="watchdog")
    model.set_highlight(marked)
    table.set_highlight(marked)
    table.resize(900, 500)
    table.show()

    shot = table.gutter.grab().toImage()
    tick = mark_accent(table._scheme).rgb()
    painted = sum(
        shot.pixel(x, y) == tick for y in range(shot.height()) for x in range(shot.width())
    )
    assert model.highlight_hits == 10
    assert painted == 10 * _TICK_WIDTH * table.gutter.sectionSize(0)


def test_a_half_typed_highlight_keeps_the_previous_one(window: MainWindow) -> None:
    """Half a pattern is not "mark nothing", and it must not read as one."""
    window.filter_bar._highlight.setText("error")
    window._apply_highlight()
    window.filter_bar._highlight_regex.setChecked(True)
    window.filter_bar._highlight.setText("[com")
    window._apply_highlight()
    assert window.model.highlight == Highlight(text="error")


def test_clearing_the_filter_leaves_the_highlight_alone(window: MainWindow) -> None:
    """The banner's way out is for a filter that hides everything. A highlight
    hides nothing, so taking it away there answers a question nobody asked."""
    window.filter_bar._highlight.setText("watchdog")
    window._apply_highlight()
    window.filter_bar.clear()
    assert window.model.highlight == Highlight(text="watchdog")


def test_closing_the_capture_drops_the_highlight(window: MainWindow) -> None:
    """The one door that empties the window rather than pointing it elsewhere."""
    window.filter_bar._highlight.setText("watchdog")
    window._apply_highlight()
    window.close_capture()
    assert window.model.highlight == Highlight()
    assert window.table.gutter.isHidden()


# -- the repeat marker -------------------------------------------------------


def test_the_repeat_marker_is_drawn_muted(window: MainWindow) -> None:
    """A run of one process is what blanking exists to make scannable, so
    putting a character back on every row of it has to cost the eye nothing."""
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QStyleOptionViewItem

    from ostrace.gui.theme import token

    window.model.append([make_record(i) for i in range(3)])
    option = QStyleOptionViewItem()
    index = window.model.index(1, int(Column.PROCESS))
    window.table.severity_delegate.initStyleOption(option, index)
    assert option.text == window.model.data(index, Qt.ItemDataRole.DisplayRole)
    assert option.palette.color(QPalette.ColorRole.Text) == token("text-muted", window.scheme)
