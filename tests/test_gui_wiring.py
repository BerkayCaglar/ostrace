# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The window driven end to end against a real capture.

No display and no clicking: the loader is stepped by hand and the widgets are
addressed directly, so this runs offscreen on all three operating systems like
everything else. What it proves is that the pieces are actually connected --
which is the class of bug that unit tests on each piece cannot see.
"""

from __future__ import annotations

import pytest

from ostrace.model import Level, Record
from tests.helpers import ERRORS, MIXED

pytest.importorskip("PySide6", reason="the gui extra is not installed")

from ostrace.gui.columns import Column
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
