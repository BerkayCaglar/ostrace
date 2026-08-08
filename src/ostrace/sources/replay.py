# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Replay a recorded session as if it were a device.

This is what makes the project testable. A committed fixture goes in, records
come out, and nothing downstream can tell the difference from a live iPhone --
so the analysis and export layers are covered by CI on three operating systems
without any of them having a device attached.

It is also useful in its own right: re-exporting an old capture in a new format
is the same operation as capturing a new one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ostrace.errors import StorageError
from ostrace.model import DeviceInfo
from ostrace.storage.session import SessionReader
from ostrace.storage.spool import SpoolReader

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from ostrace.model import Gap, Record

__all__ = ["ReplaySource"]

_UNKNOWN_DEVICE = DeviceInfo(
    udid="",
    name="recorded session",
    product_type="unknown",
    product_version="unknown",
)


class ReplaySource:
    """Yield the records of a session directory or a bare spool file."""

    name = "replay"

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._session: SessionReader | None = None

        if self.path.is_dir():
            self._session = SessionReader(self.path)
            self._reader: SessionReader | SpoolReader = self._session
        elif self.path.is_file():
            self._reader = SpoolReader(self.path)
        else:
            msg = f"no session or spool at {self.path}"
            raise StorageError(msg)

    async def device_info(self) -> DeviceInfo:
        """The device the session came from, or a placeholder for a bare spool."""
        if self._session is not None and self._session.meta is not None:
            return self._session.meta.device
        return _UNKNOWN_DEVICE

    @property
    def started_at(self) -> datetime:
        """When the original capture began, or the epoch if unrecorded."""
        if self._session is not None and self._session.meta is not None:
            return self._session.meta.started_at
        return datetime.fromtimestamp(0, tz=UTC)

    async def stream(self) -> AsyncGenerator[Record | Gap, None]:
        """Yield everything in the session -- records and gaps -- in order."""
        for item in self._reader.items():
            yield item

    async def records(self) -> AsyncGenerator[Record, None]:
        """Yield only the records, skipping gap markers."""
        for record in self._reader.records():
            yield record

    def gaps(self) -> list[Gap]:
        return list(self._reader.gaps())

    @property
    def truncated(self) -> bool:
        """True when the spool has no gzip trailer -- still open, or killed."""
        return self._reader.truncated

    async def aclose(self) -> None:
        """Nothing to release: the readers open the file per iteration."""
        return

    def __repr__(self) -> str:
        kind = "session" if self._session is not None else "spool"
        return f"ReplaySource({kind}={self.path.name!r})"
