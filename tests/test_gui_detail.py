# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The detail pane, checked against real device output.

Real records rather than synthetics, because what this pane is *for* is showing
fields whose meaning came from the device: which of two paths is the executable
and which is the loaded library, whether a subsystem was present, what the
device's UTC offset actually was. A hand-written record would agree with
whatever the pane happened to do.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from ostrace.model import Gap, Record
from ostrace.storage.spool import SpoolReader
from tests.helpers import MIXED

pytest.importorskip("PySide6", reason="the gui extra is not installed")

from PySide6.QtWidgets import QApplication, QLabel

from ostrace.gui.widgets.detail_pane import ABSENT, DetailPane
from ostrace.gui.windows.main import MainWindow

pytestmark = pytest.mark.gui


def field_widgets(pane: DetailPane) -> list[QLabel]:
    """The value half of every field, plus the message block.

    Reaching into the pane because geometry is what is under test here and
    there is no public accessor for it -- the pane's own interface is text.
    Driven from ``_rows``, which is the same mapping ``field()`` answers from,
    so a value that is on screen is in here whichever of the two layouts it
    ended up in.
    """
    return list(pane._rows.values())


@pytest.fixture(scope="module")
def records() -> list[Record]:
    return [item for item in SpoolReader(MIXED).items() if isinstance(item, Record)]


@pytest.fixture
def pane(qt_app: object) -> DetailPane:
    del qt_app
    return DetailPane()


def test_nothing_is_selected_to_begin_with(pane: DetailPane) -> None:
    """An empty pane says so, rather than showing a form full of dashes."""
    assert pane.field("Nothing selected") is not None


def test_both_clocks_and_their_difference(pane: DetailPane, records: list[Record]) -> None:
    """The pane is where this project's timestamp rule becomes visible.

    A record's timestamp carries the *device's* UTC offset, because the host is
    a different clock in a frequently different zone. Nothing on screen says so
    until the two are shown together with the delta between them.
    """
    record = records[0]
    host_now = record.timestamp - timedelta(seconds=1.5)
    pane.show_record(record, host_now)

    assert pane.field("Device time") is not None
    assert pane.field("Host time") is not None
    assert pane.field("Difference") == "+1.500 s"


def test_the_device_offset_is_not_silently_dropped(pane: DetailPane, records: list[Record]) -> None:
    """The rendered device time carries an offset, not a bare local time."""
    record = records[0]
    pane.show_record(record)
    shown = pane.field("Device time")
    assert shown is not None
    assert shown[-5:].lstrip("+-").isdigit(), f"no UTC offset in {shown!r}"


def test_the_two_paths_are_shown_as_different_things(
    pane: DetailPane, records: list[Record]
) -> None:
    """``process_path`` is the executable; ``image_path`` is the library loaded
    into it. They read backwards and differ in about nine records in ten, which
    is exactly why both are on screen with distinct labels."""
    with_both = next(r for r in records if r.image_path and r.process_path)
    pane.show_record(with_both)
    assert pane.field("Process path") != pane.field("Image")


def test_absent_fields_use_the_exporters_spelling(pane: DetailPane, records: list[Record]) -> None:
    """A value copied out of this pane should match what a bundle would hold."""
    without_subsystem = next(r for r in records if r.subsystem is None)
    pane.show_record(without_subsystem)
    assert pane.field("Subsystem") == ABSENT


def test_a_gap_says_plainly_that_the_records_are_unrecoverable(pane: DetailPane) -> None:
    """A gap is a fact about the capture, not an apologetic aside.

    It gets the same treatment as a record, and it states the one thing a
    reader most needs to know: that nothing buffered what is missing, so there
    is nowhere else to look for it.
    """
    records = [item for item in SpoolReader(MIXED).items() if isinstance(item, Record)]
    gap = Gap(
        start=records[0].timestamp,
        end=records[0].timestamp + timedelta(seconds=4),
        reason="connection dropped",
    )
    pane.show_gap(gap)

    assert pane.field("Reason") == "connection dropped"
    assert pane.field("Duration") == "4.000 s"
    recoverable = pane.field("Recoverable")
    assert recoverable is not None
    assert recoverable.startswith("No.")


