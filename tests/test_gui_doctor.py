# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Doctor window, and the dead ends it exists to end.

The checks have existed since phase 1 and only the command line could run them,
so somebody who installed this for the window met a dead end at exactly the
moment something was wrong — and the answer is almost never in the program.

The window is driven with reports built here rather than by running the real
checks: those open sockets and a lockdown session, which is a device test. What
is under test is what the window does with an answer, which is where the bugs
that reach a user live.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from ostrace.devices.doctor import Report, Status
from ostrace.sources.base import CaptureState
from tests.helpers import make_record

pytest.importorskip("PySide6", reason="the gui extra is not installed")

from ostrace.gui.windows.doctor import MARKS, DoctorThread, DoctorWindow
from ostrace.gui.windows.main import RECONNECT_MESSAGE, MainWindow

if TYPE_CHECKING:
    from PySide6.QtWidgets import QTreeWidgetItem

pytestmark = pytest.mark.gui


def healthy() -> Report:
    report = Report()
    report.add("ostrace", Status.OK, "0.1.1 on Python 3.13 (win32)")
    report.add("usbmux", Status.OK, "Apple Mobile Device Service on 127.0.0.1:27015")
    report.add("devices", Status.OK, "1 connected: 1 USB, 0 network")
    return report


def broken() -> Report:
    report = Report()
    report.add("ostrace", Status.OK, "0.1.1 on Python 3.13 (win32)")
    report.add(
        "usbmux",
        Status.FAIL,
        "nothing listening on 127.0.0.1:27015",
        "Apple Mobile Device Service is not running.",
    )
    report.add("devices", Status.SKIP, "not checked: there is no usbmux to ask")
    return report


def rows(window: DoctorWindow) -> list[QTreeWidgetItem]:
    """Every top-level row. `topLevelItem` is typed optional and is not, for an
    index the widget itself just gave out."""
    tree = window.checks
    found = [tree.topLevelItem(index) for index in range(tree.topLevelItemCount())]
    return [item for item in found if item is not None]


@pytest.fixture
def doctor(qt_app: object) -> DoctorWindow:
    del qt_app
    return DoctorWindow()


class TestWhatItShows:
    def test_one_row_per_check(self, doctor: DoctorWindow) -> None:
        doctor._show_report(healthy())

        assert [row.text(0) for row in rows(doctor)] == ["ostrace", "usbmux", "devices"]

    def test_the_status_is_a_word_and_not_only_a_colour(self, doctor: DoctorWindow) -> None:
        """`docs/design/gui.md` §10's rule, and this window is read by somebody
        already having a bad time, often over a screen share."""
        doctor._show_report(broken())

        assert [row.text(1) for row in rows(doctor)] == [
            MARKS[Status.OK],
            MARKS[Status.FAIL],
            MARKS[Status.SKIP],
        ]

    def test_a_hint_is_a_row_of_its_own(self, doctor: DoctorWindow) -> None:
        """The hints are sentences and the details are phrases. In one column
        every row would be as tall as the longest hint."""
        doctor._show_report(broken())

        usbmux = rows(doctor)[1]
        assert usbmux.childCount() == 1
        assert "Apple Mobile Device Service" in usbmux.child(0).text(2)

    def test_a_healthy_report_says_so_in_a_sentence(self, doctor: DoctorWindow) -> None:
        """A list of ticks with no summary makes the reader count them."""
        doctor._show_report(healthy())

        assert "in place" in doctor._summary.text()

    def test_a_broken_one_counts_the_failures(self, doctor: DoctorWindow) -> None:
        doctor._show_report(broken())

        assert doctor._summary.text().startswith("1 of 3")

    def test_running_again_replaces_rather_than_appends(self, doctor: DoctorWindow) -> None:
        doctor._show_report(broken())
        doctor._show_report(healthy())

        assert len(rows(doctor)) == 3

    def test_a_failure_to_run_at_all_is_shown_rather_than_swallowed(
        self, doctor: DoctorWindow
    ) -> None:
        doctor._show_failure("OSError: something went wrong")

        assert "something went wrong" in doctor._summary.text()
        assert doctor.again.isEnabled(), "there would be no way to try again"


class TestTakingItAway:
    """The reason to run this is usually to tell somebody else what it said."""

    def test_the_report_copies_out_as_text(self, doctor: DoctorWindow) -> None:
        doctor._show_report(broken())

        text = doctor.as_text()

        assert "usbmux" in text
        assert MARKS[Status.FAIL] in text
        assert "Apple Mobile Device Service is not running." in text, "the hint was dropped"

    def test_nothing_to_copy_is_not_a_crash(self, doctor: DoctorWindow) -> None:
        assert doctor.as_text() == ""


