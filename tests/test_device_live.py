# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests that need a physical device.

Excluded from CI (``-m "not device"``); run locally with ``pytest -m device``.

These are the only tests that can catch an upstream change in the shape of a
``SyslogEntry``. The committed fixtures were captured through the same mapping,
so they prove the mapping handles real *values* -- they cannot prove it still
matches the library's current *fields*. That is what this file is for.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta

import pytest

from ostrace.errors import OstraceError
from ostrace.model import Level, Platform, Record
from ostrace.sources.os_trace import OsTraceSource, ReconnectPolicy

pytestmark = pytest.mark.device

#: Enough to see a spread of levels and subsystems without waiting long.
SAMPLE = 400
#: Wall-clock ceiling. Never derived from record arrival: a quiet device can go
#: silent for tens of seconds, so a timeout that waits for the next record in
#: order to notice the time is a hang.
TIMEOUT = 60.0


async def sample(count: int = SAMPLE) -> list[Record]:
    """Pull `count` records and shut the session down deterministically.

    The ``async with source`` is the part that matters, and it is the pattern
    every consumer that stops early has to follow. Closing the generator alone
    is not enough: its ``GeneratorExit`` cannot be delivered while the innermost
    read is blocked on the socket, so finalisation is left pending and the
    socket survives until the garbage collector reaches it.
    """
    records: list[Record] = []

    async def pull(source: OsTraceSource) -> None:
        async with contextlib.aclosing(source.records()) as stream:
            async for record in stream:
                records.append(record)
                if len(records) >= count:
                    return

    async with OsTraceSource(reconnect=ReconnectPolicy.disabled()) as source:
        await asyncio.wait_for(pull(source), timeout=TIMEOUT)
    return records


@pytest.fixture(scope="module")
def live() -> list[Record]:
    return asyncio.run(sample())


def test_the_device_is_identified() -> None:
    info = asyncio.run(OsTraceSource().device_info())
    assert info.udid
    assert info.product_type.startswith("iPhone") or info.product_type.startswith("iPad")
    assert info.product_version
    # Without this the timestamps are meaningless, so it is not optional.
    assert info.utc_offset is not None
    assert -timedelta(hours=14) <= info.utc_offset <= timedelta(hours=14)


def test_the_host_and_device_clocks_roughly_agree() -> None:
    """A large skew makes correlating device logs with host events wrong, and it
    is worth reporting rather than silently absorbing."""
    info = asyncio.run(OsTraceSource().device_info())
    assert info.clock_skew is not None
    assert abs(info.clock_skew) < timedelta(minutes=5)


def test_reading_identity_mid_stream_keeps_the_streaming_session() -> None:
    """The live half of the session-lifecycle regression.

    An earlier version answered ``device_info()`` by opening a second lockdown
    and, on releasing it, deregistered the first -- so ``aclose()`` had nothing
    to close and every start/stop cycle leaked a socket. The stubbed tests pin
    the bookkeeping; only a real session proves the socket underneath survives
    the question being asked.
    """

    async def run() -> None:
        async with (
            OsTraceSource(reconnect=ReconnectPolicy.disabled()) as source,
            contextlib.aclosing(source.stream()) as stream,
        ):
            async for _ in stream:
                break

            streaming = source._active
            assert streaming is not None

            info = await source.device_info()
            assert info.udid
            # Identity comes from the session already in hand. Opening a
            # second one is what used to cost the stream its socket.
            assert source._active is streaming

    asyncio.run(asyncio.wait_for(run(), TIMEOUT))


@pytest.mark.parametrize("reconnect", [ReconnectPolicy.disabled(), ReconnectPolicy(delay=0.1)])
def test_aclose_actually_stops_a_running_stream(reconnect: ReconnectPolicy) -> None:
    """`aclose()` closed the wrong socket, and only a device could show it.

    Records arrive over the ``os_trace_relay`` service connection, not over the
    lockdown session that started it. Closing the lockdown returned in a
    millisecond and looked like success -- while this device delivered a further
    8,239 records in the next five seconds, and the orphaned service left the
    next capture unable to stream at all.

    The stubbed tests cannot reach this: they replace ``_stream_once``, which is
    the only place the service connection exists.

    Run with reconnection both off and on, because a stop must not be mistaken
    for an outage: with reconnection on, the losing read would otherwise be
    treated as a device that went away, and the source would dutifully
    reconnect to the device the caller just asked it to let go of.
    """

    async def run() -> None:
        source = OsTraceSource(reconnect=reconnect)
        streaming = asyncio.Event()
        seen = 0

        async def drain() -> None:
            nonlocal seen
            async with contextlib.aclosing(source.stream()) as stream:
                async for _ in stream:
                    seen += 1
                    streaming.set()

        task = asyncio.create_task(drain())
        try:
            await asyncio.wait_for(streaming.wait(), TIMEOUT)
            await source.aclose()
            stopped_at = seen

            # Stopping is a clean end, not an error: a stop button that reports
            # a failure every time is a stop button nobody trusts.
            await asyncio.wait_for(task, timeout=15.0)
            assert task.exception() is None

            assert seen == stopped_at, "records kept arriving after aclose()"
            assert source._active is None
            assert source._stream_service is None
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, OstraceError):
                await task

    asyncio.run(run())


def test_records_arrive_and_are_well_formed(live: list[Record]) -> None:
    assert len(live) == SAMPLE
    for record in live:
        assert record.timestamp.tzinfo is not None
        # pid 0 is the kernel, and it logs plenty -- memory pressure, swapout,
        # APFS. A `> 0` check here fails on a real device within a few hundred
        # records.
        assert record.pid >= 0
        assert record.process
        assert record.process == record.process_path.rsplit("/", 1)[-1]
        assert record.platform is Platform.IOS
        assert isinstance(record.level, Level)


def test_the_kernel_is_named_rather_than_numbered(live: list[Record]) -> None:
    """The kernel arrives as pid 0. It must still get a process name, or the
    viewer shows a column of zeroes for one of the noisiest sources on the
    device."""
    kernel = [record for record in live if record.pid == 0]
    if not kernel:
        pytest.skip("no kernel records in this sample")
    for record in kernel:
        assert record.process
        assert not record.process.isdigit()


def test_the_structured_fields_are_actually_populated(live: list[Record]) -> None:
    """The entire justification for using os_trace_relay over the legacy relay.

    If this fails, we are getting text-tier data and the rewrite bought nothing.
    """
    with_subsystem = sum(1 for record in live if record.subsystem)
    assert with_subsystem / len(live) > 0.8

    assert any(record.thread_id for record in live)
    assert any(record.image_path for record in live)
    assert any(record.timestamp.microsecond for record in live)


def test_the_debug_and_info_tiers_arrive(live: list[Record]) -> None:
    """The legacy relay delivers essentially only NOTICE. Getting the lower
    tiers is the measured reason this source was chosen."""
    levels = {record.level for record in live}
    assert levels & {Level.DEBUG, Level.INFO}


def test_a_shared_library_is_never_the_process(live: list[Record]) -> None:
    """Guards the two upstream fields that read backwards. See the same test in
    test_sources_replay.py -- this is the live half of it."""
    assert not [record for record in live if record.process_path.endswith(".dylib")]
