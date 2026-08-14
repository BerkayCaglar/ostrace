# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The four knobs the command line has, reaching the capture.

`ostrace capture` has taken ``--duration``, ``--max-records``, ``--no-reconnect``
and ``--output`` since phase 3a. Every one of them was already plumbed as far as
`ostrace.capture.capture` or `OsTraceSource`; what was missing was anything in
the interface that supplied them.

The limits are asserted where they are *enforced* -- against a real capture
writing a real session -- rather than by reading the value back off the object
that was handed them. A parameter that arrives and is then ignored is exactly
the defect this is for.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

import pytest

from ostrace.storage.capture import open_capture
from tests.helpers import ScriptedSource, make_record

pytest.importorskip("PySide6", reason="the gui extra is not installed")

from ostrace.gui.capture_controller import CaptureController
from ostrace.gui.models import RecordModel
from ostrace.gui.pump import Pump
from ostrace.gui.widgets.banner import Notice
from ostrace.gui.widgets.capture_options_dialog import CaptureOptions, CaptureOptionsDialog
from ostrace.gui.windows.main import MainWindow

if TYPE_CHECKING:
    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    from ostrace.model import Gap, Record

#: Enough `_step` calls to read the mixed fixture whole, with room to spare.
#: A bound rather than `while True`: a loader that never finishes should fail
#: this test rather than hang the suite.
_LOAD_STEPS = 200

pytestmark = pytest.mark.gui


@pytest.fixture
def controller(qt_app: object) -> CaptureController:
    del qt_app
    return CaptureController(RecordModel())


@pytest.fixture
def window(qt_app: object) -> MainWindow:
    del qt_app
    return MainWindow()


def written(controller: CaptureController) -> list[Path]:
    """Collect where each capture wrote itself, as it ends.

    Off `session_at` rather than off `controller.path`: the path is the running
    thread's, and by the time a capture has ended there is no thread to ask.
    That ordering is the point of the signal -- until the thread ends the
    session file is still being written and its sidecar is not finalised.
    """
    reported: list[Path] = []
    controller.session_at.connect(reported.append)
    return reported


def only(reported: list[Path]) -> Path:
    assert len(reported) == 1, f"expected one session, got {reported}"
    return reported[0]


def run_out(controller: CaptureController, app: QApplication) -> None:
    """Let the capture end because the source ran out, not because it was told to.

    `stop` cancels, and a cancellation that arrives before the session file has
    been opened leaves nothing on disk to read -- which is correct behaviour and
    useless for asserting what a *limit* wrote. So the thread is joined, and the
    events it queued on the way are delivered before anything is read: the path
    is reported from a signal, and a signal nobody pumped has not arrived.
    """
    thread = controller._thread
    assert thread is not None, "nothing was started"
    assert thread.wait(30_000), "the scripted capture never ended"
    app.processEvents()


class TestTheLimitsReachTheCapture:
    """Against the written session, not against the parameter."""

    def test_a_record_limit_stops_the_capture(
        self, controller: CaptureController, qt_app: QApplication
    ) -> None:
        reported = written(controller)
        source = ScriptedSource([make_record(index) for index in range(20)])

        controller.start(source, max_records=5)
        run_out(controller, qt_app)

        assert len(list(open_capture(only(reported)).items())) == 5

    def test_no_limit_takes_everything(
        self, controller: CaptureController, qt_app: QApplication
    ) -> None:
        """The control. Without it the test above would pass against a capture
        that had simply stopped early for some other reason."""
        reported = written(controller)
        source = ScriptedSource([make_record(index) for index in range(20)])

        controller.start(source)
        run_out(controller, qt_app)

        assert len(list(open_capture(only(reported)).items())) == 20

    def test_a_time_limit_is_carried_to_the_thread(self, controller: CaptureController) -> None:
        """Carried rather than enforced here, and asserted that way on purpose:
        `capture` runs a duration off a timer, so an end-to-end assertion would
        be a race between a scripted source and a stopwatch. What this covers is
        the half that was missing -- the value reaching the thread at all."""
        controller.start(ScriptedSource([make_record(0)]), duration=30.0)
        thread = controller._thread
        assert thread is not None

        assert thread.duration == 30.0

        controller.stop()

    def test_a_destination_is_where_the_session_goes(
        self, controller: CaptureController, qt_app: QApplication, tmp_path: Path
    ) -> None:
        """Where, not exactly what: `paths` normalises the name it is given and
        adds the session suffix, which is its decision to make and not this
        dialog's. What the option controls is the directory."""
        reported = written(controller)
        wanted = tmp_path / "somewhere-of-my-own"

        controller.start(ScriptedSource([make_record(0)]), destination=wanted)
        run_out(controller, qt_app)

        written_to = only(reported)
        assert written_to.parent == tmp_path
        assert written_to.stem == "somewhere-of-my-own"
        assert list(open_capture(written_to).items())


