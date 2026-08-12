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

import asyncio
import time
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ostrace.analysis.scan import ScanResult
from ostrace.exporters.base import ExportResult
from ostrace.exporters.notes import export_notes
from ostrace.model import DeviceInfo, Gap, Level, Record
from ostrace.sources.replay import ReplaySource
from ostrace.storage.capture import open_capture
from tests.helpers import ERRORS, ScriptedSource, make_record

pytest.importorskip("PySide6", reason="the gui extra is not installed")

from PySide6.QtWidgets import QApplication

from ostrace.gui.markers import Eviction
from ostrace.gui.models import RecordModel
from ostrace.gui.pump import RATE_WINDOW_MS, Pump
from ostrace.gui.theme import Scheme
from ostrace.gui.windows.main import MainWindow

if TYPE_CHECKING:
    from pathlib import Path

    from ostrace.gui.live import CaptureThread

pytestmark = pytest.mark.gui


@pytest.fixture
def model(qt_app: object) -> RecordModel:
    del qt_app
    return RecordModel(Scheme.LIGHT)


def once_recording(window: MainWindow, timeout: float = 30.0) -> CaptureThread:
    """Wait until the capture has a session file open.

    A capture is not recording the instant ``start_capture`` returns: the
    thread has to be scheduled and the device identified first. Anything
    asserting what a *recorded* capture leaves behind has to wait for that, and
    the session path appearing is the moment it is true.
    """
    thread = window.capture_controller._thread
    assert thread is not None
    deadline = time.monotonic() + timeout
    while thread.path is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert thread.path is not None, "the capture never opened a session"
    return thread


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


def test_the_quiet_ticks_between_bursts_are_not_a_rate_of_zero(model: RecordModel) -> None:
    """What the status bar actually showed against a device.

    A device does not deliver evenly: it hands over a batch and then says
    nothing for several 50 ms ticks. The rate was computed from one tick, so
    the commonest reading was 0 -- and a readout that says 0 while a capture is
    plainly streaming does not look like a bug, it looks like the device having
    stopped.
    """
    queue: deque[object] = deque(make_record(i) for i in range(100))
    pump = Pump(queue, model)  # type: ignore[arg-type]
    rates: list[float] = []
    pump.rate_changed.connect(rates.append)

    pump.drain()
    for _ in range(5):  # the ticks a quiet moment produces next
        pump.drain()

    assert len(rates) == 6
    assert all(rate > 0 for rate in rates), rates


def test_a_device_that_really_stops_does_read_zero(model: RecordModel) -> None:
    """The window has to empty, or the readout would be a different lie.

    Asked for a moment past the window rather than by sleeping through it: the
    figure is a function of when it is asked, which is exactly what makes that
    possible.
    """
    queue: deque[object] = deque(make_record(i) for i in range(10))
    pump = Pump(queue, model)  # type: ignore[arg-type]
    pump.drain()

    later = pump._clock.elapsed() + RATE_WINDOW_MS + 1
    assert pump._rate(later) == 0.0


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
    thread = window.capture_controller._thread
    assert thread is not None
    assert thread.wait(30_000), "the capture thread did not finish"

    # Drain by hand: no event loop is running, so the pump's timer never fires.
    assert window.capture_controller._pump is not None
    window.capture_controller._pump.drain()

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

    thread = window.capture_controller._thread
    assert thread is not None
    assert thread.wait(30_000)
    window.stop_capture()

    assert destination.is_dir()
    written = [item for item in open_capture(destination).items() if isinstance(item, Record)]
    assert len(written) == 3000


def test_disconnecting_leaves_a_capture_that_can_be_exported(
    qt_app: object, tmp_path: Path
) -> None:
    """The dead end a user hits within a minute of first opening the viewer.

    Capture from the device, press Export, and be told to disconnect to finish
    the recording. Disconnect, press Export again, and be told exactly the same
    thing -- because nothing set the window's capture, and nothing ever would.
    The records were on disk the whole time; the window simply did not know
    where.
    """
    del qt_app
    window = MainWindow()
    window.start_capture(
        ScriptedSource([make_record(i) for i in range(500)], delay=0.01),
        destination=tmp_path / "live.ostrace",
    )
    once_recording(window)

    window.stop_capture()

    assert window.capture is not None, "disconnecting left nothing to export"
    list(window.capture.items())  # the session is finalised and readable
    # The stem, not the file name: `.ostrace` is what marks it as a capture,
    # and a title bar is not where somebody reads a suffix.
    assert window.windowTitle() == "live — ostrace", "the window never says where it went"


