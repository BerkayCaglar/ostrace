# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The live source's control flow, without a device.

`pymobiledevice3` is replaced at the three seams the source uses -- opening a
lockdown session, reading device identity, and building the relay service --
so the reconnect loop, the gap bookkeeping and the session lifecycle are all
exercised in CI. The record *mapping* is covered against real captures in
`test_sources_replay.py`; this file is about what happens around it.

The third seam is recent and it is the point of this file's design. Everything
here used to replace `_stream_once` wholesale, and that method is where the
second socket is acquired, recorded and released -- so socket ownership was
structurally invisible to every test in it. Measured: deleting the
`_stream_service` binding, and swapping the `async with` operands so the
lockdown closes before the service, each left all 520 tests green. Scripting
the *service* instead runs the real block, and both mutations now fail.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import types
from typing import TYPE_CHECKING, Any

import pytest

from ostrace.errors import (
    DeviceNotPairedError,
    NoDeviceFoundError,
    StreamInterruptedError,
    UsbmuxUnavailableError,
    translate,
)
from ostrace.model import DeviceInfo, Gap, Level, Platform, Record
from ostrace.sources import os_trace
from ostrace.sources.base import CaptureState
from ostrace.sources.os_trace import OsTraceSource, ReconnectPolicy

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

DEVICE_OFFSET = dt.timedelta(hours=3)
SKEW = dt.timedelta(seconds=10)


class FakeLockdown:
    """The session, and the record of what was entered and left around it.

    ``events`` is shared with the service opened from this lockdown, because
    the order the two are released in is the thing worth asserting and neither
    object can see it alone.
    """

    def __init__(self, index: int) -> None:
        self.index = index
        self.closed = False
        self.events: list[str] = []

    async def close(self) -> None:
        self.closed = True

    async def __aenter__(self) -> FakeLockdown:
        self.events.append("lockdown in")
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.events.append("lockdown out")


class FakeService:
    """The ``os_trace_relay`` connection: the second socket, scripted.

    Its ``syslog()`` yields what the device would have sent, so the source's
    own mapper turns it back into the records a test asked for -- pinned by
    ``test_the_scripted_entries_map_back_to_the_records_they_came_from``.
    """

    def __init__(self, entries: list[Any], events: list[str]) -> None:
        self._entries = entries
        self.events = events
        self.closed = False

    async def __aenter__(self) -> FakeService:
        self.events.append("service in")
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.events.append("service out")

    async def close(self) -> None:
        self.closed = True

    async def syslog(self, *, pid: int, stream_flags: int) -> AsyncGenerator[Any, None]:
        del pid, stream_flags
        for item in self._entries:
            if isinstance(item, BaseException):
                raise item
            yield item


