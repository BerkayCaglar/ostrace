# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""A directory an agent can investigate with ``grep`` and bounded line reads.

Everything here is chosen for tools rather than for a context window: plain
text rather than gzip, exactly one record per physical line, fixed
tab-separated columns so that every match is self-describing, and line-number
pointers so that "what was happening around this error" is a bounded read of a
known range instead of another search.

The format is a contract. See ``docs/formats/agent-bundle.md``; changing a
column there is a breaking change, and this module is what has to agree with it.
"""

from __future__ import annotations

import re
from contextlib import ExitStack
from typing import TYPE_CHECKING, TextIO

from ostrace.analysis.scan import ABSENT, ScanResult
from ostrace.exporters.base import ExportResult, escape, register
from ostrace.model import Record

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

    from ostrace.analysis.scan import TemplateKey, TemplateStats
    from ostrace.model import DeviceInfo, Gap

__all__ = ["AgentBundleExporter", "row"]

#: Every file in the bundle, on every platform. **Contract.**
_ENCODING = "utf-8"
_NEWLINE = "\n"

#: How much of the capture the generated CLAUDE.md is allowed to describe. The
#: file has to stay a constant size: a bundle of two million records must not
#: produce a longer one than a bundle of six thousand, or the documentation
#: stops being loadable exactly when the capture most needs explaining.
_DOC_ERROR_PATTERNS = 12
_DOC_ROWS = 8


def row(record: Record) -> str:
    """One record as the six contract columns, tab separated.

    Absent values are written as ``-`` rather than left empty: an empty field
    between two tabs is ambiguous to read and trivial to mis-split.
    """
    return "\t".join(
        (
            # Device local time. The timestamp carries the device's offset, so
            # formatting it without conversion is what makes the column mean
            # "what the clock on the phone said".
            record.timestamp.strftime("%Y-%m-%dT%H:%M:%S"),
            record.level.title,
            record.process_label,
            record.subsystem or ABSENT,
            record.category or ABSENT,
            escape(record.message),
        )
    )


class AgentBundleExporter:
    """Write the seven-file bundle."""

    name = "agent-bundle"
    description = "A directory of tab-separated text for grep-based investigation"
    suffix = "-bundle"

    def export(
        self,
        items: Iterable[Record | Gap],
        destination: Path,
        *,
        device: DeviceInfo | None = None,
    ) -> ExportResult:
        destination.mkdir(parents=True, exist_ok=True)
        scan = ScanResult()

        session_log = destination / "session.log"
        errors_log = destination / "errors.log"

        # Both data files are written in the same pass as the scan, because the
        # line numbers the scan records are line numbers *in session.log*.
        # Deriving them separately would mean two definitions of the same fact.
        with ExitStack() as stack:
            log = stack.enter_context(self._open(session_log))
            errors = stack.enter_context(self._open(errors_log))

            line = 0
            # Measured while writing, not estimated afterwards. The search
            # advice below divides a tool's 30,000-character output limit by
            # this, and it used to add a flat 60 to the *raw* message length --
            # understating a real record by around 20 characters, which put the
            # advertised match limit 11-22% above the truth. Erring high is the
            # unsafe direction: the whole note exists to stop a silent
            # truncation.
            written = 0
            for item in items:
                if not isinstance(item, Record):
                    scan.add_gap(item)
                    continue
                line += 1
                scan.add(item, line)
                rendered = row(item)
                log.write(rendered + "\n")
                written += len(rendered) + 1
                if item.is_error:
                    errors.write(f"{line}\t{rendered}\n")

        mean_line = written // line if line else 0
        files = [session_log, errors_log]
        files.append(self._write_patterns(destination, scan))
        files.append(
            self._write_counts(
                destination, "processes", "process", scan.processes, scan.process_errors
            )
        )
        files.append(
            self._write_counts(
                destination, "subsystems", "subsystem", scan.subsystems, scan.subsystem_errors
            )
        )
        files.append(self._write_timeline(destination, scan))
        files.append(self._write_gaps(destination, scan))
        files.append(self._write_documentation(destination, scan, device, mean_line))

        return ExportResult(destination=destination, files=files, scan=scan)

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------

    @staticmethod
    def _open(path: Path) -> TextIO:
        """Always UTF-8 with LF endings, including on Windows. **Contract.**"""
        return path.open("w", encoding=_ENCODING, newline=_NEWLINE)

    def _write_patterns(self, destination: Path, scan: ScanResult) -> Path:
        path = destination / "patterns.tsv"
        ordered: list[tuple[TemplateKey, TemplateStats]] = sorted(
            scan.templates.items(), key=lambda kv: -kv[1].count
        )
        with self._open(path) as handle:
            handle.write("count\tlevel\tprocess\tsubsystem\tfirst_line\ttemplate\n")
            for (level, process, subsystem, template), stats in ordered:
                handle.write(
                    f"{stats.count}\t{level.title}\t{process}\t{subsystem}\t"
                    f"{stats.first_line}\t{escape(template)}\n"
                )
        return path

    def _write_counts(
        self,
        destination: Path,
        stem: str,
        column: str,
        totals: dict[str, int],
        errors: dict[str, int],
    ) -> Path:
        """``processes.tsv`` and ``subsystems.tsv``: same shape, same question.

        The useful ratio is "this is 3% of the log and 60% of the errors", which
        needs both numbers side by side rather than two files to join.

        ``column`` is passed rather than derived from ``stem``: chopping the
        trailing letter off a plural gives ``subsystem`` and ``processe``, and
        the header is part of the contract.
        """
        path = destination / f"{stem}.tsv"
        with self._open(path) as handle:
            handle.write(f"count\terrors\t{column}\n")
            for name, count in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0])):
                handle.write(f"{count}\t{errors.get(name, 0)}\t{name}\n")
        return path

    def _write_timeline(self, destination: Path, scan: ScanResult) -> Path:
        path = destination / "timeline.tsv"
        with self._open(path) as handle:
            handle.write("minute\trecords\terrors\tfirst_line\n")
            for minute in sorted(scan.minutes):
                stats = scan.minutes[minute]
                # Minute-resolution ISO, not bare HH:MM: a capture that runs
                # past midnight would otherwise sort its second hour first.
                handle.write(
                    f"{minute.strftime('%Y-%m-%dT%H:%M')}\t{stats.records}\t"
                    f"{stats.errors}\t{stats.first_line}\n"
                )
        return path

    def _write_gaps(self, destination: Path, scan: ScanResult) -> Path:
        """Where the capture has holes, as data rather than as prose.

        Every other export states a gap inside the thing a reader reads: the
        text and markdown exporters draw a rule across the log, jsonl writes a
        `{"gap": true}` line, ai-report gives it a section. The bundle said it
        only in `CLAUDE.md` -- which is explicitly outside the format contract
        -- so `session.log`, `errors.log`, `timeline.tsv` and `patterns.tsv`
        all read straight across the hole, and every `grep` an agent runs is
        answered as though the device had simply been quiet.

        Its own file rather than a marker line in `session.log`, because that
        file's contract is one record per line and every recipe in the bundle
        depends on it. Always written, including with no gaps: a file that
        appears only on bad news cannot be told from a file nobody wrote --
        Wireshark bug 12005, which the status bar already answers for.
        """
        path = destination / "gaps.tsv"
        with self._open(path) as handle:
            handle.write("start\tend\tseconds\treason\n")
            for gap in scan.gaps:
                handle.write(
                    f"{gap.start.isoformat()}\t{gap.end.isoformat()}\t"
                    f"{gap.duration.total_seconds():.3f}\t{escape(gap.reason)}\n"
                )
        return path

    def _write_documentation(
        self,
        destination: Path,
        scan: ScanResult,
        device: DeviceInfo | None,
        mean_line: int,
    ) -> Path:
        # Named CLAUDE.md deliberately: Claude Code loads a CLAUDE.md found in a
        # subdirectory as soon as it reads a file there, so the column spec and
        # the traps arrive without anyone having to know to ask for them.
        path = destination / "CLAUDE.md"
        with self._open(path) as handle:
            handle.write("\n".join(_documentation(scan, device, mean_line)) + "\n")
        return path


def _inline_code(text: str) -> str:
    """Wrap arbitrary device output in a markdown code span that survives it.

    A log message is not markdown-safe. One in this project's own fixture is
    ``could not find `cpu-avg-limiter-input-w2r property`` -- a single stray
    backtick, which closes a one-backtick span early and renders the rest of
    the line as prose. CommonMark's rule is that a span fenced with *n*
    backticks may contain runs of fewer than *n*, so the fence is sized to the
    content; the padding space is required when the content itself begins or
    ends with a backtick.
    """
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    padding = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{padding}{text}{padding}{fence}"


def _documentation(scan: ScanResult, device: DeviceInfo | None, mean_line: int) -> Iterator[str]:
    """The generated CLAUDE.md, as lines.

    Bounded by construction: every list below has a fixed limit, so the length
    depends on the shape of the format and not on the size of the capture.
    """
    yield "# This capture"
    yield ""
    yield "Records from an iOS device, exported by `ostrace`. Read this before"
    yield "searching: the traps at the bottom are the ones that mislead people."
    yield ""

    yield "## What is here"
    yield ""
    yield "| File | Contents |"
    yield "| --- | --- |"
    yield "| `session.log` | Every record, one per line. The main data file. |"
    yield "| `errors.log` | Error and Fault only, prefixed by their `session.log` line. |"
    yield "| `patterns.tsv` | Distinct message templates with counts. |"
    yield "| `processes.tsv` | Records and errors per process. |"
    yield "| `subsystems.tsv` | Records and errors per subsystem. |"
    yield "| `timeline.tsv` | Per-minute counts, with a line to jump to. |"
    yield "| `gaps.tsv` | Where the capture has holes. Empty means none. |"
    yield "| `CLAUDE.md` | This file. |"
    yield ""

    yield "## Columns"
    yield ""
    yield "`session.log` is six tab-separated columns, no header:"
    yield ""
    yield "```"
    yield "timestamp<TAB>level<TAB>process[pid]<TAB>subsystem<TAB>category<TAB>message"
    yield "```"
    yield ""
    if scan.sample is not None:
        yield f"One real record from this capture, at line {scan.sample_line}:"
        yield ""
        yield "```"
        yield row(scan.sample)[:400]
        yield "```"
        yield ""
    yield "An absent value is written `-`, never an empty field. Messages are"
    yield "folded onto one line: newline becomes `\\n`, tab `\\t`, backslash `\\\\`."
    yield "**Every match is therefore a complete record**, carrying its own"
    yield "timestamp, level and process. That is the point of the format."
    yield ""

    yield from _statistics(scan, device)
    yield from _error_patterns(scan)
    yield from _recipes(scan, mean_line)
    yield from _traps()


