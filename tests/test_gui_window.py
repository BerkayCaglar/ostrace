# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The window shell: menu roles, table configuration, and the header fix.

These run offscreen on all three operating systems. What they can prove is
structure -- that a rule the design document states is actually wired up. What
they cannot prove is appearance, because the offscreen plugin has no platform
theme and no fonts; that is what the screenshot job is for.

The macOS menu-role test is the most valuable thing in this file. Qt silently
relocates menu items on macOS by matching their text, every action defaults to
being eligible, and there is no Mac here to notice.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the gui extra is not installed")

from PySide6.QtCore import (
    QAbstractTableModel,
    QMetaMethod,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
)
from PySide6.QtGui import QAction, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QHeaderView,
    QStyle,
    QStyleOptionHeader,
    QStyleOptionViewItem,
    QTableView,
)

from ostrace.gui.columns import COLUMNS, Column
from ostrace.gui.models import RecordModel
from ostrace.gui.shortcuts import BINDINGS, RELOCATED
from ostrace.gui.theme import Scheme, palette_for, selection_row, severity_for, token
from ostrace.gui.widgets.log_table import (
    MESSAGE_MINIMUM,
    FastHeader,
    LogTable,
    MiddleElidingDelegate,
    SeverityDelegate,
)
from ostrace.gui.windows.main import MainWindow
from ostrace.model import Level
from tests.helpers import ERRORS, load, make_record

pytestmark = pytest.mark.gui

#: Qt hands either kind to a model, and the stubs say so.
_Index = QModelIndex | QPersistentModelIndex


@pytest.fixture
def window(qt_app: QApplication) -> MainWindow:
    del qt_app  # required so that exactly one QApplication exists first
    return MainWindow()


@pytest.mark.parametrize("scheme", list(Scheme))
def test_the_table_paints_the_scheme_it_was_given(qt_app: QApplication, scheme: Scheme) -> None:
    """A pixel, not a palette, because the palette was right and the paint was
    not.

    A scroll area paints its background from the *viewport's* palette, and the
    viewport ends up holding one of its own with every role explicitly
    resolved -- after which nothing set on the view reaches it. Measured with
    the table's ``Base`` correctly at ``#1b1e24`` and the viewport still
    painting ``#ffffff``: rows carrying `AlternateBase` came out dark and the
    ones showing the background stayed white, so the dark theme rendered as
    white stripes through a dark table. Every assertion that read
    ``table.palette()`` passed throughout.
    """
    del qt_app
    table = LogTable(scheme=scheme)
    table.resize(400, 200)
    table.show()
    QApplication.processEvents()

    painted = table.viewport().grab().toImage().pixelColor(20, 20)

    assert painted == token("surface-raised", scheme)


def test_a_theme_switch_reaches_the_paint(qt_app: QApplication) -> None:
    """And it has to keep reaching it after the table has been built."""
    del qt_app
    table = LogTable(scheme=Scheme.LIGHT)
    table.resize(400, 200)
    table.show()
    QApplication.processEvents()

    table.set_scheme(Scheme.DARK)
    QApplication.processEvents()

    painted = table.viewport().grab().toImage().pixelColor(20, 20)
    assert painted == token("surface-raised", Scheme.DARK)


class TestTheColumnsFitTheWindow:
    """`stretchLastSection` only grows the last section into space left over.

    When the columns before it have used the window there is nothing left, so
    it keeps its default hundred pixels and the table scrolls sideways -- with
    no rows in it, which is how this was noticed. Measured on the shipped
    budgets at a 1,280-pixel window: five fixed columns of 91 characters came
    to 1,183 pixels of a 1,254-pixel viewport, leaving the message 71.
    """

    @pytest.fixture
    def table(self, qt_app: QApplication) -> LogTable:
        del qt_app
        table = LogTable()
        table.setModel(RecordModel())
        table.resize(1280, 400)
        table.show()
        QApplication.processEvents()
        return table

    def test_the_message_keeps_room_to_be_read(self, table: LogTable) -> None:
        unit = table.fontMetrics().horizontalAdvance("0")
        message = table.columnWidth(int(Column.MESSAGE))
        assert message >= MESSAGE_MINIMUM * unit, f"the message got {message // unit} characters"

    def test_nothing_overflows_the_window(self, table: LogTable) -> None:
        widths = sum(table.columnWidth(index) for index in range(len(COLUMNS)))
        assert widths <= table.viewport().width()
        assert table.horizontalScrollBar().maximum() == 0

    def test_the_two_columns_with_a_known_length_are_not_trimmed(self, table: LogTable) -> None:
        """A timestamp missing its last digits is a timestamp nobody can use,
        and `Level` has to fit ``User Action`` and its glyph."""
        unit = table.fontMetrics().horizontalAdvance("0")
        for column in (Column.TIME, Column.LEVEL):
            budget = COLUMNS[int(column)].characters
            assert budget is not None
            assert table.columnWidth(int(column)) >= budget * unit

    def test_restored_widths_are_not_overruled(self, table: LogTable) -> None:
        """They are a decision the user already made."""
        wanted = [300, 300, 300, 300, 300, 300]
        table.restore_column_widths(wanted)
        table.resize(900, 400)
        QApplication.processEvents()

        assert table.columnWidth(int(Column.TIME)) == 300


