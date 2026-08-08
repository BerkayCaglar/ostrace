# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The budgeted report.

Every test here is ultimately about one property: the report may drop anything
it likes, but it must say so. A summary that quietly stops at the budget reads
as complete, and a reader then draws conclusions from an absence that is an
artefact of truncation rather than a fact about the device.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ostrace.analysis.scan import EXCERPT_AFTER, EXCERPT_BEFORE, ScanResult, scan
from ostrace.exporters.ai_report import DEFAULT_BUDGET_TOKENS, AiReportExporter, render
from ostrace.model import Level
from ostrace.storage.spool import SpoolReader
from tests.helpers import ERRORS, MIXED, make_gap, make_record

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(scope="module")
def errors_scan() -> ScanResult:
    """The error-heavy capture: the one that exercises every section."""
    return scan(SpoolReader(ERRORS).items())


class TestBudget:
    def test_a_tight_budget_is_respected(self, errors_scan: ScanResult) -> None:
        generous = render(errors_scan, budget_tokens=None)
        tight = render(errors_scan, budget_tokens=2_000)
        assert len(tight) < len(generous)

    def test_a_tight_budget_declares_every_drop(self, errors_scan: ScanResult) -> None:
        """The property the whole format rests on."""
        tight = render(errors_scan, budget_tokens=2_000)
        omissions = tight.split("## 7. What this report leaves out")[1]
        assert "did not fit the budget" in omissions
        assert "Nothing was dropped" not in omissions

    def test_an_unlimited_budget_says_nothing_was_dropped(self, errors_scan: ScanResult) -> None:
        report = render(errors_scan, budget_tokens=None)
        assert "Nothing was dropped for space" in report
        assert "did not fit the budget" not in report

    def test_the_closing_section_survives_any_budget(self, errors_scan: ScanResult) -> None:
        """It is the part that declares the drops, so it must never be the part
        that gets dropped."""
        for tokens in (200, 1_000, 5_000, DEFAULT_BUDGET_TOKENS):
            report = render(errors_scan, budget_tokens=tokens)
            assert "## 7. What this report leaves out" in report

    def test_errors_are_kept_before_bulk_patterns(self, errors_scan: ScanResult) -> None:
        """A budget spent evenly would describe the first two minutes perfectly
        and the rest not at all. Errors are what a reader came for."""
        tight = render(errors_scan, budget_tokens=1_500)
        error_rows = tight.split("## 4.")[1].split("## 5.")[0].count("[x")
        assert error_rows > 0

    def test_the_counts_reported_are_of_the_whole_capture(self, errors_scan: ScanResult) -> None:
        """Truncating the report must not truncate the numbers: "3,000 records"
        stays true however little of it is shown."""
        tight = render(errors_scan, budget_tokens=500)
        assert f"| Records | {errors_scan.records:,} |" in tight
        assert f"| At Error or Fault | {errors_scan.errors:,} |" in tight


class TestContent:
    def test_it_states_the_levels_ios_actually_emits(self, errors_scan: ScanResult) -> None:
        report = render(errors_scan, budget_tokens=None)
        guidance = report.split("## 3.")[0]
        assert "`User Action`" in guidance
        assert "there is no `Warning` and no `Critical`" in guidance

    def test_it_warns_that_error_is_not_a_fault(self, errors_scan: ScanResult) -> None:
        """The single most common misreading of an iOS log, and this fixture is
        3,000 records of mostly-routine `Error`."""
        report = render(errors_scan, budget_tokens=None)
        assert "does not mean something is wrong" in report

    def test_subsystems_are_reported(self, errors_scan: ScanResult) -> None:
        """The column the predecessor did not have."""
        report = render(errors_scan, budget_tokens=None)
        assert "| Subsystem | Records | Errors |" in report

    def test_gaps_are_declared_twice(self) -> None:
        """Once where a reader is told how to read the report, and once in the
        closing list. An absence across a gap proves nothing, and that has to
        reach a reader who skipped the preamble."""
        result = scan([make_record(0, level=Level.ERROR), make_gap(0), make_record(1)])
        report = render(result, budget_tokens=None)
        assert report.count("gap") >= 2

    def test_a_capture_with_no_errors_says_so_rather_than_inventing_a_window(self) -> None:
        report = render(scan([make_record(0)]), budget_tokens=None)
        assert "_No records at `Error` or `Fault`._" in report
        assert "nothing to centre a window on" in report