class TestTheOptionsValue:
    """A value the window holds, deliberately not one settings restore."""

    def test_the_default_behaves_as_capture_always_has(self) -> None:
        assert CaptureOptions().is_default

    @pytest.mark.parametrize(
        "options",
        [
            CaptureOptions(duration=30.0),
            CaptureOptions(max_records=1_000),
            CaptureOptions(reconnect=False),
        ],
    )
    def test_anything_set_is_not_the_default(self, options: CaptureOptions) -> None:
        assert not options.is_default

    def test_it_says_what_is_set_and_nothing_about_what_is_not(self) -> None:
        summary = CaptureOptions(duration=30.0, reconnect=False).summary

        assert "30 seconds" in summary
        assert "no reconnect" in summary
        assert "records" not in summary


class TestTheDialog:
    """Handed a value, asked for one back. It starts no capture."""

    def test_it_opens_showing_what_it_was_given(self, qt_app: object) -> None:
        del qt_app
        dialog = CaptureOptionsDialog(CaptureOptions(duration=45.0, reconnect=False))

        assert dialog.limit_duration.isChecked()
        assert dialog.duration.value() == 45.0
        assert not dialog.reconnect.isChecked()
        assert not dialog.limit_records.isChecked()

    def test_an_unticked_limit_is_no_limit_however_its_box_reads(self, qt_app: object) -> None:
        """The box keeps a value while it is disabled -- it has to show
        something -- and a dialog that read it anyway would apply a limit
        nobody asked for."""
        del qt_app
        dialog = CaptureOptionsDialog(CaptureOptions())
        dialog.max_records.setValue(7)

        assert dialog.options().max_records is None

    def test_ticking_a_limit_makes_its_box_usable(self, qt_app: object) -> None:
        """A number beside an unticked box that cannot be typed into is a
        control that looks broken rather than off."""
        del qt_app
        dialog = CaptureOptionsDialog(CaptureOptions())
        assert not dialog.duration.isEnabled()

        dialog.limit_duration.setChecked(True)

        assert dialog.duration.isEnabled()

    def test_what_it_returns_round_trips(self, qt_app: object) -> None:
        del qt_app
        wanted = CaptureOptions(duration=12.5, max_records=900, reconnect=False)

        assert CaptureOptionsDialog(wanted).options() == wanted

    def test_an_empty_destination_is_none_rather_than_a_path_to_nowhere(
        self, qt_app: object
    ) -> None:
        """`paths` is the only module allowed to decide where a session goes,
        and `Path("")` is the current directory rather than an absence."""
        del qt_app
        dialog = CaptureOptionsDialog(CaptureOptions())
        dialog.destination.setText("   ")

        assert dialog.options().destination is None


