# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The live source's control flow, without a device.

`pymobiledevice3` is replaced at the two seams the source uses -- opening a
lockdown session and reading device identity -- so the reconnect loop, the gap
bookkeeping and the session lifecycle are all exercised in CI. The record
*mapping* is covered against real captures in `test_sources_replay.py`; this
file is about what happens around it.
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
)
from ostrace.model import DeviceInfo, Gap, Level, Platform, Record
from ostrace.sources import os_trace
from ostrace.sources.os_trace import OsTraceSource, ReconnectPolicy

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

DEVICE_OFFSET = dt.timedelta(hours=3)
SKEW = dt.timedelta(seconds=10)


class FakeLockdown:
    def __init__(self, index: int) -> None:
        self.index = index
        self.closed = False

    async def close(self) -> None:
        self.closed = True

    async def __aenter__(self) -> FakeLockdown:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


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


def emitting(
    *connections: list[Record | BaseException],
    monkeypatch: pytest.MonkeyPatch,
) -> list[Any]:
    """Drive `_stream_once` through a scripted sequence of connections.

    One list per connection: its records in order, optionally ending with the
    exception that connection raises. A list that simply runs out models a
    stream that ended by itself -- which the source treats as an outage, since
    a live stream does not end on its own.
    """
    remaining = list(connections)
    used: list[Any] = []

    async def fake_once(
        self: OsTraceSource,
        lockdown: Any,
        tz: dt.tzinfo,
    ) -> AsyncGenerator[Record, None]:
        used.append(lockdown)
        if not remaining:
            # Fail loudly rather than let a test spin: with a zero delay, an
            # endlessly-reconnecting source is an infinite loop.
            msg = "stream script exhausted"
            raise DeviceNotPairedError(msg)
        for item in remaining.pop(0):
            if isinstance(item, BaseException):
                raise item
            yield item

    monkeypatch.setattr(OsTraceSource, "_stream_once", fake_once)
    return used


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
        used = emitting([record(i) for i in range(5)], monkeypatch=monkeypatch)
        source = OsTraceSource(reconnect=ReconnectPolicy.disabled())

        async def run() -> None:
            await take(source, 2)
            assert source._active is used[0]
            await source.aclose()

        asyncio.run(run())
        assert seam.opened[0].closed is True

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
