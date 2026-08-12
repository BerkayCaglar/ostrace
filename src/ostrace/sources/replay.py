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

from ostrace.model import DeviceInfo
from ostrace.sources.base import SourceCloseMixin
from ostrace.storage.capture import Capture

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

_EPOCH = datetime.fromtimestamp(0, tz=UTC)


class ReplaySource(SourceCloseMixin):
    """Yield the records of a session directory or a bare spool file."""

    name = "replay"

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

        # A session directory and a bare spool differ in exactly one way: one
        # has metadata. Which of the two this is was decided here *and* in
        # `storage.capture`, in near-identical lines, which is the duplication
        # that class's own docstring says it exists to prevent -- so this asks
        # it instead of deciding again.
        self._capture = Capture(self.path)

    async def device_info(self) -> DeviceInfo:
        """The device the session came from, or a placeholder for a bare spool."""
        meta = self._capture.meta
        return meta.device if meta is not None else _UNKNOWN_DEVICE

    @property
    def started_at(self) -> datetime:
        """When the original capture began, or the epoch if unrecorded."""
        meta = self._capture.meta
        return meta.started_at if meta is not None else _EPOCH

    async def stream(self) -> AsyncGenerator[Record | Gap, None]:
        """Yield everything in the session -- records and gaps -- in order."""
        for item in self._capture.items():
            yield item

    @property
    def truncated(self) -> bool:
        """True when the spool has no gzip trailer -- still open, or killed.

        Meaningful only for a recorded session; a live source has no equivalent,
        which is why it is here rather than on the protocol.
        """
        return self._capture.truncated

    async def aclose(self) -> None:
        """Nothing to release: the reader opens the file per iteration."""
        return

    def __repr__(self) -> str:
        kind = "session" if self.path.is_dir() else "spool"
        return f"ReplaySource({kind}={self.path.name!r})"