class TestWhatThePausedViewSays:
    """A pause raises one question: is it safe to keep reading, or is the
    queue about to hit its limit and start evicting."""

    def test_a_paused_pump_says_how_much_is_waiting(self, qt_app: QApplication) -> None:
        del qt_app
        queue: deque[Record | Gap] = deque()
        pump = Pump(queue, RecordModel())
        counts: list[int] = []
        pump.buffered.connect(counts.append)
        pump.set_paused(paused=True)

        queue.extend(make_record(index) for index in range(3))
        pump.drain()

        assert counts == [3]

    def test_a_running_pump_says_nothing_about_it(self, qt_app: QApplication) -> None:
        """Running, the answer is always near zero, and the readout that
        matters is the rate."""
        del qt_app
        queue: deque[Record | Gap] = deque([make_record(0)])
        pump = Pump(queue, RecordModel())
        counts: list[int] = []
        pump.buffered.connect(counts.append)

        pump.drain()

        assert counts == []

    def test_the_banner_counts_while_it_stays_the_one_showing(self, window: MainWindow) -> None:
        window.set_paused(paused=True)

        window._on_buffered(1_200)

        assert "1,200 records are waiting" in window.banner.text

    def test_a_more_urgent_notice_is_not_replaced_by_a_count(self, window: MainWindow) -> None:
        """The pump keeps ticking through an outage. A reconnect banner
        overwritten every fiftieth of a second would be the more urgent message
        losing to the less urgent."""
        window.set_paused(paused=True)
        window.banner.show_message("the device stopped talking", "Retry", key=Notice.RECONNECTING)

        window._on_buffered(1_200)

        assert window.banner.text == "the device stopped talking"

    def test_nothing_waiting_is_not_worth_a_number(self, window: MainWindow) -> None:
        """`0 waiting` is a number that teaches the eye to skip the line it
        sits on."""
        window.set_paused(paused=True)

        assert "waiting" not in window.banner.text


class TestWhatTheStatusBarSays:
    def test_the_session_size_is_reported_while_capturing(self, window: MainWindow) -> None:
        """`StatusBar.set_volume` has taken this since it was written and
        nothing ever supplied it. The retained count is capped and says nothing
        about the file, which is not.

        Read after joining the thread and *before* the events it queued are
        delivered. That is not a trick: the size comes off the running
        capture's own path, and delivering `completed` is what winds the
        capture down and takes the path with it. Asked afterwards the answer is
        `None`, which is the next test.
        """
        window.start_capture(ScriptedSource([make_record(index) for index in range(40)]))
        thread = window.capture_controller._thread
        assert thread is not None
        assert thread.wait(30_000), "the scripted capture never ended"

        assert window._bytes_on_disk()

    def test_there_is_no_size_without_a_capture(self, window: MainWindow) -> None:
        """A capture opened from disk is not growing, and a window with nothing
        open has no file at all."""
        assert window._bytes_on_disk() is None


class TestStoppingALoad:
    """`CaptureLoader.cancel` existed from the day the loader was written and
    nothing in the interface could reach it."""

    def test_reading_a_capture_offers_a_way_to_stop(
        self, window: MainWindow, mixed_fixture: Path
    ) -> None:
        window.open_capture(mixed_fixture)

        assert window.banner.current_key is Notice.LOADING
        assert "Reading" in window.banner.text

    def test_stopping_keeps_what_was_read(self, window: MainWindow, mixed_fixture: Path) -> None:
        """A half-read capture is not a failure state: the records that arrived
        are as true as they would have been at the end."""
        window.open_capture(mixed_fixture)
        assert window._loader is not None
        window._loader._step()
        read = window._loader.loaded
        assert read, "nothing was read, so stopping proves nothing"

        window.cancel_loading()

        assert window.model.retained == read
        assert "Stopped reading" in window.banner.text

    def test_the_notice_comes_down_when_the_reading_finishes(
        self, window: MainWindow, mixed_fixture: Path
    ) -> None:
        """Offering to stop something that has stopped is a control that does
        nothing, which is how a window teaches people not to read it."""
        window.open_capture(mixed_fixture)
        loader = window._loader
        assert loader is not None
        # Driven by hand rather than by its timer: a zero-delay `QTimer` needs
        # an event loop to run out, and a test that spun one would be waiting
        # on the clock instead of on the reading.
        for _ in range(_LOAD_STEPS):
            loader._step()
            if window.banner.current_key is not Notice.LOADING:
                break

        assert window.banner.current_key is not Notice.LOADING
        assert window.model.retained == loader.loaded
