# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Narrowing a capture without retyping what is already on the screen.

The right-click and the recent list are one feature seen from two ends: the
first says "this, please" about a row in front of you, and the second says it
again tomorrow without you having to remember what you typed.

Against the real capture, because "the process on this row" is whatever the
device actually emitted, and a synthetic stand-in would agree with whatever the
implementation happened to do.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from ostrace.model import Gap, Level, Record
from tests.helpers import ERRORS

pytest.importorskip("PySide6", reason="the gui extra is not installed")

from ostrace.gui.filters import Filter
from ostrace.gui.markers import when
from ostrace.gui.settings import WindowSettings
from ostrace.gui.widgets.filter_bar import NO_RECENT, FilterBar
from ostrace.gui.windows.main import MainWindow
from ostrace.storage.capture import open_capture

if TYPE_CHECKING:
    from PySide6.QtWidgets import QMenu

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def capture_rows() -> list[Record | Gap]:
    return list(open_capture(ERRORS).items())


@pytest.fixture
def window(qt_app: object, capture_rows: list[Record | Gap]) -> MainWindow:
    del qt_app
    window = MainWindow()
    window.model.append(capture_rows)
    return window


def entries(menu: QMenu) -> list[str]:
    return [action.text() for action in menu.actions() if not action.isSeparator()]


class TestTheRowMenu:
    """Built by the window from actions the window already owns."""

    @staticmethod
    def _menu_for(window: MainWindow, row: int) -> QMenu:
        """The menu, built and not popped.

        `_on_context_menu` ends in a modal ``exec``, and a test that reaches
        one does not fail -- it hangs. So the window builds and pops in two
        methods and this drives the first, which is the same split the export
        dialog and `Go to Time` already use. Reaching for the second cost this
        suite two minutes and a killed job before the split existed.
        """
        window.go_to(row)
        return window.row_menu(window.model.index(row, 0))

    def test_it_offers_the_process_on_the_row(self, window: MainWindow) -> None:
        record = window.model.row_at(10)
        assert isinstance(record, Record)

        offered = entries(self._menu_for(window, 10))

        assert any(record.process in text and "process" in text for text in offered)

    def test_choosing_it_narrows_to_that_process(self, window: MainWindow) -> None:
        record = window.model.row_at(10)
        assert isinstance(record, Record)

        window.filter_by_process(record.process)
        window._apply_filter()

        assert window.model.rowCount() < len(window.model._rows)
        assert all(
            not isinstance(row := window.model.row_at(index), Record)
            or record.process in row.process
            for index in range(window.model.rowCount())
        )

    def test_it_keeps_the_rest_of_the_filter(self, window: MainWindow) -> None:
        """The right-click is almost always the second step: somebody already
        at `Error and above` who spots a noisy process wants the errors from
        it, not a fresh start."""
        window.filter_bar.set_filter(Filter(minimum_level=Level.ERROR))
        window._apply_filter()

        window.filter_by_process("dasd")
        window._apply_filter()

        assert window.model.filter.minimum_level is Level.ERROR
        assert window.model.filter.process == "dasd"

    def test_a_marker_row_is_not_offered_a_process(self, window: MainWindow) -> None:
        """A gap has none, and an entry that filtered by the empty string would
        quietly mean "everything" -- which is the opposite of narrowing."""
        start = when(window.model.row_at(0))
        window.model.append(
            [Gap(start=start, end=start + timedelta(seconds=2), reason="connection dropped")]
        )
        marker = window.model.rowCount() - 1
        assert not isinstance(window.model.row_at(marker), Record)

        offered = entries(self._menu_for(window, marker))

        assert not any("process" in text for text in offered)

    def test_it_always_offers_copy_and_mark(self, window: MainWindow) -> None:
        """Every entry is an action the window already owns, so the menu cannot
        drift from the keyboard."""
        offered = entries(self._menu_for(window, 10))

        assert window.action_copy.text() in offered
        assert window.action_mark.text() in offered


