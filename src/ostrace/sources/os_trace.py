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
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ostrace.devices.discovery import open_lockdown, read_device_info
from ostrace.errors import OstraceError, StreamInterruptedError, translate
from ostrace.model import Gap, Level, Platform, Record, basename
from ostrace.sources.base import SourceCloseMixin

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from datetime import tzinfo

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


def _guard_optimized_interpreter() -> None:
    """Refuse to stream under ``-O`` / ``PYTHONOPTIMIZE``.

    ``pymobiledevice3``'s stream loop is written as
    ``assert await self.service.recvall(1) == b"\\x02"``. Optimisation strips
    assert statements *including the await inside them*, which desynchronises
    the frame protocol and yields garbage records rather than an exception.
    Silent corruption is worse than a refusal to start.

    Checked here rather than at package import: it is a constraint of this one
    library, and offline work -- replaying a session, re-exporting a capture --
    neither touches it nor deserves to be blocked by it.
    """
    if sys.flags.optimize:  # pragma: no cover - depends on interpreter flags
        msg = "ostrace cannot stream from a device under -O / PYTHONOPTIMIZE"
        raise OstraceError(
            msg,
            hint=(
                "The device stream protocol depends on assert statements that "
                "optimisation removes. Unset PYTHONOPTIMIZE and run again."
            ),
        )


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


