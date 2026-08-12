# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Folding a capture into statistics.

The counting rules are ours, so synthetic records are the right input for
asserting them precisely -- a test about "errors are attributed to the right
process" needs a known number of errors, not a real one. The properties that
have to hold of *real* data, and the line-number contract the exporter depends
on, are asserted against the committed fixture at the end.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import pytest

from ostrace.analysis.scan import MAX_TEMPLATES, ScanResult, counted, scan
from ostrace.model import Gap, Level, Record
from ostrace.storage.spool import SpoolReader
from tests.helpers import MIXED, make_gap, make_record

if TYPE_CHECKING:
    from collections.abc import Iterator


class TestCounting:
    def test_an_empty_scan_reports_nothing_rather_than_dividing_by_zero(self) -> None:
        result = scan([])
        assert result.records == 0
        assert result.average_message_length == 0
        assert result.first is None

    def test_records_and_errors_are_counted_separately(self) -> None:
        result = scan(
            [
                make_record(0, level=Level.NOTICE),
                make_record(1, level=Level.ERROR),
                make_record(2, level=Level.FAULT),
            ]
        )
        assert result.records == 3
        assert result.errors == 2
        assert result.levels[Level.FAULT] == 1

    def test_user_action_is_not_an_error(self) -> None:
        """Apple's numbering puts USER_ACTION at 3 and ERROR at 16, so anything
        keyed off the raw value gets this wrong. Ours is ordered."""
        result = scan([make_record(0, level=Level.USER_ACTION)])
        assert result.errors == 0

    def test_errors_are_attributed_to_their_process_and_subsystem(self) -> None:
        result = scan(
            [
                make_record(0, level=Level.ERROR, process="cloudd"),
                make_record(1, level=Level.NOTICE, process="cloudd"),
                make_record(2, level=Level.NOTICE, process="dasd"),
            ]
        )
        assert result.processes["cloudd"] == 2
        assert result.process_errors["cloudd"] == 1
        assert result.process_errors["dasd"] == 0
        assert result.subsystem_errors["com.apple.cloudkit"] == 1

    def test_a_missing_subsystem_is_counted_under_a_dash(self) -> None:
        """So the file's counts still add up to the record count. How much of a
        capture carries no subsystem is itself worth knowing."""
        record = Record(
            timestamp=dt.datetime(2026, 8, 8, 13, 0, tzinfo=dt.UTC),
            level=Level.NOTICE,
            pid=0,
            process="kernel",
            process_path="",
            subsystem=None,
            category=None,
            thread_id=None,
            image_path=None,
            message="memory pressure",
            platform=make_record(0).platform,
        )
        result = scan([record])
        assert result.subsystems["-"] == 1
        assert sum(result.subsystems.values()) == result.records


class TestSpanAndTimeline:
    def test_the_span_is_the_extremes_not_the_ends(self) -> None:
        """A device under load emits slightly out of order, so the last record
        is not reliably the latest one. Taking the ends would report a span
        that is short, or negative."""
        early = dt.datetime(2026, 8, 8, 13, 0, 0, tzinfo=dt.UTC)
        late = dt.datetime(2026, 8, 8, 13, 5, 0, tzinfo=dt.UTC)
        result = ScanResult()
        result.add(_stamped(late), 1)
        result.add(_stamped(early), 2)
        assert result.first == early
        assert result.last == late

    def test_minutes_bucket_and_point_at_their_first_line(self) -> None:
        base = dt.datetime(2026, 8, 8, 13, 0, 0, tzinfo=dt.UTC)
        result = ScanResult()
        result.add(_stamped(base), 1)
        result.add(_stamped(base + dt.timedelta(seconds=30)), 2)
        result.add(_stamped(base + dt.timedelta(minutes=1), level=Level.ERROR), 3)

        first, second = sorted(result.minutes)
        assert result.minutes[first].records == 2
        assert result.minutes[first].errors == 0
        assert result.minutes[first].first_line == 1
        assert result.minutes[second].errors == 1
        assert result.minutes[second].first_line == 3


