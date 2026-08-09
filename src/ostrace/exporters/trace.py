# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Verbatim windows around each anchor, for following causality.

Use this when the question is *why*, rather than *what* or *how often*. The AI
report tells you that a pattern fired 340 times; this tells you what else the
device was doing the first time it did.

Nothing here is templated and nothing is reordered, so the identifiers that let
you follow one object across a sequence are intact. The cost is coverage: only
the neighbourhoods of the anchors are present, and the report says how many
anchors it could not reach.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ostrace.analysis.scan import ScanResult
from ostrace.analysis.trace import (
    DEFAULT_AFTER,
    TracePolicy,
    TraceResult,
    is_error,
    trace,
)
from ostrace.exporters.base import ExportResult, register
from ostrace.exporters.plaintext import line as plain_line
from ostrace.model import Record

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from pathlib import Path

    from ostrace.analysis.trace import Window
    from ostrace.model import DeviceInfo, Gap

__all__ = ["TraceExporter", "render"]

#: Marks an anchor in the output. A leading character rather than a highlight,
#: so it survives being pasted anywhere and can be grepped for.
_ANCHOR = ">>"
_CONTEXT = "  "


class TraceExporter:
    """Chronological, verbatim windows around each anchor."""

    name = "trace"
    description = "Verbatim windows around each error, for following what led to it"
    suffix = "-trace.md"

    def __init__(
        self,
        *,
        anchor: Callable[[Record], bool] = is_error,
        policy: TracePolicy | None = None,
    ) -> None:
        self.anchor = anchor
        self.policy = policy if policy is not None else TracePolicy()

    def export(
        self,
        items: Iterable[Record | Gap],
        destination: Path,
        *,
        device: DeviceInfo | None = None,
    ) -> ExportResult:
        destination.parent.mkdir(parents=True, exist_ok=True)

        # One pass produces both: the trace is what gets written, and the scan
        # is what lets the header say how much of the capture it represents.
        # Walking twice would mean reading the session twice.
        scan = ScanResult()
        traced = trace(_counting(items, scan), anchor=self.anchor, policy=self.policy)

        destination.write_text(
            "\n".join(render(traced, scan, device)) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return ExportResult(destination=destination, files=[destination], scan=scan)


def _counting(items: Iterable[Record | Gap], scan: ScanResult) -> Iterator[Record | Gap]:
    """Fold each item into ``scan`` as it passes through to the tracer."""
    line = 0
    for item in items:
        if isinstance(item, Record):
            line += 1
            scan.add(item, line)
        else:
            scan.add_gap(item)
        yield item


def render(
    traced: TraceResult,
    scan: ScanResult,
    device: DeviceInfo | None = None,
) -> Iterator[str]:
    """The report, as lines."""
    yield "# iOS log capture — trace"
    yield ""
    if device is not None and device.udid:
        yield f"Device: {device.label}"
        yield ""

    yield f"{traced.records_scanned:,} records scanned, {traced.anchors_seen:,} anchors found,"
    yield f"{len(traced.windows):,} window(s) written."
    yield ""

    if traced.truncated:
        yield (
            f"**{traced.anchors_missed:,} anchors are not in this file.** The window "
            f"limit was reached, so tracing stopped opening new ones. What is here "
            f"is the earliest part of the capture, not a sample of all of it."
        )
        yield ""
    if scan.gaps:
        yield (
            f"**The capture has {len(scan.gaps)} gap(s).** A window spanning one has a "
            f"hole in it, and a sequence read across it is not a sequence."
        )
        yield ""

    if not traced.windows:
        yield "No anchors matched, so there is nothing to trace."
        yield ""
        return

    yield "Lines marked `>>` are the anchors. Everything else is context, in the"
    yield "order the device delivered it, with nothing templated or removed."
    yield ""

    for number, window in enumerate(traced.windows, start=1):
        yield from _window(number, window)


def _window(number: int, window: Window) -> Iterator[str]:
    anchors = window.anchor_records
    first = anchors[0] if anchors else window.records[0]
    last_line = window.first_line + len(window.records) - 1

    yield f"## Window {number} — {first.timestamp:%H:%M:%S}, {len(anchors)} anchor(s)"
    yield ""
    yield f"Records {window.first_line:,} to {last_line:,} of the capture."
    if window.truncated:
        yield ""
        yield (
            "This window hit the size limit, so it ends mid-sequence rather than "
            "where the interesting records stopped. Read on from the next line "
            "of the capture itself."
        )
    elif anchors and window.anchors[-1] + DEFAULT_AFTER >= len(window.records):
        # The other way a window ends early, and it said nothing at all: the
        # capture ran out. Silence there reads as "the device went quiet after
        # the error", which is the conclusion this format exists to prevent --
        # and it is the *last* window, which is the one a reader studies.
        after = len(window.records) - window.anchors[-1] - 1
        yield ""
        yield (
            f"The capture ends here, so this window carries {after:,} record(s) "
            f"after its last anchor rather than {DEFAULT_AFTER}. What follows is "
            f"unknown, not absent."
        )
    yield ""
    yield "```log"
    marked = set(window.anchors)
    for index, record in enumerate(window.records):
        prefix = _ANCHOR if index in marked else _CONTEXT
        yield f"{prefix} {plain_line(record)}"
    yield "```"
    yield ""


register(TraceExporter())