def test_a_record_is_not_squeezed_into_the_previous_one_s_height(
    pane: DetailPane, records: list[Record]
) -> None:
    """The bug every other test here is blind to, because they all read text.

    The pane sizes itself from what its wrapped text actually needs, and it
    asked the layout that question immediately after replacing the rows -- when
    the layout still answered for the *previous* contents. Coming from the
    "Nothing selected" placeholder, twelve fields were given eight pixels each
    where they needed sixteen, and every row rendered as its own top half. The
    text was correct throughout, which is why nothing caught it until somebody
    looked at a picture.

    A relation, not a measurement: each row is compared against its own
    requirement in whatever font is in use. Nothing here asserts a pixel count,
    which it could not do offscreen -- the offscreen font database is empty on
    Windows and returns numbers for a face no user will ever see.
    """
    pane.resize(600, 80)  # deliberately far shorter than twelve rows need
    pane.show()
    pane.show_record(records[0])
    # Geometry is applied by the event loop, and there is not one here. Every
    # other test in this file reads text, which is why none of them needs this.
    QApplication.processEvents()

    squeezed = [
        label.text()
        for label in field_widgets(pane)
        if label.height() < label.heightForWidth(label.width())
    ]
    assert not squeezed, f"{len(squeezed)} rows rendered shorter than their text"


def test_a_rebuild_leaves_nothing_of_the_previous_contents_on_screen(
    pane: DetailPane, records: list[Record]
) -> None:
    """``takeAt`` unhooks a row from the layout; it does not stop it painting.

    Replacing the contents took each old row out of the grid and handed it to
    ``deleteLater``, which destroys it whenever the event loop next drains.
    Until then it was still a visible child sitting at its old geometry, drawn
    straight over the rows that replaced it -- the "Nothing selected"
    placeholder printed across ``Device time``.

    Interactive use hides this, because the loop drains before the next paint.
    What sees it is anything that rebuilds and renders in one pass: every
    ``grab()`` in this suite, and ``tools/capture_screens.py``, whose whole job
    is to show what this window looks like on macOS. It is the second bug in
    this pane found by looking at a picture rather than by reading text, and
    like the first one every existing assertion passed throughout.

    Asserted without ``processEvents``, which is both what a synchronous render
    observes and the honest test: ``processEvents`` does not deliver
    ``DeferredDelete`` anyway, so the stale rows survive it too.
    """
    pane.resize(600, 400)
    pane.show()
    pane.show_record(records[0])

    stale = [
        label.text()
        for label in pane.findChildren(QLabel)
        if label.isVisible() and label.text().startswith("Nothing selected")
    ]
    assert not stale, f"{len(stale)} row(s) of the previous contents are still on screen"


def test_the_message_is_a_block_of_its_own(pane: DetailPane, records: list[Record]) -> None:
    """The one field with anything to say does not share a column with ``PID``.

    It is still reachable as a field, which is the pane's interface, but it is
    laid out separately -- the fields are short and the message is long, and a
    single column sized for both gave the message a strip and left the rest of
    the pane empty.
    """
    long_message = max(records, key=lambda record: len(record.message))
    pane.show_record(long_message)

    assert pane.field("Message") == long_message.message
    assert pane._message.isVisibleTo(pane)
    assert pane._message.wordWrap(), "a message that cannot wrap is a message with one line of it"


def test_a_gap_has_no_message_block(pane: DetailPane, records: list[Record]) -> None:
    """A gap has no message, and an empty framed box saying so is furniture."""
    start = records[0].timestamp
    pane.show_gap(Gap(start=start, end=start + timedelta(seconds=2), reason="unplugged"))

    assert not pane._message.isVisibleTo(pane)
    assert pane.field("Message") is None


