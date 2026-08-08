# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""A report that shrinks to fit a token budget, and says what it dropped.

A capture is far larger than any context window, so a model-facing report is
always a lossy summary. The only question is whether the loss is *declared*. A
report that quietly stops at the budget reads as complete, and a reader draws
conclusions from an absence that is an artefact of truncation rather than a fact
about the device. Every section here counts what it could not fit, and the last
section lists it.

The budget is spent in priority order rather than evenly. Errors come before
patterns and patterns before the verbatim excerpt, because a report that
describes the whole capture badly is more useful than one that describes the
first two minutes of it perfectly.

Prefer the agent bundle where the reader can run `grep`: it is not lossy at all.
This format is for handing a capture to something that can only be given text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ostrace.analysis.scan import ABSENT, MAX_TEMPLATES, ScanResult
from ostrace.exporters.base import ExportResult, escape, register
from ostrace.exporters.plaintext import line as plain_line
from ostrace.model import Record

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

    from ostrace.model import DeviceInfo, Gap

__all__ = ["DEFAULT_BUDGET_TOKENS", "AiReportExporter"]

#: Rough characters per token for English text with a lot of punctuation and
#: identifiers. Deliberately conservative: overshooting a context window costs
#: the reader the whole report, and undershooting costs a few patterns.
CHARS_PER_TOKEN = 3.6

#: What a caller gets without asking. Comfortably inside a small context window,
#: and `None` means "no limit" rather than "some default I did not choose".
DEFAULT_BUDGET_TOKENS = 30_000

#: How the budget left after the fixed header is divided. The remainder after
#: these two goes to the verbatim excerpt.
_ERRORS_SHARE = 0.45
_PATTERNS_SHARE = 0.75

#: Processes named individually before the rest are summarised as a count.
_PROCESS_ROWS = 25
_SUBSYSTEM_ROWS = 15


class AiReportExporter:
    """A templated, budgeted, self-declaring summary."""

    name = "ai-report"
    description = "A summary that shrinks to a token budget and states what it dropped"

    def __init__(self, budget_tokens: int | None = DEFAULT_BUDGET_TOKENS) -> None:
        self.budget_tokens = budget_tokens

    def export(
        self,
        items: Iterable[Record | Gap],
        destination: Path,
        *,
        device: DeviceInfo | None = None,
    ) -> ExportResult:
        destination.parent.mkdir(parents=True, exist_ok=True)

        scan = ScanResult()
        number = 0
        for item in items:
            if isinstance(item, Record):
                number += 1
                scan.add(item, number)
            else:
                scan.add_gap(item)

        text = render(scan, device, budget_tokens=self.budget_tokens)
        destination.write_text(text, encoding="utf-8", newline="\n")
        return ExportResult(destination=destination, files=[destination], scan=scan)


def render(
    scan: ScanResult,
    device: DeviceInfo | None = None,
    *,
    budget_tokens: int | None = DEFAULT_BUDGET_TOKENS,
) -> str:
    """Build the report. Separate from the exporter so it can be tested directly."""
    budget = None if budget_tokens is None else int(budget_tokens * CHARS_PER_TOKEN)
    dropped: list[str] = []

    head = "\n".join(_header(scan, device))
    spent = len(head)

    errors = "\n".join(
        _errors(scan, dropped, _share(budget, spent, _ERRORS_SHARE)),
    )
    spent += len(errors)

    patterns = "\n".join(
        _patterns(scan, dropped, _share(budget, spent, _PATTERNS_SHARE)),
    )
    spent += len(patterns)

    # What is left, less room for the closing section -- which must never be the
    # thing that gets dropped, since it is the part that declares the drops.
    remaining = None if budget is None else max(0, budget - spent - 2_000)
    excerpt = "\n".join(_excerpt(scan, dropped, remaining))

    return "\n".join([head, errors, patterns, excerpt, "\n".join(_omissions(scan, dropped))])


def _share(budget: int | None, spent: int, fraction: float) -> int | None:
    if budget is None:
        return None
    return max(0, int((budget - spent) * fraction))


