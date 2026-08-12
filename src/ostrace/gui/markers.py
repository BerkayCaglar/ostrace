# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rows that are not device records.

A marker states something about the *integrity* of what is on screen: records
were lost, or records were dropped from the view. `docs/design/gui.md` §3 makes
one invariant of it — **a marker is never hidden by a filter** — because a
filter says which records the user wants, and a marker says whether the answer
is complete. Hiding it makes the filtered view lie about itself.

`Gap` is not defined here: it belongs to the capture, travels in the record
stream in position, and is written to the session file. `Eviction` is the view's
own, and the distinction is the point:

- a **gap** means those records are gone, and nothing buffered them;
- an **eviction** means those records are on disk and merely not on screen.

Rendering the two the same way would make the GUI lie about the session file,
which is a worse failure than either. Every log viewer surveyed says nothing
at all when its own buffer evicts — Logcat's ``trimToSize()`` is silent, and
Console.app discards after "a few seconds" at exactly this project's
throughput.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias, TypeGuard

from ostrace.model import Gap, Record

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

__all__ = ["Eviction", "Row", "TrimPlan", "is_marker", "is_record", "plan_trim", "when"]


@dataclass(frozen=True, slots=True)
class Eviction:
    """The view dropped its own oldest rows to stay bounded.

    One of these sits at the head of the view once anything has been evicted,
    and it is *updated* rather than accumulated -- twenty evictions are one
    fact about the view, not twenty rows of noise at the top.
    """

    count: int
    #: The timestamp of the newest record that was dropped, so the row can say
    #: where the visible window actually begins.
    through: datetime

    @property
    def text(self) -> str:
        """Wording that does not overstate the loss.

        It says where to look, because there *is* somewhere to look. A gap has
        no such sentence and must not borrow one.
        """
        return (
            f"---- {self.count:,} earlier records are in the capture but not in "
            f"this view (through {self.through:%H:%M:%S}) ----"
        )


#: What a row of the model holds.
Row: TypeAlias = Record | Gap | Eviction


def when(row: Row) -> datetime:
    """When a row happened, whichever of the three kinds it is.

    The three carry the instant under three different names, and each name is
    right for its own kind: a record has one timestamp, a gap has a start and
    an end, and an eviction is a running total whose only instant is the newest
    record it covers. A search by time has to treat them as one sequence, so
    the mapping lives here beside the alias rather than as a chain of
    ``isinstance`` in whoever is searching.

    A gap answers with its *start*: it begins where the records stopped, which
    is the moment somebody looking for "when did it go quiet" means.
    """
    if isinstance(row, Record):
        return row.timestamp
    if isinstance(row, Gap):
        return row.start
    return row.through


def is_record(row: Row) -> TypeGuard[Record]:
    """Whether ``row`` is a device record, and therefore filterable.

    A `TypeGuard` rather than a bare predicate so that the one place which
    decides -- `models.RecordModel._passes` -- is also the place a type checker
    proves a filter is only ever handed a `Record`. The invariant and the types
    then say the same thing, and neither can drift from the other.
    """
    return isinstance(row, Record)


def is_marker(row: Row) -> bool:
    """Whether ``row`` is exempt from filtering.

    By type, at one place. This is the whole implementation of the invariant in
    §3, and it is deliberately a type test rather than a predicate: Android
    Studio has the same mechanism and still let one discontinuity notice
    through as an ordinary record, so a ``tag:`` filter hides the message
    explaining why data is missing.
    """
    return not is_record(row)


@dataclass(frozen=True, slots=True)
class TrimPlan:
    """What one trim will do, worked out before anything moves.

    Separated from the doing because the arithmetic is the hard part and the
    bracketing is the dangerous part, and neither is easy to read while it is
    tangled with the other. `beginRemoveRows` and `beginInsertRows` are not
    interchangeable and the wrong one silently corrupts a view's idea of its
    own rows -- so the decision about *which* bracket to open is made here,
    where it can be asserted without a model, and carried out there, next to
    the mutation it protects.
    """

    #: Source rows leaving, always a prefix and always on a row boundary.
    drop: int
    #: What every surviving index moves by. One less than ``drop`` when a
    #: notice takes the departing rows' place at the top.
    offset: int
    #: View rows leaving. Zero when the filter was already hiding all of them.
    gone: int
    #: The eviction notice to put at the top, or ``None`` when nothing dropped
    #: was a record -- there is no such thing as "gaps evicted".
    notice: Eviction | None
    #: Whether a notice is already at the top, being replaced rather than
    #: added. The difference between the surviving rows keeping their view
    #: positions and all of them shifting by one.
    replacing: bool
    #: Records and gaps in the dropped prefix, for the counters the status bar
    #: reads once per pump tick.
    records: int
    gaps: int


def plan_trim(
    rows: Sequence[Row],
    visible: Sequence[int],
    *,
    row_cap: int,
    margin: float,
    evicted: int,
) -> TrimPlan | None:
    """Work out the trim, or ``None`` when the cap has not been exceeded.

    One pass over the prefix that is leaving. The newest dropped timestamp
    comes out of that pass rather than from a ``max()`` over twenty thousand
    rows, because they are in arrival order and it is always the last one --
    which was measured, and was part of the 118 ms this operation used to cost.

    ``visible`` is ascending, so the visible rows being removed are a
    contiguous prefix of it: that is what makes a trim one removal rather than
    twenty thousand, and it is why the answer can be found by bisection.
    """
    if len(rows) <= int(row_cap * (1 + margin)):
        return None

    drop = len(rows) - row_cap
    records = 0
    gaps = 0
    newest: datetime | None = None
    for row in rows[:drop]:
        if isinstance(row, Record):
            records += 1
            newest = row.timestamp
        elif isinstance(row, Gap):
            gaps += 1

    notice = Eviction(count=evicted + records, through=newest) if newest is not None else None
    replacing = bool(rows) and isinstance(rows[0], Eviction)

    gone = bisect_left(visible, drop)
    if notice is not None and replacing:
        # The old notice is inside the dropped prefix and the new one takes its
        # place, so one fewer row actually leaves the view.
        gone -= 1

    return TrimPlan(
        drop=drop,
        offset=drop - 1 if notice is not None else drop,
        gone=gone,
        notice=notice,
        replacing=replacing,
        records=records,
        gaps=gaps,
    )