class TestTheRecentList:
    """Going back to a filter, without having named it first."""

    def test_it_starts_by_saying_there_is_nothing_yet(self, qt_app: object) -> None:
        """Rather than an empty menu, which has been pressed and answered
        nothing."""
        del qt_app
        bar = FilterBar()

        assert bar.recent_entries == [NO_RECENT]

    def test_a_filter_left_alone_is_remembered(self, window: MainWindow) -> None:
        """Driven off the settle timer rather than the apply, because every
        keystroke applies."""
        window.filter_bar.set_filter(Filter(process="dasd"))
        window._apply_filter()

        window._remember_filter()

        assert window.filter_bar.recent_entries == ["process dasd"]

    def test_a_filter_typed_through_is_not(self, window: MainWindow) -> None:
        """The prefixes of one filter are not four filters.

        Each edit restarts the settle timer, so nothing on the way to `dasd`
        ever stands long enough to count -- which is what this asserts by
        letting only the last one settle.
        """
        for text in ("d", "da", "das", "dasd"):
            window.filter_bar.set_filter(Filter(process=text))
            window._apply_filter()

        window._remember_filter()

        assert window.filter_bar.recent_entries == ["process dasd"]

    def test_choosing_one_puts_it_back_in_the_bar(self, window: MainWindow) -> None:
        wanted = Filter(minimum_level=Level.ERROR, process="dasd", search="timeout")

        window._on_recent_chosen(wanted)
        window._apply_filter()

        assert window.model.filter == wanted

    def test_it_survives_a_restart(self, window: MainWindow) -> None:
        """Offered, not applied. `_save_layout` refuses to remember the filter
        in force for a reason -- one that survives a restart is one the user
        has to remember they set -- and a filter merely on a menu changes
        nothing about what the window shows until somebody picks it.
        """
        window.filter_bar.set_filter(Filter(process="dasd"))
        window._apply_filter()
        window._remember_filter()

        reopened = MainWindow()

        assert reopened.filter_bar.recent_entries == ["process dasd"]
        assert reopened.model.filter.is_empty, "it was applied, not merely offered"

    def test_one_unreadable_entry_does_not_cost_the_others(self, window: MainWindow) -> None:
        window.filter_bar.set_filter(Filter(process="dasd"))
        window._apply_filter()
        window._remember_filter()
        settings = WindowSettings()
        stored = settings.store.value("filters/recent")
        assert isinstance(stored, list)
        settings.store.setValue("filters/recent", ["{ not json", *stored])

        reopened = MainWindow()

        assert reopened.filter_bar.recent_entries == ["process dasd"]


class TestSettingTheBar:
    """One change rather than five."""

    def test_a_whole_filter_is_one_signal(self, qt_app: object) -> None:
        """Five separate edits would be five `changed` signals and, through the
        debounce, up to five rescans of the whole capture on the way to the one
        that was asked for."""
        del qt_app
        bar = FilterBar()
        changes: list[int] = []
        bar.changed.connect(lambda: changes.append(1))

        bar.set_filter(Filter(minimum_level=Level.ERROR, process="a", subsystem="b", search="c"))

        assert changes == [1]

    def test_it_round_trips_through_the_widgets(self, qt_app: object) -> None:
        del qt_app
        bar = FilterBar()
        wanted = Filter(minimum_level=Level.FAULT, process="a", subsystem="b", search="c.*d")
        wanted = Filter(
            minimum_level=wanted.minimum_level,
            process=wanted.process,
            subsystem=wanted.subsystem,
            search=wanted.search,
            regex=True,
        )

        bar.set_filter(wanted)

        assert bar.minimum_level is Level.FAULT
        assert bar.process == "a"
        assert bar.subsystem == "b"
        assert bar.search == "c.*d"
        assert bar.regex

    def test_narrowing_by_process_leaves_the_other_fields_alone(self, qt_app: object) -> None:
        del qt_app
        bar = FilterBar()
        bar.set_filter(Filter(minimum_level=Level.ERROR, search="timeout"))

        bar.set_process("dasd")

        assert bar.process == "dasd"
        assert bar.minimum_level is Level.ERROR
        assert bar.search == "timeout"
