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

from PySide6.QtWidgets import QApplication

from ostrace.gui.filters import Filter, SavedFilter, save
from ostrace.gui.markers import when
from ostrace.gui.settings import WindowSettings
from ostrace.gui.widgets.filter_bar import NO_RECENT, NO_SAVED, FilterBar
from ostrace.gui.widgets.saved_filters_dialog import SavedFiltersDialog
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


class TestWhetherTheBarNarrowsAnything:
    """The window asks this to tell "the device is quiet" from "your filter
    hides everything", which are the same empty table otherwise."""

    def test_an_untouched_bar_narrows_nothing(self, qt_app: object) -> None:
        del qt_app
        assert FilterBar().is_empty

    def test_a_half_typed_pattern_is_not_an_empty_bar(self, qt_app: object) -> None:
        """It is a narrowing the user is in the middle of writing, and the
        answer decides whether the window offers to clear a filter or explains
        that the capture is empty.

        Asked of the assembled filter now rather than of the five fields, so
        the bar and the filter cannot disagree about what empty means -- and
        assembling can fail, which the fields never could.
        """
        bar = FilterBar()
        bar._regex.setChecked(True)
        bar._search.setText("[unclosed")

        assert not bar.is_empty


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


class TestExcludingFromTheBar:
    """`≠` inside the field it modifies, rather than a checkbox after three."""

    def test_the_toggles_live_inside_the_fields_they_modify(self, qt_app: object) -> None:
        """A `Regex` checkbox sitting after three fields does not say which
        field it applies to, and a bar reading `Process [ ] Subsystem [ ] ≠`
        has one toggle and two candidates."""
        del qt_app
        bar = FilterBar()

        assert bar._process_exclude in bar._process.actions()
        assert bar._subsystem_exclude in bar._subsystem.actions()
        assert bar._regex in bar._search.actions()

    def test_every_toggle_says_what_it_is(self, qt_app: object) -> None:
        """An in-field action has no visible label at all, so anything reading
        the window gets the action's name or nothing."""
        del qt_app
        bar = FilterBar()

        for action, _glyph in bar._toggles:
            assert action.text(), "an unnamed in-field toggle is unreadable aloud"
            assert action.toolTip() != action.text(), "the tooltip repeats the name"

    def test_the_flags_reach_the_filter(self, qt_app: object) -> None:
        del qt_app
        bar = FilterBar()
        bar._process.setText("backupd")
        bar._process_exclude.setChecked(True)

        assert bar.current().process_exclude
        assert not bar.current().subsystem_exclude

    def test_a_whole_filter_including_its_flags_is_one_signal(self, qt_app: object) -> None:
        """Seven controls, one rescan. The count moved when the flags were
        added, which is the point of the bar writing them all together."""
        del qt_app
        bar = FilterBar()
        changes: list[int] = []
        bar.changed.connect(lambda: changes.append(1))
        wanted = Filter(
            minimum_level=Level.ERROR,
            process="a",
            subsystem="b",
            search="c",
            process_exclude=True,
            subsystem_exclude=True,
        )

        bar.set_filter(wanted)

        assert len(changes) == 1
        assert bar.current() == wanted


class TestTheFiltersMenu:
    """Both halves of going back to a filter, under one button."""

    def test_each_half_says_why_it_is_empty(self, qt_app: object) -> None:
        """A button that opens a menu with a blank section has been pressed and
        answered nothing."""
        del qt_app
        bar = FilterBar()

        assert bar.recent_entries == [NO_RECENT]
        assert bar.saved_entries == [NO_SAVED]

    def test_a_named_filter_is_offered_by_its_name(self, qt_app: object) -> None:
        del qt_app
        bar = FilterBar()

        bar.set_saved([SavedFilter("watchdog", Filter(process="watchdogd"))])

        assert bar.saved_entries == ["watchdog"]

    def test_choosing_a_named_one_carries_its_terms_not_its_name(self, qt_app: object) -> None:
        """The window puts a `Filter` in the bar. A menu that emitted the name
        would make the window look it up again in a list that may have moved
        while the menu was open."""
        del qt_app
        bar = FilterBar()
        terms = Filter(process="watchdogd")
        bar.set_saved([SavedFilter("watchdog", terms)])
        chosen: list[object] = []
        bar.recent_chosen.connect(chosen.append)

        bar._saved_actions[0].trigger()

        assert chosen == [terms]

    def test_saving_is_offered_but_refused_with_nothing_to_save(self, qt_app: object) -> None:
        """Present rather than hidden: a row that appears only once you have
        used the feature is one nobody discovers."""
        del qt_app
        bar = FilterBar()
        rows = {action.text(): action for action in bar._recent_menu.actions()}

        assert not rows["Save current filter…"].isEnabled()
        assert not rows["Manage saved filters…"].isEnabled()

    def test_saving_turns_on_as_soon_as_there_is_something_to_save(self, qt_app: object) -> None:
        del qt_app
        bar = FilterBar()

        bar.set_filter(Filter(process="dasd"))

        rows = {action.text(): action for action in bar._recent_menu.actions()}
        assert rows["Save current filter…"].isEnabled()


