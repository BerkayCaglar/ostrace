# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The source protocol.

A source answers two questions: what device is this, and what records does it
produce. Nothing else. Keeping the surface this small is what makes a recorded
session substitutable for a live device in every test.

Anything one source can do and another cannot stays off the protocol:
**extras are constructor arguments and properties, never protocol members.**
A consumer takes a ``LogSource`` and cannot know which one it holds, so a
method only one side has is a method it must not call -- and one it can see is
one it eventually will. :class:`CaptureState` below is the worked example:
only the live source reports it, so it arrives through a callable handed in at
construction.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ostrace.model import Record

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from types import TracebackType
    from typing import Self

    from ostrace.model import DeviceInfo, Gap

__all__ = ["CaptureState", "LogSource", "SourceCloseMixin"]


class CaptureState(StrEnum):
    """What a source may say about its connection while the capture runs.

    Here rather than in ``sources.os_trace``, which is the only source that
    says either, because the *listener* is a window and this is the module a
    consumer holding a ``LogSource`` already imports.

    The reason this placement used to give was that importing from
    ``os_trace`` would pull pymobiledevice3 -- ninety distributions -- and make
    the window unimportable under ``-O``. Both are false, and measured:
    importing ``sources.os_trace`` pulls **no** pymobiledevice3 modules, because
    the library is imported inside ``_open_service``, and the ``-O`` guard
    refuses at *construction*, not at import.

    A ``StrEnum`` rather than two strings so the set is closed and a type
    checker can see it -- the next state, a logcat source's "waiting for
    device", is a member here instead of another loose literal. ``str`` at the
    same time because the value crosses a Qt ``Signal(str)``, which delivers a
    plain ``str`` on the far side; comparing that against a member still works,
    which is the whole reason for this base class rather than ``Enum``.
    """

    RECONNECTING = "reconnecting"
    STREAMING = "streaming"


@runtime_checkable
class LogSource(Protocol):
    """Something that yields records."""

    #: Short stable identifier, written into the session metadata so that an
    #: export can say which service produced the data. A session captured over
    #: the legacy relay contains only the notice tier and carries no subsystem
    #: on any record; a reader who cannot tell that from a reader looking at a
    #: quiet device will draw the wrong conclusion.
    name: str

    async def device_info(self) -> DeviceInfo:
        """Identify the device. May be called before iteration starts."""
        ...

    def stream(self) -> AsyncGenerator[Record | Gap, None]:
        """Yield records until the source is exhausted or closed.

        Yields :class:`~ostrace.model.Gap` as well as
        :class:`~ostrace.model.Record`, in stream order. A gap has a *position*
        -- it happened between these two records and not those two -- and
        reporting it through a side channel throws that away. The cost is an
        isinstance check in consumers that do not care, which is cheaper than
        the alternative of a log with an unplaceable hole in it.

        Live sources never exhaust. They end when cancelled, or when
        reconnection has been abandoned, at which point they raise
        :class:`~ostrace.errors.StreamInterruptedError`.

        **This may block indefinitely without yielding.** A quiet device
        produces nothing for long stretches -- measured here at up to forty
        seconds of complete silence -- so a caller that needs to stop on a
        timer must drive that from a separate task. Waiting for the next record
        in order to notice that time has passed is a hang, not a timeout.
        """
        ...

    def records(self) -> AsyncGenerator[Record, None]:
        """:meth:`stream` without the gap markers."""
        ...

    async def aclose(self) -> None:
        """Release the connection or file handle."""
        ...

    async def __aenter__(self) -> LogSource:
        """Every source is an async context manager.

        Declared on the protocol rather than left to implementations, because a
        consumer holding a ``LogSource`` writes ``async with`` without knowing
        which one it has -- and a replay fixture that did not support it would
        fail exactly where the test suite is meant to prove substitutability.
        """
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...


class SourceCloseMixin:
    """``__aenter__``/``__aexit__`` written once, in terms of ``aclose()``.

    Implementations inherit this instead of repeating the pair. A third source
    then gets the behaviour by construction rather than by remembering.
    """

    async def aclose(self) -> None:
        """Release whatever the source holds.

        Abstract on purpose. A default that quietly did nothing would give a
        future source a working ``async with`` that releases nothing, and the
        failure would only show up as sockets accumulating under load. A source
        with genuinely nothing to release says so explicitly.
        """
        raise NotImplementedError

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def records(self) -> AsyncGenerator[Record, None]:
        """Filter :meth:`stream` down to records.

        One implementation for every source: the predicate is identical and the
        only thing that differs is where the stream comes from.
        """
        async for item in self.stream():
            if isinstance(item, Record):
                yield item

    def stream(self) -> AsyncGenerator[Record | Gap, None]:  # pragma: no cover - overridden
        raise NotImplementedError
