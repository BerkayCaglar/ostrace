# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""What an export could not tell you.

Every exporter in this package declares its own omissions, and this is the
sentence each of those omissions becomes. It lives here rather than in the CLI
because the graphical viewer has to say exactly the same things: two spellings
of "this capture has a gap in it" would eventually disagree about which one
mattered, and the whole point is that the reader is told the same truth
whichever way they asked.

Each note exists because, without it, an absence in the output means something
other than "the device did not do that" -- which is the conclusion a reader
reaches by default, and the one that sends them looking in the wrong place.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ostrace.exporters.base import ExportResult

__all__ = ["export_notes"]


def export_notes(
    result: ExportResult, *, truncated: bool, malformed: int = 0, running: bool = False
) -> list[str]:
    """Everything about this export a reader would otherwise assume away.

    ``running`` says the capture was still being recorded when this was
    written. It replaces the truncation note rather than joining it: both
    describe the same missing gzip trailer, and "the process was killed"
    alongside "it is still going" is two guesses where there is a known answer.
    An export taken this way is a snapshot, and the reader has to be told that
    the end of it is *when they pressed the button* rather than when the device
    stopped -- otherwise the last record reads as the last thing that happened.
    """
    notes: list[str] = []
    if running:
        notes.append(
            f"this is a snapshot of a capture that was still recording. It ends at "
            f"the {result.records:,} records written so far, which is where the file "
            f"had got to and not where the device stopped. The capture continues."
        )
    elif truncated:
        notes.append(
            "the capture has no gzip trailer -- it was still being written, the "
            "process was killed, or it is not a gzip file at all. Whatever decoded "
            "is complete; the tail may not be."
        )
    if malformed:
        # The reader counts these and, until this note existed, nothing read the
        # count -- so the one number saying "records are missing from this
        # export" was the only omission the package did not declare.
        notes.append(
            f"{malformed:,} line(s) in the capture could not be decoded and are "
            f"missing from this export."
        )
    scan = result.scan
    if scan is None:
        return notes
    if scan.gaps:
        notes.append(
            f"{len(scan.gaps)} gap(s) in the capture: the device was unreachable for "
            f"part of it, and nothing follows from an absence across one."
        )
    if scan.templates_dropped:
        notes.append(
            f"{scan.templates_dropped:,} records exceeded the distinct-pattern limit "
            f"and are not represented in the pattern statistics."
        )
    if scan.records == 0:
        notes.append("the capture contains no records.")
    return notes