def _statistics(scan: ScanResult, device: DeviceInfo | None) -> Iterator[str]:
    yield "## Size and shape"
    yield ""
    if device is not None and device.udid:
        yield f"- Device: {device.label}"
    yield f"- Records: {scan.records:,}, of which {scan.errors:,} at Error or Fault"
    if scan.first is not None and scan.last is not None:
        yield (f"- Span: {scan.first:%Y-%m-%d %H:%M:%S} to {scan.last:%H:%M:%S}, device local time")
    yield f"- Distinct message templates: {len(scan.templates):,}"
    yield f"- Average record length: about {scan.average_message_length} characters"
    if scan.templates_dropped:
        yield (
            f"- **{scan.templates_dropped:,} records are missing from "
            f"`patterns.tsv`**: the capture exceeded the distinct-template "
            f"limit. Every other file still counts them."
        )
    if scan.gaps:
        yield (
            f"- **{len(scan.gaps)} gap(s)**: the capture has holes where the "
            f"device was unreachable. Absence of an event across a gap proves "
            f"nothing."
        )
        for gap in scan.gaps[:_DOC_ROWS]:
            yield f"  - {gap.start:%H:%M:%S} to {gap.end:%H:%M:%S} ({gap.reason})"
    yield ""

    if scan.processes:
        yield "Busiest processes:"
        yield ""
        for name, count in scan.processes.most_common(_DOC_ROWS):
            errors = scan.process_errors.get(name, 0)
            share = f", {errors:,} at Error or above" if errors else ""
            yield f"- `{name}` — {count:,} records{share}"
        yield ""