class OsTraceSource(SourceCloseMixin):
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
        _guard_optimized_interpreter()

        self.udid = udid
        self.stream_flags = stream_flags
        self.pid = pid
        self.reconnect = reconnect if reconnect is not None else ReconnectPolicy()

        self._device: DeviceInfo | None = None
        self._last_seen: datetime | None = None
        # The lockdown session currently held, whichever call opened it, so
        # that aclose() has exactly one thing to close. See aclose().
        self._active: Any | None = None
        # Insertion-ordered, doubling as the membership test: one structure
        # rather than a deque and a set hand-synchronised at the eviction point.
        # It records what arrived just before a drop, so that the backlog
        # HISTORICAL replays after a reconnect can be recognised.
        self._recent: dict[tuple[Any, ...], None] = {}
        self._suppressing = 0
        # Process names repeat: 38 distinct paths across 5,000 fixture records.
        # Deriving the basename per record measured at a third of the entire
        # per-record ingest cost.
        self._process_names: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _open(self) -> Any:  # noqa: ANN401 - LockdownClient, imported lazily
        """Open a lockdown session and register it as the resource we hold."""
        lockdown = await open_lockdown(self.udid)
        self._active = lockdown
        return lockdown

    async def _release(self) -> None:
        active, self._active = self._active, None
        if active is not None:
            # LockdownClient.close() is the async one; there is no aclose().
            # Suppressed because a socket that has already gone away is not a
            # reason to fail whatever we were doing with it.
            with contextlib.suppress(Exception):
                await active.close()

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
        unwinds the generator. Every path that opens a session registers it
        here, so this covers all of them. Use the source as an async context
        manager whenever iteration might stop early.
        """
        await self._release()

    async def device_info(self) -> DeviceInfo:
        """Identify the device, opening a short-lived session if needed."""
        if self._device is None:
            lockdown = await self._open()
            try:
                self._device = await read_device_info(lockdown)
            finally:
                await self._release()
        return self._device

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    async def stream(self) -> AsyncGenerator[Record | Gap, None]:
        """Yield records, and a :class:`~ostrace.model.Gap` for each outage.

        Reconnection is ours to own: neither ``pymobiledevice3`` nor its CLI
        retries. Records the device emitted during an outage are unrecoverable,
        so the gap is reported rather than closed over.
        """
        pending_gap: tuple[datetime, str] | None = None
        connected_once = False
        retries = 0

        while True:
            try:
                lockdown = await self._open()
            except OstraceError as exc:
                # The first connect never retries. There is no capture to
                # resume, and a device that was never trusted will not become
                # trusted by waiting -- the hint is the whole answer, and
                # sitting on it for a minute helps nobody.
                if not (connected_once and self.reconnect.enabled and exc.recoverable):
                    raise
                retries += 1
                if retries > self.reconnect.max_retries:
                    raise
                if pending_gap is None:
                    pending_gap = (self._last_seen or _now(), exc.message)
                await asyncio.sleep(self.reconnect.delay)
                continue

            connected_once = True
            retries = 0

            if pending_gap is not None:
                start, reason = pending_gap
                pending_gap = None
                # The device replays its backlog on every connect, so the first
                # stretch after an outage overlaps what we already have.
                self._suppressing = _DEDUPE_WINDOW
                yield Gap(start=start, end=_now(), reason=reason)

            tzinfo = (await self.device_info()).tzinfo
            try:
                async for record in self._stream_once(lockdown, tzinfo):
                    yield record
            except StreamInterruptedError as exc:
                if not self.reconnect.enabled:
                    raise
                reason = exc.message
            else:
                # A live stream does not end by itself. If it did, the device
                # went away quietly, which is the same outage in a politer form.
                if not self.reconnect.enabled:
                    return
                reason = "stream ended"

            pending_gap = (self._last_seen or _now(), reason)
            await asyncio.sleep(self.reconnect.delay)

    async def _stream_once(
        self,
        lockdown: Any,  # noqa: ANN401 - LockdownClient, imported lazily
        tz: tzinfo,
    ) -> AsyncGenerator[Record, None]:
        from pymobiledevice3.services.os_trace import OsTraceService  # noqa: PLC0415

        try:
            async with lockdown:
                service = OsTraceService(lockdown=lockdown)
                async for entry in service.syslog(
                    pid=self.pid,
                    stream_flags=self.stream_flags,
                ):
                    record = self._to_record(entry, tz)
                    if self._suppressing:
                        self._suppressing -= 1
                        if self._key(record) in self._recent:
                            continue
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

    # ------------------------------------------------------------------
    # Record construction
    # ------------------------------------------------------------------

    def _to_record(self, entry: Any, tz: tzinfo) -> Record:  # noqa: ANN401 - SyslogEntry
        """Convert one ``SyslogEntry`` into a :class:`~ostrace.model.Record`.

        Two field names are worth being careful about, because they read
        backwards. ``entry.filename`` is the *process* executable;
        ``entry.image_name`` is the binary that emitted the record, which is
        usually a framework or plugin loaded into that process. They differ in
        roughly nine records out of ten, and mapping them the other way round
        attributes every plugin's output to whatever host process happened to
        load it.
        """
        process_path = entry.filename or ""
        process = self._process_names.get(process_path)
        if process is None:
            process = sys.intern(basename(process_path) or str(entry.pid))
            self._process_names[process_path] = process

        label = entry.label
        timestamp = entry.timestamp

        return Record(
            timestamp=timestamp.replace(tzinfo=tz) if timestamp.tzinfo is None else timestamp,
            level=_LEVELS.get(entry.level.name, Level.NOTICE),
            pid=entry.pid,
            process=process,
            process_path=process_path,
            subsystem=label.subsystem if label is not None else None,
            category=label.category if label is not None else None,
            thread_id=entry.thread_id,
            image_path=entry.image_name or None,
            message=entry.message or "",
            platform=Platform.IOS,
        )

    # ------------------------------------------------------------------
    # Backlog suppression
    # ------------------------------------------------------------------

    @staticmethod
    def _key(record: Record) -> tuple[Any, ...]:
        return (record.timestamp, record.pid, record.thread_id, record.message)

    def _remember(self, record: Record) -> None:
        if not self.reconnect.enabled:
            # Nothing can ever consult the window, so do not pay to fill it.
            return
        recent = self._recent
        recent[self._key(record)] = None
        if len(recent) > _DEDUPE_WINDOW:
            del recent[next(iter(recent))]


def _now() -> datetime:
    return datetime.now(tz=UTC)
