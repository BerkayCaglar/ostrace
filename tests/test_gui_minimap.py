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
from PySide6.QtGui import QImage, QMouseEvent

from ostrace.gui.filters import Filter
from ostrace.gui.models import BUCKET_ROWS, Band, RecordModel
from ostrace.gui.theme import Scheme, palette_for, severity_for
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


# -- the trim keeps the summary honest ---------------------------------------


def test_trimming_leaves_the_same_summary_as_a_full_rebuild(model: RecordModel) -> None:
    """The safety net under an optimisation that could drift silently.

    One trim drops 20,000 rows and cost 118 ms, most of it recomputing every
    bucket -- twice. It now reuses the buckets that survive, which is only
    correct while the cut lands on a bucket boundary and nothing has shifted
    the view rows underneath them. A summary that drifts out of step does not
    fail loudly: it points at the wrong part of the log, which is worse than
    no strip at all.

    So the assertion is equivalence with the slow path, not a timing.
    """
    model._row_cap = 2_000
    rows: list[object] = []
    for index in range(6_000):
        rows.append(make_record(index, level=Level.ERROR if index % 97 == 0 else Level.DEBUG))
        if index % 1_500 == 0:
            rows.append(gap_at(index))
    model.append(rows)  # type: ignore[arg-type]

    assert len(model._rows) <= int(2_000 * 1.1) + 1, "the cap did not bite"
    fast = model.overview(BANDS)

    model._rebuild_buckets()
    assert model.overview(BANDS) == fast


def test_the_gap_count_survives_trimming(model: RecordModel) -> None:
    """It is read once per pump tick, so it is maintained rather than scanned
    -- and a maintained counter is one that can drift."""
    model._row_cap = 500
    rows: list[object] = []
    for index in range(3_000):
        rows.append(make_record(index))
        if index % 250 == 0:
            rows.append(gap_at(index))
    model.append(rows)  # type: ignore[arg-type]

    assert model.gaps == sum(1 for row in model._rows if isinstance(row, Gap))


def test_the_gap_count_matches_after_every_batch(model: RecordModel) -> None:
    model.append([make_record(0), gap_at(1), make_record(1)])
    assert model.gaps == 1
    model.append([gap_at(2), gap_at(3)])
    assert model.gaps == 3
    model.set_filter(Filter(minimum_level=Level.FAULT))
    assert model.gaps == 3, "a filter hides rows; it does not discard the capture"


def test_a_theme_switch_reaches_the_background(qt_app: object) -> None:
    """The background colour is prebuilt with the stripe colours rather than
    looked up in `paintEvent`, because `palette_for` measured 60.6 us a call
    and this repaints on every scroll, every arriving batch and every resize.

    Prebuilding is only correct if the switch invalidates it, and nothing else
    here would notice: every other rendering test builds the strip in the
    scheme it then asserts. Leaving the refresh out of `set_scheme` left all
    371 GUI tests green and the strip painting a light background inside a dark
    window.
    """
    del qt_app
    strip = Minimap(Scheme.LIGHT)
    strip.resize(10, 40)

    strip.set_scheme(Scheme.DARK)

    image = QImage(strip.size(), QImage.Format.Format_ARGB32)
    strip.render(image)
    wanted = palette_for(Scheme.DARK).base().color().name()
    assert image.pixelColor(5, 20).name() == wanted, "the strip kept the light background"


def test_the_strip_actually_draws_its_bands(qt_app: object) -> None:
    """Every other test here asserts `overview()` -- the data, not the picture.

    Making `paintEvent` return straight after filling the background left all
    of them green. That is the shape of the `FastHeader` bug this project
    already paid for: the suite passed, the benchmark improved, and only a
    screenshot showed an empty strip. Colour is not a font metric, so a render
    is safe offscreen.
    """
    del qt_app
    model = RecordModel(Scheme.LIGHT)
    model.append([make_record(index, level=Level.ERROR) for index in range(1000)])

    strip = Minimap(Scheme.LIGHT)
    strip.resize(10, 200)
    strip.set_model(model)

    image = QImage(strip.size(), QImage.Format.Format_ARGB32)
    strip.render(image)

    painted = {image.pixelColor(5, y).name() for y in range(200)}
    wanted = severity_for(Level.ERROR, Scheme.LIGHT).foreground.name()
    assert wanted in painted, f"the error colour {wanted} was never drawn"