def _header(scan: ScanResult, device: DeviceInfo | None) -> Iterator[str]:
    """The part that is never budgeted: what this is and how to read it.

    Unbudgeted on purpose. Every other section can be cut down, but a reader
    who cannot tell what `Error` means in an iOS log will misread whatever
    survives -- so the guidance is worth more than the rows it displaces.
    """
    yield from _identity(scan, device)
    yield from _guidance(scan)
    yield from _distribution(scan)


def _identity(scan: ScanResult, device: DeviceInfo | None) -> Iterator[str]:
    yield "# iOS log capture — analysis report"
    yield ""
    yield "## 1. What this is"
    yield ""
    yield "| | |"
    yield "| --- | --- |"
    if device is not None and device.udid:
        yield f"| Device | {device.label} |"
        yield f"| UDID | `{device.udid}` |"
    yield f"| Records | {scan.records:,} |"
    yield f"| At Error or Fault | {scan.errors:,} |"
    if scan.first is not None and scan.last is not None:
        yield f"| First record | {scan.first:%Y-%m-%d %H:%M:%S} (device local time) |"
        yield f"| Last record | {scan.last:%Y-%m-%d %H:%M:%S} |"
    yield f"| Distinct patterns | {len(scan.templates):,} |"
    if scan.gaps:
        yield f"| Gaps | {len(scan.gaps)} |"
    yield ""


def _guidance(scan: ScanResult) -> Iterator[str]:
    yield "## 2. How to read it"
    yield ""
    yield "iOS logs are extremely repetitive, so messages are **templated**:"
    yield "variable parts are replaced by `<N>` (integer), `<F>` (decimal),"
    yield "`<HEX>`, `<UUID>` and `<PATH>`, and messages that collapse to the same"
    yield "template are counted as one row."
    yield ""
    yield "- `[x1234]` means the pattern occurred 1,234 times."
    yield "- Levels in increasing severity: `Debug` < `Info` < `Notice` <"
    yield "  `User Action` < `Error` < `Fault`. That is the entire set iOS emits;"
    yield "  there is no `Warning` and no `Critical`."
    yield "- **`Error` does not mean something is wrong.** Routine retries, cache"
    yield "  misses and link telemetry are all logged at `Error`. The count is"
    yield "  what distinguishes a fault from normal behaviour."
    yield "- `<private>` is the device redacting its own logs before they left it."
    yield "  It was never available to this tool and cannot be recovered."
    yield "- Section 5 is verbatim; sections 3 and 4 are templated."
    yield ""
    if scan.gaps:
        yield "This capture has holes in it. Nothing can be concluded from the"
        yield "absence of an event across a gap:"
        yield ""
        for gap in scan.gaps[:10]:
            yield f"- {gap.start:%H:%M:%S} to {gap.end:%H:%M:%S} — {gap.reason}"
        yield ""


def _distribution(scan: ScanResult) -> Iterator[str]:
    yield "## 3. Shape of the capture"
    yield ""
    yield "| Level | Records | Share |"
    yield "| --- | ---: | ---: |"
    total = max(1, scan.records)
    for level in sorted(scan.levels, reverse=True):
        count = scan.levels[level]
        yield f"| {level.title} | {count:,} | {100.0 * count / total:.1f}% |"
    yield ""

    yield "| Process | Records | Share | Errors |"
    yield "| --- | ---: | ---: | ---: |"
    for name, count in scan.processes.most_common(_PROCESS_ROWS):
        errors = scan.process_errors.get(name, 0)
        yield f"| `{name}` | {count:,} | {100.0 * count / total:.1f}% | {errors:,} |"
    if len(scan.processes) > _PROCESS_ROWS:
        yield ""
        yield f"_{len(scan.processes) - _PROCESS_ROWS:,} further processes, all lower volume._"
    yield ""

    yield "| Subsystem | Records | Errors |"
    yield "| --- | ---: | ---: |"
    for name, count in scan.subsystems.most_common(_SUBSYSTEM_ROWS):
        label = name if name != ABSENT else "_(none)_"
        yield f"| `{label}` | {count:,} | {scan.subsystem_errors.get(name, 0):,} |"
    if len(scan.subsystems) > _SUBSYSTEM_ROWS:
        yield ""
        yield f"_{len(scan.subsystems) - _SUBSYSTEM_ROWS:,} further subsystems._"
    yield ""


