# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The agent bundle.

This format is a contract (``docs/formats/agent-bundle.md``), so most of these
tests are about shape rather than behaviour: a column that moves breaks bundles
already written to disk.

The property everything else rests on is that one record is one physical line
with exactly six fields. It is asserted here against the committed capture,
because a hand-written message would only contain the escapes someone thought
to include -- and the one that matters is the one nobody thought of.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from ostrace.exporters.agent_bundle import AgentBundleExporter, row
from ostrace.exporters.base import EXPORTERS, escape, register
from ostrace.model import Level, Record
from ostrace.storage.spool import SpoolReader
from tests.helpers import ERRORS, MIXED, make_gap, make_record

if TYPE_CHECKING:
    from pathlib import Path

    from ostrace.exporters.base import ExportResult

BUNDLE_FILES = {
    "CLAUDE.md",
    "session.log",
    "errors.log",
    "patterns.tsv",
    "processes.tsv",
    "subsystems.tsv",
    "timeline.tsv",
    "gaps.tsv",
}


@pytest.fixture(scope="module")
def bundle(tmp_path_factory: pytest.TempPathFactory) -> ExportResult:
    """A real capture, exported once for the whole module."""
    destination = tmp_path_factory.mktemp("bundles") / "mixed-bundle"
    return AgentBundleExporter().export(SpoolReader(MIXED).items(), destination)


def lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


#: The escape table of ``exporters.base.escape``, read the other way.
_UNESCAPED = {"\\\\": "\\", "\\n": "\n", "\\t": "\t"}


def unfold(line: str) -> str:
    r"""Read an escaped message back, the inverse ADR 0005 promises a test of.

    Test-local on purpose. Nothing in the package reads a bundle back in, and a
    published ``unfold`` would be another piece of surface to keep working
    rather than a check on the surface that exists.

    One left-to-right pass rather than three ``replace`` calls, because chained
    replaces are the bug this is looking for: ``.replace("\\n", "\n")`` applied
    to ``\\n`` -- an escaped backslash followed by an ``n`` -- turns a literal
    two-character sequence into a real newline, which is precisely the
    confusion the escaping order exists to prevent.
    """
    out: list[str] = []
    index = 0
    while index < len(line):
        pair = line[index : index + 2]
        if pair in _UNESCAPED:
            out.append(_UNESCAPED[pair])
            index += 2
            continue
        out.append(line[index])
        index += 1
    return "".join(out)


class TestEscaping:
    def test_backslash_is_escaped_before_newline(self) -> None:
        r"""A message containing a literal ``\n`` must stay distinguishable from
        one containing a real newline. Escaping in the other order makes them
        identical, and lossy in exactly the case someone is investigating."""
        assert escape("a\\nb") == "a\\\\nb"
        assert escape("a\nb") == "a\\nb"

    def test_windows_line_endings_collapse_to_one(self) -> None:
        assert escape("a\r\nb") == "a\\nb"
        assert escape("a\rb") == "a\\nb"

    def test_tabs_are_escaped_because_they_are_the_separator(self) -> None:
        assert escape("a\tb") == "a\\tb"

    def test_ordinary_text_is_untouched(self) -> None:
        assert escape("nothing to do here") == "nothing to do here"

    @pytest.mark.parametrize(
        "message",
        [
            "plain",
            "",
            "two\nlines",
            "tab\there",
            "both\ta\nmixture",
            "literal backslash-n: \\n not a newline",
            "backslash at the end \\",
            "\\\\n",
            "\\",
            "unicode: Berkay'ın iPhone'u — ölçüm",  # noqa: RUF001 - the point is non-ASCII
            "redacted <private> value",
            "   leading and trailing   ",
        ],
    )
    def test_folding_then_unfolding_gives_the_message_back(self, message: str) -> None:
        """ADR 0005 lists this round trip as its confirmation criterion and the
        format document states the property it rests on: a literal
        two-character ``\\n`` survives folding and stays distinguishable from a
        real newline. Until now it was argued from the four cases above rather
        than demonstrated.
        """
        assert unfold(escape(message)) == message

    @pytest.mark.parametrize("message", ["a\rb", "a\r\nb"])
    def test_a_carriage_return_is_the_one_thing_folding_does_not_give_back(
        self,
        message: str,
    ) -> None:
        r"""``\r``, ``\r\n`` and ``\n`` all fold to ``\n``, by contract: a
        Windows line ending inside a message must not read as a blank line, and
        that means three inputs share one output.

        So the round trip above is exact for everything except the form of the
        line ending, which is deliberately not carried. Stated here rather than
        left as a gap in the parametrisation, because a case that is missing
        looks the same as a case nobody thought of.
        """
        assert escape(message) == "a\\nb"
        assert unfold(escape(message)) == "a\nb"


