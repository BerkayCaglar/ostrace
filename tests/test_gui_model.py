# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The table model, against real captures.

Everything here runs offscreen on all three operating systems: a model needs no
display, no platform theme and no font, which is why the design puts as much of
the program's behaviour into it as will go.

Real fixture records rather than synthetics wherever the assertion is about how
device output is *interpreted* — which process labels collide, which records
have no subsystem, how long a run of one process actually gets. Synthetics are
used only where the assertion is about the model's own bookkeeping, and are
built to be obviously artificial so nobody mistakes them for evidence about a
device.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from ostrace.model import Gap, Level, Record
from ostrace.storage.spool import SpoolReader
from tests.helpers import ERRORS, MIXED, make_record

pytest.importorskip("PySide6", reason="the gui extra is not installed")

from PySide6.QtCore import QModelIndex, Qt

from ostrace.gui.columns import Column
from ostrace.gui.filters import Filter
from ostrace.gui.markers import Eviction, is_marker, is_record
from ostrace.gui.models import RecordModel
from ostrace.gui.theme import Scheme

if TYPE_CHECKING:
    from ostrace.gui.markers import Row

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def capture() -> list[Row]:
    return list(SpoolReader(MIXED).items())


@pytest.fixture(scope="module")
def records(capture: list[Row]) -> list[Record]:
    return [item for item in capture if isinstance(item, Record)]


@pytest.fixture(scope="module")
def error_records() -> list[Record]:
    """The error-heavy capture, which is the only one carrying `Fault`.

    Measured: the mixed capture is 3,863 Debug, 742 Info, 393 Notice and 2
    Error, with no Fault at all. Any assertion about the top of the severity
    range has to come from here.
    """
    return [item for item in SpoolReader(ERRORS).items() if isinstance(item, Record)]


@pytest.fixture
def model(qt_app: object) -> RecordModel:
    del qt_app
    return RecordModel(Scheme.LIGHT)


def text(model: RecordModel, row: int, column: Column) -> str:
    value = model.data(model.index(row, int(column)), Qt.ItemDataRole.DisplayRole)
    assert isinstance(value, str)
    return value


# -- the marker invariant ----------------------------------------------------


def test_a_gap_survives_a_filter_that_excludes_everything_around_it(
    model: RecordModel, records: list[Record]
) -> None:
    """The invariant, stated as a test.

    A filter says which records the user wants; a marker says whether the
    answer is complete. A filtered view that hides its own gaps is lying about
    what it does not contain, and the reader cannot tell.
    """
    gap = Gap(
        start=records[0].timestamp,
        end=records[0].timestamp + timedelta(seconds=3),
        reason="connection dropped",
    )
    model.append([*records[:50], gap, *records[50:100]])
    before = model.rowCount()

    model.set_filter(Filter(process="a-process-that-does-not-exist"))

    assert before > 1
    assert model.rowCount() == 1, "only the gap should remain"
    assert is_marker(model.row_at(0))
    assert "gap" in text(model, 0, Column.MESSAGE)


def test_an_eviction_notice_also_survives_a_filter(model: RecordModel) -> None:
    """Every discontinuity is a marker, not just the one that was thought of
    first. Android Studio has this exemption and still classified one of its
    own loss notices as an ordinary record."""
    tiny = RecordModel(Scheme.LIGHT, row_cap=100)
    tiny.append([make_record(i) for i in range(200)])
    tiny.set_filter(Filter(minimum_level=Level.FAULT))

    assert tiny.evicted > 0
    assert any(isinstance(tiny.row_at(row), Eviction) for row in range(tiny.rowCount()))


def test_a_gap_and_an_eviction_do_not_read_the_same(model: RecordModel) -> None:
    """They look alike and mean opposite things.

    One says the records are gone forever; the other says they are on disk and
    merely not on screen. Rendering them identically would make the view lie
    about the session file.
    """
    tiny = RecordModel(Scheme.LIGHT, row_cap=50)
    tiny.append([make_record(i) for i in range(120)])
    eviction = next(
        tiny.row_at(row) for row in range(tiny.rowCount()) if isinstance(tiny.row_at(row), Eviction)
    )
    assert isinstance(eviction, Eviction)

    assert "in the capture but not in this view" in eviction.text
    assert "gap" not in eviction.text.casefold()


def test_the_gap_row_uses_the_exporter_wording(model: RecordModel, records: list[Record]) -> None:
    """`docs/formats/` wins, and the same event should read the same in the
    table as it does in a plaintext export."""
    gap = Gap(
        start=records[0].timestamp,
        end=records[0].timestamp + timedelta(seconds=1),
        reason="device disconnected",
    )
    model.append([gap])
    assert text(model, 0, Column.MESSAGE).startswith("---- gap ")
    assert "(device disconnected)" in text(model, 0, Column.MESSAGE)
    assert text(model, 0, Column.LEVEL) == "GAP"