def _errors(scan: ScanResult, dropped: list[str], budget: int | None) -> Iterator[str]:
    yield "## 4. Error patterns, most frequent first"
    yield ""
    top = scan.top_error_templates(limit=len(scan.templates) or 1)
    if not top:
        yield "_No records at `Error` or `Fault`._"
        yield ""
        return

    covered = sum(stats.count for _, stats in top)
    yield f"{len(top):,} distinct error patterns across {covered:,} records."
    yield ""
    yield "```log"
    spent = 0
    for index, ((level, process, subsystem, template), stats) in enumerate(top):
        entry = (
            f"[x{stats.count:,}] line {stats.first_line} {process} "
            f"<{level.title}> {subsystem} {escape(template)[:300]}"
        )
        if budget is not None and spent + len(entry) > budget:
            dropped.append(
                f"Section 4: {len(top) - index:,} of {len(top):,} error patterns "
                f"did not fit the budget; the most frequent are shown."
            )
            break
        yield entry
        spent += len(entry)
    yield "```"
    yield ""


def _patterns(scan: ScanResult, dropped: list[str], budget: int | None) -> Iterator[str]:
    yield "## 5. All patterns by volume"
    yield ""
    ordered = sorted(scan.templates.items(), key=lambda kv: -kv[1].count)
    if not ordered:
        yield "_Nothing to summarise._"
        yield ""
        return

    yield "The bulk of the capture. Each row is one template and its count."
    yield ""
    yield "```log"
    spent = 0
    # `shown` is the loop index at the point of breaking: the check happens
    # before the row is written, so index == rows already emitted.
    for shown, ((level, process, subsystem, template), stats) in enumerate(ordered):
        entry = (
            f"[x{stats.count:,}] line {stats.first_line} {process} "
            f"<{level.title}> {subsystem} {escape(template)[:300]}"
        )
        if budget is not None and spent + len(entry) > budget:
            dropped.append(
                f"Section 5: {len(ordered) - shown:,} of {len(ordered):,} patterns "
                f"did not fit the budget; the {shown:,} most frequent are shown."
            )
            break
        yield entry
        spent += len(entry)
    yield "```"
    if scan.templates_dropped:
        yield ""
        yield (
            f"_The distinct-pattern cap of {MAX_TEMPLATES:,} was reached, so "
            f"{scan.templates_dropped:,} records are not represented by any row "
            f"above. They are counted everywhere else._"
        )
    yield ""


def _excerpt(scan: ScanResult, dropped: list[str], budget: int | None) -> Iterator[str]:
    yield "## 6. Verbatim, around the first error"
    yield ""
    if not scan.excerpt:
        yield "_No errors, so there is nothing to centre a window on._"
        yield ""
        return

    yield "Untouched records either side of the earliest `Error` or `Fault`, so"
    yield "that the detail templating hides is still visible. The first error,"
    yield "not the most frequent: what follows it may be consequence."
    yield ""
    yield f"Starting at record {scan.excerpt_line:,}."
    yield ""
    yield "```log"
    spent = 0
    for index, record in enumerate(scan.excerpt):
        entry = plain_line(record)
        if budget is not None and spent + len(entry) > budget:
            dropped.append(
                f"Section 6: {len(scan.excerpt) - index:,} lines of the verbatim "
                f"excerpt did not fit the budget."
            )
            break
        yield entry
        spent += len(entry)
    yield "```"
    yield ""


def _omissions(scan: ScanResult, dropped: list[str]) -> Iterator[str]:
    yield "## 7. What this report leaves out"
    yield ""
    if dropped:
        for note in dropped:
            yield f"- {note}"
    else:
        yield "- Nothing was dropped for space. Every record is present, either"
        yield "  verbatim or counted under a pattern."
    yield (
        "- Templated rows have had their variable parts replaced, so individual "
        "values — the identifier, the path, the number — are not in this report. "
        "Export the same capture as an agent bundle to search the raw text."
    )
    if scan.gaps:
        yield (
            f"- {len(scan.gaps)} gap(s) in the capture itself, listed in section 2. "
            f"Those records were never received and are not recoverable."
        )
    yield "- The complete capture remains on disk; this is derived from it."
    yield ""


register(AiReportExporter())
