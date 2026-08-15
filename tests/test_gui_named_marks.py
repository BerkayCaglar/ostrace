# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Marks that carry a note, and that outlive the window.

Two things are being asserted here and they pull in opposite directions. A mark
must still be one keypress with nothing asked of the reader — naming is the
expensive half and going back is the useful one — and a mark that *is* named has
to survive a trim, a rebase, a restart, and a settings file somebody has edited
by hand.

The persistence half keys on the record's timestamp, because a source index
means nothing between sessions. `docs/design/gui.md` §5 carries the measurement
that makes that usable: 39,786 records off an `iPhone18,2` across two captures,
every timestamp unique.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ostrace.model import Gap
from tests.helpers import ERRORS, load, make_record

pytest.importorskip("PySide6", reason="the gui extra is not installed")

from PySide6.QtCore import QSettings

from ostrace.gui.columns import Column
from ostrace.gui.markers import when
from ostrace.gui.models import RecordModel
from ostrace.gui.settings import MARKED_CAPTURES, WindowSettings
from ostrace.gui.windows.main import MainWindow

pytestmark = pytest.mark.gui


@pytest.fixture
def model(qt_app: object) -> RecordModel:
    del qt_app
    built = RecordModel()
    built.append([make_record(i, message=f"record {i}") for i in range(20)])
    return built


@pytest.fixture
def window(qt_app: object) -> MainWindow:
    del qt_app
    return MainWindow()


@pytest.fixture
def settings() -> WindowSettings:
    """A store of its own, emptied first.

    `conftest` redirects where `QSettings` files live per test, and that is not
    enough on its own: Qt caches an instance per organisation and application
    inside the process, so a store built with the same pair in a later test
    hands back the values the earlier one wrote. Found exactly that way — a test
    asserting an empty store failed carrying its neighbour's capture.
    """
    store = QSettings("ostrace-test", "marks")
    store.clear()
    return WindowSettings(store)


# -- naming ------------------------------------------------------------------


def test_a_mark_starts_unnamed(model: RecordModel) -> None:
    """One keypress, nothing asked. A viewer that wanted a name before it would
    remember anything gets asked for nothing — the recent-filter argument,
    applied to the other thing a reader leaves behind."""
    model.toggle_mark(3)
    assert model.is_marked(3)
    assert model.mark_name(3) == ""


def test_naming_an_unmarked_row_marks_it(model: RecordModel) -> None:
    """Typing a note about a row says something stronger than the key that
    merely flags one, so it is not made to come second."""
    model.set_mark_name(5, "watchdog fires here")
    assert model.is_marked(5)
    assert model.mark_name(5) == "watchdog fires here"


def test_clearing_a_name_keeps_the_mark(model: RecordModel) -> None:
    """Emptying the text is a correction. Answering it by unmarking would lose
    the row as well as the note."""
    model.set_mark_name(5, "wrong")
    model.set_mark_name(5, "")
    assert model.is_marked(5)
    assert model.mark_name(5) == ""


def test_a_name_is_stripped_and_an_unchanged_name_is_not_a_change(
    model: RecordModel,
) -> None:
    changes = 0

    def count() -> None:
        nonlocal changes
        changes += 1

    model.set_mark_name(5, "  spaced  ")
    assert model.mark_name(5) == "spaced"
    model.marks_changed.connect(count)
    model.set_mark_name(5, "spaced")
    assert changes == 0


def test_an_unmarked_row_has_no_name(model: RecordModel) -> None:
    assert model.mark_name(2) == ""


# -- surviving what moves the rows -------------------------------------------


