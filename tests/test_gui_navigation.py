# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Moving around a log, marking it, and copying out of it.

Against a real capture, because what "next error" means depends on what the
device actually emitted -- the error-heavy fixture holds 2,187 Errors and 63
Faults among 3,000 records, and a synthetic stand-in would agree with whatever
the implementation happened to do.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ostrace.model import Gap, Level, Record
from tests.helpers import ERRORS, make_record

pytest.importorskip("PySide6", reason="the gui extra is not installed")

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QAbstractSlider, QApplication

from ostrace.gui.columns import Column
from ostrace.gui.filters import Filter
from ostrace.gui.models import Find, RecordModel
from ostrace.gui.theme import Scheme
from ostrace.gui.windows.main import MainWindow
from ostrace.storage.capture import open_capture

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


# -- navigation --------------------------------------------------------------


def test_next_error_lands_on_an_error(window: MainWindow) -> None:
    window.go_to(0)
    window.find_next(Find.ERROR)

    row = window.model.row_at(window.table.currentIndex().row())
    assert isinstance(row, Record)
    assert row.is_error


def test_next_error_wraps_rather_than_stopping(window: MainWindow) -> None:
    """A log is read in a loop. A "next error" that goes quiet at the end of
    the buffer looks broken rather than finished."""
    last_error = max(
        row
        for row in range(window.model.rowCount())
        if isinstance(record := window.model.row_at(row), Record) and record.is_error
    )
    window.go_to(last_error)
    window.find_next(Find.ERROR)

    assert window.table.currentIndex().row() < last_error


def test_previous_error_goes_backwards_and_lands_on_an_error(window: MainWindow) -> None:
    """It used to assert only that backwards and forwards differed.

    Making `find(backwards=True)` return the immediately preceding row --
    whatever kind it was -- left that assertion true and the whole suite green.
    Half the contract is the direction; the other half is that the thing it
    lands on is the kind that was asked for.
    """
    start = window.model.rowCount() - 1
    window.go_to(start)
    window.find_next(Find.ERROR, backwards=True)
    row = window.table.currentIndex().row()

    landed = window.model.row_at(row)
    assert isinstance(landed, Record), "not a record"
    assert landed.is_error, "not an error"
    expected = max(
        candidate
        for candidate in range(start)
        if isinstance(record := window.model.row_at(candidate), Record) and record.is_error
    )
    assert row == expected, "not the nearest error behind the cursor"


def test_finding_nothing_leaves_the_selection_alone(qt_app: object) -> None:
    """An empty result is not a reason to move the user somewhere arbitrary."""
    del qt_app
    window = MainWindow()
    window.model.append([make_record(i, level=Level.INFO) for i in range(20)])
    window.go_to(5)

    window.find_next(Find.ERROR)

    assert window.table.currentIndex().row() == 5


def test_gap_navigation_finds_a_marker(qt_app: object) -> None:
    """The reason this exists: a gap far outside the viewport is otherwise
    something the reader never learns about."""
    del qt_app
    window = MainWindow()
    start = datetime(2026, 8, 8, 13, 0, tzinfo=UTC)
    gap = Gap(start=start, end=start + timedelta(seconds=2), reason="connection dropped")
    window.model.append([*(make_record(i) for i in range(40)), gap, make_record(40)])

    window.go_to(0)
    window.find_next(Find.MARKER)

    assert isinstance(window.model.row_at(window.table.currentIndex().row()), Gap)


def test_go_to_bottom_twice_resumes_following(window: MainWindow) -> None:
    """Two commands on one key, in the order klogg settled on.

    Conflating them is what leaves Wireshark's users with "Ctrl End is close,
    but doesn't resume auto scroll".

    Observed through the selection rather than through a flag, because the flag
    is gone: a caret on a row that is no longer the last one is exactly how
    `_follow` recognises a reader who has stopped tailing, so "resume" has to
    mean letting go of the row. It used to set a boolean nothing ever read.
    """
    last = window.model.rowCount() - 1
    window.go_to(0)

    window.go_to_bottom()
    assert window.table.currentIndex().row() == last, "the first press travels"

    window.go_to_bottom()
    assert not window.table.currentIndex().isValid(), "the second press lets go and tails"


