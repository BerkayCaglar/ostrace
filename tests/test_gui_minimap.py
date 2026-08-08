# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The overview strip, and the two ways of getting it wrong.

It exists to reveal a discontinuity *outside* the viewport -- a gap forty
thousand rows above where somebody is reading is otherwise something they never
learn about. Both failures found while building it were about resolution, in
opposite directions, and both are asserted here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ostrace.model import Gap, Level, Record
from tests.helpers import make_record

pytest.importorskip("PySide6", reason="the gui extra is not installed")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent

from ostrace.gui.filters import Filter
from ostrace.gui.models import BUCKET_ROWS, Band, RecordModel
from ostrace.gui.theme import Scheme
from ostrace.gui.widgets.minimap import Minimap

pytestmark = pytest.mark.gui

BANDS = 180


def press_at(y: int) -> QMouseEvent:
    """A left click at ``y``. The six-argument form; the shorter one is
    deprecated in Qt 6 and warns."""
    point = QPointF(5, y)
    return QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        point,
        point,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def gap_at(offset: int = 0) -> Gap:
    start = datetime(2026, 8, 8, 13, 0, tzinfo=UTC) + timedelta(seconds=offset)
    return Gap(start=start, end=start + timedelta(seconds=2), reason="connection dropped")


@pytest.fixture
def model(qt_app: object) -> RecordModel:
    del qt_app
    return RecordModel(Scheme.LIGHT)


# -- resolution --------------------------------------------------------------


def test_a_single_gap_lights_a_single_band(model: RecordModel) -> None:
    """The first failure, and the one that matters.

    Summarising gaps by bucket smeared two gaps across seventy-nine bands out
    of a hundred and eighty -- a picture saying that two fifths of the log was
    missing. Gaps are rare and are the whole reason the strip exists, so they
    are placed exactly.
    """
    rows: list[object] = [make_record(i) for i in range(1200)]
    rows.insert(300, gap_at())
    model.append(rows)  # type: ignore[arg-type]

    bands = model.overview(BANDS)
    assert sum(1 for band in bands if band & Band.MARKER) == 1


def test_a_short_capture_is_not_collapsed_to_a_few_stripes(model: RecordModel) -> None:
    """The second failure, in the opposite direction.

    Lighting only the band a bucket *starts* in works when there are more
    buckets than bands, and collapses to five lit stripes out of a hundred and
    eighty when there are fewer. Every band a bucket spans gets its flags.
    """
    model.append([make_record(i, level=Level.ERROR) for i in range(BUCKET_ROWS * 2)])

    lit = sum(1 for band in model.overview(BANDS) if band & Band.ERROR)
    assert lit > BANDS // 2, f"only {lit} of {BANDS} bands lit"


def test_the_gap_lands_where_the_gap_is(model: RecordModel) -> None:
    """A marker in the wrong band is worse than no marker: it sends the reader
    to a part of the log that is intact."""
    rows: list[object] = [make_record(i) for i in range(1000)]
    rows.insert(900, gap_at())
    model.append(rows)  # type: ignore[arg-type]

    bands = model.overview(BANDS)
    lit = [index for index, band in enumerate(bands) if band & Band.MARKER]
    assert lit == [900 * BANDS // 1001]


def test_marks_are_placed_exactly_too(model: RecordModel) -> None:
    model.append([make_record(i) for i in range(1000)])
    model.toggle_mark(100)
    model.toggle_mark(700)

    bands = model.overview(BANDS)
    assert sum(1 for band in bands if band & Band.MARK) == 2


# -- keeping up --------------------------------------------------------------


def test_the_summary_follows_a_filter(model: RecordModel) -> None:
    """The strip describes what is on screen, not what is retained.

    A summary of hidden rows would point at bands the user cannot scroll to.
    Asserted by filtering the errors away entirely: counting lit bands before
    and after proves nothing, because a handful of errors spread through a
    capture lights every band either way.
    """
    model.append(
        [make_record(i, level=Level.ERROR, process="noisy") for i in range(300)]
        + [make_record(i, level=Level.INFO, process="quiet") for i in range(300)]
    )
    assert any(band & Band.ERROR for band in model.overview(BANDS))

    model.set_filter(Filter(process="quiet"))

    assert model.rowCount() == 300
    assert not any(band & Band.ERROR for band in model.overview(BANDS))


def test_appending_extends_the_summary(model: RecordModel) -> None:
    model.append([make_record(i) for i in range(500)])
    quiet = model.overview(BANDS)
    assert not any(quiet)

    model.append([make_record(500, level=Level.FAULT)])
    assert any(band & Band.ERROR for band in model.overview(BANDS))


def test_an_empty_model_summarises_to_nothing(model: RecordModel) -> None:
    assert model.overview(BANDS) == []


def test_zero_bands_is_not_an_error(model: RecordModel) -> None:
    """A strip with no height happens during layout, before the window is
    shown."""
    model.append([make_record(0)])
    assert model.overview(0) == []


# -- the widget --------------------------------------------------------------


def test_clicking_asks_for_the_row_under_the_cursor(qt_app: object) -> None:
    """What makes it a control rather than a decoration."""
    del qt_app
    model = RecordModel(Scheme.LIGHT)
    model.append([make_record(i) for i in range(1000)])

    strip = Minimap(Scheme.LIGHT)
    strip.resize(10, 200)
    strip.set_model(model)

    asked: list[int] = []
    strip.row_requested.connect(asked.append)

    strip.mousePressEvent(press_at(100))

    assert asked == [500]


def test_clicking_an_empty_strip_asks_for_nothing(qt_app: object) -> None:
    del qt_app
    strip = Minimap(Scheme.LIGHT)
    strip.resize(10, 200)
    strip.set_model(RecordModel(Scheme.LIGHT))

    asked: list[int] = []
    strip.row_requested.connect(asked.append)
    strip.mousePressEvent(press_at(100))
    assert asked == []


def test_the_strip_is_sized_from_the_font_not_in_pixels(qt_app: object) -> None:
    """macOS cannot have High DPI scaling turned off and reports an integer
    device pixel ratio where Windows allows fractional."""
    del qt_app
    strip = Minimap(Scheme.LIGHT)
    assert strip.width() == int(strip.fontMetrics().horizontalAdvance("0") * 2.0)


def test_rebuilding_only_repaints_when_something_changed(qt_app: object) -> None:
    """It runs four times a second during a capture; a repaint that draws the
    same picture is a repaint nobody needed."""
    del qt_app
    model = RecordModel(Scheme.LIGHT)
    model.append([make_record(i, level=Level.ERROR) for i in range(500)])
    strip = Minimap(Scheme.LIGHT)
    strip.resize(10, 200)
    strip.set_model(model)

    first = list(strip._bands)
    strip.rebuild()
    assert strip._bands == first

    model.append([make_record(500) for _ in range(2000)])
    strip.rebuild()
    assert strip._bands != first


def test_a_record_model_with_only_markers_still_summarises(model: RecordModel) -> None:
    """A capture that is nothing but a gap is degenerate but legal."""
    model.append([gap_at(1), gap_at(2)])
    bands = model.overview(BANDS)
    assert sum(1 for band in bands if band & Band.MARKER) >= 1
    assert not any(band & Band.ERROR for band in bands)


def test_the_summary_describes_records_not_rows(model: RecordModel) -> None:
    """One last sanity check that errors are read from the record and not from
    the row's position."""
    model.append(
        [make_record(0, level=Level.INFO), make_record(1, level=Level.FAULT)],
    )
    assert any(band & Band.ERROR for band in model.overview(BANDS))
    assert isinstance(model.row_at(1), Record)