class TestCopyingTheFilter:
    """The half of a shareable filter that needs no parser."""

    def test_it_puts_the_text_form_on_the_clipboard(self, window: MainWindow) -> None:
        window.filter_bar.set_filter(
            Filter(minimum_level=Level.ERROR, process="backupd", process_exclude=True)
        )

        window.copy_filter()

        clipboard = QApplication.clipboard()
        assert clipboard is not None
        assert clipboard.text() == "level:error -process:backupd"

    def test_a_window_showing_everything_offers_nothing_to_copy(self, window: MainWindow) -> None:
        """`as_text` on an empty filter is an empty line, and a menu item that
        silently empties the clipboard is worse than one that is greyed."""
        assert not window.action_copy_filter.isEnabled()

        window.filter_bar.set_filter(Filter(process="dasd"))

        assert window.action_copy_filter.isEnabled()

    def test_a_half_typed_pattern_is_not_copied(self, window: MainWindow) -> None:
        """The model is still on the previous filter, and copying that would
        hand over the filter the user is leaving rather than the one in front
        of them."""
        window.filter_bar._search.setText("[unclosed")
        window.filter_bar._regex.setChecked(True)
        clipboard = QApplication.clipboard()
        assert clipboard is not None
        clipboard.setText("untouched")

        window.copy_filter()

        assert clipboard.text() == "untouched"


class TestNamedFiltersInTheWindow:
    """Kept, offered and written down, without a modal in the test."""

    def test_saving_one_offers_it_and_stores_it(self, window: MainWindow) -> None:
        entry = SavedFilter("watchdog", Filter(process="watchdogd"))

        window._set_saved(save(window._saved, entry))

        assert window.filter_bar.saved_entries == ["watchdog"]
        assert WindowSettings().read_saved() == [entry]

    def test_they_survive_a_restart(self, window: MainWindow) -> None:
        window._set_saved([SavedFilter("watchdog", Filter(process="watchdogd"))])

        reopened = MainWindow()

        assert reopened.filter_bar.saved_entries == ["watchdog"]
        assert reopened.model.filter.is_empty, "it was offered, not applied"

    def test_one_unreadable_entry_does_not_cost_the_others(self, window: MainWindow) -> None:
        window._set_saved([SavedFilter("watchdog", Filter(process="watchdogd"))])
        settings = WindowSettings()
        stored = settings.store.value("filters/saved")
        assert isinstance(stored, list)
        settings.store.setValue("filters/saved", ["{ not json", *stored])

        reopened = MainWindow()

        assert reopened.filter_bar.saved_entries == ["watchdog"]

    def test_the_dialog_removes_one_and_the_window_keeps_the_rest(self, window: MainWindow) -> None:
        """The dialog owns no settings: it is handed a list and returns one, so
        what is kept and where stays the window's decision."""
        keep = SavedFilter("errors", Filter(minimum_level=Level.ERROR))
        window._set_saved([keep, SavedFilter("watchdog", Filter(process="watchdogd"))])
        dialog = SavedFiltersDialog(window._saved, window)
        dialog.list.setCurrentRow(1)

        dialog._remove_selected()
        window._set_saved(dialog.saved)

        assert window.filter_bar.saved_entries == ["errors"]
        assert WindowSettings().read_saved() == [keep]

    def test_the_dialog_says_what_a_name_stands_for(self, window: MainWindow) -> None:
        """Two filters saved under different names are told apart by something
        other than the name being wrong."""
        window._set_saved([SavedFilter("watchdog", Filter(process="watchdogd"))])
        dialog = SavedFiltersDialog(window._saved, window)

        assert dialog.terms.text() == "process:watchdogd"

    def test_nothing_selected_disables_both_verbs(self, window: MainWindow) -> None:
        """A button that responds to a press by doing nothing is
        indistinguishable from one that is broken."""
        dialog = SavedFiltersDialog([], window)

        assert not dialog.rename.isEnabled()
        assert not dialog.remove.isEnabled()