def test_a_selected_row_is_not_dragged_away_by_the_tail(window: MainWindow) -> None:
    """The Console.app bug, from the direction that actually bites.

    Follow is derived, never stored -- but it was derived from the scrollbar
    alone, and clicking a row does not move the scrollbar. So a reader who
    selected a record mid-capture had it yanked off screen by the next batch.
    `docs/design/gui.md` §4 calls breaking follow on selection "not optional",
    and with a detail pane it is the primary interaction.
    """
    window.table.scrollToBottom()
    window.go_to(5)

    window.model.append([make_record(i) for i in range(500, 600)])
    window._follow()

    assert window.table.currentIndex().row() == 5, "the selection moved"
    bar = window.table.verticalScrollBar()
    assert bar.value() < bar.maximum(), "the tail dragged the view off the selected row"


def test_with_nothing_selected_the_tail_still_follows(window: MainWindow) -> None:
    """The other half: breaking follow on selection must not break follow."""
    window.table.clearSelection()
    window.table.setCurrentIndex(QModelIndex())
    window.table.scrollToBottom()

    window.model.append([make_record(i) for i in range(500, 600)])
    window._follow()

    bar = window.table.verticalScrollBar()
    assert bar.value() >= bar.maximum() - 4


def test_stepping_works_without_the_table_having_focus(window: MainWindow) -> None:
    """Wireshark documents exactly this, and with a detail pane it is necessary
    rather than a nicety: reading a record puts focus in the pane."""
    window.go_to(10)
    window.detail.setFocus()

    window.step_row(1)
    assert window.table.currentIndex().row() == 11

    window.step_row(-1)
    assert window.table.currentIndex().row() == 10


def test_stepping_stops_at_the_ends(window: MainWindow) -> None:
    window.go_to(0)
    window.step_row(-1)
    assert window.table.currentIndex().row() == 0


# -- marks -------------------------------------------------------------------


def test_a_mark_survives_a_filter_change(window: MainWindow) -> None:
    """Marks are held by source index, the same handle selection anchors on.

    Held by row number they would silently move to whatever record now occupies
    that row -- a bookmark pointing at the wrong line is worse than no
    bookmark.
    """
    error_row = next(
        row
        for row in range(window.model.rowCount())
        if isinstance(record := window.model.row_at(row), Record) and record.is_error
    )
    window.go_to(error_row)
    window.toggle_mark()
    marked = window.model.row_at(error_row)

    window.model.set_filter(Filter(minimum_level=Level.ERROR))

    still = [
        window.model.row_at(row)
        for row in range(window.model.rowCount())
        if window.model.is_marked(row)
    ]
    assert still == [marked]


def test_a_mark_outranks_the_severity_colour(window: MainWindow) -> None:
    """A mark is the user's annotation and a tint is the program's. When they
    disagree the user wins, or marking a Fault would do nothing visible --
    exactly where it matters most."""
    from PySide6.QtCore import Qt

    row = next(
        r
        for r in range(window.model.rowCount())
        if isinstance(record := window.model.row_at(r), Record) and record.level is Level.FAULT
    )
    before = window.model.data(window.model.index(row, 0), Qt.ItemDataRole.BackgroundRole)
    window.go_to(row)
    window.toggle_mark()
    after = window.model.data(window.model.index(row, 0), Qt.ItemDataRole.BackgroundRole)

    assert after != before


def test_marking_twice_unmarks(window: MainWindow) -> None:
    window.go_to(3)
    window.toggle_mark()
    assert window.model.marks == 1
    window.toggle_mark()
    assert window.model.marks == 0


def test_clearing_marks_follows_the_current_model(window: MainWindow) -> None:
    """The model is replaced whenever a capture is opened. A handler bound to
    the old one would go on clearing marks nobody can see."""
    window.go_to(3)
    window.toggle_mark()

    window.open_capture(ERRORS)
    loader = window._loader
    assert loader is not None
    loader._step()  # one batch is enough to have rows to mark

    window.go_to(0)
    window.toggle_mark()
    assert window.model.marks == 1

    window.clear_marks()
    assert window.model.marks == 0


