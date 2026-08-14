# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The capture lifecycle, without a window.

That is the point of the object being separate: starting a thread, draining a
queue, waiting, parking what will not stop and joining it later are mechanics,
and asserting them used to require a `MainWindow` -- a toolbar, a minimap, a
detail pane and a settings store -- because that is where they lived.

A `QApplication` is still needed. These are `QObject`s with signals and a
`QTimer`, and the pump's timer only fires under one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.helpers import ScriptedSource, make_record

pytest.importorskip("PySide6", reason="the gui extra is not installed")

from PySide6.QtCore import QThread

from ostrace.gui.capture_controller import CaptureController, Lifecycle
from ostrace.gui.models import RecordModel
from ostrace.sources.base import CaptureState

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.gui


class StuckThread(QThread):
    """A capture thread that refuses to end, the way a held device does.

    Stands in for the one case the bounded wait exists for. Nothing else here
    can produce it: a scripted source finishes in microseconds, and a test that
    waited for a real stuck device would be a device test.
    """

    def __init__(self) -> None:
        super().__init__()
        self.path: Path | None = None
        self.queue: object = None
        self.stopped = False
        self._release = False

    def run(self) -> None:
        while not self._release:
            self.msleep(5)

    def stop(self) -> None:
        self.stopped = True

    def let_go(self) -> None:
        """Let the thread end, as the device eventually does."""
        self._release = True


@pytest.fixture
def controller(qt_app: object) -> CaptureController:
    del qt_app
    return CaptureController(RecordModel())


def states(controller: CaptureController) -> list[Lifecycle]:
    seen: list[Lifecycle] = []
    controller.state_changed.connect(seen.append)
    return seen


class TestNothingRunning:
    def test_it_starts_idle(self, controller: CaptureController) -> None:
        assert controller.state is Lifecycle.IDLE
        assert not controller.is_running
        assert controller.path is None

    def test_stopping_nothing_is_not_an_error(self, controller: CaptureController) -> None:
        """Every path that winds a capture down goes through one door --
        Disconnect, a failure, the end of the stream, closing the window -- so
        the door has to tolerate being pushed when nobody is there."""
        seen = states(controller)

        controller.stop()
        controller.stop()

        assert seen == []
        assert controller.state is Lifecycle.IDLE

    def test_the_link_state_of_a_capture_that_is_over_is_ignored(
        self, controller: CaptureController
    ) -> None:
        """A notification can arrive after the capture it describes has been
        let go of. Recording it would walk the lifecycle backwards, out of
        `IDLE` into `STREAMING`, and the window would re-enable Disconnect for
        a device nobody holds.
        """
        seen = states(controller)

        controller.link_state(CaptureState.STREAMING)

        assert seen == []
        assert controller.state is Lifecycle.IDLE


class TestACaptureThatRunsAndEnds:
    def test_the_lifecycle_in_order(self, controller: CaptureController) -> None:
        seen = states(controller)

        controller.start(ScriptedSource([make_record(0), make_record(1)]))
        assert seen[0] is Lifecycle.STARTING
        controller.stop()

        assert seen[-1] is Lifecycle.IDLE
        assert Lifecycle.STOPPING in seen
        assert not controller.is_running

    def test_the_session_path_is_reported_when_it_has_really_ended(
        self, controller: CaptureController
    ) -> None:
        """Not before: until the thread ends the session file is still being
        written and its sidecar is not finalised."""
        reported: list[object] = []
        controller.session_at.connect(reported.append)

        controller.start(ScriptedSource([make_record(0)]))
        controller.stop()

        assert len(reported) == 1

    def test_the_device_answering_moves_it_on(self, controller: CaptureController) -> None:
        seen = states(controller)
        identified: list[object] = []
        controller.identified.connect(identified.append)

        controller.start(ScriptedSource([make_record(0)]))
        controller._on_identified(object())

        assert Lifecycle.IDENTIFIED in seen
        assert len(identified) == 1
        controller.stop()

    def test_the_link_going_and_coming_back_shows_in_the_lifecycle(
        self, controller: CaptureController
    ) -> None:
        seen = states(controller)
        controller.start(ScriptedSource([make_record(0)]))

        controller.link_state(CaptureState.STREAMING)
        controller.link_state(CaptureState.RECONNECTING)
        controller.link_state(CaptureState.STREAMING)

        assert seen.count(Lifecycle.RECONNECTING) == 1
        assert seen.count(Lifecycle.STREAMING) == 2
        controller.stop()

    def test_the_same_state_twice_is_said_once(self, controller: CaptureController) -> None:
        """The window's handler fans out to six controls, a title and a
        placeholder. Repeating that on every arriving batch is work nobody
        asked for."""
        controller.start(ScriptedSource([make_record(0)]))
        seen = states(controller)

        controller.link_state(CaptureState.STREAMING)
        controller.link_state(CaptureState.STREAMING)
        controller.link_state(CaptureState.STREAMING)

        assert seen == [Lifecycle.STREAMING]
        controller.stop()


