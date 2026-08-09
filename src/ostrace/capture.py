# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The capture loop: a source in, a session file out.

Kept out of ``cli.py`` because it is the thing a GUI needs too, and a stop
button has the same obligations as Ctrl-C.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ostrace.model import Gap, Record
from ostrace.paths import session_path
from ostrace.storage.session import SessionWriter

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

    from ostrace.sources.base import LogSource

__all__ = ["CaptureResult", "capture"]

#: How often to report progress, in records. Frequent enough to look alive on a
#: busy device, rare enough not to dominate the loop on one delivering 1,600 a
#: second.
_PROGRESS_EVERY = 250


@dataclass(frozen=True, slots=True)
class CaptureResult:
    path: Path
    records: int
    gaps: int
    started_at: datetime
    ended_at: datetime
    #: True when the capture stopped because it was asked to, rather than
    #: because the source gave up.
    stopped_early: bool = False

    @property
    def duration_seconds(self) -> float:
        return (self.ended_at - self.started_at).total_seconds()


async def capture(  # noqa: PLR0913 -- six knobs and a source, all keyword-only
    source: LogSource,
    *,
    destination: Path | None = None,
    duration: float | None = None,
    max_records: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    on_item: Callable[[Record | Gap], None] | None = None,
    on_open: Callable[[Path], None] | None = None,
) -> CaptureResult:
    """Stream from ``source`` into a session file until told to stop.

    ``duration`` is enforced with :func:`asyncio.timeout`, which fires from a
    timer rather than from record arrival. That distinction is the whole game:
    a quiet device produces nothing for tens of seconds, so a limit checked
    only when the next record shows up is not a limit, it is a hang.

    Both the session and the source are closed on every exit path, including
    cancellation, so the sidecar is always finalised and the device socket is
    always released.

    ``on_item`` receives every record and gap as it is written, in stream
    order. It exists so that a live view can show what is being captured
    without a second loop over the device: there is one stream, one place that
    understands its lifecycle, and one session file. It is called on whatever
    thread is running this coroutine, so an implementation that hands work to
    another thread should do the cheapest possible thing here.

    ``on_open`` is called once, with the session path, as soon as there is one.
    Only the result carries it otherwise -- and a cancelled capture has no
    result, which left a caller that stopped one with no way to find the file
    it had just finished writing. Where that file goes is `paths`' decision,
    and a caller working it out for itself would be making the decision twice.
    """
    device = await source.device_info()
    started_at = device.now()
    path = destination if destination is not None else session_path(device.name, _stamp(started_at))

    records = 0
    gaps = 0
    stopped_early = False

    writer = SessionWriter(
        path,
        device=device,
        source=source.name,
        started_at=started_at,
        flags={"max_records": max_records, "duration": duration},
    )
    if on_open is not None:
        # `writer.path` rather than `path`: the writer is what settles the
        # suffix, and it is what the result reports.
        on_open(writer.path)
    try:
        async with source, contextlib.aclosing(source.stream()) as stream:
            try:
                async with asyncio.timeout(duration):
                    async for item in stream:
                        if on_item is not None:
                            on_item(item)
                        if isinstance(item, Record):
                            writer.write(item)
                            records += 1
                            if on_progress is not None and records % _PROGRESS_EVERY == 0:
                                on_progress(records, gaps)
                        elif isinstance(item, Gap):
                            writer.write_gap(item)
                            gaps += 1
                        if max_records is not None and records >= max_records:
                            stopped_early = True
                            break
            except TimeoutError:
                stopped_early = True
    finally:
        ended_at = device.now()
        writer.close(ended_at=ended_at)

    if on_progress is not None:
        on_progress(records, gaps)

    return CaptureResult(
        path=writer.path,
        records=records,
        gaps=gaps,
        started_at=started_at,
        ended_at=ended_at,
        stopped_early=stopped_early,
    )


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y%m%d-%H%M%S")
