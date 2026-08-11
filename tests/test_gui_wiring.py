# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The window driven end to end against a real capture.

No display and no clicking: the loader is stepped by hand and the widgets are
addressed directly, so this runs offscreen on all three operating systems like
everything else. What it proves is that the pieces are actually connected --
which is the class of bug that unit tests on each piece cannot see.
"""

from __future__ import annotations

import gc

import pytest

from ostrace.model import Level, Record
from tests.helpers import ERRORS, MIXED, ScriptedSource

pytest.importorskip("PySide6", reason="the gui extra is not installed")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from ostrace.gui.columns import Column
from ostrace.gui.filters import Filter
from ostrace.gui.live import CaptureThread
from ostrace.gui.theme import Scheme, contrast_ratio, palette_for, severity_for
from ostrace.gui.windows.main import MainWindow

pytestmark = pytest.mark.gui


def load(window: MainWindow, path: object) -> None:
    """Open a capture and read all of it, without an event loop."""
    window.open_capture(path)  # type: ignore[arg-type]
    loader = window._loader
    assert loader is not None
    while loader.loaded < 10**9:
        before = loader.loaded
        loader._step()
        if loader.loaded == before:
            break


@pytest.fixture
def window(qt_app: object) -> MainWindow:
    del qt_app
    return MainWindow()


def test_a_standing_filter_reaches_the_next_capture(window: MainWindow) -> None:
    """The bar and the model have to agree after a swap.

    Opening a capture over another left the bar displaying a filter that the
    new model was not applying: every row on screen, and the chrome insisting
    the view was narrowed. Carrying the filter to the next capture is a
    decision and clearing it would be another one -- displaying it without
    applying it is neither, it is the window lying about what is on screen.
    """
    load(window, ERRORS)
    window.filter_bar.set_filter(Filter(minimum_level=Level.ERROR))
    window._apply_filter()
    assert 0 < window.model.rowCount() < window.model.retained

    load(window, MIXED)

    assert not window.filter_bar.is_empty
    assert window.model.filter.minimum_level is Level.ERROR
    assert 0 < window.model.rowCount() < window.model.retained


def test_nothing_from_the_previous_capture_outlives_the_swap(window: MainWindow) -> None:
    """Every capture opened in a session used to stay in memory.

    Both halves are asserted because the model has two owners and releasing
    one of them frees nothing. The window is its Qt parent, so Qt holds it
    until the window dies; the loader keeps it in an attribute, and the loader
    is parented to the window too, which keeps its Python wrapper alive and the
    model reference in it. Measured over twenty successive opens: deleting only
    the model grows the process 41.2 MiB, only the loader 40.6 MiB, neither
    41.0 MiB, both 2.2 MiB.

    So a spy on one of them would pass while the leak continued, which is what
    makes the pair worth pinning rather than the pair being tidy.
    """
    load(window, ERRORS)
    replaced_model = window.model
    replaced_loader = window._loader
    assert replaced_loader is not None
    gone: list[str] = []
    replaced_model.destroyed.connect(lambda *_: gone.append("model"))
    replaced_loader.destroyed.connect(lambda *_: gone.append("loader"))

    load(window, MIXED)
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    assert sorted(gone) == ["loader", "model"], f"still alive: {gone}"


def test_a_capture_that_will_not_open_offers_another(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The banner's job is the way out, not the acknowledgement.

    Whatever is wrong with the file, the next thing wanted is a different one,
    and the window already knows how to ask for it.
    """
    chosen: list[bool] = []
    monkeypatch.setattr(MainWindow, "choose_capture", lambda self: chosen.append(True))

    window.open_capture(ERRORS.with_name("no-such-capture.jsonl.gz"))

    assert window.banner._action.text() == "Open another…"
    window.banner.act()
    assert chosen, "the action did not reach the file chooser"