class TestTheViewportMarker:
    """Where you are, on the strip that says what is there.

    Without it the strip is a picture rather than a map -- and the click-to-jump
    it has always had is aiming at a target the reader cannot see themselves on.
    """

    @staticmethod
    def _strip(qt_app: object, scheme: Scheme = Scheme.LIGHT) -> Minimap:
        del qt_app
        model = RecordModel(scheme)
        model.append([make_record(index) for index in range(1000)])
        strip = Minimap(scheme)
        strip.resize(10, 200)
        strip.set_model(model)
        return strip

    @staticmethod
    def _column(strip: Minimap) -> list[str]:
        """Every pixel down the middle of the strip, top to bottom."""
        image = QImage(strip.size(), QImage.Format.Format_ARGB32)
        strip.render(image)
        return [image.pixelColor(5, y).name() for y in range(strip.height())]

    @staticmethod
    def _marked(column: list[str], base: str) -> list[int]:
        return [y for y, colour in enumerate(column) if colour != base]

    def test_it_is_drawn_where_the_reader_is(self, qt_app: object) -> None:
        """Read off the picture, not off the stored range.

        The whole failure mode here is a marker that is computed correctly and
        painted nowhere -- which is what `paintEvent` returning early already
        did to the bands once, with the suite green throughout.
        """
        strip = self._strip(qt_app)
        base = self._column(strip)[0]

        strip.set_viewport(0, 39)
        top = self._marked(self._column(strip), base)

        strip.set_viewport(600, 639)
        low = self._marked(self._column(strip), base)

        assert top, "nothing was drawn for a viewport at the top"
        assert low, "nothing was drawn for a viewport further down"
        assert max(top) < min(low), "the marker did not move down with the viewport"

    def test_it_covers_the_share_of_the_capture_that_is_on_screen(self, qt_app: object) -> None:
        """Half the rows on screen is half the strip, near enough.

        Near enough because the edge is drawn on the boundary and the fill is
        rounded to whole pixels; the assertion is the proportion rather than an
        exact pixel count, which would be asserting the rounding.
        """
        strip = self._strip(qt_app)
        base = self._column(strip)[0]

        strip.set_viewport(0, 499)
        half = self._marked(self._column(strip), base)

        assert 90 <= len(half) <= 110, f"{len(half)} of 200 pixels for half the capture"

    def test_a_viewport_too_small_to_see_is_still_drawn(self, qt_app: object) -> None:
        """Forty rows in two hundred thousand is a third of a pixel.

        Rounded away, and the reader concludes the strip has no marker at all.
        """
        strip = self._strip(qt_app)
        base = self._column(strip)[0]

        strip.set_viewport(500, 501)

        assert len(self._marked(self._column(strip), base)) >= 3

    def test_an_empty_range_draws_nothing(self, qt_app: object) -> None:
        """What a window with no capture in it reports, and there is nowhere in
        an empty strip for a reader to be."""
        strip = self._strip(qt_app)
        base = self._column(strip)[0]

        strip.set_viewport(0, -1)

        assert self._marked(self._column(strip), base) == []

    def test_it_follows_the_scheme(self, qt_app: object) -> None:
        """The marker itself, not the background behind it.

        Comparing two whole strips would pass without a marker at all, because
        the two schemes fill their backgrounds differently to begin with.
        """
        marks = {}
        for scheme in (Scheme.LIGHT, Scheme.DARK):
            strip = self._strip(qt_app, scheme)
            base = self._column(strip)[0]
            strip.set_viewport(0, 99)
            column = self._column(strip)
            marks[scheme] = {column[y] for y in self._marked(column, base)}
            assert marks[scheme], f"nothing was drawn under {scheme}"

        assert marks[Scheme.LIGHT].isdisjoint(marks[Scheme.DARK])

    def test_the_same_range_twice_does_not_repaint(self, qt_app: object) -> None:
        """Asked on every scroll, every resize and every batch of arrivals, and
        a reader stopped on one screen of a growing capture gets the same
        answer every time."""
        strip = self._strip(qt_app)
        strip.set_viewport(10, 50)

        updates: list[int] = []
        strip.update = lambda: updates.append(1)  # type: ignore[assignment,method-assign]

        strip.set_viewport(10, 50)
        assert updates == []

        strip.set_viewport(10, 51)
        assert updates == [1]


def test_the_drawn_colours_follow_the_scheme(qt_app: object) -> None:
    """`set_scheme` rebuilds the prebuilt colours; nothing checked they reach
    the paint."""
    del qt_app
    model = RecordModel(Scheme.LIGHT)
    model.append([make_record(index, level=Level.ERROR) for index in range(1000)])

    def painted(scheme: Scheme) -> set[str]:
        strip = Minimap(scheme)
        strip.resize(10, 200)
        strip.set_model(model)
        image = QImage(strip.size(), QImage.Format.Format_ARGB32)
        strip.render(image)
        return {image.pixelColor(5, y).name() for y in range(200)}

    assert painted(Scheme.LIGHT) != painted(Scheme.DARK)