@pytest.fixture
def seam(monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    """Replace the two device seams and record what the source does with them."""
    state = types.SimpleNamespace(opened=[], open_errors=[])

    async def fake_open(udid: str | None = None) -> FakeLockdown:
        if state.open_errors:
            raise state.open_errors.pop(0)
        lockdown = FakeLockdown(len(state.opened) + 1)
        state.opened.append(lockdown)
        return lockdown

    async def fake_info(lockdown: Any, connection: str = "usb") -> DeviceInfo:
        return DeviceInfo(
            udid="00000000-000000000000000A",
            name="Test iPhone",
            product_type="iPhone18,2",
            product_version="26.5.2",
            utc_offset=DEVICE_OFFSET,
            clock_skew=SKEW,
        )

    monkeypatch.setattr(os_trace, "open_lockdown", fake_open)
    monkeypatch.setattr(os_trace, "read_device_info", fake_info)
    return state


def record(index: int, message: str | None = None) -> Record:
    return Record(
        timestamp=dt.datetime(2026, 8, 8, 13, 0, index, tzinfo=dt.UTC),
        level=Level.NOTICE,
        pid=147,
        process="cloudd",
        process_path="/usr/libexec/cloudd",
        subsystem=None,
        category=None,
        thread_id=None,
        image_path=None,
        message=message if message is not None else f"m{index}",
        platform=Platform.IOS,
    )


def as_entry(record: Record) -> Any:
    """The ``SyslogEntry`` the device would have sent for this record.

    Two field names read backwards and this is the place it matters:
    ``filename`` is the process executable and ``image_name`` is the binary
    that emitted the record.
    """
    return types.SimpleNamespace(
        pid=record.pid,
        filename=record.process_path,
        image_name=record.image_path,
        timestamp=record.timestamp,
        thread_id=record.thread_id,
        label=None,
        message=record.message,
        level=types.SimpleNamespace(name=record.level.name),
    )


def emitting(
    *connections: list[Record | BaseException],
    monkeypatch: pytest.MonkeyPatch,
) -> types.SimpleNamespace:
    """Script the relay service through a sequence of connections.

    One list per connection: its records in order, optionally ending with the
    exception that connection raises. A list that simply runs out models a
    stream that ended by itself -- which the source treats as an outage, since
    a live stream does not end on its own.

    The seam is ``_open_service`` rather than ``_stream_once``: replacing the
    latter skips the block that acquires, records and releases the second
    socket, which is the block worth testing.
    """
    remaining = list(connections)
    state = types.SimpleNamespace(lockdowns=[], services=[])

    def fake_open_service(self: OsTraceSource, lockdown: Any) -> FakeService:
        del self
        state.lockdowns.append(lockdown)
        if not remaining:
            # Fail loudly rather than let a test spin: with a zero delay, an
            # endlessly-reconnecting source is an infinite loop.
            msg = "stream script exhausted"
            raise DeviceNotPairedError(msg)
        entries = [
            item if isinstance(item, BaseException) else as_entry(item) for item in remaining.pop(0)
        ]
        service = FakeService(entries, lockdown.events)
        state.services.append(service)
        return service

    monkeypatch.setattr(OsTraceSource, "_open_service", fake_open_service)
    return state


async def take(source: OsTraceSource, count: int) -> list[Record | Gap]:
    out: list[Record | Gap] = []
    async with contextlib.aclosing(source.stream()) as stream:
        async for item in stream:
            out.append(item)
            if len(out) >= count:
                return out
    return out


class TestSessionLifecycle:
    def test_streaming_opens_exactly_one_session(
        self,
        seam: types.SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Identity is read from the session already held.

        Opening a second one to answer `device_info()` doubled the most
        expensive operation at capture start -- usbmux connect, pairing
        validation, TLS handshake -- for values the first session already had.
        """
        emitting([record(0), record(1)], monkeypatch=monkeypatch)
        source = OsTraceSource(reconnect=ReconnectPolicy.disabled())
        asyncio.run(take(source, 2))
        assert len(seam.opened) == 1

    def test_aclose_closes_the_streaming_session(
        self,
        seam: types.SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The regression that matters most.

        `device_info()` used to open a second session and, on releasing it,
        clear the field naming the *streaming* one -- so `aclose()` closed
        nothing and every start/stop cycle leaked a socket.
        """
        scripted = emitting([record(i) for i in range(5)], monkeypatch=monkeypatch)
        source = OsTraceSource(reconnect=ReconnectPolicy.disabled())

        async def run() -> None:
            await take(source, 2)
            assert source._active is scripted.lockdowns[0]
            await source.aclose()

        asyncio.run(run())
        assert seam.opened[0].closed is True

    def test_aclose_releases_the_service_before_the_lockdown(self) -> None:
        """The order, which is the whole of this project's hardest-won rule.

        A device stream is two sockets: the lockdown session, and the
        `os_trace_relay` service connection lockdown merely starts. The service
        is what the generator is blocked reading, so it has to be closed first
        or the close cannot interrupt the read it is trying to end.

        Nothing asserted the *order* -- deleting the service close, or swapping
        the two, left the whole suite green, and the device test only checks
        that both fields end up `None`. `aclose()` itself is bookkeeping over
        two objects, so it needs no hardware to pin down.
        """
        closed: list[str] = []

        class FakeService:
            async def close(self) -> None:
                closed.append("service")

        source = OsTraceSource(reconnect=ReconnectPolicy.disabled())
        source._stream_service = FakeService()
        source._active = types.SimpleNamespace(close=lambda: closed.append("lockdown"))

        asyncio.run(source.aclose())

        assert closed == ["service", "lockdown"]
        assert source._stream_service is None
        assert source._active is None  # type: ignore[unreachable]

    def test_the_scripted_entries_map_back_to_the_records_they_came_from(
        self,
        seam: types.SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The honesty check on the script itself.

        A test writes `record(0)`; a device sends a `SyslogEntry`. Now that the
        seam is the service, everything here travels through the source's real
        mapper, so the two have to agree exactly -- otherwise every assertion
        about a message below is an assertion about something the mapper
        invented.
        """
        wanted = [record(0), record(1, "a message with spaces in it")]
        emitting(list(wanted), monkeypatch=monkeypatch)
        source = OsTraceSource(reconnect=ReconnectPolicy.disabled())

        assert asyncio.run(take(source, 2)) == wanted

    def test_the_service_is_held_while_streaming_and_let_go_afterwards(
        self,
        seam: types.SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`aclose()` can only close a socket somebody wrote down.

        Deleting the one line that records it left every test green while
        recreating the original failure exactly: an `iPhone18,2` delivered
        8,239 further records in the five seconds after a "successful" close.
        The field was invisible because the tests replaced the method that
        sets it.
        """
        scripted = emitting([record(0), record(1)], monkeypatch=monkeypatch)
        source = OsTraceSource(reconnect=ReconnectPolicy.disabled())

        async def run() -> tuple[Any, Any]:
            stream = source.stream()
            await anext(stream)
            # Read while the generator is suspended at its yield: the only
            # moment at which the answer means anything.
            held = source._stream_service
            async for _ in stream:
                pass
            return held, source._stream_service

        held, afterwards = asyncio.run(run())

        assert held is scripted.services[0]
        assert afterwards is None, "the field outlived the connection"

    def test_the_stream_block_releases_the_service_before_the_lockdown(
        self,
        seam: types.SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The same rule as `aclose()`, one line further down and easier to
        reverse: `async with a, b` releases b first, so the operand order *is*
        the ordering.

        Swapping the two left all 520 tests green, because the only test that
        asserted an order asserted `aclose()`'s -- over fields it set by hand,
        which is a different mechanism reaching the same two objects.

        Read after the connection has finished on its own, not after closing
        the generator: closing it leaves both context managers un-exited, as
        the test below measures.
        """
        scripted = emitting([record(0), record(1)], monkeypatch=monkeypatch)
        source = OsTraceSource(reconnect=ReconnectPolicy.disabled())

        async def run() -> None:
            async for _ in source.stream():
                pass

        asyncio.run(run())

        assert scripted.lockdowns[0].events == [
            "lockdown in",
            "service in",
            "service out",
            "lockdown out",
        ]

    def test_closing_the_stream_does_not_by_itself_release_either_socket(
        self,
        seam: types.SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Why `aclose()` exists at all, measured rather than asserted in prose.

        Closing the outer generator throws `GeneratorExit` at its `yield`, but
        the per-connection generator underneath is only finalised when the event
        loop gets round to it -- at `asyncio.run`'s `shutdown_asyncgens`, which
        is after everything a caller does. So the instant after
        `stream.aclose()` returns, neither context manager has exited and the
        service socket is still open and still named.

        That is the whole reason releasing a device closes the service itself
        instead of trusting the generator machinery. If a future Python
        finalises promptly this fails, and the right response is to read the
        rationale in `aclose()` again rather than to delete the assertion.
        """
        scripted = emitting([record(i) for i in range(5)], monkeypatch=monkeypatch)
        source = OsTraceSource(reconnect=ReconnectPolicy.disabled())

        async def run() -> tuple[Any, list[str]]:
            stream = source.stream()
            await anext(stream)
            await stream.aclose()
            return source._stream_service, list(scripted.lockdowns[0].events)

        still_held, events = asyncio.run(run())

        assert still_held is scripted.services[0]
        assert events == ["lockdown in", "service in"], "something was released after all"

    def test_a_deliberate_stop_is_not_reported_as_an_outage(
        self,
        seam: types.SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Stopping and losing the device look identical from inside the loop.

        `aclose()` works by closing the socket the stream is reading, so the
        read fails exactly as it would if the cable were pulled. Told apart by
        the wrong half, the source answers a stop by reconnecting to the device
        it was just asked to release, and writes a gap for an outage that never
        happened.
        """
        emitting(
            [record(0), record(1), StreamInterruptedError("socket closed")],
            [record(2)],
            monkeypatch=monkeypatch,
        )
        source = OsTraceSource(reconnect=ReconnectPolicy(delay=0.0))

        async def run() -> list[Record | Gap]:
            out: list[Record | Gap] = []
            async with contextlib.aclosing(source.stream()) as stream:
                async for item in stream:
                    out.append(item)
                    if len(out) == 2:
                        await source.aclose()
            return out

        items = asyncio.run(run())

        # Ends where it was stopped: no gap, and the second connection in the
        # script is never reached.
        assert [type(item).__name__ for item in items] == ["Record", "Record"]
        assert len(seam.opened) == 1

    def test_releasing_one_session_does_not_deregister_another(self) -> None:
        """`_close` closes by identity, and the 0.1.1 bug is what happens when
        it does not: `device_info()` opened a short-lived session and, on
        releasing it, cleared the field naming the *streaming* one -- after
        which `aclose()` closed nothing and every start/stop cycle leaked a
        socket.

        Nothing reaches that sequence today. `stream()` reads identity from the
        session it already holds, and `device_info()` answers from the cache
        once a capture is running, so the guard defends a path with no caller.
        It is asserted anyway: clearing the field wholesale leaves all 556
        tests green -- measured, under the shadow method -- and the code that
        decides who opens what is the code package D is about to move.
        """
        source = OsTraceSource(reconnect=ReconnectPolicy.disabled())
        streaming = FakeLockdown(1)
        short_lived = FakeLockdown(2)
        source._active = streaming

        asyncio.run(source._close(short_lived))

        assert source._active is streaming, "releasing another session deregistered the stream"
        assert short_lived.closed is True, "the session it was given stayed open"

    def test_a_short_lived_identity_session_is_closed_and_deregistered(
        self,
        seam: types.SimpleNamespace,
    ) -> None:
        source = OsTraceSource()
        info = asyncio.run(source.device_info())
        assert info.product_type == "iPhone18,2"
        assert seam.opened[0].closed is True
        assert source._active is None


class TestReconnect:
    def test_a_recoverable_outage_yields_a_gap_and_resumes(
        self,
        seam: types.SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        emitting(
            [record(0), StreamInterruptedError("device disconnected")],
            [record(1)],
            monkeypatch=monkeypatch,
        )
        source = OsTraceSource(reconnect=ReconnectPolicy(delay=0.0))
        items = asyncio.run(take(source, 3))

        assert [type(item).__name__ for item in items] == ["Record", "Gap", "Record"]
        assert isinstance(items[1], Gap)
        assert items[1].reason == "device disconnected"

    def test_the_gap_reason_is_readable_when_the_device_error_said_nothing(
        self,
        seam: types.SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The pulled-cable case, end to end from the exception that caused it.

        `ConnectionTerminatedError` is raised upstream with no message, so the
        gap took the class name and printed it at the reader: `---- gap ... to
        ... (ConnectionTerminatedError) ----`, in every export and both viewer
        panes. The reason travels this far from `translate`, so the outage is
        built the same way here rather than handed in ready-made.
        """
        upstream = type("ConnectionTerminatedError", (Exception,), {})
        emitting([record(0), translate(upstream())], [record(1)], monkeypatch=monkeypatch)
        source = OsTraceSource(reconnect=ReconnectPolicy(delay=0.0))
        items = asyncio.run(take(source, 3))

        gap = items[1]
        assert isinstance(gap, Gap)
        assert gap.reason == "the connection to the device was lost"
        assert "Error" not in gap.reason

    def test_a_recoverable_error_that_is_not_a_stream_interruption_also_retries(
        self,
        seam: types.SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Recoverability is the error's own answer, not a type check.

        A yanked cable does not always surface as ConnectionTerminatedError;
        matching on that one class dropped the capture for every other shape a
        recoverable outage arrives in.
        """
        emitting(
            [record(0), NoDeviceFoundError("device went away")],
            [record(1)],
            monkeypatch=monkeypatch,
        )
        source = OsTraceSource(reconnect=ReconnectPolicy(delay=0.0))
        items = asyncio.run(take(source, 3))
        assert [type(item).__name__ for item in items] == ["Record", "Gap", "Record"]

    def test_an_unrecoverable_error_propagates_immediately(
        self,
        seam: types.SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        emitting([record(0), DeviceNotPairedError("not paired")], monkeypatch=monkeypatch)
        source = OsTraceSource(reconnect=ReconnectPolicy(delay=0.0))
        with pytest.raises(DeviceNotPairedError):
            asyncio.run(take(source, 3))

    def test_the_first_connect_never_retries(
        self,
        seam: types.SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """There is no capture to resume, and the hint is the whole answer.

        Sitting through thirty silent retries before showing 'answer Trust This
        Computer' helps nobody.
        """
        emitting(monkeypatch=monkeypatch)
        seam.open_errors = [DeviceNotPairedError("not paired")]
        source = OsTraceSource(reconnect=ReconnectPolicy(delay=0.0, max_retries=30))

        with pytest.raises(DeviceNotPairedError):
            asyncio.run(take(source, 1))
        assert seam.opened == []

    def test_reconnection_gives_up_after_the_retry_budget(
        self,
        seam: types.SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        emitting([record(0), StreamInterruptedError("dropped")], monkeypatch=monkeypatch)
        seam.open_errors = [UsbmuxUnavailableError("gone") for _ in range(5)]
        source = OsTraceSource(reconnect=ReconnectPolicy(delay=0.0, max_retries=2))

        with pytest.raises(UsbmuxUnavailableError):
            asyncio.run(take(source, 5))

    def test_reconnecting_suppresses_the_replayed_backlog(
        self,
        seam: types.SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """HISTORICAL replays the device's backlog on every connect, so the
        first stretch after an outage repeats what we already have."""
        first = [record(0), record(1)]
        emitting(
            [*first, StreamInterruptedError("dropped")],
            [*first, record(2)],
            monkeypatch=monkeypatch,
        )
        source = OsTraceSource(reconnect=ReconnectPolicy(delay=0.0))
        items = asyncio.run(take(source, 4))

        messages = [item.message for item in items if isinstance(item, Record)]
        assert messages == ["m0", "m1", "m2"], "the replayed pair must not appear twice"

    def test_a_gap_is_measured_on_one_clock(
        self,
        seam: types.SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Gap start is a device timestamp. Taking the end from the host clock
        made the duration wrong by the skew, and negative whenever the device
        ran ahead."""
        emitting(
            [record(0), StreamInterruptedError("dropped")],
            [record(1)],
            monkeypatch=monkeypatch,
        )
        source = OsTraceSource(reconnect=ReconnectPolicy(delay=0.0))
        items = asyncio.run(take(source, 3))

        gap = next(item for item in items if isinstance(item, Gap))
        assert gap.duration >= dt.timedelta(0)
        assert gap.end.utcoffset() == DEVICE_OFFSET


class TestRecordMapping:
    def test_an_empty_process_path_is_named_per_pid(self) -> None:
        """The kernel and a few others arrive with no filename. The fallback
        depends on the pid, so caching it against the path made the first such
        pid name every later one."""
        source = OsTraceSource()
        first = source._to_record(entry(101, ""), dt.UTC)
        second = source._to_record(entry(202, ""), dt.UTC)
        assert (first.process, second.process) == ("101", "202")

    def test_a_real_path_is_cached(self) -> None:
        source = OsTraceSource()
        first = source._to_record(entry(1, "/usr/libexec/cloudd"), dt.UTC)
        second = source._to_record(entry(2, "/usr/libexec/cloudd"), dt.UTC)
        assert first.process == second.process == "cloudd"
        assert first.process is second.process, "the cache should hand back one object"

    def test_an_unmapped_level_does_not_crash(self) -> None:
        source = OsTraceSource()
        result = source._to_record(entry(1, "/usr/libexec/x", level="SOMETHING_NEW"), dt.UTC)
        assert result.level is Level.NOTICE

    def test_a_naive_timestamp_gains_the_device_offset(self) -> None:
        source = OsTraceSource()
        tz = dt.timezone(DEVICE_OFFSET)
        assert source._to_record(entry(1, "/x"), tz).timestamp.utcoffset() == DEVICE_OFFSET


def entry(pid: int, filename: str, *, level: str = "NOTICE") -> Any:
    return types.SimpleNamespace(
        pid=pid,
        filename=filename,
        image_name=None,
        # Naive on purpose: this is what the device sends, and attaching its
        # offset is the mapping under test.
        timestamp=dt.datetime(2026, 8, 8, 13, 0, 0),  # noqa: DTZ001
        thread_id=7,
        label=None,
        message="m",
        level=types.SimpleNamespace(name=level),
    )


class TestStoppingDuringAnOutage:
    def test_a_stop_during_a_reconnect_does_not_reopen_the_device(
        self,
        seam: types.SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The two-sockets rule, arriving through the path it did not cover.

        `stream()` guards its own reconnect delay, but the retry loop inside
        `_connect` slept up to thirty times of its own and checked nothing. A
        stop that landed there returned in a millisecond reporting success --
        there was no service socket to close at that moment -- and the loop
        went on to open a fresh lockdown *and* a fresh relay, delivering more
        records into a stream nobody was reading.
        """
        source = OsTraceSource(reconnect=ReconnectPolicy(delay=0.01, max_retries=30))
        emitting(
            [record(0), StreamInterruptedError("cable pulled")],
            [record(1)],
            monkeypatch=monkeypatch,
        )

        async def run() -> list[Record | Gap]:
            async def stop_soon() -> None:
                await asyncio.sleep(0.015)
                await source.aclose()

            collected: list[Record | Gap] = []
            stopper: asyncio.Future[None] | None = None
            async for item in source.stream():
                collected.append(item)
                if stopper is None:
                    # Armed from inside the loop, while the generator is
                    # suspended at its yield: the first connect has to succeed,
                    # and only the reconnects after it fail. The attempt after
                    # the third failure would succeed, which is what makes the
                    # session count meaningful.
                    seam.open_errors.extend(NoDeviceFoundError("gone") for _ in range(3))
                    stopper = asyncio.ensure_future(stop_soon())
            if stopper is not None:
                await stopper
            return collected

        items = asyncio.run(run())

        assert len(seam.opened) == 1, f"reopened the device after a stop: {len(seam.opened)}"
        assert not any(isinstance(item, Gap) for item in items), "a stop is not an outage"


def test_a_source_that_forgets_aclose_is_loud_rather_than_leaky() -> None:
    """`SourceCloseMixin.aclose` raises rather than defaulting to a no-op.

    A default that quietly did nothing would give a future source a working
    `async with` that releases nothing, and the failure would show up as
    sockets accumulating under load rather than as an error. Replacing the
    raise with `return` left the whole suite green.
    """
    from ostrace.sources.base import SourceCloseMixin

    class Forgetful(SourceCloseMixin):
        name = "forgetful"

    with pytest.raises(NotImplementedError):
        asyncio.run(Forgetful().aclose())


class TestSayingSoWhileItHappens:
    """`on_state`, which exists for one reason the `Gap` cannot cover.

    A gap is the *record* of an outage and travels in the stream in position,
    which is where its meaning is. But it can only be written once the device
    is back, and the question somebody watching a stalled window has is being
    asked several seconds before that.
    """

    def test_it_says_reconnecting_during_the_outage_and_streaming_after(
        self, seam: types.SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        del seam
        states: list[str] = []
        emitting(
            [record(0), StreamInterruptedError("socket closed")],
            [record(1)],
            monkeypatch=monkeypatch,
        )
        source = OsTraceSource(reconnect=ReconnectPolicy(delay=0.0), on_state=states.append)

        asyncio.run(take(source, 3))

        assert states == [
            CaptureState.STREAMING,
            CaptureState.RECONNECTING,
            CaptureState.STREAMING,
        ]

    def test_a_capture_with_no_outage_says_streaming_once(
        self, seam: types.SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        del seam
        states: list[str] = []
        emitting([record(0), record(1)], monkeypatch=monkeypatch)
        source = OsTraceSource(reconnect=ReconnectPolicy.disabled(), on_state=states.append)

        asyncio.run(take(source, 2))

        assert states == [CaptureState.STREAMING]

    def test_a_listener_that_raises_does_not_cost_the_capture(
        self, seam: types.SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The records are the product and the notification is a courtesy.

        A device released because a banner threw would lose everything the
        device says next, which is the opposite of what a log viewer is for.
        """

        def explode(state: str) -> None:
            msg = f"listener is broken ({state})"
            raise RuntimeError(msg)

        del seam
        emitting(
            [record(0), StreamInterruptedError("socket closed")],
            [record(1)],
            monkeypatch=monkeypatch,
        )
        source = OsTraceSource(reconnect=ReconnectPolicy(delay=0.0), on_state=explode)

        items = asyncio.run(take(source, 3))

        assert [type(item).__name__ for item in items] == ["Record", "Gap", "Record"]

    def test_no_listener_is_the_ordinary_case(
        self, seam: types.SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The CLI passes none, and the code path with nobody watching is the
        one that runs on every capture this project has ever taken."""
        del seam
        emitting([record(0)], [record(1)], monkeypatch=monkeypatch)
        source = OsTraceSource(reconnect=ReconnectPolicy(delay=0.0))

        assert len(asyncio.run(take(source, 3))) == 3