class TestTemplates:
    def test_messages_differing_only_in_a_number_are_one_template(self) -> None:
        result = scan(
            [
                make_record(0, message="fetched 214 rows"),
                make_record(1, message="fetched 9271 rows"),
            ]
        )
        assert len(result.templates) == 1
        stats = next(iter(result.templates.values()))
        assert stats.count == 2
        assert stats.first_line == 1
        # The example is a real message, not the template.
        assert stats.example == "fetched 214 rows"

    def test_the_same_message_from_two_processes_stays_two_templates(self) -> None:
        """The key carries process, level and subsystem. "who said it" is most
        of what makes a repeated line meaningful."""
        result = scan(
            [
                make_record(0, message="timed out", process="cloudd"),
                make_record(1, message="timed out", process="dasd"),
            ]
        )
        assert len(result.templates) == 2

    def test_reaching_the_cap_counts_what_it_dropped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Silent truncation reads as "this is everything". It is not.

        The cap is lowered rather than met: building fifty thousand distinct
        templates would test the machine, and the messages would have to avoid
        every substitution pattern to stay distinct, which makes them nothing
        like the data.
        """
        monkeypatch.setattr("ostrace.analysis.scan.MAX_TEMPLATES", 3)
        result = ScanResult()
        for i, word in enumerate(["alpha", "bravo", "charlie", "delta", "echo"]):
            result.add(make_record(i, message=word), i + 1)

        assert len(result.templates) == 3
        assert result.templates_dropped == 2
        # Everything else still counts every record: only the template is lost.
        assert result.records == 5
        assert result.processes["cloudd"] == 5

    def test_the_real_cap_is_far_above_what_a_capture_produces(self) -> None:
        """A cap that ordinary use reaches is a bug, not a bound. The committed
        fixture folds 5,000 records into fewer than 1,500 templates."""
        assert MAX_TEMPLATES > 10_000

    def test_top_error_templates_are_ordered_by_frequency(self) -> None:
        """Frequency, not severity: iOS logs routine chatter at Error, so how
        often a thing normally happens is what decides whether it matters."""
        records = [make_record(i, level=Level.ERROR, message="common") for i in range(5)]
        records += [make_record(9, level=Level.FAULT, message="rare")]
        records += [make_record(10, level=Level.NOTICE, message="noise")]
        result = scan(records)

        top = result.top_error_templates()
        assert [stats.count for _, stats in top] == [5, 1]
        assert all(key[0] >= Level.ERROR for key, _ in top)


class TestSample:
    def test_an_error_is_preferred_over_the_first_record(self) -> None:
        result = scan(
            [
                make_record(0, level=Level.NOTICE, message="ordinary"),
                make_record(1, level=Level.ERROR, message="the interesting one"),
                make_record(2, level=Level.FAULT, message="a later one"),
            ]
        )
        assert result.sample is not None
        assert result.sample.message == "the interesting one"
        assert result.sample_line == 2

    def test_without_an_error_the_first_record_is_used(self) -> None:
        result = scan([make_record(0, message="only this")])
        assert result.sample is not None
        assert result.sample.message == "only this"
        assert result.sample_line == 1


class TestGaps:
    def test_a_gap_is_kept_but_takes_no_line_number(self) -> None:
        """`session.log` holds records only. Numbering a gap would put every
        pointer after the first outage one line out of step."""
        result = scan([make_record(0), make_gap(0), make_record(1)])
        assert result.records == 2
        assert len(result.gaps) == 1
        assert result.templates[next(iter(result.templates))].first_line == 1
        lines = {stats.first_line for stats in result.templates.values()}
        assert lines == {1, 2}


@pytest.fixture(scope="module")
def fixture_scan() -> ScanResult:
    """A real capture, folded once for the whole module."""
    return scan(SpoolReader(MIXED).items())


class TestAgainstTheFixture:
    def test_it_folds_a_real_capture(self, fixture_scan: ScanResult) -> None:
        assert fixture_scan.records == 5000
        assert fixture_scan.templates_dropped == 0
        assert len(fixture_scan.templates) < fixture_scan.records

    def test_every_record_lands_in_exactly_one_minute_bucket(
        self, fixture_scan: ScanResult
    ) -> None:
        assert sum(m.records for m in fixture_scan.minutes.values()) == fixture_scan.records
        assert sum(m.errors for m in fixture_scan.minutes.values()) == fixture_scan.errors

    def test_the_counters_reconcile_with_the_record_count(self, fixture_scan: ScanResult) -> None:
        """Every record has exactly one process, one subsystem and one level, so
        each counter has to total the same number. A mismatch means a record was
        counted twice or dropped."""
        assert sum(fixture_scan.processes.values()) == fixture_scan.records
        assert sum(fixture_scan.subsystems.values()) == fixture_scan.records
        assert sum(fixture_scan.levels.values()) == fixture_scan.records

    def test_error_counts_never_exceed_total_counts(self, fixture_scan: ScanResult) -> None:
        for name, errors in fixture_scan.process_errors.items():
            assert errors <= fixture_scan.processes[name]
        assert sum(fixture_scan.process_errors.values()) == fixture_scan.errors

    def test_the_structured_tiers_are_present(self, fixture_scan: ScanResult) -> None:
        """Guards the reason this source was chosen at all: the legacy relay
        delivers essentially only NOTICE and no subsystem."""
        assert fixture_scan.levels[Level.DEBUG] or fixture_scan.levels[Level.INFO]
        with_subsystem = fixture_scan.records - fixture_scan.subsystems["-"]
        assert with_subsystem / fixture_scan.records > 0.8


def _stamped(when: dt.datetime, *, level: Level = Level.NOTICE) -> Record:
    base = make_record(0, level=level)
    return Record(
        timestamp=when,
        level=base.level,
        pid=base.pid,
        process=base.process,
        process_path=base.process_path,
        subsystem=base.subsystem,
        category=base.category,
        thread_id=base.thread_id,
        image_path=base.image_path,
        message=base.message,
        platform=base.platform,
    )


class TestCounted:
    """The walk five exporters used to write out for themselves.

    Six of them kept a counter, incremented it for records only and called
    `add` or `add_gap` -- the same eight lines apiece, and the counter is the
    line number that makes `errors.log`'s pointers mean anything.
    """

    def test_it_numbers_records_and_not_gaps(self) -> None:
        """A gap occupies no line in the formats that number their lines, so
        the record after one takes the next number rather than skipping it."""
        result = ScanResult()
        items: list[Record | Gap] = [make_record(0), make_gap(0), make_record(1)]

        list(counted(items, result))

        assert result.records == 2
        assert len(result.gaps) == 1

    def test_the_line_a_record_took_is_the_count_after_it(self) -> None:
        """Which is what lets the one caller that needs the number read it off
        the scan instead of being handed a tuple per record."""
        result = ScanResult()
        seen: list[int] = []

        for item in counted([make_record(index) for index in range(5)], result):
            assert isinstance(item, Record)
            seen.append(result.records)

        assert seen == [1, 2, 3, 4, 5]

    def test_everything_passes_through_in_order(self) -> None:
        """It folds on the way past; it does not filter, reorder or hold."""
        items: list[Record | Gap] = [make_record(0), make_gap(0), make_record(1)]

        assert list(counted(items, ScanResult())) == items

    def test_it_does_not_materialise_its_input(self) -> None:
        """An export may be handed a stream and `items` is consumed once, which
        is the rule `exporters.base` states."""
        result = ScanResult()
        taken = 0

        def source() -> Iterator[Record | Gap]:
            nonlocal taken
            for index in range(100):
                taken += 1
                yield make_record(index)

        first = next(iter(counted(source(), result)))

        assert isinstance(first, Record)
        assert taken == 1, "the whole stream was pulled to yield one item"