class TestRunningTheChecks:
    def test_the_thread_carries_the_report_back(
        self, qt_app: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The checks are async and the interface is not.

        `devices.doctor.run` waits on sockets with a two-second timeout apiece;
        on the interface thread that is a window frozen for as long as the
        diagnosis takes, which is longest in exactly the case somebody is
        running it.
        """
        del qt_app
        import ostrace.devices.doctor as module

        wanted = healthy()

        async def fake_run(udid: str | None = None) -> Report:
            del udid
            return wanted

        monkeypatch.setattr(module, "run", fake_run)
        seen: list[object] = []
        thread = DoctorThread()
        thread.reported.connect(seen.append)

        thread.run()  # on this thread: what `start` would do on its own

        assert seen == [wanted]

    def test_a_diagnosis_that_dies_says_so(
        self, qt_app: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A diagnosis that fails silently is the worst kind: the window that
        was opened to explain a problem explains nothing and looks broken."""
        del qt_app
        import ostrace.devices.doctor as module

        async def explode(udid: str | None = None) -> Report:
            del udid
            msg = "usbmux went away"
            raise OSError(msg)

        monkeypatch.setattr(module, "run", explode)
        seen: list[str] = []
        thread = DoctorThread()
        thread.failed.connect(seen.append)

        thread.run()

        assert seen
        assert "usbmux went away" in seen[0]

    def test_asking_twice_does_not_open_two_sessions(
        self, qt_app: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A second lockdown against a device is the thing this project
        already knows stalls the first."""
        del qt_app
        import ostrace.devices.doctor as module

        started = asyncio.Event()

        async def slow(udid: str | None = None) -> Report:
            del udid
            started.set()
            await asyncio.sleep(0.5)
            return healthy()

        monkeypatch.setattr(module, "run", slow)
        window = DoctorWindow()
        window.start()
        first = window._thread

        window.start()

        assert window._thread is first, "a second run was started under the first"
        window.close()


class TestReachingIt:
    def test_the_window_offers_it_from_help(self, qt_app: object) -> None:
        del qt_app
        window = MainWindow()

        assert window.action_doctor.isEnabled()
        assert window.action_doctor.shortcut().toString()

    def test_a_capture_that_died_offers_it_rather_than_a_retry(self, qt_app: object) -> None:
        """A capture that ran and then died is a different situation from one
        that never started. Pressing Capture again is one click away on the
        toolbar; what the user does not have is any way to find out why.
        """
        del qt_app
        window = MainWindow()

        window._on_capture_failed("device disconnected")

        assert "Diagnose" in window.banner._action.text()


class TestTheBannersThatEndADeadEnd:
    """Two states §6 calls "must be visible" that nothing made visible."""

    def test_an_outage_is_announced_while_it_is_happening(self, qt_app: object) -> None:
        """The `Gap` is the record of an outage and stays that -- it travels in
        the stream in position, which is where its meaning is. But it can only
        be written once the device is back, and the question somebody staring
        at a stalled window has is being asked several seconds before that.
        """
        del qt_app
        window = MainWindow()

        window._on_capture_state(CaptureState.RECONNECTING)

        assert window.banner.text == RECONNECT_MESSAGE
        assert "Disconnect" in window.banner._action.text(), (
            "the only decision left is whether to stop waiting"
        )

    def test_it_survives_the_trip_across_the_signal(self, qt_app: object) -> None:
        """The state crosses a thread as a Qt `Signal(str)`, and Qt converts.

        Measured: a `CaptureState` emitted through one arrives on the far side
        as a plain `str` -- `'reconnecting'`, type `str`, on both a direct and
        a queued connection. That is why the enum derives from `str`; an
        ordinary `Enum` would arrive as its own repr and match nothing here.

        Every other test in this class calls the handler directly and would
        pass either way.
        """
        del qt_app
        window = MainWindow()

        window.capture_state.emit(CaptureState.RECONNECTING)

        assert window.banner.text == RECONNECT_MESSAGE

    def test_coming_back_clears_it(self, qt_app: object) -> None:
        del qt_app
        window = MainWindow()
        window._on_capture_state(CaptureState.RECONNECTING)

        window._on_capture_state(CaptureState.STREAMING)

        assert window.banner.text == ""

    def test_coming_back_clears_nothing_else(self, qt_app: object) -> None:
        """A pause raised during the outage is a different state that is still
        true, and clearing it would leave the view frozen with nothing on
        screen saying why."""
        del qt_app
        window = MainWindow()
        window._on_capture_state(CaptureState.RECONNECTING)
        window.banner.show_message("The view is paused.", "Resume")

        window._on_capture_state(CaptureState.STREAMING)

        assert window.banner.text == "The view is paused."

    def test_the_end_of_a_capture_offers_an_export(self, qt_app: object) -> None:
        """Until now the records stopped arriving and the window said so in no
        way a person notices."""
        del qt_app
        window = MainWindow()
        window.model.append([make_record(index) for index in range(40)])

        window._on_capture_finished(None)

        assert "40" in window.banner.text
        assert "Export" in window.banner._action.text()