def test_names_survive_a_trim() -> None:
    """The rebase moves marks with their records; it has to move the notes with
    them, or a name ends up describing somebody else's message.

    Marked *after* the first trim and near the end, which is the case worth
    asserting: a mark on a record the next trim evicts is supposed to go with
    it, and a test that marked one of those would pass while proving the
    opposite thing.
    """
    bounded = RecordModel(row_cap=100)
    bounded.append([make_record(i, message=f"early {i}") for i in range(200)])
    last = bounded.rowCount() - 1
    bounded.set_mark_name(last, "the interesting one")
    marked = bounded.cell_text(last, int(Column.MESSAGE))

    bounded.append([make_record(i, message=f"later {i}") for i in range(40)])

    rows = bounded.marked_view_rows()
    assert len(rows) == 1
    assert bounded.mark_name(rows[0]) == "the interesting one"
    assert bounded.cell_text(rows[0], int(Column.MESSAGE)) == marked


def test_a_mark_on_an_evicted_record_goes_with_it() -> None:
    """The other half of the same rule, and the reason the one above has to mark
    a row near the end: keeping a mark that points at nothing is worse than
    losing it, because the reader jumps to a row that is not the one they
    marked."""
    bounded = RecordModel(row_cap=100)
    bounded.append([make_record(i, message=f"early {i}") for i in range(60)])
    bounded.set_mark_name(0, "gone soon")
    bounded.append([make_record(i, message=f"later {i}") for i in range(300)])
    assert bounded.marks == 0


def test_names_survive_the_eviction_notice_being_inserted(model: RecordModel) -> None:
    """`note_eviction` shifts every source index by one to make room at the top."""
    model.set_mark_name(4, "before the notice")
    model.note_eviction(12, datetime.now(UTC))
    rows = model.marked_view_rows()
    assert [model.mark_name(row) for row in rows] == ["before the notice"]


# -- what gets written out ---------------------------------------------------


def test_named_marks_carry_the_moment_rather_than_the_row(model: RecordModel) -> None:
    model.set_mark_name(4, "here")
    (moment, name), *rest = model.named_marks()
    assert not rest
    assert name == "here"
    # `when` rather than `.timestamp`: a row can be a marker, which carries its
    # moment under a different name. That is the model's own rule, so the test
    # reads it the model's way.
    assert moment == when(model.row_at(4))


def test_a_mark_on_an_eviction_notice_is_not_written_out(model: RecordModel) -> None:
    """That row is an artefact of this view's cap, not a moment in the capture,
    and a restored mark pointing at one would be a note about a notice."""
    model.note_eviction(12, datetime.now(UTC))
    model.set_mark_name(0, "the notice")
    model.set_mark_name(3, "a real record")
    assert [name for _, name in model.named_marks()] == ["a real record"]


def test_a_gap_can_be_marked_and_written_out() -> None:
    """A gap is exactly the kind of thing worth annotating — it is the row that
    says the log is incomplete."""
    model = RecordModel()
    moment = make_record(0).timestamp
    model.append(
        [
            make_record(0),
            Gap(start=moment, end=moment + timedelta(seconds=8), reason="the cable was pulled"),
        ]
    )
    model.set_mark_name(1, "unplugged it here")
    assert model.named_marks() == [(moment, "unplugged it here")]


# -- putting them back -------------------------------------------------------


def test_marks_are_restored_onto_the_rows_they_were_made_on(
    model: RecordModel,
) -> None:
    model.set_mark_name(4, "here")
    model.set_mark_name(9, "and here")
    saved = model.named_marks()

    fresh = RecordModel()
    fresh.append([make_record(i, message=f"record {i}") for i in range(20)])
    assert fresh.restore_marks(saved) == 2
    assert fresh.mark_name(4) == "here"
    assert fresh.mark_name(9) == "and here"


def test_restoring_says_how_many_landed(model: RecordModel) -> None:
    """A capture read under a row cap holds its tail, so a mark made near its
    beginning has no row to go back to. The count is what lets the window say so
    rather than silently returning four of eleven."""
    lost = datetime.now(UTC) + timedelta(days=1)
    assert model.restore_marks([(when(model.row_at(2)), "kept"), (lost, "gone")]) == 1
    assert model.mark_name(2) == "kept"


def test_restoring_into_an_empty_model_does_nothing(qt_app: object) -> None:
    del qt_app
    assert RecordModel().restore_marks([(datetime.now(UTC), "x")]) == 0


