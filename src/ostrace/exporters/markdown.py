# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The capture as a document, for pasting into an issue or a message.

The distinction from the plain-text export is what surrounds the records: this
one says which device, over what span, how much of it, and what the columns
mean. A log excerpt sent to someone else without that provokes the same three
questions every time.

A word on the code fence, because the hazard is real and it turns out not to
apply. Device messages contain backticks -- one in this project's own fixture
does -- and a fence can normally be broken out of from inside. It cannot be
here: a closing fence must be a line of nothing but backticks, and every line in
the block begins with a timestamp. The block is therefore safe by construction,
which is why it can be written as a stream rather than buffered to size a fence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ostrace.analysis.scan import ScanResult
from ostrace.exporters.base import ExportResult, register
from ostrace.exporters.plaintext import gap_line, line
from ostrace.model import Record

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

    from ostrace.model import DeviceInfo, Gap

__all__ = ["MarkdownExporter"]

#: Busiest processes named in the summary.
_SUMMARY_ROWS = 6


class MarkdownExporter:
    """A readable document: a summary, then the records verbatim."""

    name = "markdown"
    description = "A document with a summary and the records verbatim"
    suffix = ".md"

    def export(
        self,
        items: Iterable[Record | Gap],
        destination: Path,
        *,
        device: DeviceInfo | None = None,
    ) -> ExportResult:
        destination.parent.mkdir(parents=True, exist_ok=True)
        scan = ScanResult()

        # The summary describes the records, so it cannot be written until they
        # have been counted -- and the records must not be held in memory to
        # make that possible. The body goes to a temporary file beside the
        # destination, and the two are joined once the numbers are known.
        body = destination.with_name(destination.name + ".part")
        try:
            with body.open("w", encoding="utf-8", newline="\n") as handle:
                number = 0
                for item in items:
                    if isinstance(item, Record):
                        number += 1
                        scan.add(item, number)
                        handle.write(line(item) + "\n")
                    else:
                        scan.add_gap(item)
                        handle.write(
                            gap_line(
                                f"{item.start:%H:%M:%S}",
                                f"{item.end:%H:%M:%S}",
                                item.reason,
                            )
                            + "\n"
                        )

            with (
                destination.open("w", encoding="utf-8", newline="\n") as out,
                body.open(encoding="utf-8") as rendered,
            ):
                out.write("\n".join(_preamble(scan, device)) + "\n")
                for chunk in rendered:
                    out.write(chunk)
                out.write("```\n")
        finally:
            body.unlink(missing_ok=True)

        return ExportResult(destination=destination, files=[destination], scan=scan)


def _preamble(scan: ScanResult, device: DeviceInfo | None) -> Iterator[str]:
    yield "# iOS log capture"
    yield ""
    yield "| | |"
    yield "| --- | --- |"
    if device is not None and device.udid:
        yield f"| Device | {device.label} |"
        yield f"| UDID | `{device.udid}` |"
    yield f"| Records | {scan.records:,} |"
    yield f"| At Error or Fault | {scan.errors:,} |"
    if scan.first is not None and scan.last is not None:
        yield f"| From | {scan.first:%Y-%m-%d %H:%M:%S} (device local time) |"
        yield f"| To | {scan.last:%Y-%m-%d %H:%M:%S} |"
    if scan.gaps:
        yield f"| Gaps | {len(scan.gaps)} — the capture has holes |"
    yield ""

    if scan.processes:
        top = ", ".join(
            f"`{name}` ({count:,})" for name, count in scan.processes.most_common(_SUMMARY_ROWS)
        )
        yield f"Busiest: {top}."
        yield ""

    yield "## Line format"
    yield ""
    yield "```"
    yield "HH:MM:SS.mmm  level  process[pid]  subsystem/category  message"
    yield "```"
    yield ""
    yield "Levels in increasing severity: `Debug` < `Info` < `Notice` <"
    yield "`User Action` < `Error` < `Fault`. That is the whole set iOS emits —"
    yield "there is no `Warning` and no `Critical`, whatever other tools report."
    yield "A parenthesised name in the process column is the library that emitted"
    yield "the record, not the process. `<private>` is the device redacting its"
    yield "own logs before they leave it, and cannot be recovered."
    yield ""
    if scan.gaps:
        yield "A `---- gap ----` line marks a stretch where the device was"
        yield "unreachable. Nothing can be concluded from an absence across one."
        yield ""
    yield "## Records"
    yield ""
    yield "```log"


register(MarkdownExporter())