def test_the_close_control_asks_rather_than_hides(pane: DetailPane, records: list[Record]) -> None:
    """Pressing it emits; the window turns that into a deselect.

    The pane does not hide itself, and does not empty itself either. One that
    can disappear is one the user has to work out how to bring back, and
    `docs/design/gui.md` §9 has it always present on purpose.
    """
    seen: list[bool] = []
    pane.closed.connect(lambda: seen.append(True))
    pane.show_record(records[0])

    pane._close.click()

    assert seen == [True]
    assert pane.field("Message") is not None, "the pane cleared itself instead of asking"


def test_nothing_selected_offers_nothing_to_close(pane: DetailPane) -> None:
    """A close button on an empty pane is a control that does nothing."""
    pane.clear()
    assert not pane._close.isVisibleTo(pane)


def test_show_item_dispatches_on_the_kind(pane: DetailPane, records: list[Record]) -> None:
    """``Gap`` travels in the stream alongside records, so whatever the table
    hands the pane is one of two types and the pane sorts it out itself."""
    pane.show_item(records[0])
    assert pane.field("Message") is not None

    pane.show_item(
        Gap(
            start=records[0].timestamp,
            end=records[0].timestamp + timedelta(seconds=1),
            reason="device disconnected",
        )
    )
    assert pane.field("Message") is None
    assert pane.field("Reason") == "device disconnected"


class TestPuttingThePaneAway:
    """`Ctrl+I`, and the two things that made it not a one-liner.

    Driven through the menu item rather than through `set_detail_visible`,
    because the item is the only thing that calls it and a window whose tick
    and pane disagreed would need two presses to show it -- the first of which
    appears to do nothing.
    """

    @staticmethod
    def _shown(qt_app: object) -> MainWindow:
        del qt_app
        window = MainWindow()
        window.resize(900, 600)
        window.show()
        QApplication.processEvents()
        return window

    def test_it_starts_showing(self, qt_app: object) -> None:
        window = self._shown(qt_app)

        assert window.detail.isVisible()
        assert window.action_detail_pane.isChecked()

    def test_the_key_puts_it_away_and_brings_it_back(self, qt_app: object) -> None:
        window = self._shown(qt_app)

        window.action_detail_pane.setChecked(False)
        assert not window.detail.isVisible()

        window.action_detail_pane.setChecked(True)
        assert window.detail.isVisible()

    def test_it_comes_back_the_size_it_went_away(self, qt_app: object) -> None:
        """A pane that came back bigger than it went away is one there is no
        way to put right that a second press does not undo again.

        This pins a *Qt* behaviour rather than ours: `QSplitter` keeps a hidden
        child's size and gives it back. The window used to save and restore the
        sizes by hand, and this test stayed green with that removed -- which is
        how the two lines were found to be restoring numbers Qt had already
        restored. Worth keeping: the day somebody replaces `setVisible` with
        `removeWidget`, the sizes stop coming back and nothing else notices.
        """
        window = self._shown(qt_app)
        window._split.setSizes([500, 100])
        QApplication.processEvents()
        before = window._split.sizes()

        window.action_detail_pane.setChecked(False)
        QApplication.processEvents()
        window.action_detail_pane.setChecked(True)
        QApplication.processEvents()

        assert window._split.sizes() == before

    def test_the_table_takes_the_room(self, qt_app: object) -> None:
        """Otherwise the pane is hidden and its share of the window is not,
        which reads as a rendering fault rather than as a hidden pane."""
        window = self._shown(qt_app)
        before = window.table.height()

        window.action_detail_pane.setChecked(False)
        QApplication.processEvents()

        assert window.table.height() > before

    def test_it_is_remembered(self, qt_app: object) -> None:
        window = self._shown(qt_app)
        window.action_detail_pane.setChecked(False)
        window._save_layout()

        reopened = self._shown(qt_app)

        assert not reopened.detail.isVisible()
        assert not reopened.action_detail_pane.isChecked(), "the tick disagreed with the pane"
