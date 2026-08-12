# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a trim will do, worked out without doing it.

No Qt. The arithmetic is the hard part of the hardest method in the model --
a bisect, two off-by-ones and a decision about which Qt bracket to open, where
the wrong bracket silently corrupts a view's idea of its own rows. Asserting it
used to mean building a model, filling it past a cap and reading the signals
back out.

The property tests below compare the plan against a naive recomputation over
generated inputs. The naive version is deliberately stupid -- it filters lists
where the real one bisects -- because the point of a second implementation is
that it is wrong in different places, and agreeing on ten thousand inputs is
evidence the way one careful reading is not.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from ostrace.gui.markers import Eviction, Row, TrimPlan, plan_trim
from ostrace.model import Gap, Record
from tests.helpers import make_record

MARGIN = 0.1


def gap(index: int) -> Gap:
    start = datetime(2026, 8, 8, 13, index % 60, tzinfo=UTC)
    return Gap(start=start, end=start, reason="dropped")


def build(shape: str) -> list[Row]:
    """Rows from a description: ``r`` record, ``g`` gap, ``e`` eviction."""
    rows: list[Row] = []
    for index, kind in enumerate(shape):
        if kind == "r":
            rows.append(make_record(index))
        elif kind == "g":
            rows.append(gap(index))
        else:
            rows.append(Eviction(count=index, through=datetime(2026, 8, 8, tzinfo=UTC)))
    return rows


@dataclass(frozen=True, slots=True)
class Naive:
    """The same answer, computed the obvious way. Not fast, and not clever."""

    drop: int
    offset: int
    gone: int
    has_notice: bool
    replacing: bool
    records: int
    gaps: int


def naively(rows: list[Row], visible: list[int], row_cap: int, evicted: int) -> Naive | None:
    del evicted
    if len(rows) <= int(row_cap * (1 + MARGIN)):
        return None
    drop = len(rows) - row_cap
    dropped = rows[:drop]
    records = len([row for row in dropped if isinstance(row, Record)])
    gaps = len([row for row in dropped if isinstance(row, Gap)])
    has_notice = records > 0
    replacing = bool(rows) and isinstance(rows[0], Eviction)
    gone = len([index for index in visible if index < drop])
    if has_notice and replacing:
        gone -= 1
    return Naive(
        drop=drop,
        offset=drop - 1 if has_notice else drop,
        gone=gone,
        has_notice=has_notice,
        replacing=replacing,
        records=records,
        gaps=gaps,
    )


def plan(rows: list[Row], visible: list[int], row_cap: int, evicted: int = 0) -> TrimPlan | None:
    return plan_trim(rows, visible, row_cap=row_cap, margin=MARGIN, evicted=evicted)


class TestWhenNothingHappens:
    def test_under_the_cap_is_no_plan(self) -> None:
        rows = build("r" * 50)

        assert plan(rows, list(range(50)), row_cap=100) is None

    def test_over_the_cap_but_inside_the_margin_is_no_plan(self) -> None:
        """The margin is what makes a trim amortised. Trimming the moment the
        cap is passed would trim on every arriving batch forever."""
        rows = build("r" * 105)

        assert plan(rows, list(range(105)), row_cap=100) is None

    def test_the_margin_is_where_it_says_it_is(self) -> None:
        rows = build("r" * 111)

        trimmed = plan(rows, list(range(111)), row_cap=100)

        assert trimmed is not None
        assert trimmed.drop == 11, "everything above the cap goes, not everything above the margin"


class TestTheNotice:
    def test_dropping_only_gaps_makes_no_notice(self) -> None:
        """There is no such thing as "gaps evicted": a gap is already the
        record of something missing, and a notice about one would be a second
        marker for the same fact."""
        rows = build("g" * 60 + "r" * 60)

        trimmed = plan(rows, list(range(120)), row_cap=100)

        assert trimmed is not None
        assert trimmed.records == 0
        assert trimmed.notice is None
        assert trimmed.offset == trimmed.drop, "nothing takes the dropped rows' place"

    def test_the_notice_counts_every_record_ever_evicted(self) -> None:
        rows = build("r" * 120)

        trimmed = plan(rows, list(range(120)), row_cap=100, evicted=500)

        assert trimmed is not None
        assert trimmed.notice is not None
        assert trimmed.notice.count == 520

    def test_the_notice_carries_the_newest_dropped_timestamp(self) -> None:
        """Always the last one, because rows are in arrival order -- which is
        why this is a single pass and not a `max()` over twenty thousand."""
        rows = build("r" * 120)
        last_dropped = rows[19]
        assert isinstance(last_dropped, Record)

        trimmed = plan(rows, list(range(120)), row_cap=100)

        assert trimmed is not None
        assert trimmed.notice is not None
        assert trimmed.notice.through == last_dropped.timestamp

    def test_replacing_a_notice_shifts_the_survivors_by_one_less(self) -> None:
        """The old notice is inside the dropped prefix and the new one takes
        its place, so one fewer row actually leaves the view."""
        rows = build("e" + "r" * 119)

        trimmed = plan(rows, list(range(120)), row_cap=100)

        assert trimmed is not None
        assert trimmed.replacing is True
        assert trimmed.gone == trimmed.drop - 1


class TestAgainstANaiveRecomputation:
    """Ten thousand shapes, two implementations, one answer."""

    @pytest.mark.parametrize("seed", range(20))
    def test_they_agree(self, seed: int) -> None:
        rng = random.Random(seed)
        for _ in range(500):
            length = rng.randrange(0, 260)
            shape = "".join(rng.choice("rrrrggge") for _ in range(length))
            rows = build(shape)
            visible = sorted(rng.sample(range(length), k=rng.randrange(0, length + 1)))
            row_cap = rng.randrange(1, 200)

            wanted = naively(rows, visible, row_cap, evicted=0)
            got = plan(rows, visible, row_cap)

            if wanted is None:
                assert got is None, f"{shape=} {row_cap=}"
                continue
            assert got is not None, f"{shape=} {row_cap=}"
            assert (got.drop, got.offset, got.gone) == (wanted.drop, wanted.offset, wanted.gone), (
                f"{shape=} {visible=} {row_cap=}"
            )
            assert (got.records, got.gaps) == (wanted.records, wanted.gaps), f"{shape=}"
            assert (got.notice is not None) == wanted.has_notice, f"{shape=}"
            assert got.replacing == wanted.replacing, f"{shape=}"

    def test_a_filter_hiding_the_dropped_rows_removes_nothing_from_the_view(self) -> None:
        """The case the bisection exists for, and the one an off-by-one would
        get wrong quietly: everything leaving the model was already hidden, so
        the view loses no rows and must not be told it did."""
        rows = build("r" * 200)
        visible = list(range(150, 200))

        trimmed = plan(rows, visible, row_cap=100)

        assert trimmed is not None
        assert trimmed.drop == 100
        assert trimmed.gone == 0