# -- the panel ---------------------------------------------------------------


def test_the_panel_shows_the_name_in_place_of_the_message(window: MainWindow) -> None:
    """A name exists precisely because the message head was not a good enough
    label, so showing both would put the worse one back beside it."""
    window.model.append([make_record(i, message=f"a long dull message {i}") for i in range(5)])
    window.model.set_mark_name(2, "watchdog fires here")
    window.marks_panel.rebuild()
    assert any("watchdog fires here" in entry for entry in window.marks_panel.entries)
    assert not any("a long dull message 2" in entry for entry in window.marks_panel.entries)


def test_the_name_comes_straight_after_the_time(window: MainWindow) -> None:
    """The panel is a narrow dock, so whatever is last on the line is what gets
    elided away. Written after the level and the process, the name was exactly
    that — a rendered panel showed the line ending at the process and the one
    part the reader wrote themselves never on screen.
    """
    window.model.append([make_record(i, message=f"a long dull message {i}") for i in range(5)])
    window.model.set_mark_name(2, "watchdog fires here")
    window.marks_panel.rebuild()
    entry = next(item for item in window.marks_panel.entries if "watchdog" in item)
    time = window.model.cell_text(2, int(Column.TIME))
    assert entry == f"{time}  watchdog fires here"


def test_the_panel_still_shows_the_message_for_an_unnamed_mark(
    window: MainWindow,
) -> None:
    window.model.append([make_record(i, message=f"a long dull message {i}") for i in range(5)])
    window.model.toggle_mark(2)
    window.marks_panel.rebuild()
    assert any("a long dull message 2" in entry for entry in window.marks_panel.entries)


# -- the settings store ------------------------------------------------------


def test_marks_round_trip_through_the_store(settings: WindowSettings) -> None:
    capture = Path("/captures/one.jsonl.gz")
    marks = [(datetime.now(UTC), "first"), (datetime.now(UTC) + timedelta(seconds=1), "second")]
    settings.write_marks(capture, marks)
    assert settings.read_marks(capture) == marks


def test_each_capture_keeps_its_own_marks(settings: WindowSettings) -> None:
    moment = datetime.now(UTC)
    settings.write_marks(Path("/captures/one.jsonl.gz"), [(moment, "one")])
    settings.write_marks(Path("/captures/two.jsonl.gz"), [(moment, "two")])
    assert settings.read_marks(Path("/captures/one.jsonl.gz")) == [(moment, "one")]
    assert settings.read_marks(Path("/captures/two.jsonl.gz")) == [(moment, "two")]


def test_a_capture_with_no_marks_left_is_removed(settings: WindowSettings) -> None:
    """An entry saying nothing still occupies one of the twenty."""
    capture = Path("/captures/one.jsonl.gz")
    settings.write_marks(capture, [(datetime.now(UTC), "one")])
    settings.write_marks(capture, [])
    assert settings.read_marks(capture) == []
    assert settings.store.value("marks/captures") == []


def test_the_oldest_capture_falls_off_the_end(settings: WindowSettings) -> None:
    """Capped by capture rather than by mark: one capture's notes are one piece
    of work, and the thing that grows without bound is how many captures have
    ever been opened."""
    moment = datetime.now(UTC)
    for index in range(MARKED_CAPTURES + 3):
        settings.write_marks(Path(f"/captures/{index}.jsonl.gz"), [(moment, str(index))])
    assert settings.read_marks(Path("/captures/0.jsonl.gz")) == []
    assert settings.read_marks(Path(f"/captures/{MARKED_CAPTURES + 2}.jsonl.gz")) == [
        (moment, str(MARKED_CAPTURES + 2))
    ]


