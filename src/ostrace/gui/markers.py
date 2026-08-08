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

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias, TypeGuard

from ostrace.model import Gap, Record

if TYPE_CHECKING:
    from datetime import datetime

__all__ = ["Eviction", "Row", "is_marker", "is_record"]


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
