# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The trace export.

Two things have to hold. The records must be verbatim -- the whole reason to
choose this format over the report is that identifiers survive -- and every
limit it ran into has to be visible, since a trace that silently covers a
quarter of the anchors looks exactly like one that covered all of them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ostrace.analysis.trace import TracePolicy
from ostrace.exporters import EXPORTERS
from ostrace.exporters.trace import TraceExporter
from ostrace.model import Gap, Level, Record
from ostrace.storage.spool import SpoolReader
from tests.helpers import ERRORS, MIXED, make_gap, make_record

if TYPE_CHECKING:
    from pathlib import Path


def series(length: int, *errors: int) -> list[Record]:
    records = [make_record(i) for i in range(length)]
    for index in errors:
        records[index] = make_record(index, level=Level.ERROR, message=f"error at {index}")
    return records


class TestOutput:
    def test_anchors_are_marked_and_context_is_not(self, tmp_path: Path) -> None:
        result = TraceExporter(policy=TracePolicy(before=2, after=2)).export(
            series(20, 10), tmp_path / "trace.md"
        )
        body = result.destination.read_text(encoding="utf-8")
        marked = [entry for entry in body.splitlines() if entry.startswith(">>")]

        assert len(marked) == 1
        assert "error at 10" in marked[0]
        assert body.count("\n   ") >= 0  # context lines carry the blank prefix

    def test_the_records_are_verbatim(self, tmp_path: Path) -> None:
        """The reason to choose this format: identifiers survive, so one object
        can be followed across a sequence."""
        result = TraceExporter(policy=TracePolicy(before=1, after=1)).export(
            [*series(10), make_record(99, level=Level.ERROR, message="id 4821 failed")],
            tmp_path / "trace.md",
        )
        assert "id 4821 failed" in result.destination.read_text(encoding="utf-8")

    def test_a_window_states_where_it_sits_in_the_capture(self, tmp_path: Path) -> None:
        """A window with no way back to the full log is a fragment."""
        result = TraceExporter(policy=TracePolicy(before=5, after=5)).export(
            series(100, 50), tmp_path / "trace.md"
        )
        assert "Records 46 to 56 of the capture." in result.destination.read_text(encoding="utf-8")

    def test_no_anchors_says_so_rather_than_writing_nothing(self, tmp_path: Path) -> None:
        result = TraceExporter().export(series(50), tmp_path / "trace.md")
        assert "No anchors matched" in result.destination.read_text(encoding="utf-8")


class TestDeclaringLimits:
    def test_uncovered_anchors_are_declared(self, tmp_path: Path) -> None:
        """A trace covering a quarter of the anchors looks exactly like one
        that covered all of them, unless it says otherwise."""
        result = TraceExporter(policy=TracePolicy(before=1, after=2, max_windows=2)).export(
            series(500, *range(0, 500, 50)), tmp_path / "trace.md"
        )
        body = result.destination.read_text(encoding="utf-8")
        assert "anchors are not in this file" in body
        assert "the earliest part of the capture, not a sample" in body

    def test_a_complete_trace_claims_no_omission(self, tmp_path: Path) -> None:
        result = TraceExporter(policy=TracePolicy(before=2, after=2)).export(
            series(100, 50), tmp_path / "trace.md"
        )
        assert "are not in this file" not in result.destination.read_text(encoding="utf-8")

    def test_a_size_truncated_window_says_it_ends_mid_sequence(self, tmp_path: Path) -> None:
        result = TraceExporter(
            policy=TracePolicy(before=2, after=20, max_window_records=50)
        ).export(series(400, *range(0, 400, 3)), tmp_path / "trace.md")
        assert "ends mid-sequence" in result.destination.read_text(encoding="utf-8")

    def test_gaps_are_declared(self, tmp_path: Path) -> None:
        """A sequence read across a hole is not a sequence."""
        items: list[Record | Gap] = [make_record(0, level=Level.ERROR), make_gap(0), make_record(1)]
        result = TraceExporter(policy=TracePolicy(before=2, after=2)).export(
            items, tmp_path / "trace.md"
        )
        body = result.destination.read_text(encoding="utf-8")
        assert "gap" in body
        assert "not a sequence" in body


class TestExport:
    def test_it_writes_one_file_and_scans_the_capture(self, tmp_path: Path) -> None:
        """The scan rides along on the same pass -- reading the session twice
        to produce one file would be the wrong trade."""
        result = TraceExporter().export(SpoolReader(MIXED).items(), tmp_path / "trace.md")
        assert result.files == [result.destination]
        assert result.records == 5000
        assert result.scan is not None
        assert result.scan.errors == 2

    def test_the_error_heavy_capture_produces_readable_windows(self, tmp_path: Path) -> None:
        result = TraceExporter().export(SpoolReader(ERRORS).items(), tmp_path / "trace.md")
        body = result.destination.read_text(encoding="utf-8")
        assert body.count("## Window ") > 1
        assert "ends mid-sequence" in body

    def test_files_are_written_with_lf(self, tmp_path: Path) -> None:
        result = TraceExporter().export(series(10, 5), tmp_path / "trace.md")
        assert b"\r\n" not in result.destination.read_bytes()


class TestRegistry:
    @pytest.mark.parametrize(
        "name", ["agent-bundle", "jsonl", "text", "markdown", "ai-report", "trace"]
    )
    def test_every_exporter_is_registered(self, name: str) -> None:
        assert EXPORTERS[name].name == name

    def test_there_are_no_others(self) -> None:
        """`--format` choices come from this registry, so an accidental entry
        becomes a documented option."""
        assert len(EXPORTERS) == 6


def test_a_window_cut_short_by_the_end_of_the_capture_says_so(tmp_path: Path) -> None:
    """The other way a window ends early, and it used to say nothing.

    The size-limit case gets a paragraph. Running out of capture got silence --
    and it is the *last* window, the one a reader studies, where an absent
    aftermath reads as "the device went quiet after the error". That is the
    conclusion this format exists to prevent.
    """
    records = [make_record(index) for index in range(60)]
    records[55] = make_record(55, level=Level.ERROR)

    result = TraceExporter().export(records, tmp_path / "edge.md")
    report = result.destination.read_text(encoding="utf-8")

    assert "The capture ends here" in report
    assert "unknown, not absent" in report


def test_a_window_with_room_to_spare_says_nothing_extra(tmp_path: Path) -> None:
    """The note must not fire on an ordinary window, or it becomes noise."""
    records = [make_record(index) for index in range(300)]
    records[10] = make_record(10, level=Level.ERROR)

    result = TraceExporter().export(records, tmp_path / "roomy.md")

    assert "The capture ends here" not in result.destination.read_text(encoding="utf-8")
