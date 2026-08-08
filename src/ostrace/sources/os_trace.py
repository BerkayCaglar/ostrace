# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The primary source: ``com.apple.os_trace_relay``.

This is the service Console.app uses. It carries the unified logging record
itself -- level, subsystem, category, thread id, the emitting binary and a
microsecond timestamp -- rather than a line of text, and it carries the DEBUG
and INFO tiers that the legacy relay never sends.

Measured on an ``iPhone18,2`` running iOS 26.5.2: 96.8% of records carry a
subsystem and category, and DEBUG plus INFO account for about seven records in
eight. See ``docs/research/log-sources-comparison.md``.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from ostrace.devices.discovery import open_lockdown, read_device_info
from ostrace.errors import OstraceError, StreamInterruptedError, translate
from ostrace.model import Gap, Level, Platform, Record

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from ostrace.model import DeviceInfo

__all__ = ["DEFAULT_STREAM_FLAGS", "OsTraceSource", "ReconnectPolicy"]

# PAYLOAD | HISTORICAL | CALLSTACK | DEBUG, which is also the library's default.
#
# HISTORICAL is kept deliberately, and this is worth stating because the obvious
# reasoning points the other way. It replays the device's backlog at connect,
# which for a live view sounds like noise to be switched off. Measured on iOS
# 26.5.2, switching it off does not trim the stream -- it starves it: the same
# device that delivers roughly 1,600 records a second with the flag delivered 65
# a second without it, in bursts separated by up to forty seconds of complete
# silence. Dropping DEBUG as well produced literally nothing in forty-five
# seconds. A viewer defaulting to "live only" would look broken.
DEFAULT_STREAM_FLAGS = 60

#: Apple's own values are not severity-ordered -- NOTICE is 0 and DEBUG is 2 --
#: so this mapping is not cosmetic. See :class:`ostrace.model.Level`.
_LEVELS: dict[str, Level] = {
    "DEBUG": Level.DEBUG,
    "INFO": Level.INFO,
    "NOTICE": Level.NOTICE,
    "USER_ACTION": Level.USER_ACTION,
    "ERROR": Level.ERROR,
    "FAULT": Level.FAULT,
}

#: How many records after a reconnect to check against the pre-drop tail.
_DEDUPE_WINDOW = 20_000


@dataclass(frozen=True, slots=True)
class ReconnectPolicy:
    """What to do when the device goes away mid-capture.

    Grouped rather than passed as loose keyword arguments because the three
    settings are only meaningful together: a delay and a retry count mean
    nothing when reconnection is off.
    """

    enabled: bool = True
    delay: float = 2.0
    #: Consecutive failed reconnection attempts before giving up. At the default
    #: delay that is a minute of trying, which covers a cable being reseated
    #: without hanging forever on a device that has genuinely gone.
    max_retries: int = 30

    @classmethod
    def disabled(cls) -> ReconnectPolicy:
        """Fail on the first outage. What tests and one-shot captures want."""
        return cls(enabled=False)


