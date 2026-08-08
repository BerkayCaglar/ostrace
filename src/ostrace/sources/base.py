# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The source protocol.

A source answers two questions: what device is this, and what records does it
produce. Nothing else. Keeping the surface this small is what makes a recorded
session substitutable for a live device in every test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ostrace.model import Record

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from types import TracebackType
    from typing import Self

    from ostrace.model import DeviceInfo, Gap

__all__ = ["LogSource", "SourceCloseMixin"]


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

    async def aclose(self) -> None:  # pragma: no cover - overridden
        """Release whatever the source holds."""

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