def test_writing_a_capture_again_moves_it_to_the_front(settings: WindowSettings) -> None:
    """So the cap drops the capture nobody has opened in longest rather than the
    one that happened to be stored first."""
    moment = datetime.now(UTC)
    first = Path("/captures/first.jsonl.gz")
    settings.write_marks(first, [(moment, "first")])
    for index in range(MARKED_CAPTURES - 1):
        settings.write_marks(Path(f"/captures/{index}.jsonl.gz"), [(moment, str(index))])
    settings.write_marks(first, [(moment, "still here")])
    settings.write_marks(Path("/captures/one-more.jsonl.gz"), [(moment, "new")])
    assert settings.read_marks(first) == [(moment, "still here")]


def test_an_unreadable_entry_costs_itself(settings: WindowSettings) -> None:
    """The rule the recent filters follow: a line written by another version is
    that line's problem, not the store's."""
    moment = datetime.now(UTC)
    settings.write_marks(Path("/captures/good.jsonl.gz"), [(moment, "kept")])
    stored = settings.store.value("marks/captures")
    settings.store.setValue("marks/captures", ["not json at all", *stored, 17])
    assert settings.read_marks(Path("/captures/good.jsonl.gz")) == [(moment, "kept")]


def test_a_naive_moment_is_refused(settings: WindowSettings) -> None:
    """The project's timestamp rule, applied to a value read off disk exactly as
    it applies to one read off a device: a naive moment is rejected rather than
    guessed at."""
    capture = Path("/c.jsonl.gz")
    settings.store.setValue(
        "marks/captures",
        [
            json.dumps(
                {
                    "capture": str(capture.resolve()),
                    "marks": [
                        {"at": "2026-08-15T10:00:00", "name": "naive"},
                        {"at": "2026-08-15T10:00:01+03:00", "name": "aware"},
                    ],
                }
            )
        ],
    )
    assert [name for _, name in settings.read_marks(capture)] == ["aware"]


def test_one_capture_reached_by_two_paths_has_one_set_of_marks(
    settings: WindowSettings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same file opened from two directories is one capture. Filing its
    notes under the string each caller happened to type would look like losing
    them, depending on how the file was opened."""
    capture = tmp_path / "session.jsonl.gz"
    capture.write_bytes(b"")
    moment = datetime.now(UTC)
    settings.write_marks(capture, [(moment, "absolute")])
    monkeypatch.chdir(tmp_path)
    assert settings.read_marks(Path("session.jsonl.gz")) == [(moment, "absolute")]


def test_an_unknown_capture_has_no_marks(settings: WindowSettings) -> None:
    assert settings.read_marks(Path("/captures/never-seen.jsonl.gz")) == []


# -- the window, end to end --------------------------------------------------


def test_marks_come_back_when_the_capture_is_reopened(qt_app: object) -> None:
    """The whole point, and the only assertion that exercises the two halves
    against each other: the timestamps written on the way out are the handles
    resolved on the way in."""
    del qt_app
    window = MainWindow()
    load(window, ERRORS)
    window.model.set_mark_name(7, "the one that matters")
    marked = window.model.cell_text(7, int(Column.MESSAGE))
    window.close_capture()
    assert window.model.marks == 0

    load(window, ERRORS)
    rows = window.model.marked_view_rows()
    assert len(rows) == 1
    assert window.model.mark_name(rows[0]) == "the one that matters"
    assert window.model.cell_text(rows[0], int(Column.MESSAGE)) == marked


def test_an_unnamed_mark_comes_back_too(qt_app: object) -> None:
    del qt_app
    window = MainWindow()
    load(window, ERRORS)
    window.model.toggle_mark(3)
    window.close_capture()
    load(window, ERRORS)
    assert window.model.marks == 1
    assert window.model.mark_name(window.model.marked_view_rows()[0]) == ""


def test_clearing_the_marks_and_closing_forgets_them(qt_app: object) -> None:
    """A cleared mark is a decision, and it has to reach the store: marks that
    came back after being cleared would be the feature refusing to be switched
    off."""
    del qt_app
    window = MainWindow()
    load(window, ERRORS)
    window.model.toggle_mark(3)
    window.close_capture()
    load(window, ERRORS)
    window.clear_marks()
    window.close_capture()
    load(window, ERRORS)
    assert window.model.marks == 0