class OsTraceSource:
    """Stream records from a connected device."""

    name = "os_trace_relay"

    def __init__(
        self,
        udid: str | None = None,
        *,
        stream_flags: int = DEFAULT_STREAM_FLAGS,
        pid: int = -1,
        reconnect: ReconnectPolicy | None = None,
    ) -> None:
        self.udid = udid
        self.stream_flags = stream_flags
        self.pid = pid
        self.reconnect = reconnect if reconnect is not None else ReconnectPolicy()

        self._device: DeviceInfo | None = None
        self._last_seen: datetime | None = None
        # The session currently being streamed, so that a consumer stopping
        # early can tear it down deterministically. See aclose().
        self._active: Any | None = None
        # Bounded record of what arrived just before a drop, so that the
        # backlog HISTORICAL replays after reconnect can be recognised.
        self._recent: deque[tuple[Any, ...]] = deque(maxlen=_DEDUPE_WINDOW)
        self._recent_set: set[tuple[Any, ...]] = set()
        self._suppressing = 0

    async def device_info(self) -> DeviceInfo:
        """Identify the device, opening a short-lived session if needed."""
        if self._device is None:
            lockdown = await open_lockdown(self.udid)
            try:
                self._device = await read_device_info(lockdown)
            finally:
                # LockdownClient.close() is the async one; there is no aclose().
                # Suppressed because a socket that has already gone away is not
                # a reason to fail identifying the device we just identified.
                with contextlib.suppress(Exception):
                    await lockdown.close()
        return self._device

    async def records(self) -> AsyncGenerator[Record, None]:
        """Only the records, dropping gap markers."""
        async for item in self.stream():
            if isinstance(item, Record):
                yield item

    async def stream(self) -> AsyncGenerator[Record | Gap, None]:
        """Yield records, and a :class:`~ostrace.model.Gap` for each outage.

        Reconnection is ours to own: neither ``pymobiledevice3`` nor its CLI
        retries. Records the device emitted during an outage are unrecoverable,
        so the gap is reported rather than closed over.
        """
        device = await self.device_info()
        tzinfo = device.tzinfo
        pending_gap: tuple[datetime, str] | None = None
        retries = 0

        while True:
            try:
                lockdown = await open_lockdown(self.udid)
            except OstraceError as exc:
                retries += 1
                if not self.reconnect.enabled or retries > self.reconnect.max_retries:
                    raise
                await asyncio.sleep(self.reconnect.delay)
                if pending_gap is None:
                    pending_gap = (self._now(), str(exc.message))
                continue

            if pending_gap is not None:
                start, reason = pending_gap
                pending_gap = None
                # The device replays its backlog on every connect, so the first
                # stretch after an outage overlaps what we already have.
                self._suppressing = _DEDUPE_WINDOW
                yield Gap(start=start, end=self._now(), reason=reason)

            retries = 0
            try:
                async for record in self._stream_once(lockdown, tzinfo):
                    yield record
            except OstraceError as exc:
                if not self.reconnect.enabled or not isinstance(exc, StreamInterruptedError):
                    raise
                pending_gap = (self._last_seen or self._now(), exc.message)
                await asyncio.sleep(self.reconnect.delay)
            else:
                # A live stream does not end by itself. If it did, the device
                # went away quietly, which is the same outage in a politer form.
                if not self.reconnect.enabled:
                    return
                pending_gap = (self._last_seen or self._now(), "stream ended")
                await asyncio.sleep(self.reconnect.delay)

    async def _stream_once(
        self,
        lockdown: Any,  # noqa: ANN401 - LockdownClient, imported lazily
        tzinfo: Any,  # noqa: ANN401 - tzinfo
    ) -> AsyncGenerator[Record, None]:
        from pymobiledevice3.services.os_trace import OsTraceService  # noqa: PLC0415

        self._active = lockdown
        try:
            async with lockdown:
                service = OsTraceService(lockdown=lockdown)
                async for entry in service.syslog(
                    pid=self.pid,
                    stream_flags=self.stream_flags,
                ):
                    record = _to_record(entry, tzinfo)
                    if self._suppressing and self._is_replay(record):
                        self._suppressing -= 1
                        continue
                    self._suppressing = max(0, self._suppressing - 1)
                    self._remember(record)
                    self._last_seen = record.timestamp
                    yield record
        except asyncio.CancelledError:
            raise
        except OstraceError:
            raise
        except Exception as exc:
            raise translate(exc) from exc
        finally:
            self._active = None

    def _key(self, record: Record) -> tuple[Any, ...]:
        return (record.timestamp, record.pid, record.thread_id, record.message)

    def _remember(self, record: Record) -> None:
        key = self._key(record)
        if len(self._recent) == self._recent.maxlen:
            self._recent_set.discard(self._recent[0])
        self._recent.append(key)
        self._recent_set.add(key)

    def _is_replay(self, record: Record) -> bool:
        return self._key(record) in self._recent_set

    @staticmethod
    def _now() -> datetime:
        return datetime.now(tz=UTC)

    async def aclose(self) -> None:
        """Close the live session, if one is open.

        A consumer that stops iterating early -- a GUI stop button, a capture
        that reached its record limit -- leaves the stream generator suspended
        on a socket read. Closing the generator alone does not help: the
        ``GeneratorExit`` cannot be delivered until that read returns, so the
        finalisation is left pending and the socket stays open until the garbage
        collector happens to reach it. Starting and stopping a capture
        repeatedly then accumulates sockets.

        Closing the session from the outside makes the pending read fail, which
        unwinds the generator. Call this, or use the source as an async context
        manager, whenever iteration might stop early.
        """
        active, self._active = self._active, None
        if active is not None:
            with contextlib.suppress(Exception):
                await active.close()

    async def __aenter__(self) -> OsTraceSource:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()


def _to_record(entry: Any, tzinfo: Any) -> Record:  # noqa: ANN401 - SyslogEntry
    """Convert one ``SyslogEntry`` into a :class:`~ostrace.model.Record`.

    Two field names are worth being careful about, because they read backwards.
    ``entry.filename`` is the *process* executable; ``entry.image_name`` is the
    binary that emitted the record, which is usually a framework or plugin
    loaded into that process. They differ in roughly nine records out of ten,
    and mapping them the other way round attributes every plugin's output to
    whatever host process happened to load it.
    """
    process_path = entry.filename or ""
    label = entry.label
    timestamp = entry.timestamp

    return Record(
        timestamp=timestamp.replace(tzinfo=tzinfo) if timestamp.tzinfo is None else timestamp,
        level=_LEVELS.get(entry.level.name, Level.NOTICE),
        pid=entry.pid,
        process=PurePosixPath(process_path).name or str(entry.pid),
        process_path=process_path,
        subsystem=label.subsystem if label is not None else None,
        category=label.category if label is not None else None,
        thread_id=entry.thread_id,
        image_path=entry.image_name or None,
        message=entry.message or "",
        platform=Platform.IOS,
    )