# -- filtering ---------------------------------------------------------------


def test_filtering_by_level_is_a_threshold_not_an_equality(
    model: RecordModel, error_records: list[Record]
) -> None:
    """Apple's own values are not severity-ordered, so this is only expressible
    because `Level` is our enum: `NOTICE=0, INFO=1, DEBUG=2, ERROR=16`.

    `Fault` surviving an `Error` threshold is the whole assertion: under
    equality it would be filtered out, and under Apple's numbering `>= ERROR`
    against the raw values would keep almost everything.
    """
    model.append(error_records)
    model.set_filter(Filter(minimum_level=Level.ERROR))

    shown = [model.row_at(row) for row in range(model.rowCount())]
    assert all(isinstance(r, Record) and r.level >= Level.ERROR for r in shown)
    assert any(isinstance(r, Record) and r.level is Level.FAULT for r in shown)
    assert len(shown) < len(error_records), "a threshold that keeps everything is not a filter"


def test_a_process_filter_matches_a_pid_exactly_but_a_name_loosely(
    model: RecordModel, records: list[Record]
) -> None:
    """Both are what people have in front of them: a name read off the table,
    or a pid copied out of a crash report. `97` must not match `launchd[9712]`."""
    subject = records[0]
    model.append(records)

    model.set_filter(Filter(process=str(subject.pid)))
    assert all(
        isinstance(r, Record) and r.pid == subject.pid
        for r in (model.row_at(i) for i in range(model.rowCount()))
    )

    model.set_filter(Filter(process=subject.process[:4]))
    assert model.rowCount() > 0


def test_an_invalid_regex_is_refused_rather_than_matching_nothing() -> None:
    """A user halfway through typing `[com` has an incomplete pattern, not an
    empty log. A view that empties itself as they type is indistinguishable
    from a device that stopped talking."""
    with pytest.raises(ValueError, match="invalid regular expression"):
        Filter(search="[unclosed", regex=True)


def test_a_plain_search_is_not_a_regex(model: RecordModel) -> None:
    """Typing `a.b` should find `a.b`, not `axb`."""
    model.append([make_record(0, message="literal a.b here"), make_record(1, message="axb")])
    model.set_filter(Filter(search="a.b"))
    assert model.rowCount() == 1


def test_setting_an_identical_filter_does_not_rescan(
    model: RecordModel, records: list[Record]
) -> None:
    """Typing and deleting one character must not cost a scan of the capture.

    Asserted through `modelAboutToBeReset`, which is what a rescan emits and
    what would throw the view to the top.
    """
    model.append(records[:500])
    model.set_filter(Filter(minimum_level=Level.NOTICE))

    resets = []
    model.modelAboutToBeReset.connect(lambda: resets.append(1))
    model.set_filter(Filter(minimum_level=Level.NOTICE))
    assert resets == []

    model.set_filter(Filter(minimum_level=Level.ERROR))
    assert len(resets) == 1


def test_a_filter_hides_rows_without_discarding_the_capture(
    model: RecordModel, records: list[Record]
) -> None:
    """Retention is not visibility. Clearing a filter brings everything back
    because nothing was thrown away to apply it."""
    model.append(records)
    everything = model.rowCount()

    model.set_filter(Filter(minimum_level=Level.FAULT))
    assert model.rowCount() < everything
    assert model.retained == len(records)
    assert model.hidden_by_filter == len(records) - model.rowCount()

    model.set_filter(Filter())
    assert model.rowCount() == everything


def test_records_arriving_under_a_filter_are_tested_as_they_arrive(
    model: RecordModel, records: list[Record]
) -> None:
    """The steady state is O(batch): only a filter change rescans."""
    model.set_filter(Filter(minimum_level=Level.ERROR))
    model.append(records)

    expected = sum(1 for r in records if r.level >= Level.ERROR)
    assert model.rowCount() == expected


# -- the row cap -------------------------------------------------------------


def test_the_cap_tolerates_a_margin_before_trimming(qt_app: object) -> None:
    """A stream sitting exactly at the limit must not trigger a removal on
    every batch."""
    del qt_app
    model = RecordModel(Scheme.LIGHT, row_cap=100)
    model.append([make_record(i) for i in range(105)])
    assert model.evicted == 0, "within the margin"

    model.append([make_record(i) for i in range(105, 130)])
    assert model.evicted > 0


def test_trimming_keeps_the_newest_records(qt_app: object) -> None:
    del qt_app
    model = RecordModel(Scheme.LIGHT, row_cap=50)
    model.append([make_record(i, message=f"record {i}") for i in range(200)])

    last = model.row_at(model.rowCount() - 1)
    assert isinstance(last, Record)
    assert last.message == "record 199"


