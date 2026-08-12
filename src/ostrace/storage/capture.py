# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Opening a capture, whatever shape it arrived in.

A capture reaches a user in one of two forms: a session directory written by
`ostrace capture`, which carries a metadata sidecar, or a bare ``.jsonl.gz``
spool that somebody attached to a bug report. Both are legitimate, and the
offline path exists precisely for the second one.

Deciding which is which is *one* decision, so it lives in one place. It used to
be made inline by the `export` subcommand, and the graphical viewer would have
had to make it again -- at which point the two would eventually disagree about
something small, like whether a directory with no sidecar is an error.

Metadata is optional and its absence is never fatal. A capture without a
sidecar still has every record in it; refusing to open the records because
their description is missing would be the wrong trade for a diagnostic tool.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ostrace.errors import StorageError
from ostrace.storage.session import SessionReader
from ostrace.storage.spool import SpoolReader

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ostrace.model import DeviceInfo, Gap, Record
    from ostrace.storage.session import SessionMeta

__all__ = ["Capture", "open_capture"]


class Capture:
    """A capture on disk, read the same way whichever form it took."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        if not self.path.exists():
            msg = f"no capture at {self.path}"
            raise StorageError(msg, hint="Pass a session directory or a .jsonl.gz capture file.")

        self._reader: SessionReader | SpoolReader
        if self.path.is_dir():
            self._reader = SessionReader(self.path)
        else:
            self._reader = SpoolReader(self.path)

    @property
    def meta(self) -> SessionMeta | None:
        """What the capture says about itself, or ``None`` for a bare spool.

        The whole sidecar rather than a field at a time. Everything on it is
        needed by somebody -- the device by the title, the source by the
        exporters' caveat, the counts by a summary -- and adding an accessor
        per field is how one consumer ends up reaching past this class for the
        one nobody added yet.
        """
        if isinstance(self._reader, SessionReader):
            return self._reader.meta
        return None

    @property
    def device(self) -> DeviceInfo | None:
        """Which device this came from, when the capture says.

        ``None`` for a bare spool, which carries no sidecar. Consumers render
        without it rather than requiring it.
        """
        meta = self.meta
        return meta.device if meta is not None else None

    @property
    def truncated(self) -> bool:
        """True when the spool has no gzip trailer.

        Either still being written, or the process that was writing it was
        killed. Worth surfacing: the last records of a truncated capture are
        missing, and their absence means nothing about the device.
        """
        return self._reader.truncated

    @property
    def malformed(self) -> int:
        """Lines the reader could not decode, once it has read them.

        Zero until something has iterated: the readers count as they go, which
        is the only way a stream that recovers from damage can count at all. A
        consumer reporting this must therefore ask *after* it has finished
        reading, not before.
        """
        return self._reader.malformed

    def items(self) -> Iterator[Record | Gap]:
        """Records and gaps, in the order the device delivered them."""
        return self._reader.items()

    def __iter__(self) -> Iterator[Record | Gap]:
        return self.items()


def open_capture(path: Path | str) -> Capture:
    """Open a session directory or a bare capture file."""
    return Capture(Path(path))