def test_a_mark_on_an_evicted_record_goes_with_it(qt_app: object) -> None:
    """Keeping a mark that points at nothing is worse than losing it: the user
    would jump to a row that is not the one they marked."""
    del qt_app
    model = RecordModel(Scheme.LIGHT, row_cap=50)
    model.append([make_record(i) for i in range(40)])
    model.toggle_mark(2)
    assert model.marks == 1

    model.append([make_record(i) for i in range(40, 200)])
    for row in range(model.rowCount()):
        assert not model.is_marked(row) or isinstance(model.row_at(row), Record)


# -- copy --------------------------------------------------------------------


def test_copying_a_row_fills_in_the_blanked_repeats(qt_app: object) -> None:
    """What was elided on screen to make a long run scannable would be a hole
    in a pasted record."""
    del qt_app
    window = MainWindow()
    window.model.append([make_record(i) for i in range(3)])

    # The second row's process cell is blanked in the table.
    assert window.model.data(window.model.index(1, int(Column.PROCESS))) == ""

    window.table.selectRow(1)
    window.copy_selection()

    clipboard = QApplication.clipboard()
    assert clipboard is not None
    assert "cloudd" in clipboard.text()


def test_copying_produces_one_line_per_row(window: MainWindow) -> None:
    window.table.selectRow(0)
    window.table.selectionModel().select(
        window.model.index(1, 0),
        window.table.selectionModel().SelectionFlag.Select
        | window.table.selectionModel().SelectionFlag.Rows,
    )
    window.copy_selection()

    clipboard = QApplication.clipboard()
    assert clipboard is not None
    lines = clipboard.text().splitlines()
    assert len(lines) == 2
    assert all(line.count("\t") == window.model.columnCount() - 1 for line in lines)


def test_a_multi_line_message_stays_one_row(qt_app: object) -> None:
    """Device messages really do contain newlines.

    A record that spills across several lines breaks every consumer of a
    tab-separated paste -- which is the entire audience for this feature. The
    exporters' own folding rule is reused rather than reinvented.
    """
    del qt_app
    window = MainWindow()
    window.model.append([make_record(0, message="first line\nsecond line\twith a tab")])

    window.table.selectRow(0)
    window.copy_selection()

    clipboard = QApplication.clipboard()
    assert clipboard is not None
    assert len(clipboard.text().splitlines()) == 1
    # The two-character escape, not a real newline: the message is still
    # legible and still recoverable, but it no longer breaks the row.
    assert "\\n" in clipboard.text()
    assert "\\t" in clipboard.text()


def test_copying_nothing_leaves_the_clipboard_alone(window: MainWindow) -> None:
    clipboard = QApplication.clipboard()
    assert clipboard is not None
    clipboard.setText("untouched")

    window.table.clearSelection()
    window.copy_selection()

    assert clipboard.text() == "untouched"


def test_the_tail_follows_a_capture_that_was_never_scrolled(window: MainWindow) -> None:
    """The state a real capture actually starts in, which no other test used.

    Every follow test here scrolls to the bottom first -- and that setup is
    exactly what hid this. Appending does not move a scrollbar: Qt raises the
    maximum and leaves the value where it was, so a check made after the insert
    saw 0 out of 3,919 and concluded the user had scrolled up. Follow never
    engaged once, because the only thing that could have returned the bar to
    the bottom was the follow it was refusing to do.

    Shipped in 0.1.0 and reported as "auto scroll is not working", which it was
    not.
    """
    bar = window.table.verticalScrollBar()
    assert bar.value() == 0, "a fresh window has never been scrolled"

    for batch in range(3):
        window.model.append([make_record(batch * 100 + i) for i in range(100)])
        window._scrolled.invalidate()  # the 100 ms coalescing, not the rule
        window._follow()

    assert bar.value() >= bar.maximum() - 4