def _error_patterns(scan: ScanResult) -> Iterator[str]:
    top = scan.top_error_templates(_DOC_ERROR_PATTERNS)
    if not top:
        yield "## Errors"
        yield ""
        yield "No records at Error or Fault in this capture."
        yield ""
        return

    yield "## The error patterns, most frequent first"
    yield ""
    yield "Frequency is what decides whether a finding is real. iOS logs a great"
    yield "deal of routine chatter at `Error`; something that fires hundreds of"
    yield "times is how the device normally behaves."
    yield ""
    for (level, process, _subsystem, _template), stats in top:
        excerpt = escape(stats.example)[:150]
        yield f"- **{stats.count:,}x** `{process}` {level.title}, first at line {stats.first_line}"
        yield f"  - {_inline_code(excerpt)}"
    yield ""


def _recipes(scan: ScanResult, mean_line: int) -> Iterator[str]:
    yield "## Searching"
    yield ""
    yield "**Count before you read.** Tool output is truncated at 30,000"
    yield "characters, silently. At this capture's average record length that is"
    yield f"reached at roughly {max(1, 30_000 // max(1, mean_line))} matches."
    yield ""
    yield "```bash"
    yield "# how many, before asking for any content"
    yield r"rg -c '\t(Error|Fault)\t' session.log"
    yield ""
    yield "# one subsystem across every process"
    yield r"rg -n '\tcom\.apple\.network\t' session.log | head -n 50"
    yield ""
    yield "# what dominates by volume"
    yield "head -n 30 patterns.tsv"
    yield ""
    yield "# context around a known line, without searching again"
    # A real range from this capture rather than a made-up one, so the example
    # works when pasted -- and stays in range for a fifty-record bundle.
    start = max(1, scan.sample_line - 20)
    yield f"sed -n '{start},{start + 60}p' session.log"
    yield "```"
    yield ""


def _traps() -> Iterator[str]:
    yield "## Traps"
    yield ""
    yield "- **`Error` does not mean something is wrong.** Link-quality"
    yield "  telemetry, cache misses and routine retries are all logged at"
    yield "  `Error`. Check `patterns.tsv` for the count before concluding."
    yield "- **The level names are not ordered as Apple numbers them.** iOS"
    yield "  reports `NOTICE=0, INFO=1, DEBUG=2, USER_ACTION=3, ERROR=16,"
    yield "  FAULT=17`, so anything comparing the raw values is wrong. The names"
    yield "  in this bundle are already ordered by severity."
    yield "- **`process[pid]` may carry a parenthesised library**, as in"
    yield "  `backboardd(SomePlugin)[70]`. That names the binary that emitted the"
    yield "  record, not the process. Attributing it to the host process blames"
    yield "  whatever happened to load the plugin."
    yield "- **Records are in arrival order, not sorted.** A device under load"
    yield "  emits slightly out of order — about 0.065% of records. Sorting would"
    yield "  hide that, so it is not done."
    yield "- **`<private>` is iOS redacting its own logs** before they leave the"
    yield "  device. It is not something this tool removed, and it cannot be"
    yield "  recovered."


register(AgentBundleExporter())