class TestADeviceThatWillNotLetGo:
    """The bounded wait exists because a device can refuse, and the window must
    not freeze while it does."""

    @pytest.fixture
    def stuck(self, controller: CaptureController, monkeypatch: pytest.MonkeyPatch) -> StuckThread:
        """A started capture whose thread will outlive the stop wait."""
        monkeypatch.setattr("ostrace.gui.capture_controller.STOP_TIMEOUT_MS", 20)
        controller.start(ScriptedSource([make_record(0)]))
        thread = StuckThread()
        # Replace the real thread rather than the wait: what is under test is
        # what this object does when a wait times out, and a real thread that
        # genuinely does not end is the only honest way to time one out.
        real = controller._thread
        assert real is not None
        # Asserted, and generous, for the reason this whole class is about.
        # `CaptureThread` is constructed with no parent, so Python owns it
        # alone and the line below drops the last reference -- onto a `QThread`
        # that has not finished, if this wait gave up. Qt's destructor calls
        # `qFatal` on one of those, which does not fail a test: it takes the
        # process. Measured by setting this wait to zero, which turns twelve
        # passing tests into exit `0xC0000409` after eight dots, with nothing
        # printed. The wait returns the moment the thread ends, so the ceiling
        # costs nothing when it is not needed, and every other thread wait in
        # this suite is already `assert wait(30_000)`.
        assert real.wait(30_000), "the scripted capture never ended"
        # Not a `CaptureThread`: what is under test is what this object does
        # when a wait times out, and the real one cannot be made to.
        controller._thread = thread  # type: ignore[assignment]
        thread.start()
        return thread

    def test_a_thread_that_outlives_the_wait_is_parked_rather_than_dropped(
        self, controller: CaptureController, stuck: StuckThread
    ) -> None:
        """Clearing the reference would drop the last one to a running
        `QThread`, and Qt's destructor calls `qFatal` on one of those: the
        window would not report a stuck capture, it would take the process
        down."""
        seen = states(controller)

        controller.stop()

        assert seen[-1] is Lifecycle.PARKED
        assert controller._parked
        assert stuck.stopped, "it was asked to stop before being parked"
        stuck.let_go()
        controller.shutdown()

    def test_the_parked_pump_is_alive_and_paused(
        self, controller: CaptureController, stuck: StuckThread
    ) -> None:
        """The rule this object exists to keep: the pump outlives the thread.

        The thread is still producing into the queue, and a stopped pump leaves
        those records accumulating with nothing bounding them -- against a
        device delivering 1,600 a second. Paused, the pump keeps its own bound
        and evicts with a notice, which is the honest answer: they are in the
        session file and no longer in the view.
        """
        pump = controller._pump
        assert pump is not None

        controller.stop()

        assert pump.paused is True
        assert pump._timer.isActive(), "a stopped pump stops bounding the queue"
        stuck.let_go()
        controller.shutdown()

    def test_shutdown_waits_for_what_was_parked(
        self, controller: CaptureController, stuck: StuckThread, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A `QThread` still running when Python drops its last reference
        aborts the process -- measured here once as exit `0xC0000409` with
        nothing printed.

        The wait is widened for this one. The fixture sets 20 ms because what
        *it* is for is a wait that times out; what this is for is a wait that
        succeeds, and 20 ms against a thread waking from a 5 ms sleep is a
        margin the machine can eat. It did: this failed once on a macOS runner
        and nowhere else, which read as a flake and was two faults at once --
        a budget that was really a race, and `shutdown` treating the timeout as
        a success. The second one is `test_shutdown_keeps_what_its_wait_did_not
        _catch`.
        """
        controller.stop()
        stuck.let_go()
        monkeypatch.setattr("ostrace.gui.capture_controller.STOP_TIMEOUT_MS", 30_000)

        controller.shutdown()

        assert controller._parked == []
        assert not stuck.isRunning()

    def test_shutdown_keeps_what_its_wait_did_not_catch(
        self, controller: CaptureController, stuck: StuckThread, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A wait that timed out is not a wait that succeeded.

        `shutdown` used to clear the parked list unconditionally, which threw
        away the last reference to a *running* thread and did the exact thing
        `_park` exists to prevent -- `CaptureThread` has no parent, so that
        reference is the only one, and Qt's destructor calls `qFatal` on a
        running thread. It does not fail a test; it takes the process.

        Caught by CI on macOS, once, where the fixture's 20 ms wait was long
        enough on every other runner and not on that one. Forced here rather
        than waited for: at zero the wait cannot succeed, so the assertion is
        about the branch and not about the timing of the machine running it.
        """
        controller.stop()
        assert controller._parked
        monkeypatch.setattr("ostrace.gui.capture_controller.STOP_TIMEOUT_MS", 0)

        controller.shutdown()

        assert controller._parked, "a running thread was let go of"
        assert stuck.isRunning()
        pump = controller._parked[0][1]
        assert pump is not None
        assert pump._timer.isActive(), "the pump went while its thread was still producing"

        stuck.let_go()
        assert stuck.wait(30_000)
        controller._reap()
        assert controller._parked == []

    def test_a_parked_capture_that_ends_lets_go_by_itself(
        self, controller: CaptureController, stuck: StuckThread
    ) -> None:
        """`shutdown` is the last resort, not the mechanism. A device that
        releases a second later should not leave a thread held until the window
        closes."""
        controller.stop()
        pump = controller._parked[0][1]
        assert pump is not None

        stuck.let_go()
        stuck.wait(1_000)
        controller._reap()

        assert controller._parked == []
        assert controller.state is Lifecycle.IDLE
        assert not pump._timer.isActive(), "the pump outlived the thread and then went"
