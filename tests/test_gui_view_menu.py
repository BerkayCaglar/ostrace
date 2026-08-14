# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the View menu got: marks you can list, columns you can turn off.

Plus the two things that live nowhere else -- the strip's keyboard, and the
bar folding when the window is narrow.

Against the real capture wherever the answer depends on what a device emitted:
which rows are marked is the user's doing, but what a marked row *reads* as is
the device's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ostrace.model import Gap, Record
from tests.helpers import ERRORS

pytest.importorskip("PySide6", reason="the gui extra is not installed")

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from ostrace.gui.columns import COLUMNS, Column
from ostrace.gui.filters import Filter
from ostrace.gui.settings import WindowSettings
from ostrace.gui.widgets.filter_bar import WRAP_WIDTH, FilterBar
from ostrace.gui.widgets.marks_panel import NO_MARKS
from ostrace.gui.windows.main import MainWindow
from ostrace.storage.capture import open_capture

if TYPE_CHECKING:
    from ostrace.gui.widgets.minimap import Minimap

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


def press(widget: Minimap, key: Qt.Key) -> None:
    """Send one key, the way the platform would."""
    widget.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


class TestTheMarksPanel:
    """Marking has existed since phase 4 and the only way back to a mark was to
    step through them one at a time."""

    def test_it_starts_hidden(self, window: MainWindow) -> None:
        """It is the one part of this window that is only sometimes wanted."""
        assert window.marks_panel.isHidden()
        assert not window.action_marks_panel.isChecked()

    def test_it_says_why_it_is_empty(self, window: MainWindow) -> None:
        assert window.marks_panel.entries == [NO_MARKS]

    def test_marking_a_row_puts_it_in_the_list(self, window: MainWindow) -> None:
        window.go_to(12)
        window.toggle_mark()

        assert len(window.marks_panel.entries) == 1
        record = window.model.row_at(12)
        assert isinstance(record, Record)
        assert record.process in window.marks_panel.entries[0]

    def test_unmarking_takes_it_out_again(self, window: MainWindow) -> None:
        window.go_to(12)
        window.toggle_mark()
        window.toggle_mark()

        assert window.marks_panel.entries == [NO_MARKS]

    def test_choosing_one_goes_there(self, window: MainWindow) -> None:
        window.go_to(40)
        window.toggle_mark()
        window.go_to(0)

        window.marks_panel.list.item(0).setSelected(True)
        window.marks_panel._on_activated(window.marks_panel.list.item(0))

        assert window.table.currentIndex().row() == 40

    def test_a_mark_the_filter_hides_is_not_offered(self, window: MainWindow) -> None:
        """The panel is a way back to something on screen. An entry that
        selected nothing would look broken."""
        window.go_to(12)
        window.toggle_mark()
        record = window.model.row_at(12)
        assert isinstance(record, Record)

        window.filter_bar.set_filter(Filter(process=record.process, process_exclude=True))
        window._apply_filter()

        assert window.marks_panel.entries == [NO_MARKS]

    def test_clearing_the_marks_empties_it(self, window: MainWindow) -> None:
        window.go_to(12)
        window.toggle_mark()

        window.clear_marks()

        assert window.marks_panel.entries == [NO_MARKS]

    def test_closing_it_by_its_own_cross_unticks_the_menu(self, window: MainWindow) -> None:
        """`setChecked` emits `toggled`, which is wired to the verb -- so a
        panel closed by its own control would tick the item back on and reopen
        it. The theme switch had this bug first."""
        window.action_marks_panel.setChecked(True)
        assert not window.marks_panel.isHidden()

        window.marks_panel.close()

        assert not window.action_marks_panel.isChecked()
        assert window.marks_panel.isHidden()


