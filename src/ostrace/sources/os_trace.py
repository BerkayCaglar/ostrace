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
        # The lockdown session currently held, whichever call opened it. See
        # aclose().
        self._active: Any | None = None
        # The os_trace_relay service, while streaming. This is a *second*
        # socket: lockdown starts the service and hands back its own connection,
        # so closing the lockdown does not touch it. Measured on an iPhone18,2 --
        # after closing only the lockdown, the stream delivered a further 8,239
        # records in five seconds. See aclose().
        self._stream_service: Any | None = None
        # Set once aclose() has been called, so that the reconnect loop can tell
        # "the user stopped this" from "the device went away".
        self._closing = False
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

    async def _close(self, lockdown: Any) -> None:  # noqa: ANN401 - LockdownClient
        """Close one session, clearing ``_active`` only if it is that one.

        Closing by identity rather than by clearing the field wholesale: a
        short-lived session opened to read the device's identity must not
        deregister -- or close -- a streaming session opened elsewhere.
        """
        if self._active is lockdown:
            self._active = None
        # LockdownClient.close() is the async one; there is no aclose().
        # Suppressed because a socket that has already gone away is not a
        # reason to fail whatever we were doing with it.
        with contextlib.suppress(Exception):
            await lockdown.close()

    async def aclose(self) -> None:
        """Close whatever the source holds: the stream service, then lockdown.

        A consumer that stops iterating early -- a GUI stop button, a capture
        that reached its record limit -- leaves the stream generator suspended
        on a socket read. Closing the generator alone does not help: the
        ``GeneratorExit`` cannot be delivered until that read returns, so the
        finalisation is left pending and the socket stays open until the garbage
        collector happens to reach it. Starting and stopping a capture
        repeatedly then accumulates sockets.

        **There are two sockets, and closing the wrong one looks like success.**
        The lockdown session is what identity is read from and what starts the
        service; the records arrive over a separate connection that
        ``OsTraceService`` holds. An earlier version closed only the lockdown,
        returned in a millisecond, and left the stream running -- an
        ``iPhone18,2`` delivered a further 8,239 records in the five seconds
        after "closing". Nothing in the stubbed tests could see it: they replace
        ``_stream_once``, which is where the service socket lives.

        The service is closed first, because that is the read the generator is
        blocked on. Use the source as an async context manager whenever
        iteration might stop early.
        """
        self._closing = True

        service = self._stream_service
        if service is not None:
            self._stream_service = None
            # An already-dead connection is not a reason to fail a shutdown.
            with contextlib.suppress(Exception):
                await service.close()

        active = self._active
        if active is not None:
            await self._close(active)

    async def device_info(self) -> DeviceInfo:
        """Identify the device, opening a short-lived session if needed."""
        device = self._device
        if device is None:
            lockdown = await self._open()
            try:
                device = await self._identify(lockdown)
            finally:
                await self._close(lockdown)
        return device

    def _stopped(self) -> bool:
        """Whether ``aclose()`` has been called.

        Read through a call rather than as an attribute so that it is genuinely
        re-read each time. ``aclose()`` runs in another task, and a type checker
        narrowing the attribute after one test declares the next one dead code
        -- reasoning that is sound only in a world where nothing else is
        running, which is not the world a stop button lives in.
        """
        return self._closing

    async def _identify(self, lockdown: Any) -> DeviceInfo:  # noqa: ANN401 - LockdownClient
        """Read device identity from a session we already hold.

        Called with the streaming session rather than opening a second one: the
        values come from the dictionary the client already fetched during the
        handshake, so this costs nothing, and opening a second session used to
        deregister the first.

        Refreshed on every connect rather than cached once. A capture that
        reconnects may be reconnecting to a device whose UTC offset has moved --
        daylight saving, or a phone that travelled -- and stamping later records
        with the original offset makes them plausible and an hour wrong.
        """
        self._device = await read_device_info(lockdown)
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

        while True:
            try:
                lockdown = await self._connect(resuming=connected_once)
            except OstraceError as exc:
                if pending_gap is None:
                    raise
                # Reconnection was attempted and abandoned. The outage is the
                # more useful thing to report than the last attempt's error.
                raise StreamInterruptedError(pending_gap[1]) from exc

            if lockdown is None:
                # Stopped while reconnecting. Returning here is what stops the
                # loop from opening a fresh lockdown *and* a fresh relay for a
                # capture that has already been released.
                return

            connected_once = True

            # Identity comes from the session we just opened, and is refreshed
            # on every connect: free, because the values are already in hand,
            # and it keeps the UTC offset current across a long capture.
            device = await self._identify(lockdown)

            if pending_gap is not None:
                start, reason = pending_gap
                pending_gap = None
                # The device replays its backlog on every connect, so the first
                # stretch after an outage overlaps what we already have.
                self._suppressing = _DEDUPE_WINDOW
                yield Gap(start=start, end=self._device_now(), reason=reason)

            try:
                async for record in self._stream_once(lockdown, device.tzinfo):
                    # Backlog suppression is asked about here rather than inside
                    # _stream_once: it is reconnect policy, and _stream_once is
                    # only "what this one connection produced".
                    if self._is_replayed(record):
                        continue
                    self._remember(record)
                    self._last_seen = record.timestamp
                    yield record
            except OstraceError as exc:
                outage = self._outage_reason(exc)
            else:
                outage = self._outage_reason(None)
            if outage is None:
                return

            pending_gap = (self._last_seen or self._device_now(), outage)
            await asyncio.sleep(self.reconnect.delay)
            # Checked again after the wait: a stop that lands during the
            # reconnect delay must not be answered by reconnecting.
            if self._stopped():
                return

    def _outage_reason(self, exc: OstraceError | None) -> str | None:
        """What to write in the gap, or ``None`` to end the stream.

        ``exc`` is what the connection raised, or ``None`` when it simply ran
        out. Both arrive here because both mean the same thing: this connection
        is over, and the only question is whether another one should be opened.
        """
        # `aclose()` closes the socket out from under the pending read, so a
        # deliberate stop arrives looking exactly like an outage. It is not
        # one: reconnecting would be the opposite of what was asked, and
        # reporting an error would make every stop button look like a failure.
        if self._stopped() or not self.reconnect.enabled:
            return None
        if exc is None:
            # A live stream does not end by itself. If it did, the device went
            # away quietly, which is the same outage in a politer form.
            return "stream ended"
        # One question, asked the same way here as at connect time: is waiting
        # going to help? Matching on a specific exception type instead would
        # miss a recoverable outage that arrives wearing a different class.
        if not exc.recoverable:
            raise exc
        return exc.message

    async def _connect(self, *, resuming: bool) -> Any | None:  # noqa: ANN401 - LockdownClient
        """Open a session, retrying only when retrying could plausibly work.

        The first connect never retries: there is no capture to resume, and a
        device that was never trusted will not become trusted by waiting. The
        hint is the whole answer, and sitting on it for a minute helps nobody.

        A stop lands here too, and until it was checked for, it was ignored:
        `stream()` guards its own reconnect delay, but this loop sleeps up to
        thirty times of its own and looked at nothing. `aclose()` during an
        outage returned in a millisecond reporting success -- there was no
        service socket to close at that moment -- and this loop then went on to
        open a fresh lockdown *and* a fresh relay and deliver more records into
        a stream nobody was reading. The same failure the two-sockets rule
        exists for, arriving through the one path the rule did not cover.
        """
        retries = 0
        while True:
            if self._stopped():
                # `None` rather than an exception: a deliberate stop is not an
                # outage, and reporting one would make every stop during a
                # reconnect look like a failure.
                return None
            try:
                return await self._open()
            except OstraceError as exc:
                if not (resuming and self.reconnect.enabled and exc.recoverable):
                    raise
                retries += 1
                if retries > self.reconnect.max_retries:
                    raise
                await asyncio.sleep(self.reconnect.delay)

    async def _stream_once(
        self,
        lockdown: Any,  # noqa: ANN401 - LockdownClient, imported lazily
        tz: tzinfo,
    ) -> AsyncGenerator[Record, None]:
        from pymobiledevice3.services.os_trace import OsTraceService  # noqa: PLC0415

        try:
            # The service is entered as a context manager rather than merely
            # constructed: it owns a connection of its own, and leaving that to
            # the lockdown's teardown leaks it -- the lockdown does not know
            # about it.
            async with lockdown, OsTraceService(lockdown=lockdown) as service:
                self._stream_service = service
                async for entry in service.syslog(
                    pid=self.pid,
                    stream_flags=self.stream_flags,
                ):
                    yield self._to_record(entry, tz)
        except asyncio.CancelledError:
            raise
        except OstraceError:
            raise
        except Exception as exc:
            raise translate(exc) from exc
        finally:
            self._stream_service = None
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
            name = basename(process_path)
            if name:
                process = sys.intern(name)
                self._process_names[process_path] = process
            else:
                # A path that yields no name -- the kernel and a few others
                # arrive with an empty one. The fallback depends on the pid, so
                # it must NOT be cached against the path: doing so made the
                # first such pid name every later one.
                process = str(entry.pid)

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

    def _is_replayed(self, record: Record) -> bool:
        """Whether this record is backlog already delivered before an outage.

        Only ever true inside the window following a reconnect: the device
        replays its history on every connect, so the first stretch after an
        outage overlaps what the session already contains.
        """
        if not self._suppressing:
            return False
        self._suppressing -= 1
        return self._key(record) in self._recent

    def _remember(self, record: Record) -> None:
        if not self.reconnect.enabled:
            # Nothing can ever consult the window, so do not pay to fill it.
            return
        recent = self._recent
        recent[self._key(record)] = None
        if len(recent) > _DEDUPE_WINDOW:
            del recent[next(iter(recent))]

    def _device_now(self) -> datetime:
        """Now, on the device's clock.

        Gap boundaries must come from one clock: the start is a timestamp the
        device stamped, so taking the end from the host makes the duration
        wrong by the skew and negative whenever the device runs ahead.
        """
        device = self._device
        return device.now() if device is not None else datetime.now(tz=UTC)