class TestWhatTheWindowIsCalled:
    """The title was set from six places with six spellings.

    A live capture was titled after the *source*, which is ``os_trace_relay``:
    the Apple service the stream arrives on, identical for every device, and an
    answer to no question anybody has while looking at a window.
    """

    def test_an_empty_window_is_just_the_application(self, qt_app: object) -> None:
        del qt_app
        assert MainWindow().title_text() == "ostrace"

    def test_a_capture_says_it_is_capturing_before_the_device_answers(
        self, qt_app: object, tmp_path: Path
    ) -> None:
        """Identifying a device is a round trip. Until it lands the honest
        title is the state, not a guess at the name."""
        del qt_app
        window = MainWindow()
        window.start_capture(
            ScriptedSource([make_record(0)], delay=0.01),
            destination=tmp_path / "live.ostrace",
        )
        try:
            assert window.title_text() == "Capturing — ostrace"
        finally:
            window.stop_capture()

    def test_the_device_name_replaces_it_once_known(self, qt_app: object) -> None:
        del qt_app
        window = MainWindow()
        window.capture_controller._thread = object()  # type: ignore[assignment]
        try:
            window._on_identified(
                DeviceInfo(
                    udid="A-UDID",
                    name="Berkay's iPhone",
                    product_type="iPhone18,2",
                    product_version="26.5.2",
                    utc_offset=timedelta(hours=3),
                )
            )
            assert window.title_text() == "Capturing from Berkay's iPhone — ostrace"
        finally:
            window.capture_controller._thread = None

    def test_an_opened_capture_is_named_without_its_suffix(self, qt_app: object) -> None:
        """``ios26-errors.jsonl.gz`` is a file name. ``ios26-errors`` is what
        the capture is called."""
        del qt_app
        window = MainWindow()
        window.open_capture(ERRORS)

        assert window.title_text() == "ios26-errors — ostrace"


def test_a_running_capture_exports_as_a_snapshot(qt_app: object, tmp_path: Path) -> None:
    """This used to be refused, and the refusal was the wrong answer.

    A file growing under the exporter does produce a report whose end is
    arbitrary -- while that end goes unstated. `storage.spool` has emitted a
    ``Z_SYNC_FLUSH`` boundary since phase 1 so that a reader can decompress
    everything written so far, and `exporters.notes` exists to say what an
    export could not tell you. The capability and the vocabulary were both
    already here.

    Built through `export_dialog` rather than `export_capture`: `exec()` is a
    nested event loop that only a person can leave.
    """
    del qt_app
    window = MainWindow()
    window.start_capture(
        ScriptedSource([make_record(i) for i in range(500)], delay=0.01),
        destination=tmp_path / "live.ostrace",
    )
    once_recording(window)

    dialog = window.export_dialog()

    assert dialog is not None, "a running capture offered nothing to export"
    assert dialog.running, "the dialog did not know it was writing a snapshot"
    assert window.capture_controller._thread is not None, "exporting stopped the capture"
    dialog.deleteLater()

    window.stop_capture()


def test_a_snapshot_export_says_that_it_is_one(qt_app: object, tmp_path: Path) -> None:
    """The note is the whole argument for allowing this.

    Without it the last record in the export reads as the last thing that
    happened, when it is only where the file had got to when the button was
    pressed.
    """
    del qt_app
    scan = ScanResult()
    for index in range(3):
        scan.add(make_record(index), index + 1)
    outcome = ExportResult(destination=tmp_path / "out.md", scan=scan)

    notes = export_notes(outcome, truncated=True, running=True)

    assert any("snapshot" in note for note in notes)
    assert any("3 records" in note for note in notes), notes
    assert not any("process was killed" in note for note in notes), (
        "the truncation guess is still offered beside the known answer"
    )