class TestRow:
    def test_the_six_columns_in_order(self) -> None:
        record = make_record(0, message="hello")
        fields = row(record).split("\t")
        assert len(fields) == 6
        assert fields[0] == "2026-08-08T13:00:00"
        assert fields[1] == "Notice"
        # The synthetic record's image differs from its process, so the label
        # names the emitting binary too -- see the dedicated test below.
        assert fields[2] == "cloudd(CloudKit)[147]"
        assert fields[3] == "com.apple.cloudkit"
        assert fields[4] == "default"
        assert fields[5] == "hello"

    def test_absent_values_are_a_dash_not_an_empty_field(self) -> None:
        record = Record(
            timestamp=dt.datetime(2026, 8, 8, 13, 0, tzinfo=dt.UTC),
            level=Level.FAULT,
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
        fields = row(record).split("\t")
        assert fields[3] == "-"
        assert fields[4] == "-"
        assert "" not in fields

    def test_user_action_keeps_its_space(self) -> None:
        """The level set is exactly what iOS emits, and `User Action` is two
        words. A reader grepping for it needs the documented spelling."""
        assert row(make_record(0, level=Level.USER_ACTION)).split("\t")[1] == "User Action"

    def test_the_emitting_library_appears_in_parentheses(self) -> None:
        """What makes a record attributable to a plugin rather than to whatever
        process happened to load it."""
        record = make_record(0)
        assert record.image is not None
        assert row(record).split("\t")[2] == f"cloudd({record.image})[147]"


class TestShape:
    def test_every_promised_file_is_written(self, bundle: ExportResult) -> None:
        assert {p.name for p in bundle.destination.iterdir()} == BUNDLE_FILES
        assert {p.name for p in bundle.files} == BUNDLE_FILES

    def test_a_capture_with_nothing_in_it_still_writes_every_file(self, tmp_path: Path) -> None:
        """Every file is written on every export, the format document says,
        including with nothing to put in it -- a file that appears only on bad
        news cannot be told from a file nobody wrote.

        Zero records is also the case that reaches the arithmetic hardest: the
        mean line length divides by the record count.
        """
        result = AgentBundleExporter().export([], tmp_path / "nothing")

        assert {p.name for p in result.destination.iterdir()} == BUNDLE_FILES
        assert {p.name for p in result.files} == BUNDLE_FILES
        assert result.records == 0
        assert lines(result.destination / "session.log") == []

    def test_records_are_written_in_arrival_order_and_never_sorted(self, tmp_path: Path) -> None:
        """A device under load emits slightly out of order -- 0.065% of the
        records in the committed capture. Sorting would hide that, so the format
        document says it is not done and the bundle's own Traps section tells
        the reader so. Nothing asserted it.
        """
        result = AgentBundleExporter().export(
            [make_record(2), make_record(0), make_record(1)],
            tmp_path / "unsorted",
        )

        messages = [entry.split("\t")[5] for entry in lines(result.destination / "session.log")]
        assert messages == ["record number 2", "record number 0", "record number 1"]

    def test_one_record_is_one_line(self, bundle: ExportResult) -> None:
        assert len(lines(bundle.destination / "session.log")) == bundle.records
        assert bundle.records == 5000

    def test_every_line_has_exactly_six_fields(self, bundle: ExportResult) -> None:
        """The property the whole format rests on.

        An unescaped tab adds a column and an unescaped newline adds a line;
        either way a grep hit stops being a complete record, which is the one
        thing the format promises.
        """
        offenders = [
            (n, line[:120])
            for n, line in enumerate(lines(bundle.destination / "session.log"), start=1)
            if line.count("\t") != 5
        ]
        assert not offenders, f"{len(offenders)} malformed lines, first: {offenders[:2]}"

    def test_the_tsv_files_carry_their_headers(self, bundle: ExportResult) -> None:
        expected = {
            "patterns.tsv": "count\tlevel\tprocess\tsubsystem\tfirst_line\ttemplate",
            "processes.tsv": "count\terrors\tprocess",
            "subsystems.tsv": "count\terrors\tsubsystem",
            "timeline.tsv": "minute\trecords\terrors\tfirst_line",
        }
        for name, header in expected.items():
            assert lines(bundle.destination / name)[0] == header

    def test_session_log_has_no_header(self, bundle: ExportResult) -> None:
        """It is data, not a table: a header line would be a record that is not
        a record, and every line-number pointer would be off by one."""
        assert lines(bundle.destination / "session.log")[0].count("\t") == 5

    def test_files_are_written_with_lf_on_every_platform(self, bundle: ExportResult) -> None:
        raw = (bundle.destination / "session.log").read_bytes()
        assert b"\r\n" not in raw


class TestPointers:
    def test_an_error_line_number_points_at_that_record(self, bundle: ExportResult) -> None:
        """The pointer is the point: it turns "what was happening around this"
        into a bounded read rather than another search."""
        session = lines(bundle.destination / "session.log")
        error_lines = lines(bundle.destination / "errors.log")
        assert error_lines, "the mixed capture contains errors"

        for entry in error_lines[:200]:
            number, _, rest = entry.partition("\t")
            assert session[int(number) - 1] == rest

    def test_errors_log_has_seven_columns(self, bundle: ExportResult) -> None:
        for entry in lines(bundle.destination / "errors.log"):
            assert entry.count("\t") == 6

    def test_errors_log_holds_exactly_the_error_records(self, bundle: ExportResult) -> None:
        session = lines(bundle.destination / "session.log")
        expected = sum(1 for line in session if line.split("\t")[1] in {"Error", "Fault"})
        assert len(lines(bundle.destination / "errors.log")) == expected
        assert expected == bundle.scan.errors if bundle.scan else False

    def test_a_pattern_first_line_shows_that_pattern(self, bundle: ExportResult) -> None:
        session = lines(bundle.destination / "session.log")
        for entry in lines(bundle.destination / "patterns.tsv")[1:50]:
            _count, level, process, subsystem, first_line, _template = entry.split("\t", 5)
            fields = session[int(first_line) - 1].split("\t")
            assert fields[1] == level
            assert fields[2].split("(")[0].split("[")[0] == process
            assert fields[3] == subsystem

    def test_a_timeline_first_line_falls_in_that_minute(self, bundle: ExportResult) -> None:
        session = lines(bundle.destination / "session.log")
        for entry in lines(bundle.destination / "timeline.tsv")[1:]:
            minute, _records, _errors, first_line = entry.split("\t")
            assert session[int(first_line) - 1].startswith(minute)


class TestCountsReconcile:
    def test_process_counts_total_the_record_count(self, bundle: ExportResult) -> None:
        rows = [entry.split("\t") for entry in lines(bundle.destination / "processes.tsv")[1:]]
        assert sum(int(r[0]) for r in rows) == bundle.records
        assert sum(int(r[1]) for r in rows) == (bundle.scan.errors if bundle.scan else -1)

    def test_subsystem_counts_total_the_record_count(self, bundle: ExportResult) -> None:
        rows = [entry.split("\t") for entry in lines(bundle.destination / "subsystems.tsv")[1:]]
        assert sum(int(r[0]) for r in rows) == bundle.records

    def test_timeline_counts_total_the_record_count(self, bundle: ExportResult) -> None:
        rows = [entry.split("\t") for entry in lines(bundle.destination / "timeline.tsv")[1:]]
        assert sum(int(r[1]) for r in rows) == bundle.records

    def test_rows_are_ordered_most_frequent_first(self, bundle: ExportResult) -> None:
        for name in ("patterns.tsv", "processes.tsv", "subsystems.tsv"):
            counts = [int(entry.split("\t")[0]) for entry in lines(bundle.destination / name)[1:]]
            assert counts == sorted(counts, reverse=True)


class TestDocumentation:
    def test_it_stays_bounded_as_the_capture_grows(self, tmp_path: Path) -> None:
        """**Contract.** A bundle of two million records must not produce a
        longer CLAUDE.md than one of six thousand, or the documentation stops
        being loadable exactly when the capture most needs explaining.
        """
        small = AgentBundleExporter().export(
            list(SpoolReader(MIXED).items())[:50], tmp_path / "small"
        )
        large = AgentBundleExporter().export(SpoolReader(MIXED).items(), tmp_path / "large")

        small_doc = len(lines(small.destination / "CLAUDE.md"))
        large_doc = len(lines(large.destination / "CLAUDE.md"))
        assert large.records == 100 * small.records
        assert large_doc < small_doc * 2, (
            f"{small.records} records produced {small_doc} lines of documentation "
            f"and {large.records} produced {large_doc}"
        )

    def test_it_shows_a_real_record_from_this_capture(self, bundle: ExportResult) -> None:
        session = lines(bundle.destination / "session.log")
        doc = (bundle.destination / "CLAUDE.md").read_text(encoding="utf-8")
        assert bundle.scan is not None
        assert session[bundle.scan.sample_line - 1][:200] in doc

    def test_gaps_are_declared_because_absence_proves_nothing(self, tmp_path: Path) -> None:
        result = AgentBundleExporter().export(
            [make_record(0), make_gap(0), make_record(1)], tmp_path / "gappy"
        )
        doc = (result.destination / "CLAUDE.md").read_text(encoding="utf-8")
        assert "gap" in doc.lower()
        assert result.records == 2

    def test_a_gap_is_in_the_data_and_not_only_in_the_prose(self, tmp_path: Path) -> None:
        """`CLAUDE.md` is outside the format contract, and it was the only file
        that mentioned a gap.

        So `session.log`, `errors.log`, `timeline.tsv` and `patterns.tsv` all
        read straight across the hole, and every search an agent runs is
        answered as though the device had simply been quiet -- which is the one
        conclusion this project exists to prevent.
        """
        result = AgentBundleExporter().export(
            [make_record(0), make_gap(0), make_record(1)], tmp_path / "gappy"
        )

        rows = lines(result.destination / "gaps.tsv")
        assert rows[0] == "start\tend\tseconds\treason"
        assert len(rows) == 2
        assert make_gap(0).reason in rows[1]
        assert len(rows[1].split("\t")) == 4

    def test_a_gap_reason_is_escaped_like_any_other_prose(self, tmp_path: Path) -> None:
        """`gaps.tsv` is four tab-separated columns and the reason is free text
        for a person, so a tab in it adds a column and a newline adds a row --
        the same damage an unescaped message does to `session.log`, in the file
        a reader consults precisely when the capture is already unreliable.
        """
        gap = replace(make_gap(0), reason="lost the cable\tand waited\nfor it")
        result = AgentBundleExporter().export([make_record(0), gap], tmp_path / "awkward")

        rows = lines(result.destination / "gaps.tsv")
        assert len(rows) == 2, "the newline in the reason must not have started a row"
        assert rows[1].count("\t") == 3
        assert rows[1].endswith("lost the cable\\tand waited\\nfor it")

    def test_the_gap_file_is_written_even_with_no_gaps(self, bundle: ExportResult) -> None:
        """A file that appears only on bad news cannot be told from a file
        nobody wrote -- Wireshark bug 12005, which the status bar already
        answers for."""
        rows = lines(bundle.destination / "gaps.tsv")
        assert rows == ["start\tend\tseconds\treason"]

    def test_a_message_containing_a_backtick_does_not_break_the_markdown(
        self, tmp_path: Path
    ) -> None:
        """Device output is not markdown-safe, and the fixture proves it: one
        real record is ``could not find `cpu-avg-limiter-input-w2r property``.
        A one-backtick span around that closes early and the rest of the line
        renders as prose."""
        result = AgentBundleExporter().export(
            [make_record(0, level=Level.ERROR, message="could not find `a-property")],
            tmp_path / "ticks",
        )
        doc = (result.destination / "CLAUDE.md").read_text(encoding="utf-8")
        assert "``could not find `a-property``" in doc

    def test_the_context_recipe_stays_inside_the_capture(self, tmp_path: Path) -> None:
        """A pasted example that reads past the end of the file teaches the
        reader that the recipes are decorative."""
        result = AgentBundleExporter().export(
            list(SpoolReader(MIXED).items())[:40], tmp_path / "short"
        )
        doc = (result.destination / "CLAUDE.md").read_text(encoding="utf-8")
        recipe = re.search(r"sed -n '(\d+),(\d+)p'", doc)
        assert recipe is not None
        start = int(recipe.group(1))
        assert 1 <= start <= result.records

    def test_a_capture_with_no_errors_says_so(self, tmp_path: Path) -> None:
        result = AgentBundleExporter().export([make_record(0)], tmp_path / "quiet")
        doc = (result.destination / "CLAUDE.md").read_text(encoding="utf-8")
        assert "No records at Error or Fault" in doc
        assert lines(result.destination / "errors.log") == []


class TestRegistry:
    def test_the_bundle_exporter_is_registered(self) -> None:
        assert EXPORTERS["agent-bundle"].name == "agent-bundle"

    def test_a_duplicate_name_is_refused(self) -> None:
        """A silently replaced exporter means `--format` quietly doing something
        other than what the name has always meant."""
        with pytest.raises(ValueError, match="already registered"):
            register(AgentBundleExporter())


class TestTheErrorHeavyFixture:
    def test_it_survives_a_capture_that_is_mostly_errors(self, tmp_path: Path) -> None:
        """The other fixture, captured separately because error records exercise
        different fields -- and because the first bundle's error paths would
        otherwise be walked by a few dozen records out of five thousand."""
        result = AgentBundleExporter().export(SpoolReader(ERRORS).items(), tmp_path / "errors")
        session = lines(result.destination / "session.log")
        error_lines = lines(result.destination / "errors.log")

        assert len(session) == result.records
        assert len(error_lines) > result.records / 2
        for entry in error_lines[:200]:
            number, _, rest = entry.partition("\t")
            assert session[int(number) - 1] == rest
