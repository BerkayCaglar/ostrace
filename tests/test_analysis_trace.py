# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Anchored verbatim windows.

The window arithmetic is ours, so synthetic records are the right input: a test
about "two anchors four records apart become one window" needs anchors at known
positions, not real ones. The fixture appears at the end, where the question is
whether the thing behaves on a real capture at all.
"""

from __future__ import annotations

from itertools import pairwise

from ostrace.analysis.trace import MAX_WINDOW_RECORDS, TracePolicy, trace
from ostrace.model import Gap, Level, Record
from ostrace.storage.spool import SpoolReader
from tests.helpers import ERRORS, make_gap, make_record


def series(length: int, *errors: int) -> list[Record]:
    """`length` records, with an error at each given index."""
    records = [make_record(i) for i in range(length)]
    for index in errors:
        records[index] = make_record(index, level=Level.ERROR, message=f"error at {index}")
    return records


class TestWindows:
    def test_no_anchors_means_no_windows(self) -> None:
        result = trace(series(50))
        assert result.windows == []
        assert result.anchors_seen == 0
        assert result.records_scanned == 50

    def test_a_window_surrounds_its_anchor(self) -> None:
        result = trace(series(300, 100), policy=TracePolicy(before=10, after=20))
        (window,) = result.windows

        assert len(window.records) == 10 + 1 + 20
        assert window.anchors == [10]
        assert window.first_line == 91
        assert window.anchor_records[0].message == "error at 100"

    def test_the_line_number_ties_back_to_the_capture(self) -> None:
        """A window with no way back to the full log is a fragment."""
        result = trace(series(300, 100), policy=TracePolicy(before=10, after=20))
        (window,) = result.windows
        assert window.records[0].message == "record number 90"
        assert window.first_line == 91

    def test_an_anchor_at_the_start_has_no_run_up(self) -> None:
        result = trace(series(50, 0), policy=TracePolicy(before=10, after=5))
        (window,) = result.windows
        assert window.first_line == 1
        assert window.anchors == [0]

    def test_a_window_cut_short_by_the_end_is_still_reported(self) -> None:
        result = trace(series(50, 45), policy=TracePolicy(before=5, after=80))
        (window,) = result.windows
        assert len(window.records) == 5 + 1 + 4


class TestMerging:
    def test_two_close_anchors_produce_one_window(self) -> None:
        """Two errors four records apart are one event described twice.
        Emitting two overlapping windows makes a reader compare them to find
        out they are the same."""
        result = trace(series(300, 100, 104), policy=TracePolicy(before=10, after=20))
        (window,) = result.windows

        assert window.anchors == [10, 14]
        assert result.anchors_covered == 2

    def test_the_second_anchor_extends_the_window(self) -> None:
        result = trace(series(300, 100, 104), policy=TracePolicy(before=10, after=20))
        (window,) = result.windows
        # The tail is measured from the *last* anchor, not the first.
        assert len(window.records) == 10 + 1 + 4 + 20

    def test_an_anchor_on_the_last_record_of_a_window_keeps_it_open(self) -> None:
        """The extension has to happen before the exhaustion check, or a window
        closes on the very record that should have prolonged it."""
        result = trace(series(300, 100, 120), policy=TracePolicy(before=5, after=20))
        assert len(result.windows) == 1
        assert result.windows[0].anchors == [5, 25]

    def test_anchors_far_apart_produce_separate_windows(self) -> None:
        result = trace(series(500, 100, 300), policy=TracePolicy(before=5, after=20))
        assert len(result.windows) == 2
        assert [w.anchors for w in result.windows] == [[5], [5]]

    def test_the_run_up_is_not_repeated_across_windows(self) -> None:
        """The records before the second anchor were already written into the
        first window; carrying them again would duplicate a chunk of the log."""
        result = trace(series(200, 50, 100), policy=TracePolicy(before=40, after=20))
        first, second = result.windows
        assert not {id(r) for r in first.records} & {id(r) for r in second.records}


class TestLimits:
    def test_the_window_cap_is_honoured(self) -> None:
        anchors = tuple(range(0, 1000, 50))
        result = trace(series(1000, *anchors), policy=TracePolicy(before=2, after=5, max_windows=3))
        assert len(result.windows) == 3

    def test_anchors_beyond_the_cap_are_counted_not_hidden(self) -> None:
        """The difference between what exists and what is shown is the thing a
        report has to declare."""
        anchors = tuple(range(0, 1000, 50))
        result = trace(series(1000, *anchors), policy=TracePolicy(before=2, after=5, max_windows=3))

        assert result.anchors_seen == len(anchors)
        assert result.anchors_covered == 3
        assert result.anchors_missed == len(anchors) - 3
        assert result.truncated

    def test_a_complete_trace_is_not_marked_truncated(self) -> None:
        result = trace(series(300, 100), policy=TracePolicy(before=5, after=10))
        assert not result.truncated
        assert result.anchors_missed == 0

    def test_a_dense_capture_does_not_become_one_enormous_window(self) -> None:
        """Capping the number of windows is not enough on its own.

        An anchor inside an open window extends it, so where anchors are dense
        the extensions never stop. The project's error-heavy fixture is 2,250
        errors in 3,000 records, and without a size limit it produced exactly
        one window containing the whole capture -- which is not a trace of
        anything.
        """
        result = trace(
            series(600, *range(0, 600, 3)),
            policy=TracePolicy(before=5, after=20, max_window_records=100),
        )

        assert len(result.windows) > 1
        for window in result.windows:
            assert len(window.records) <= 100

    def test_a_window_closed_by_size_says_so(self) -> None:
        """The reader is mid-sequence at the last line, which is a different
        thing from a run of interesting records having ended."""
        result = trace(
            series(600, *range(0, 600, 3)),
            policy=TracePolicy(before=5, after=20, max_window_records=100),
        )
        assert result.windows[0].truncated


class TestGaps:
    def test_a_gap_is_not_a_record(self) -> None:
        """Counting one would put every line pointer after it out of step."""
        items: list[Record | Gap] = [*series(20), make_gap(0), *series(20)]
        result = trace(items, anchor=lambda r: r.pid == 147, policy=TracePolicy(before=2, after=2))
        assert result.records_scanned == 40


class TestCustomAnchors:
    def test_the_anchor_predicate_is_the_whole_selection(self) -> None:
        records = series(100)
        records[42] = make_record(42, message="the interesting one")
        result = trace(
            records,
            anchor=lambda record: "interesting" in record.message,
            policy=TracePolicy(before=3, after=3),
        )
        (window,) = result.windows
        assert window.anchor_records[0].message == "the interesting one"

    def test_the_default_anchor_is_errors(self) -> None:
        result = trace(series(100, 50), policy=TracePolicy(before=3, after=3))
        assert result.anchors_seen == 1


class TestAgainstTheFixture:
    def test_it_traces_a_real_error_heavy_capture(self) -> None:
        result = trace(SpoolReader(ERRORS).items())

        assert result.records_scanned == 3000
        assert result.anchors_seen > 0
        assert len(result.windows) <= 25
        for window in result.windows:
            assert window.anchors
            assert window.first_line >= 1
            assert len(window.records) <= MAX_WINDOW_RECORDS

    def test_a_capture_that_is_mostly_errors_still_produces_a_trace(self) -> None:
        """2,250 errors in 3,000 records. Every anchor extends the window, so
        without a size limit this is one block containing everything.

        Note what is *not* asserted: that the trace is smaller than the
        capture. At this density it legitimately covers all of it — when three
        records in four are errors, everything is near an anchor. What the size
        limit buys is that it arrives as readable windows instead of one block,
        each saying it ends mid-sequence.
        """
        result = trace(SpoolReader(ERRORS).items())

        assert result.anchors_seen > 2_000
        assert len(result.windows) > 1
        assert all(len(w.records) <= MAX_WINDOW_RECORDS for w in result.windows)
        assert any(window.truncated for window in result.windows)

    def test_windows_do_not_overlap(self) -> None:
        result = trace(SpoolReader(ERRORS).items())
        spans = [(w.first_line, w.first_line + len(w.records) - 1) for w in result.windows]
        for (_, end), (start, _) in pairwise(spans):
            assert start > end, "windows overlap, so records are duplicated"