def test_the_eviction_notice_is_updated_not_accumulated(qt_app: object) -> None:
    """Twenty evictions are one fact about the view, not twenty rows of noise
    at the top of it."""
    del qt_app
    model = RecordModel(Scheme.LIGHT, row_cap=50)
    for start in range(0, 400, 40):
        model.append([make_record(i) for i in range(start, start + 40)])

    notices = [
        model.row_at(row)
        for row in range(model.rowCount())
        if isinstance(model.row_at(row), Eviction)
    ]
    assert len(notices) == 1
    assert isinstance(notices[0], Eviction)
    assert notices[0].count == model.evicted


def test_an_untrimmed_model_has_no_eviction_notice(
    model: RecordModel, records: list[Record]
) -> None:
    """The notice appears because something happened, not as furniture."""
    model.append(records)
    assert model.evicted == 0
    assert not any(isinstance(model.row_at(row), Eviction) for row in range(model.rowCount()))


# -- presentation ------------------------------------------------------------


def test_a_repeated_process_cell_is_blanked(model: RecordModel) -> None:
    """What makes a log where one process emits hundreds of consecutive
    records scannable at all."""
    model.append([make_record(i) for i in range(3)])
    assert text(model, 0, Column.PROCESS)
    assert text(model, 1, Column.PROCESS) == ""
    assert text(model, 2, Column.PROCESS) == ""


def test_a_long_run_of_repeats_does_not_exhaust_the_stack(model: RecordModel) -> None:
    """A regression test for a bug a three-row test could not see.

    Deciding whether a row repeats the one above it used to ask what that row
    *displayed*, which asks whether *it* was a repeat, all the way to the top
    of the run. Depth equals run length, and a real capture holds runs of tens
    of thousands. It now compares the underlying fields, which is O(1).

    The count is far above the interpreter's default recursion limit on
    purpose: at 3 rows the old code passed.
    """
    model.append([make_record(i) for i in range(5_000)])
    assert text(model, 4_999, Column.PROCESS) == ""
    assert text(model, 0, Column.PROCESS) != ""


def test_a_marker_breaks_a_run_of_repeats(model: RecordModel, records: list[Record]) -> None:
    """Blanking across a marker would imply a continuity that the marker exists
    to deny."""
    gap = Gap(
        start=records[0].timestamp,
        end=records[0].timestamp + timedelta(seconds=1),
        reason="connection dropped",
    )
    model.append([make_record(0), gap, make_record(1)])

    assert text(model, 1, Column.LEVEL) == "GAP"
    assert text(model, 2, Column.PROCESS) != "", "the run restarts after the marker"


def test_the_urgent_levels_carry_their_glyph_into_the_table(model: RecordModel) -> None:
    """Colour is never the only cue for severity."""
    model.append([make_record(0, level=Level.ERROR), make_record(1, level=Level.INFO)])
    assert text(model, 0, Column.LEVEL).startswith("!")
    assert text(model, 1, Column.LEVEL) == "Info"


def test_absent_fields_use_the_exporters_spelling(
    model: RecordModel, records: list[Record]
) -> None:
    """A value copied out of the table should match what a bundle would hold."""
    without = next(r for r in records if r.subsystem is None)
    model.append([without])
    assert text(model, 0, Column.SUBSYSTEM) == "-"


def test_recolouring_does_not_move_any_rows(model: RecordModel, records: list[Record]) -> None:
    """A theme switch is a repaint, not a reset: it must not throw the user's
    scroll position or selection away."""
    model.append(records[:200])
    before = model.rowCount()

    resets = []
    model.modelAboutToBeReset.connect(lambda: resets.append(1))
    changed = []
    model.dataChanged.connect(lambda *_: changed.append(1))

    model.set_scheme(Scheme.DARK)

    assert resets == []
    assert changed
    assert model.rowCount() == before


def test_severity_colours_are_not_allocated_per_cell(model: RecordModel) -> None:
    """`data()` runs per cell per role, so a colour built inside it is built
    millions of times. They are cached per level instead."""
    model.append([make_record(0, level=Level.ERROR), make_record(1, level=Level.ERROR)])
    first = model.data(model.index(0, 0), Qt.ItemDataRole.ForegroundRole)
    second = model.data(model.index(1, 0), Qt.ItemDataRole.ForegroundRole)
    assert first is second


def test_the_header_names_every_column(model: RecordModel) -> None:
    titles = [
        model.headerData(section, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
        for section in range(model.columnCount())
    ]
    assert titles == ["Time", "Level", "Process", "Subsystem", "Category", "Message"]


def test_an_invalid_index_yields_nothing(model: RecordModel) -> None:
    assert model.data(QModelIndex()) is None


def test_is_record_and_is_marker_are_complements(records: list[Record]) -> None:
    """They are used at different places and must never disagree."""
    gap = Gap(
        start=records[0].timestamp,
        end=records[0].timestamp + timedelta(seconds=1),
        reason="x",
    )
    for row in (records[0], gap, Eviction(count=1, through=records[0].timestamp)):
        assert is_record(row) != is_marker(row)
