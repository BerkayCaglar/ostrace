# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The capture as aligned columns, for reading down.

Nothing but records: no header, no metadata, no footer. This is the format for
piping into ``less`` or pasting a dozen lines into a message, and anything above
the first record is something the reader has to scroll past every time.

Alignment is why it exists at all -- the agent bundle is tab-separated and reads
badly in a terminal, and JSON reads worse. Where a value is too long for its
column the column wins: a ragged edge destroys the scanability the format is for,
and the untruncated value is available in every other export.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ostrace.analysis.scan import ABSENT, ScanResult, counted
from ostrace.exporters.base import ExportResult, escape, register
from ostrace.model import Record

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from ostrace.model import DeviceInfo, Gap

__all__ = ["PlaintextExporter", "line"]

#: ``User Action`` is eleven characters and the longest level there is.
_LEVEL_WIDTH = 11
#: Wide enough for ``backboardd(ColourSensorFilterPlugin)[70]``-shaped labels
#: without letting one outlier push every message off the right of the screen.
_PROCESS_WIDTH = 34


def _fit(text: str, width: int) -> str:
    """Pad to ``width``, or truncate with an ellipsis that says it truncated."""
    if len(text) <= width:
        return text.ljust(width)
    return text[: width - 1] + "…"


def _fit_process(label: str, width: int) -> str:
    """Like :func:`_fit`, but never at the cost of the pid.

    The label is ``process(library)[pid]`` and the pid is the last thing on it,
    so plain truncation throws away the field most often needed to correlate
    records -- ``duetexpertd(AppPredictionInternal…`` names a process the log
    contains eight of. Truncating in the middle keeps both ends.
    """
    if len(label) <= width:
        return label.ljust(width)
    pid = label[label.rindex("[") :] if label.endswith("]") and "[" in label else ""
    keep = width - len(pid) - 1
    if keep < 1:
        # A pid so long there is no room for a name. Vanishingly unlikely, and
        # the pid is still the more useful half.
        return _fit(label, width)
    return label[:keep] + "…" + pid


def line(record: Record) -> str:
    """One record as a single aligned line."""
    where = record.subsystem or ABSENT
    if record.category:
        where = f"{where}/{record.category}"
    return (
        # Milliseconds, not microseconds: at the measured 1,600 records a second
        # milliseconds already separate them, and six digits of noise per line
        # is what makes a wall of log unreadable.
        f"{record.timestamp:%H:%M:%S}.{record.timestamp.microsecond // 1000:03d}  "
        f"{_fit(record.level.title, _LEVEL_WIDTH)}  "
        f"{_fit_process(record.process_label, _PROCESS_WIDTH)}  "
        f"{_fit(where, 30)}  "
        f"{escape(record.message)}"
    )


def gap_line(start: str, end: str, reason: str) -> str:
    """A visible break, so a hole in the capture is not read as a quiet device."""
    return f"---- gap {start} to {end} ({reason}) " + "-" * 20


class PlaintextExporter:
    """Aligned columns, one record per line."""

    name = "text"
    description = "Aligned plain text, one record per line -- for reading in a terminal"
    suffix = ".log"

    def export(
        self,
        items: Iterable[Record | Gap],
        destination: Path,
        *,
        device: DeviceInfo | None = None,  # noqa: ARG002 - records only, by design
    ) -> ExportResult:
        destination.parent.mkdir(parents=True, exist_ok=True)
        scan = ScanResult()

        with destination.open("w", encoding="utf-8", newline="\n") as handle:
            for item in counted(items, scan):
                if isinstance(item, Record):
                    handle.write(line(item) + "\n")
                else:
                    handle.write(
                        gap_line(
                            f"{item.start:%H:%M:%S}",
                            f"{item.end:%H:%M:%S}",
                            item.reason,
                        )
                        + "\n"
                    )

        return ExportResult(destination=destination, files=[destination], scan=scan)


register(PlaintextExporter())
