# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Capturing from a device while the window stays usable.

The device stream is async and it blocks -- measured, a quiet iPhone can say
nothing for forty seconds -- so it cannot run on the GUI thread under any
arrangement. It gets a thread with an event loop of its own, and records reach
the GUI through a `collections.deque`: the producer calls ``append``, the
`gui.pump.Pump` on the GUI thread calls ``popleft``, and both are atomic under
the GIL, so there is no lock and no signal per record.

**No Qt signal carries a record.** At the ~1,600 records a second this device
delivers, a signal per record is 1,600 queued cross-thread events a second and
a window that cannot keep up with a device that is merely idling. Signals here
are for lifecycle only -- started, failed, finished -- which happen once each.

The capture loop itself is `ostrace.capture.capture`, unchanged and shared with
the CLI. That matters more than it looks: it is the one place that knows a
device stream is two sockets and that both must be released, in order, on every
exit path including cancellation. A second loop written for the GUI would have
had to learn that again, expensively.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QThread, Signal

from ostrace.capture import capture
from ostrace.errors import OstraceError

if TYPE_CHECKING:
    from pathlib import Path

    from ostrace.gui.markers import Row
    from ostrace.sources.base import LogSource

__all__ = ["CaptureThread"]


class CaptureThread(QThread):
    """Run a capture on its own event loop, filling a queue."""

    #: The device answered. Carries a `DeviceInfo`.
    identified = Signal(object)
    #: The capture ended by itself. Carries a `CaptureResult`.
    completed = Signal(object)
    #: A message fit to show a user.
    failed = Signal(str)

    def __init__(self, source: LogSource, *, destination: Path | None = None) -> None:
        super().__init__()
        self.source = source
        self.destination = destination
        #: Written by this thread, drained by the GUI thread. Unbounded here on
        #: purpose: the bound belongs to whoever is reading, which knows
        #: whether the reader is paused. See `gui.pump`.
        self.queue: deque[Row] = deque()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[Any] | None = None

    def run(self) -> None:
        """The thread body. Everything here is off the GUI thread."""
        try:
            asyncio.run(self._capture())
        except asyncio.CancelledError:
            # Asked to stop. Not a failure, and not worth telling the user
            # about -- they are the one who asked.
            pass
        except OstraceError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # a thread that dies silently is worse than a broad except
            self.failed.emit(f"{type(exc).__name__}: {exc}")

    async def _capture(self) -> None:
        self._loop = asyncio.get_running_loop()
        device = await self.source.device_info()
        self.identified.emit(device)

        self._task = asyncio.ensure_future(
            capture(self.source, destination=self.destination, on_item=self.queue.append)
        )
        result = await self._task
        self.completed.emit(result)

    def stop(self) -> None:
        """Ask the capture to end, from the GUI thread.

        Cancellation is scheduled *onto the capture's own loop* rather than
        performed here: an `asyncio.Task` may only be touched from the thread
        running its loop, and reaching across would corrupt the very shutdown
        this is trying to perform cleanly.

        The capture's ``finally`` then finalises the session sidecar and
        releases the device -- the service connection first, then lockdown,
        because the service is what the generator is blocked reading.
        """
        loop, task = self._loop, self._task
        if loop is None or task is None:
            return
        # RuntimeError means the loop has already finished and closed: the
        # capture ended on its own before the user asked it to. That is the
        # ordinary case when a device is unplugged and Disconnect is then
        # pressed, and there is nothing left to cancel.
        #
        # Caught rather than pre-empted with `is_closed()`: the loop belongs to
        # another thread and can close between the question and the answer.
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(task.cancel)