def test_a_trim_does_not_move_the_log_out_from_under_the_reader(qt_app: object) -> None:
    """The cap drops rows from the *top*, and a scroll position is a pixel
    offset from the top of the content.

    So the surviving rows slide up under a viewport that stays where it was.
    On a device emitting three thousand records a second that is every seven
    seconds, forever, and always while somebody is reading. Measured at a cap
    of 2,000: a reader on record 989 was looking at record 1,588 afterwards,
    having pressed nothing.

    The cap is lowered here so the trim happens in one batch; the mechanism is
    the one that runs at 200,000.
    """
    del qt_app
    window = MainWindow()
    window.model = RecordModel(window.scheme, row_cap=2_000, parent=window)
    window.table.setModel(window.model)
    window._connect_selection()
    window.resize(1280, 800)
    # Shown, or the viewport has no height, nothing scrolls and the reader is
    # left at row zero -- where a trim legitimately lands them on the eviction
    # notice, and the test would be asserting nothing.
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.show()
    QApplication.processEvents()

    window.model.append([make_record(i, message=f"record {i}") for i in range(2_000)])
    QApplication.processEvents()
    bar = window.table.verticalScrollBar()
    bar.setValue(bar.maximum() // 2)
    assert bar.value() > 0, "the reader has to be somewhere a trim can move them from"

    def top_row() -> object:
        index = window.table.indexAt(window.table.viewport().rect().topLeft())
        return window.model.row_at(index.row()) if index.isValid() else None

    reading = top_row()
    assert reading is not None

    window.model.append([make_record(2_000 + i, message=f"record {2_000 + i}") for i in range(600)])

    assert top_row() is reading, "the trim moved the log under the reader"


def test_escape_lets_go_of_a_row_and_the_tail_resumes(window: MainWindow) -> None:
    """Selecting a row stops the tail deliberately -- and there was no way to
    say you had finished reading it.

    The only route back was `Go to Bottom` pressed twice, which is a thing you
    have to be told. So a live capture stopped following the first time anybody
    clicked anything and stayed stopped.
    """
    window.model.append([make_record(i) for i in range(200)])
    window.go_to(5)
    assert window.table.currentIndex().row() == 5

    window.deselect()

    assert not window.table.currentIndex().isValid()
    window.model.append([make_record(200 + i) for i in range(100)])
    window._scrolled.invalidate()
    window._follow()
    bar = window.table.verticalScrollBar()
    assert bar.value() >= bar.maximum() - 4, "the tail did not resume"


def test_escape_does_not_move_the_view(window: MainWindow) -> None:
    """The correction, reported from a real capture.

    `deselect` used to force the at-bottom state and call `_follow`, on the
    reasoning that letting go of a row is asking for the tail back. What that
    does to somebody reading half way up a log is throw them to the end of it,
    which is precisely where they had chosen not to be. Follow is derived from
    the viewport, so a reader who deselects at the bottom gets the tail back
    without being taken there.
    """
    window.model.append([make_record(i) for i in range(500)])
    window.table.resize(600, 300)
    window.table.show()
    QApplication.processEvents()

    bar = window.table.verticalScrollBar()
    assert bar.maximum() > 0, "the table has no range, so this would prove nothing"
    window.go_to(200)
    before = bar.value()
    assert before > 0, "the view never left the top"

    window.deselect()

    assert not window.table.currentIndex().isValid()
    assert bar.value() == before, "Esc moved the view instead of only letting go of the row"


def test_scrolling_up_stops_the_tail_and_scrolling_back_resumes_it(window: MainWindow) -> None:
    """The half that protects the reader, and the half that lets them go again.

    Leaving the bottom is something a person does. `actionTriggered` is what
    says so -- it fires for a drag, a wheel, an arrow and a page, and not for
    `setValue`, which is how everything this window does moves the view. Reading
    the position on every tick instead is what broke follow entirely: a scroll
    the throttle had just skipped was indistinguishable from a reader going up.
    """
    window.table.scrollToBottom()
    bar = window.table.verticalScrollBar()

    bar.actionTriggered.emit(QAbstractSlider.SliderAction.SliderPageStepSub.value)
    bar.setValue(0)
    window.model.append([make_record(i) for i in range(500, 600)])
    window._scrolled.invalidate()
    window._follow()

    assert bar.value() == 0, "the tail dragged a reader who had scrolled away"

    bar.actionTriggered.emit(QAbstractSlider.SliderAction.SliderToMaximum.value)
    bar.setValue(bar.maximum())
    window.model.append([make_record(i) for i in range(600, 700)])
    window._scrolled.invalidate()
    window._follow()

    assert bar.value() >= bar.maximum() - 4, "the tail did not resume"