def test_disconnecting_before_the_capture_gets_going_still_releases_it(
    qt_app: object, tmp_path: Path
) -> None:
    """Identifying a device is a round trip to it, and Disconnect during that
    round trip used to do nothing whatsoever.

    ``stop`` cancels the capture task, and until that task exists there was
    nothing to cancel, so it returned quietly -- and the capture went on
    running against a device the user had already let go of. Found because a
    test disconnected quickly enough to hit it.
    """
    del qt_app

    class SlowToIdentify(ScriptedSource):
        async def device_info(self) -> DeviceInfo:
            await asyncio.sleep(0.5)
            return await super().device_info()

    window = MainWindow()
    window.start_capture(
        SlowToIdentify([make_record(i) for i in range(500)], delay=0.01),
        destination=tmp_path / "live.ostrace",
    )
    thread = window.capture_controller._thread
    assert thread is not None

    window.stop_capture()

    assert thread.isFinished(), "the capture ignored a stop it had not started yet"
    assert window.capture_controller._parked == []


def test_a_capture_that_ends_by_itself_is_picked_up_too(qt_app: object, tmp_path: Path) -> None:
    """Unplugging the device ends the capture and disables Disconnect, so the
    completion signal is the only chance to pick the session up."""
    del qt_app
    window = MainWindow()
    destination = tmp_path / "live.ostrace"
    window.start_capture(ReplaySource(ERRORS), destination=destination)

    thread = window.capture_controller._thread
    assert thread is not None
    assert thread.wait(30_000)
    QApplication.processEvents()  # deliver `completed`, which is queued

    assert window.capture is not None
    assert not window.action_disconnect.isEnabled()


def test_stopping_a_capture_that_already_ended_is_not_an_error(qt_app: object) -> None:
    """A regression test for a crash a user would hit routinely.

    The capture ends by itself when the device is unplugged, and the obvious
    next thing anyone does is press Disconnect. That reached across to a loop
    that had already closed and raised `RuntimeError: Event loop is closed`.
    """
    del qt_app
    window = MainWindow()
    window.start_capture(ReplaySource(ERRORS))
    thread = window.capture_controller._thread
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
        thread = window.capture_controller._thread
        assert thread is not None, f"attempt {attempt + 1} did not start"
        assert thread.isRunning() or thread.wait(5_000)
        window.stop_capture()
        assert window.capture_controller._thread is None

    assert window.action_capture.isEnabled()


def test_closing_the_window_releases_the_device(qt_app: object) -> None:
    """Otherwise the capture thread outlives the window it reports to, and the
    device streams into a queue nobody drains -- the exact failure this project
    already paid for once at the source level."""
    del qt_app
    window = MainWindow()
    window.start_capture(ReplaySource(ERRORS))
    assert window.capture_controller._thread is not None

    window.close()

    assert window.capture_controller._thread is None


def test_a_capture_that_will_not_stop_is_kept_rather_than_dropped(
    qt_app: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Letting go of a *running* ``QThread`` is not a leak, it is ``qFatal``.

    The wait in ``stop_capture`` is bounded on purpose, so that a device which
    will not let go cannot freeze the window -- which means it can time out,
    and the line clearing the reference would then have handed Qt a thread that
    was still running. Qt's answer to that is to abort the process, so the
    symptom is not a stuck capture, it is the viewer vanishing.

    The timeout is set to zero rather than a slow source contrived to exceed
    it: ``QThread::start`` marks the thread running before it returns, so a
    zero wait on one just started is deterministically a timeout.
    """
    del qt_app
    # The constant moved to the controller with the wait it bounds.
    monkeypatch.setattr("ostrace.gui.capture_controller.STOP_TIMEOUT_MS", 0)
    window = MainWindow()
    window.start_capture(ScriptedSource([make_record(0)], delay=1.0))

    thread = window.capture_controller._thread
    assert thread is not None
    window.stop_capture()

    assert window.capture_controller._thread is None
    parked = [held for held, _pump in window.capture_controller._parked]
    assert thread in parked, "a running capture thread was dropped"
    assert "not released the device" in window.banner.text

    assert thread.wait(30_000), "the parked capture never finished"