def test_no_action_shows_an_icon_in_a_menu(window: MainWindow) -> None:
    """The toolbar and the menus share their action objects.

    So an icon put on one for the toolbar's sake is drawn by the other in the
    column a checkmark occupies: the two jump actions carry chevrons, and
    `Next` and `Previous` therefore appeared in the View menu with what reads
    as a tick and an indicator beside them -- a few rows above a `Dark Mode`
    whose tick is real.
    """
    wearing = [
        action.text()
        for action in window.menu_items()
        if action.isIconVisibleInMenu() and not action.icon().isNull()
    ]
    assert not wearing, f"{wearing} draw an icon where a checkmark goes"


def test_the_two_relocated_actions_are_wired_to_something(
    qt_app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Quit and About are built apart from the other twenty because macOS moves
    them by menu role, and being built apart is how their wiring came to be the
    one pair nothing asserted. Measured: removing both connections leaves all
    369 GUI tests green, and the window then has a Quit that does nothing.

    Both targets are replaced rather than called. `show_about` opens a modal
    `QMessageBox`, and a modal in a test run waits for a person; `close` would
    take the window's layout-saving path with it. What is under test is the
    connection, which is what the move could lose.
    """
    del qt_app
    called: list[str] = []
    monkeypatch.setattr(MainWindow, "close", lambda self: called.append("quit"))
    monkeypatch.setattr(MainWindow, "show_about", lambda self: called.append("about"))
    window = MainWindow()

    window.action_quit.trigger()
    window.action_about.trigger()

    assert called == ["quit", "about"]


def test_the_view_menu_is_divided_into_runs(window: MainWindow) -> None:
    """Eleven items in one undivided column is a list nobody reads to the end
    of, and the grouping is declared in the bindings table so that a reordered
    item cannot leave a divider stranded behind it."""
    view = window.menus["view"]
    separators = [action for action in view.actions() if action.isSeparator()]

    assert separators, "the View menu is one flat run"
    assert not view.actions()[0].isSeparator(), "a divider above the first item"
    assert not view.actions()[-1].isSeparator(), "a divider below the last item"


class TestClosingACapture:
    """There was no way back to an empty window.

    A loaded capture, a narrowed filter, a selected row, a device in the status
    bar and a file name in the title were all reachable, and none of it was
    reversible without quitting the program.
    """

    def test_it_empties_everything(self, window: MainWindow) -> None:
        load(window, ERRORS)
        window.filter_bar._process.setText("cloudd")

        window.close_capture()

        assert window.capture is None
        assert window.model.rowCount() == 0
        assert window.filter_bar.is_empty, "the next capture would be read through this filter"
        assert window.windowTitle() == "ostrace"
        assert window.detail.field("Nothing selected") is not None

    def test_it_refuses_while_a_capture_is_running(self, window: MainWindow) -> None:
        """Disconnect releases the device and finalises the session. Doing that
        silently because somebody asked for an empty window would throw away a
        recording in progress."""
        window._capture_thread = object()  # type: ignore[assignment]
        try:
            window.close_capture()
            assert "still running" in window.banner.text
        finally:
            window._capture_thread = None


# -- the macOS menu heuristic ------------------------------------------------


def test_no_menu_item_is_left_on_the_text_heuristic(window: MainWindow) -> None:
    """Every item declares whether macOS may move it.

    ``TextHeuristicRole`` is the default, so an action is opted *into* being
    relocated by saying nothing. An item whose text contains "settings",
    "options", "preferences", "config" or "setup" then vanishes from its own
    menu into the application menu -- on the one platform that cannot be
    tested here, and only there.
    """
    stragglers = [
        action.text()
        for action in window.menu_items()
        if action.menuRole() == QAction.MenuRole.TextHeuristicRole
    ]
    assert not stragglers


def test_the_items_macos_should_relocate_say_so(window: MainWindow) -> None:
    """Opting out everywhere would be as wrong as opting in everywhere.

    Quit and About genuinely belong in the application menu on macOS;
    suppressing that would make the program feel foreign there. The rule is
    *explicit*, not *never move*.

    There is no Settings. Nothing in this release is configurable, and an
    inert Preferences item is worst on the very platform this role machinery
    exists for -- Qt moves it into the application menu, where it is the item
    people press without looking.
    """
    assert window.action_quit.menuRole() == QAction.MenuRole.QuitRole
    assert window.action_about.menuRole() == QAction.MenuRole.AboutRole
    assert not hasattr(window, "action_settings")


def test_every_menu_item_actually_does_something(window: MainWindow) -> None:
    """The gap the menu audit found: two items were connected to nothing.

    An enabled menu entry that fires no slot is indistinguishable from a broken
    program, and it was the *only* place the viewer could have told anyone its
    version. Asserted by counting receivers rather than by pressing each one,
    because pressing them opens modal dialogs.
    """
    unwired = [
        action.text()
        for action in window.menu_items()
        if not action.isSeparator()
        and not action.isSignalConnected(QMetaMethod.fromSignal(action.triggered))
    ]
    assert not unwired


def test_the_menus_outlive_the_method_that_built_them(window: MainWindow) -> None:
    """A regression test for a real bug in this file's history.

    ``bar.addMenu("title")`` returns a menu Python owns. Built into a local,
    every menu was destroyed when ``_build_menus`` returned, and the menu bar
    was left holding actions whose ``menu()`` handed back a fresh wrapper
    around freed memory -- which reports itself valid until it is used.
    """
    import gc

    import shiboken6

    gc.collect()
    assert all(shiboken6.isValid(menu) for menu in window.menus.values())
    # Derived rather than a literal: every binding becomes one item, plus Quit
    # and About, whose menu roles rather than their keys are the point.
    assert len(window.menu_items()) == len(BINDINGS) + len(RELOCATED)


def test_pause_and_disconnect_are_separate_actions(window: MainWindow) -> None:
    """Conflating them is how a "pause" loses the records it promised to keep.

    Pause is a view state; disconnect releases the device, and releasing the
    device releases the ``os_trace_relay`` service with it.
    """
    assert window.action_pause.isCheckable()
    assert not window.action_disconnect.isCheckable()
    assert "Stop" not in window.action_disconnect.text()


# -- the table ---------------------------------------------------------------


def test_the_table_never_wraps_or_autosizes(window: MainWindow) -> None:
    """Both defeat the fixed row height, in different ways.

    Wrapping forces a per-row height computation; ``ResizeToContents`` on the
    vertical header queries every row regardless of what is visible
    (QTBUG-57848, open since 2016).
    """
    table = window.table
    assert not table.wordWrap()
    assert table.textElideMode() == Qt.TextElideMode.ElideRight
    vertical = table.verticalHeader()
    assert vertical.sectionResizeMode(0) == QHeaderView.ResizeMode.Fixed
    assert vertical.defaultSectionSize() > 0


def test_the_table_uses_the_fast_header(window: MainWindow) -> None:
    assert isinstance(window.table.horizontalHeader(), FastHeader)


def test_the_fast_header_still_shows_the_column_titles(qt_app: QApplication) -> None:
    """A regression test for a bug this file's optimisation caused.

    ``FastHeader`` skips ``super().initStyleOptionForIndex`` because the
    selection query in it is quadratic — but the base method is also what fills
    in the section's *text*. The first version skipped the lot and painted a
    header with no titles at all: faster still, and a direct loss of the thing
    the class was chosen to preserve over simply hiding the header.

    Nothing failed. The suite passed, the benchmark improved, and only a
    screenshot showed the empty strip.
    """
    del qt_app
    table = LogTable()
    table.setModel(_CountingModel(rows=5))
    header = table.horizontalHeader()
    assert isinstance(header, FastHeader)

    option = QStyleOptionHeader()
    header.initStyleOptionForIndex(option, 0)

    assert option.text == "col 0"
    assert option.section == 0


class _CountingModel(QAbstractTableModel):
    """Counts ``flags()``, which is where the header bug shows up."""

    def __init__(self, rows: int, columns: int = 6) -> None:
        super().__init__()
        self._rows = rows
        self._columns = columns
        self._flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        self.flag_calls = 0

    def rowCount(self, parent: _Index | None = None) -> int:  # noqa: N802
        return 0 if parent is not None and parent.isValid() else self._rows

    def columnCount(self, parent: _Index | None = None) -> int:  # noqa: N802
        return 0 if parent is not None and parent.isValid() else self._columns

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> str | None:
        del index
        return "x" if role == Qt.ItemDataRole.DisplayRole else None

    def headerData(  # noqa: N802
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> str | None:
        del orientation
        return f"col {section}" if role == Qt.ItemDataRole.DisplayRole else None

    def flags(self, index: _Index) -> Qt.ItemFlag:
        del index
        self.flag_calls += 1
        return self._flags


ROWS = 20_000


def test_the_fast_header_stops_selection_being_quadratic(qt_app: QApplication) -> None:
    """The behavioural test for the single biggest performance lever here.

    Asserted on call counts rather than on elapsed time: the count is the
    mechanism -- the header asks the selection model, per section, whether a
    whole column is selected -- and a wall-clock threshold on a shared CI
    runner is a flaky test wearing a performance test's clothes.

    The counts below are from this same stand-in model, and that is the whole
    reason the *time* is not asserted anywhere. Measured at 200k rows against
    a `_CountingModel`, the header is worth 4.06 s → 0.008 s; against the real
    `RecordModel` it is 5.98 s → 2.92 s, about 2x, because the remaining time
    is the selection model and the repaint. A model that does nothing makes
    the header look like the whole cost. The call counts are the mechanism and
    they hold either way.
    """

    def flag_calls(*, fast: bool) -> int:
        model = _CountingModel(ROWS)
        view = QTableView()
        if fast:
            view.setHorizontalHeader(FastHeader(Qt.Orientation.Horizontal, view))
        view.setModel(model)
        view.resize(900, 600)
        view.show()
        model.flag_calls = 0
        view.selectAll()
        # The cost is in the repaint, not in selectAll() itself. Without this
        # the header never paints, nothing queries the selection model, and
        # both variants score a flattering zero.
        qt_app.processEvents()
        view.hide()
        return model.flag_calls

    stock = flag_calls(fast=False)
    fast = flag_calls(fast=True)
    assert stock > ROWS, "the stock header should query per row -- did Qt fix QTBUG-59478?"
    assert fast < 1_000, f"FastHeader still made {fast:,} flags() calls"


def test_column_widths_come_from_the_font_not_from_pixels(qt_app: QApplication) -> None:
    """No fixed pixel sizes: macOS cannot disable High DPI scaling at all, and
    reports an integer device pixel ratio where Windows allows fractional.

    Sizing happens on ``setModel`` rather than in the constructor. That is not
    incidental -- ``setColumnWidth`` addresses a column that exists, and before
    a model is attached there are none, so the constructor's call was silently
    doing nothing until this test asked.
    """
    del qt_app
    table = LogTable()
    assert table.columnWidth(0) == 0, "no model, no columns, nothing to size"

    table.setModel(_CountingModel(rows=1))
    unit = table.fontMetrics().horizontalAdvance("0")
    assert table.columnWidth(0) > 13 * unit, "the character budget, plus the style's own margins"


def test_the_time_column_holds_a_whole_timestamp(qt_app: object) -> None:
    """The column budget is characters; the style then insets the text.

    Spending the budget on the column and the margins on the text elides the
    last character of any value sized to fit exactly, which the timestamp is.
    It did not show while the body font was proportional -- `09:14:02.118` is
    mostly colons and full stops, narrower than the `0` the budget counts in --
    and it appeared the moment the body became monospaced, where every
    character is the unit.

    Asserted as a relation rather than a number: the offscreen plugin has an
    empty font database on Windows and reports a fictional advance, which is
    fine here because both sides of the comparison use the same fiction.
    """
    del qt_app
    table = LogTable()
    table.setModel(_CountingModel(rows=1))

    inset = table.style().pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, None, table) + 1
    available = table.columnWidth(int(Column.TIME)) - 2 * inset
    assert available >= table.fontMetrics().horizontalAdvance("09:14:02.118")


# -- status, banner, filter --------------------------------------------------


def test_the_gap_count_is_shown_even_when_it_is_zero(window: MainWindow) -> None:
    """Wireshark bug 12005: a counter shown only when non-zero regressed to
    never showing, and nobody could tell "no drops" from "counter broken"."""
    assert window.status.gap_text == "0 gaps"
    window.status.set_gap_count(1)
    assert window.status.gap_text == "1 gap"


def test_the_banner_is_hidden_until_there_is_something_to_say(window: MainWindow) -> None:
    assert window.banner.text == ""


def test_the_banner_offers_the_way_out_of_a_filter(window: MainWindow) -> None:
    """A banner without a recovery action is a toolbar icon with extra steps."""
    window.filter_bar._search.setText("something that matches nothing")
    window.banner.show_message(
        "All records are hidden by the filter",
        "Clear filter",
        on_action=window.filter_bar.clear,
    )
    # Read into locals rather than asserting the same property twice. mypy
    # narrows a member expression on an assert and does not un-narrow it across
    # the call that changes it, so the second assertion would be reported as
    # unreachable -- which is a fair complaint about the test, not the code.
    filtered_before, shown = window.filter_bar.is_empty, window.banner.text

    # Press the button, rather than emitting the signal it happens to send.
    # What the button *does* is carried with the message, so a test that fires
    # the signal directly would be testing a path no user can take.
    window.banner.act()
    filtered_after, hidden = window.filter_bar.is_empty, window.banner.text

    assert not filtered_before
    assert shown
    assert filtered_after
    assert not hidden


def test_clearing_the_filter_emits_once_not_once_per_field(window: MainWindow) -> None:
    """Five signals mean five rescans of the whole capture."""
    window.filter_bar._process.setText("dasd")
    window.filter_bar._subsystem.setText("com.apple")

    emissions = []
    window.filter_bar.changed.connect(lambda: emissions.append(1))
    window.filter_bar.clear()
    assert len(emissions) == 1


def test_the_process_column_keeps_the_pid_when_it_does_not_fit(qt_app: QApplication) -> None:
    """`docs/design/gui.md` §2: the `[pid]` is never the part that gets
    truncated. The table elided right, which drops exactly that.

    The pid is what tells eight instances of one process apart, and the
    plaintext exporter already takes trouble to keep it. Asserted through the
    elide mode the delegate sets rather than by measuring a rendered string:
    the offscreen font database is empty on Windows, so a width in pixels there
    describes a face nobody sees.
    """
    del qt_app
    table = LogTable()
    delegate = table.itemDelegateForColumn(int(Column.PROCESS))
    assert isinstance(delegate, MiddleElidingDelegate)

    option = QStyleOptionViewItem()
    delegate.initStyleOption(option, QModelIndex())
    assert option.textElideMode == Qt.TextElideMode.ElideMiddle

    assert table.textElideMode() == Qt.TextElideMode.ElideRight, (
        "the message column still wants its beginning"
    )


def test_a_selected_row_keeps_the_colour_of_its_level(qt_app: object) -> None:
    """Selecting a row used to delete the one signal the table exists to carry.

    `QStyledItemDelegate.initStyleOption` puts the model's `ForegroundRole` into
    the palette's `Text`, and the style then draws a selected row with
    `HighlightedText` instead -- so clicking an Error to read it was the moment
    it stopped looking like an Error. Only the glyph survived.

    Both roles carry the severity brush now. What makes that safe rather than
    merely different is the table's own `Highlight`, which is
    `theme.selection_row`; `test_gui_theme` asserts every level clears AA on it.
    """
    del qt_app
    model = RecordModel(Scheme.LIGHT)
    model.append([make_record(0, level=Level.ERROR)])
    table = LogTable(scheme=Scheme.LIGHT)
    table.setModel(model)

    index = model.index(0, int(Column.MESSAGE))
    option = QStyleOptionViewItem()
    delegate = table.itemDelegate()
    # Asserted rather than cast: the whole point is that the table's default
    # delegate is this one, so a change that dropped it should fail here.
    assert isinstance(delegate, SeverityDelegate)
    delegate.initStyleOption(option, index)

    expected = severity_for(Level.ERROR, Scheme.LIGHT).foreground
    assert option.palette.color(QPalette.ColorRole.Text) == expected
    assert option.palette.color(QPalette.ColorRole.HighlightedText) == expected


def test_the_table_selection_is_not_the_application_highlight(qt_app: object) -> None:
    """A saturated bar across a log row destroys the severity colours under it.

    The application's `Highlight` stays saturated, because a menu or a text
    selection that used a wash would read as nothing having happened.
    """
    del qt_app
    table = LogTable(scheme=Scheme.DARK)
    assert table.palette().highlight().color() == selection_row(Scheme.DARK)
    assert table.palette().highlight().color() != palette_for(Scheme.DARK).highlight().color()
