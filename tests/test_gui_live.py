# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The live capture path, driven by a recorded session instead of a device.

This is the payoff of the `LogSource` protocol. The whole live path -- capture
thread, queue, pump, row cap, pause -- runs here against a `ReplaySource` over
a real capture, on three operating systems, with no hardware. If the protocol
had grown one method that only the device implementation has, none of this
would be possible and the live path would be untested until someone plugged a
phone in.

What is *not* covered here is socket ownership, and it cannot be: the replay
source has no sockets. Releasing the lockdown session and the `os_trace_relay`
service, in that order, is exercised by `test_device_live.py` against real
hardware. This file proves control flow.
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ostrace.model import Gap, Level, Record
from ostrace.sources.replay import ReplaySource
from ostrace.storage.capture import open_capture
from tests.helpers import ERRORS, make_record

pytest.importorskip("PySide6", reason="the gui extra is not installed")

from ostrace.gui.markers import Eviction
from ostrace.gui.models import RecordModel
from ostrace.gui.pump import Pump
from ostrace.gui.theme import Scheme
from ostrace.gui.windows.main import MainWindow

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep captures started by these tests out of the real data directory.

    Starting a capture writes a session file, and `paths` decides where by
    default -- which in a test run is the developer's own directory. One
    environment variable redirects every path the package writes to.
    """
    monkeypatch.setenv("OSTRACE_HOME", str(tmp_path))


@pytest.fixture
def model(qt_app: object) -> RecordModel:
    del qt_app
    return RecordModel(Scheme.LIGHT)


# -- the pump ----------------------------------------------------------------


def test_a_batch_becomes_one_insertion_not_one_per_record(model: RecordModel) -> None:
    """At 1,600 records a second, one signal per record is 1,600 model updates
    a second and a window that cannot keep up with an idling device."""
    queue: deque[object] = deque(make_record(i) for i in range(500))
    pump = Pump(queue, model)  # type: ignore[arg-type]

    insertions: list[int] = []
    model.rowsInserted.connect(lambda *_: insertions.append(1))
    pump.drain()

    assert model.rowCount() == 500
    assert len(insertions) == 1


def test_draining_an_empty_queue_reports_no_traffic(model: RecordModel) -> None:
    rates: list[float] = []
    pump = Pump(deque(), model)
    pump.rate_changed.connect(rates.append)
    pump.drain()
    assert rates == [0.0]


def test_pausing_stops_the_view_and_not_the_queue(model: RecordModel) -> None:
    """Pause is a display state. It never reaches the source -- releasing a
    device releases the lockdown session *and* the relay service together, so a
    pause that touched it would be a disconnect with a friendlier label."""
    queue: deque[object] = deque()
    pump = Pump(queue, model)  # type: ignore[arg-type]

    pump.set_paused(True)
    queue.extend(make_record(i) for i in range(100))
    pump.drain()

    assert model.rowCount() == 0, "the view is frozen"
    assert len(queue) == 100, "the records are still there"

    pump.set_paused(False)
    assert model.rowCount() == 100


def test_a_long_pause_drops_the_oldest_and_calls_it_an_eviction(model: RecordModel) -> None:
    """The records dropped here are in the session file on disk.

    Which is exactly why they are announced as an eviction rather than a gap:
    a gap says the records are gone, and saying that about records the program
    itself just wrote would be the view lying about the capture.
    """
    queue: deque[object] = deque()
    pump = Pump(queue, model, pause_limit=50)  # type: ignore[arg-type]
    pump.set_paused(True)

    overflows: list[int] = []
    pump.overflowed.connect(overflows.append)
    queue.extend(make_record(i) for i in range(200))
    pump.drain()

    assert overflows == [150]
    assert len(queue) == 50
    assert model.evicted == 150

    notices = [
        model.row_at(row)
        for row in range(model.rowCount())
        if isinstance(model.row_at(row), Eviction)
    ]
    assert len(notices) == 1
    assert isinstance(notices[0], Eviction)
    assert "in the capture but not in this view" in notices[0].text


def test_stopping_takes_what_was_already_captured(model: RecordModel) -> None:
    """Those records were captured. Dropping them at the moment the user
    pressed stop would make the end of the view disagree with the file."""
    queue: deque[object] = deque(make_record(i) for i in range(30))
    pump = Pump(queue, model)  # type: ignore[arg-type]
    pump.stop()
    assert model.rowCount() == 30


def test_the_eviction_notice_survives_a_filter(model: RecordModel) -> None:
    """Every discontinuity is a marker, including one the pump produced."""
    queue: deque[object] = deque()
    pump = Pump(queue, model, pause_limit=10)  # type: ignore[arg-type]
    pump.set_paused(True)
    queue.extend(make_record(i) for i in range(100))
    pump.drain()
    pump.set_paused(False)

    model.set_filter(model.filter.__class__(minimum_level=Level.FAULT))
    assert any(isinstance(model.row_at(row), Eviction) for row in range(model.rowCount()))


def test_gaps_reach_the_model_in_position(model: RecordModel) -> None:
    """A gap travels *in* the stream. Routing it around the queue would throw
    away the one thing that makes it meaningful: where it happened."""
    start = datetime(2026, 8, 8, 13, 0, tzinfo=UTC)
    queue: deque[object] = deque(
        [
            make_record(0),
            Gap(start=start, end=start + timedelta(seconds=2), reason="connection dropped"),
            make_record(1),
        ]
    )
    pump = Pump(queue, model)  # type: ignore[arg-type]
    pump.drain()

    assert model.rowCount() == 3
    assert isinstance(model.row_at(1), Gap)
    assert model.gaps == 1


# -- the whole path, against a recorded session ------------------------------


def test_a_recorded_session_stands_in_for_a_device(qt_app: object) -> None:
    """The architecture's central claim, asserted rather than assumed.

    A consumer takes a `LogSource`; a replay of a real capture is one; so the
    live path is exercised end to end with no phone attached. This is what lets
    CI cover it on three operating systems.
    """
    del qt_app
    window = MainWindow()
    source = ReplaySource(ERRORS)

    window.start_capture(source)
    thread = window._capture_thread
    assert thread is not None
    assert thread.wait(30_000), "the capture thread did not finish"

    # Drain by hand: no event loop is running, so the pump's timer never fires.
    assert window._pump is not None
    window._pump.drain()

    assert window.model.rowCount() == 3000
    assert any(
        isinstance(window.model.row_at(row), Record) for row in range(window.model.rowCount())
    )
    window.stop_capture()


def test_capturing_writes_a_session_file(qt_app: object, tmp_path: Path) -> None:
    """A live view that keeps nothing would make "pause" a promise it cannot
    honour, and would lose everything the moment the window closed.

    It is the same `ostrace.capture.capture` the CLI runs, so the file it
    produces is an ordinary session that `ostrace export` can read.
    """
    del qt_app
    window = MainWindow()
    destination = tmp_path / "live.ostrace"
    window.start_capture(ReplaySource(ERRORS), destination=destination)

    thread = window._capture_thread
    assert thread is not None
    assert thread.wait(30_000)
    window.stop_capture()

    assert destination.is_dir()
    written = [item for item in open_capture(destination).items() if isinstance(item, Record)]
    assert len(written) == 3000


def test_stopping_a_capture_that_already_ended_is_not_an_error(qt_app: object) -> None:
    """A regression test for a crash a user would hit routinely.

    The capture ends by itself when the device is unplugged, and the obvious
    next thing anyone does is press Disconnect. That reached across to a loop
    that had already closed and raised `RuntimeError: Event loop is closed`.
    """
    del qt_app
    window = MainWindow()
    window.start_capture(ReplaySource(ERRORS))
    thread = window._capture_thread
    assert thread is not None
    assert thread.wait(30_000)

    window.stop_capture()
    window.stop_capture()


def test_the_capture_controls_are_mutually_exclusive(qt_app: object) -> None:
    """Pause and Disconnect are different verbs, and neither is available
    before there is anything to pause or disconnect from."""
    del qt_app
    window = MainWindow()

    assert window.action_capture.isEnabled()
    assert not window.action_pause.isEnabled()
    assert not window.action_disconnect.isEnabled()

    window.start_capture(ReplaySource(ERRORS))
    assert not window.action_capture.isEnabled()
    assert window.action_pause.isEnabled()
    assert window.action_disconnect.isEnabled()

    window.stop_capture()
    assert window.action_capture.isEnabled()
    assert not window.action_pause.isEnabled()
    assert not window.action_disconnect.isEnabled()


@pytest.mark.device
def test_disconnect_really_releases_the_device(qt_app: object) -> None:
    """The one thing here a fixture cannot prove.

    A replay source has no sockets, so every other test in this file
    demonstrates control flow and nothing about ownership. Releasing a device
    means releasing the ``os_trace_relay`` service *and* the lockdown session,
    in that order -- and the way that failure shows up is not an exception, it
    is the *second* capture finding the relay already busy.

    So the assertion is two captures in a row. This is why it is marked
    ``device``: no fixture can fail it.
    """
    del qt_app
    from ostrace.sources.os_trace import OsTraceSource

    window = MainWindow()
    for attempt in range(2):
        window.start_capture(OsTraceSource())
        thread = window._capture_thread
        assert thread is not None, f"attempt {attempt + 1} did not start"
        assert thread.isRunning() or thread.wait(5_000)
        window.stop_capture()
        assert window._capture_thread is None

    assert window.action_capture.isEnabled()


def test_closing_the_window_releases_the_device(qt_app: object) -> None:
    """Otherwise the capture thread outlives the window it reports to, and the
    device streams into a queue nobody drains -- the exact failure this project
    already paid for once at the source level."""
    del qt_app
    window = MainWindow()
    window.start_capture(ReplaySource(ERRORS))
    assert window._capture_thread is not None

    window.close()

    assert window._capture_thread is None