class TestExcerpt:
    def test_the_window_is_centred_on_the_first_error(self) -> None:
        records = [make_record(i) for i in range(10)]
        records[4] = make_record(4, level=Level.ERROR, message="the first one")
        records[7] = make_record(7, level=Level.FAULT, message="a later one")
        result = scan(records)

        assert result.excerpt[0] == records[0]
        assert result.excerpt_line == 1
        assert records[4] in result.excerpt
        assert [r.message for r in result.excerpt].count("the first one") == 1

    def test_the_window_is_bounded_on_both_sides(self) -> None:
        # Deliberately more records after the error than the window wants, so
        # the bound is what stops it rather than the capture running out.
        records = [make_record(i) for i in range(500)]
        error_at = 200
        records[error_at] = make_record(error_at, level=Level.ERROR)
        result = scan(records)

        assert len(result.excerpt) == EXCERPT_BEFORE + 1 + EXCERPT_AFTER
        assert result.excerpt_line == error_at + 1 - EXCERPT_BEFORE

    def test_the_window_stops_at_the_end_of_a_short_capture(self) -> None:
        """An error near the end has less after it than the window wants. Taking
        what exists is right; padding or refusing would both be worse."""
        records = [make_record(i) for i in range(80)]
        records[70] = make_record(70, level=Level.ERROR)
        result = scan(records)

        assert len(result.excerpt) == 80 - (70 - EXCERPT_BEFORE)
        assert result.excerpt[-1] == records[-1]

    def test_it_costs_nothing_once_taken(self) -> None:
        """The preceding-records buffer is only useful until a window exists."""
        records = [make_record(0, level=Level.ERROR)] + [make_record(i) for i in range(1, 500)]
        result = scan(records)
        assert len(result._preceding) == 0
        assert len(result.excerpt) == 1 + EXCERPT_AFTER

    def test_a_capture_with_no_errors_holds_no_window(self) -> None:
        result = scan([make_record(i) for i in range(200)])
        assert result.excerpt == []
        assert result.excerpt_line == 0

    def test_the_excerpt_is_verbatim(self) -> None:
        """Templating is what hides the one value that mattered."""
        records = [make_record(0, level=Level.ERROR, message="failed for id 918273")]
        report = render(scan(records), budget_tokens=None)
        assert "918273" in report.split("## 6.")[1]


class TestExport:
    def test_it_writes_one_file(self, tmp_path: Path) -> None:
        result = AiReportExporter().export(SpoolReader(MIXED).items(), tmp_path / "report.md")
        assert result.files == [result.destination]
        assert result.records == 5000
        assert result.destination.read_text(encoding="utf-8").startswith("# iOS log capture")

    def test_the_budget_is_configurable(self, tmp_path: Path) -> None:
        small = AiReportExporter(budget_tokens=1_000)
        large = AiReportExporter(budget_tokens=None)
        a = small.export(SpoolReader(ERRORS).items(), tmp_path / "a.md")
        b = large.export(SpoolReader(ERRORS).items(), tmp_path / "b.md")
        assert len(a.destination.read_text(encoding="utf-8")) < len(
            b.destination.read_text(encoding="utf-8")
        )

    def test_files_are_written_with_lf(self, tmp_path: Path) -> None:
        result = AiReportExporter().export([make_record(0)], tmp_path / "report.md")
        assert b"\r\n" not in result.destination.read_bytes()