class TestTheColumnChooser:
    """Over the visibility that `QSettings` was documented as keeping and did
    not: `Layout` carried widths and nothing else."""

    def test_every_column_has_a_tick_and_they_all_start_on(self, window: MainWindow) -> None:
        assert set(window.column_actions) == {spec.column for spec in COLUMNS}
        assert all(action.isChecked() for action in window.column_actions.values())

    def test_unticking_one_hides_it(self, window: MainWindow) -> None:
        window.column_actions[Column.CATEGORY].setChecked(False)

        assert window.table.isColumnHidden(int(Column.CATEGORY))
        assert not window.table.isColumnHidden(int(Column.MESSAGE))

    def test_the_last_column_cannot_be_turned_off(self, window: MainWindow) -> None:
        """A table with every column hidden is a window with nothing in it and
        no way to see why -- and it looks exactly like a capture that failed to
        load."""
        for spec in COLUMNS[:-1]:
            window.column_actions[spec.column].setChecked(False)

        assert not window.column_actions[Column.MESSAGE].isEnabled()
        assert not window.table.isColumnHidden(int(Column.MESSAGE))

    def test_the_guard_lifts_again(self, window: MainWindow) -> None:
        for spec in COLUMNS[:-1]:
            window.column_actions[spec.column].setChecked(False)

        window.column_actions[Column.TIME].setChecked(True)

        assert all(action.isEnabled() for action in window.column_actions.values())

    def test_the_choice_survives_a_restart(self, window: MainWindow) -> None:
        window.column_actions[Column.CATEGORY].setChecked(False)
        window._save_layout()

        reopened = MainWindow()

        assert not reopened.column_actions[Column.CATEGORY].isChecked()
        assert reopened.table.isColumnHidden(int(Column.CATEGORY))

    @pytest.mark.parametrize(
        "stored",
        [
            [],
            ["not a number"],
            [0, 99],
            "not a list",
        ],
    )
    def test_an_unreadable_choice_shows_everything(
        self, window: MainWindow, stored: object
    ) -> None:
        """Every rejection ends at "all of them". Showing a column that was
        meant to be hidden costs a glance; hiding one that was meant to be shown
        is a value somebody concludes the device never emitted."""
        del window
        settings = WindowSettings()
        settings.store.setValue("table/shown", stored)

        assert settings.read_layout().shown_columns is None


class TestTheStripsKeyboard:
    """A control that can only be reached with a mouse is one a keyboard user
    cannot know is there."""

    def test_it_takes_focus(self, window: MainWindow) -> None:
        assert window.minimap.focusPolicy() != Qt.FocusPolicy.NoFocus

    def test_down_and_up_step_by_a_band(self, window: MainWindow) -> None:
        asked: list[int] = []
        window.minimap.row_requested.connect(asked.append)
        window.minimap.set_viewport(1_000, 1_040)

        press(window.minimap, Qt.Key.Key_Down)
        press(window.minimap, Qt.Key.Key_Up)

        assert len(asked) == 2
        assert asked[0] > 1_000
        assert asked[1] < 1_000

    def test_the_ends_are_the_capture_not_the_strip(self, window: MainWindow) -> None:
        asked: list[int] = []
        window.minimap.row_requested.connect(asked.append)

        press(window.minimap, Qt.Key.Key_Home)
        press(window.minimap, Qt.Key.Key_End)

        assert asked == [0, window.model.rowCount() - 1]

    def test_a_step_never_leaves_the_capture(self, window: MainWindow) -> None:
        asked: list[int] = []
        window.minimap.row_requested.connect(asked.append)
        window.minimap.set_viewport(0, 40)

        press(window.minimap, Qt.Key.Key_PageUp)

        assert asked == [0]

    def test_the_strip_says_when_it_begins_and_ends(self, window: MainWindow) -> None:
        """The research asked for these drawn at the strip's ends. Measured,
        they do not fit: the strip is 12 px and the shortest usable reading
        needs 27."""
        window.minimap.rebuild()

        first = window.model.cell_text(0, int(Column.TIME))
        assert first in window.minimap.toolTip()

    def test_an_empty_capture_says_nothing_about_when(self, qt_app: object) -> None:
        del qt_app
        empty = MainWindow()

        # The span is appended on its own line. Not a search for `" to "`,
        # which the base sentence already contains in "Click to jump" -- the
        # first version of this asserted exactly that and would have failed on
        # a capture that *did* have a span.
        assert empty.minimap.toolTip().count(chr(10)) == 0