def test_a_parked_capture_offers_the_doctor(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A device still held is a consequence met later and elsewhere.

    The next capture fails on a busy relay, by which time the banner that
    warned about it is long gone. Doctor is the thing that answers whether the
    device is free, so the banner offers it while the subject is still on
    screen.
    """
    opened: list[bool] = []
    monkeypatch.setattr(MainWindow, "show_doctor", lambda self: opened.append(True))
    thread = CaptureThread(ScriptedSource([]))

    window._park(thread)

    assert window.banner._action.text() == "Diagnose…"
    window.banner.act()
    assert opened, "the action did not reach the doctor window"


def test_closing_a_capture_takes_the_filter_with_it(window: MainWindow) -> None:
    """The other half of the same rule, and the reason it is not symmetrical.

    Closing is the one moment there is no next capture to carry the filter to,
    so this door clears where every other one keeps. Pinned because the two
    halves now live in one method, and a change that made them agree would look
    like a tidy-up.
    """
    load(window, ERRORS)
    window.filter_bar.set_filter(Filter(minimum_level=Level.ERROR))
    window._apply_filter()

    window.close_capture()

    assert window.filter_bar.is_empty
    assert window.model.filter.is_empty


def test_opening_a_capture_fills_the_table(window: MainWindow) -> None:
    load(window, ERRORS)
    assert window.model.rowCount() == 3000
    assert window.table.model() is window.model


def test_the_status_bar_reports_what_was_read(window: MainWindow) -> None:
    load(window, ERRORS)
    assert window.status.gap_text == "0 gaps"
    assert "3,000" in window.status._volume.text()


def test_a_bare_spool_opens_without_a_sidecar(window: MainWindow) -> None:
    """The offline path exists precisely for a file somebody attached to a bug
    report, which has no session directory around it."""
    load(window, MIXED)
    assert window.model.rowCount() == 5000
    assert window.capture is not None
    assert window.capture.device is None


def test_opening_a_second_capture_replaces_the_first(window: MainWindow) -> None:
    """Two captures interleaved by arrival order would be a timeline that never
    happened."""
    load(window, ERRORS)
    load(window, MIXED)
    assert window.model.rowCount() == 5000


def test_a_missing_capture_is_reported_rather_than_raised(window: MainWindow) -> None:
    window.open_capture(ERRORS.with_name("no-such-capture.jsonl.gz"))
    assert "Could not open" in window.banner.text


def test_selecting_a_row_fills_the_detail_pane(window: MainWindow) -> None:
    load(window, ERRORS)
    window.table.setCurrentIndex(window.model.index(3, 0))

    row = window.model.row_at(3)
    assert isinstance(row, Record)
    assert window.detail.field("Message") == row.message


def test_the_detail_pane_shows_the_device_offset_not_a_wall_clock_delta(
    window: MainWindow,
) -> None:
    """Reading a file there is no second reading of the same moment.

    A record captured this morning is not "36,000 seconds out"; presenting that
    as a clock difference would invent a problem the device does not have. The
    offset is the fact that is true either way.
    """
    load(window, ERRORS)
    window.table.setCurrentIndex(window.model.index(0, 0))

    assert window.detail.field("Difference") is None
    offset = window.detail.field("Device UTC offset")
    assert offset is not None
    assert offset.startswith("UTC")


def test_filtering_updates_the_table(window: MainWindow) -> None:
    load(window, ERRORS)
    everything = window.model.rowCount()

    window.filter_bar._level.setCurrentIndex(4)
    window._apply_filter()

    assert window.filter_bar.minimum_level is Level.ERROR
    assert 0 < window.model.rowCount() < everything


def test_an_invalid_regex_leaves_the_view_alone_and_says_why(window: MainWindow) -> None:
    """A view that empties itself as the user types is indistinguishable from a
    device that stopped talking."""
    load(window, ERRORS)
    before = window.model.rowCount()

    window.filter_bar._search.setText("[unclosed")
    window.filter_bar._regex.setChecked(True)
    window._apply_filter()

    assert window.model.rowCount() == before
    assert "invalid regular expression" in window.banner.text


def test_a_filter_that_hides_everything_offers_a_way_back(window: MainWindow) -> None:
    """A paused stream, an over-narrow filter and a dead device all produce the
    same empty table. Only one of them has a way out."""
    load(window, ERRORS)

    window.filter_bar._process.setText("no-such-process")
    window._apply_filter()

    assert window.model.rowCount() == 0
    assert "hidden by the filter" in window.banner.text

    window.banner.act()
    window._apply_filter()

    assert window.model.rowCount() == 3000
    assert window.banner.text == ""


def test_selection_follows_the_record_across_a_filter_change(window: MainWindow) -> None:
    """A filter change must not cost the user their place.

    Wireshark has had this open since 3.0.7 and Logcat rebuilds its document on
    each filter change; lnav does solve it, by anchoring on the timestamp. Here
    the selection is anchored to the *record*, so a filter that keeps it keeps
    the user where they were reading.
    """
    load(window, ERRORS)
    chosen = next(
        row
        for row in range(window.model.rowCount())
        if isinstance(window.model.row_at(row), Record)
        and window.model.row_at(row).level >= Level.ERROR  # type: ignore[union-attr]
    )
    window.table.setCurrentIndex(window.model.index(chosen, 0))
    anchored = window.model.row_at(chosen)

    window.filter_bar._level.setCurrentIndex(4)
    window._apply_filter()

    current = window.table.currentIndex()
    assert current.isValid()
    assert window.model.row_at(current.row()) is anchored


def test_selection_falls_back_to_the_nearest_survivor(window: MainWindow) -> None:
    """When the anchored record does *not* survive the new filter.

    The user was still reading at that point in the log, and that point still
    exists even though the record they had clicked does not. The nearest
    survivor after it is the answer -- not row zero, and not the bottom.
    """
    load(window, ERRORS)

    # A Debug record that an Error threshold is certain to remove, chosen far
    # enough in that "nearest survivor" and "first row" are different answers.
    debug_row = next(
        row
        for row in range(500, window.model.rowCount())
        if isinstance(window.model.row_at(row), Record)
        and window.model.row_at(row).level is Level.DEBUG  # type: ignore[union-attr]
    )
    window.table.setCurrentIndex(window.model.index(debug_row, 0))
    dropped = window.model.row_at(debug_row)
    anchor = window.model.source_index(debug_row)

    window.filter_bar._level.setCurrentIndex(4)
    window._apply_filter()

    current = window.table.currentIndex()
    assert current.isValid()
    landed = window.model.row_at(current.row())
    assert landed is not dropped, "the anchored record was supposed to be filtered out"
    assert current.row() > 0, "row zero would mean the anchor was thrown away"
    assert window.model.source_index(current.row()) >= anchor, "landed before where they were"


class TestTheThemeSwitchReachesTheRecords:
    """`apply_theme` moves the palette. It cannot move what was resolved once.

    The severity foregrounds and the minimap's bands are built from the scheme
    when the model is, and both carry a `set_scheme` that nothing in `src/`
    called: an operating-system theme switch repainted the window in the new
    scheme and left every record's colour in the old one. Measured on the
    shipped palette, `Info` and `Notice` -- most of any capture -- came out at
    **1.14:1** against the new background.

    `docs/design/gui.md` §10 calls the switch "the same function called again",
    so the document was right and the wiring was the bug.
    """

    def test_a_switch_recolours_the_records(self, window: MainWindow) -> None:
        load(window, ERRORS)
        assert window.scheme is Scheme.LIGHT

        window.set_scheme(Scheme.DARK)

        assert window.model.scheme is Scheme.DARK
        assert window.minimap.scheme is Scheme.DARK, "the overview kept the old scheme"

    def test_every_level_stays_legible_across_the_switch(self, window: MainWindow) -> None:
        """The consequence, asserted rather than inferred.

        A model holding one scheme against a background drawn in the other is
        not merely inconsistent -- it is unreadable, which is the failure the
        contrast tests exist to prevent and the only one they could not see,
        because they only ever compare a scheme with itself.
        """
        load(window, ERRORS)
        window.set_scheme(Scheme.DARK)
        background = palette_for(Scheme.DARK).color(QPalette.ColorRole.Base)

        for level in Level:
            foreground = severity_for(level, window.model.scheme).foreground
            ratio = contrast_ratio(foreground, background)
            assert ratio >= 4.5, f"{level.name} is {ratio:.2f}:1 after the switch"

    def test_the_window_is_connected_to_the_platform(self, window: MainWindow) -> None:
        """Driven through the signal itself, not by calling the slot.

        The offscreen plugin's `setColorScheme` is a no-op, so the hints never
        move and a slot that re-read them could only ever be observed doing
        nothing. Carrying the new value as the signal's argument is what makes
        the connection testable at all -- emitting it by hand is exactly what
        the platform does.
        """
        app = QApplication.instance()
        assert isinstance(app, QApplication)

        # `colorSchemeChanged` belongs to the application, so it reaches every
        # window this session has built and not yet collected -- each of which
        # recolours a model and rebuilds an icon set. Left to CPython's own
        # timing that was 151 seconds for this one test. Collecting first is
        # not tidiness; it is the difference between driving one window and
        # driving every window the suite has ever made.
        gc.collect()

        # Both directions in one loop rather than two statements: asserting on
        # the same attribute twice narrows it to the first answer, and the
        # second comparison is then unreachable as far as a type checker knows.
        hints = app.styleHints()
        for emitted, expected in (
            (Qt.ColorScheme.Dark, Scheme.DARK),
            (Qt.ColorScheme.Light, Scheme.LIGHT),
        ):
            hints.colorSchemeChanged.emit(emitted)
            assert window.scheme is expected


def test_the_table_shows_what_the_model_says(window: MainWindow) -> None:
    """One end-to-end check that the columns are wired to the right fields.

    The escape hatch that used to be here -- accepting `""` as well as the
    value -- made the test unfailable: rendering the empty string
    unconditionally is exactly what a mis-wired column does. It was there
    because a repeated value is blanked, so the fix is to pick a row that
    *starts* a run rather than to accept any answer.
    """
    load(window, ERRORS)
    index = next(
        i
        for i in range(1, 50)
        if isinstance(row := window.model.row_at(i), Record)
        and row.subsystem
        # The first of its run: the row above it says something different, so
        # nothing is blanked and the cell must carry the real value.
        and getattr(window.model.row_at(i - 1), "subsystem", None) != row.subsystem
    )
    row = window.model.row_at(index)
    assert isinstance(row, Record)
    shown = window.model.data(window.model.index(index, int(Column.SUBSYSTEM)))
    assert shown == row.subsystem


class TestChoosingATheme:
    """Following the system is the default, not the only option.

    Reported as "there is no dark mode". There was one; there was no way to ask
    for it, and the machine it was asked on is set to light.
    """

    def test_choosing_dark_takes_effect(self, window: MainWindow) -> None:
        window.toggle_dark_mode(dark=True)

        assert window.scheme is Scheme.DARK
        assert window.model.scheme is Scheme.DARK
        assert window.table.palette().base().color() == palette_for(Scheme.DARK).base().color()

    def test_a_choice_outranks_the_system(self, window: MainWindow) -> None:
        """Otherwise the next time the machine changes its mind it silently
        overrules the person using the program."""
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        gc.collect()

        window.toggle_dark_mode(dark=True)
        app.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Light)

        assert window.scheme is Scheme.DARK

    def test_a_choice_outranks_the_system_for_the_chrome_as_well(self, window: MainWindow) -> None:
        """The half of that rule which nothing enforced.

        Two objects answered `colorSchemeChanged` under different rules: this
        window, only while the user had expressed no preference, and
        `gui.app`, unconditionally. So a system switch after a choice moved the
        application palette and the chrome stylesheet while the table, the
        model, the minimap and the icons stayed where the user had put them --
        a dark window with a white log in the middle of it. Asserting
        ``window.scheme`` could never catch it, because the window was the one
        behaving correctly.

        The handler is called directly rather than through the signal. The
        application palette is global and `colorSchemeChanged` reaches every
        window still alive in the process, so in a suite that has built a
        hundred of them the signal proves whatever the last one to answer
        happened to think. One window's rule is what is under test.
        """
        app = QApplication.instance()
        assert isinstance(app, QApplication)

        window.toggle_dark_mode(dark=True)
        window._on_color_scheme_changed(Qt.ColorScheme.Light)

        chosen = palette_for(Scheme.DARK).base().color()
        assert app.palette().base().color() == chosen, "the application followed the system anyway"
        assert window.table.palette().base().color() == chosen

    def test_following_the_system_moves_the_application_as_well(self, window: MainWindow) -> None:
        """And the other direction: with no choice made, both halves move.

        Removing `gui.app`'s connection is only correct if the window's own
        handler took over the application-wide half of the switch -- which the
        old one did not do, because something else was doing it.
        """
        app = QApplication.instance()
        assert isinstance(app, QApplication)

        window._on_color_scheme_changed(Qt.ColorScheme.Dark)

        expected = palette_for(Scheme.DARK).base().color()
        assert app.palette().base().color() == expected
        assert window.table.palette().base().color() == expected

    def test_following_the_system_is_not_a_choice(self, window: MainWindow) -> None:
        """The checkbox is wired to the toggle, so moving it to match the system
        would mark the theme as chosen -- and one system switch would work while
        every one after it did nothing."""
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        gc.collect()

        hints = app.styleHints()
        for emitted, expected in (
            (Qt.ColorScheme.Dark, Scheme.DARK),
            (Qt.ColorScheme.Light, Scheme.LIGHT),
            (Qt.ColorScheme.Dark, Scheme.DARK),
        ):
            hints.colorSchemeChanged.emit(emitted)
            assert window.scheme is expected
            assert window.action_dark_mode.isChecked() is (expected is Scheme.DARK)

    def test_the_choice_is_remembered(self, window: MainWindow) -> None:
        window.toggle_dark_mode(dark=True)

        reopened = MainWindow()
        assert reopened.scheme is Scheme.DARK
        assert reopened.action_dark_mode.isChecked()


class TestTheMinimapKnowsWhereTheReaderIs:
    """The strip draws a viewport marker; this is the half that feeds it.

    Both pieces can be right and the picture still wrong, which is why the
    painting is asserted next door and the connection is asserted here.
    """

    def test_scrolling_moves_the_marker(self, window: MainWindow) -> None:
        load(window, ERRORS)
        window.table.resize(600, 300)
        window.table.show()
        QApplication.processEvents()
        started = window.minimap._viewport

        window.go_to(2_500)
        QApplication.processEvents()

        assert started[1] >= started[0], "the marker never got a range to begin with"
        assert window.minimap._viewport[0] > started[0]

    def test_it_is_told_without_a_capture_running(self, window: MainWindow) -> None:
        """Nothing here is routed through the pump.

        A marker fed from the capture tick would sit at the top of every file
        anybody opened, which is the only way most people will use this.
        """
        load(window, ERRORS)
        window.table.resize(600, 300)
        window.table.show()
        QApplication.processEvents()

        assert window._pump is None, "a capture was running, so this proves nothing"
        assert window.minimap._viewport != (0, -1)
