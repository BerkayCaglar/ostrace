# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""What every exporter has in common.

An exporter turns a capture into something else: a directory to grep, a
document to read, a file to feed to another tool. They differ in almost
everything, so this is deliberately thin -- a name the CLI can accept, a
destination, and a result saying what was written.

The one thing they share and must not disagree on is how a record is rendered
onto a single line. That lives here, because it is the property the whole
agent-bundle format rests on: if a message can contain a newline, a grep hit
stops being a whole record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from ostrace.analysis.scan import ScanResult
    from ostrace.model import DeviceInfo, Gap, Record

__all__ = ["EXPORTERS", "ExportResult", "Exporter", "escape", "register"]


def escape(message: str) -> str:
    """Fold a message onto one physical line.

    Backslash first, so that a message containing a literal two-character
    ``\\n`` survives as ``\\\\n`` and stays distinguishable from a real newline.
    Doing it in any other order makes the escaping lossy in exactly the case
    someone reads the file to investigate.

    ``\\r\\n`` collapses to a single ``\\n`` rather than two, so a Windows-style
    line ending in a message does not read as a blank line.

    Part of the bundle contract -- see ``docs/formats/agent-bundle.md``.
    """
    return (
        message.replace("\\", "\\\\")
        .replace("\r\n", "\\n")
        .replace("\r", "\\n")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )


@dataclass(slots=True)
class ExportResult:
    """What an export produced.

    Carries the scan so a caller can report on the capture without walking it a
    second time -- the CLI prints a summary, and the GUI will want the same
    numbers for its progress dialog.
    """

    #: The directory or file to show the user. For a bundle this is the
    #: directory; for a single-file format, the file.
    destination: Path
    #: Everything written, so a caller can list or clean up precisely.
    files: list[Path] = field(default_factory=list)
    scan: ScanResult | None = None

    @property
    def records(self) -> int:
        return self.scan.records if self.scan is not None else 0


@runtime_checkable
class Exporter(Protocol):
    """Turns a capture into files on disk."""

    #: What ``--format`` accepts. Stable: it appears in scripts.
    name: str
    #: One line, for ``--help``.
    description: str
    #: Appended to the capture's name when the caller does not choose a
    #: destination -- ``-bundle`` for a directory, ``.md`` for a document. What
    #: an export is called is a property of the format; where it goes is
    #: ``paths.export_path``'s decision.
    suffix: str

    def export(
        self,
        items: Iterable[Record | Gap],
        destination: Path,
        *,
        device: DeviceInfo | None = None,
    ) -> ExportResult:
        """Write the capture to ``destination``.

        ``items`` is consumed once and may be a stream: an exporter that needs
        two passes must say so by materialising, not by iterating twice and
        silently producing an empty second half.

        ``device`` is what the capture came from, where that is known. A bare
        spool file has no metadata, so exporters must render something sensible
        without it rather than requiring it.
        """
        ...


#: Registered exporters by name. The CLI's ``--format`` choices come from here,
#: so registering one is all it takes to expose it.
EXPORTERS: dict[str, Exporter] = {}


def register(exporter: Exporter) -> Exporter:
    """Add an exporter to the registry, refusing to shadow an existing name.

    A silently replaced exporter would mean ``--format`` quietly doing
    something other than what the name has always meant.
    """
    if exporter.name in EXPORTERS:
        msg = f"an exporter named {exporter.name!r} is already registered"
        raise ValueError(msg)
    EXPORTERS[exporter.name] = exporter
    return exporter