class TestTheBarFolding:
    """Wrapping rather than scrolling sideways: a bar that scrolls hides the
    field people reach for most."""

    def test_it_is_flat_when_there_is_room(self, qt_app: object) -> None:
        del qt_app
        bar = FilterBar()
        bar.show()
        bar.resize(QSize(WRAP_WIDTH + 200, bar.sizeHint().height()))
        QApplication.processEvents()

        assert not bar._wrapped

    def test_it_folds_when_there_is_not(self, qt_app: object) -> None:
        del qt_app
        bar = FilterBar()
        # Shown, because a widget that has never been shown gets no resize
        # event and the fold is decided in one.
        bar.show()
        bar.resize(QSize(WRAP_WIDTH - 200, bar.sizeHint().height()))
        QApplication.processEvents()

        assert bar._wrapped

    def test_folding_gives_the_search_field_more_room_than_not(self, qt_app: object) -> None:
        """The whole justification, and the thing the first attempt at
        measuring it got wrong by comparing two bars that both followed the
        rule -- so each was compared against itself."""
        del qt_app

        class Pinned(FilterBar):
            def resizeEvent(self, event: object) -> None:  # noqa: N802 - Qt's name
                del event

        flat, folded = Pinned(), Pinned()
        folded._lay_out(wrapped=True)
        for bar in (flat, folded):
            bar.show()
            bar.resize(QSize(WRAP_WIDTH - 160, 64))
        QApplication.processEvents()

        assert folded._search.width() > flat._search.width()

    def test_every_control_survives_the_fold(self, qt_app: object) -> None:
        """A layout rebuilt by re-adding widgets is one that can lose a
        widget by forgetting a line."""
        del qt_app
        bar = FilterBar()
        controls = [bar._level, bar._process, bar._subsystem, bar._search, bar.recent]

        bar._lay_out(wrapped=True)
        bar._lay_out(wrapped=False)

        laid_out = {
            item.widget()
            for index in range(bar._grid.count())
            if (item := bar._grid.itemAt(index)) is not None
        }
        assert all(control in laid_out for control in controls)


class TestCopyingJustTheMessage:
    def test_it_leaves_the_other_five_columns_behind(self, window: MainWindow) -> None:
        """A tab-separated record with a timestamp, a level, a process, a
        subsystem and a category in front of the sentence is six fields of
        context around the one thing somebody wanted to quote."""
        window.go_to(12)
        window.table.selectRow(12)

        window.copy_message()

        clipboard = QApplication.clipboard()
        assert clipboard is not None
        assert clipboard.text() == window.model.cell_text(12, int(Column.MESSAGE))

    def test_nothing_selected_copies_nothing(self, window: MainWindow) -> None:
        clipboard = QApplication.clipboard()
        assert clipboard is not None
        clipboard.setText("untouched")
        window.table.clearSelection()

        window.copy_message()

        assert clipboard.text() == "untouched"


class TestTheSearchHighlight:
    """Drawn where the term hit, which answers "why did this row match?"."""

    def test_the_delegate_is_told_what_the_model_was_told(self, window: MainWindow) -> None:
        wanted = Filter(search="timeout")

        window.filter_bar.set_filter(wanted)
        window._apply_filter()

        assert window.table.message_delegate._filter == window.model.filter

    def test_it_finds_every_occurrence_and_no_empty_ones(self) -> None:
        """A pattern like `a*` matches the empty string between every pair of
        characters, and a highlight of nothing at every position is a row
        painted solid."""
        assert Filter(search="ab").spans("abcab") == [(0, 2), (3, 5)]
        assert Filter(search="b*", regex=True).spans("abc") == [(1, 2)]

    def test_a_filter_with_no_search_highlights_nothing(self) -> None:
        assert Filter(process="dasd").spans("dasd said something") == []
