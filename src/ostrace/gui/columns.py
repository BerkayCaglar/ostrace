# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the table shows, and in what order.

`Record` has thirteen fields and the table shows six. The split is not about
width: the table carries what you *scan*, and the detail pane carries what you
*confirm* once something has caught your eye. See `docs/design/gui.md` §2.

Widths are starting points in character units, resolved against the actual font
at run time, because a pixel width is wrong on every display that is not the
one it was chosen on -- and macOS reports an integer device pixel ratio where
Windows allows fractional, so there is no single correct pixel number.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

__all__ = ["COLUMNS", "Column", "column_spec"]


class Column(IntEnum):
    """Column order. **Contract with the user's muscle memory**, not with disk."""

    TIME = 0
    LEVEL = 1
    PROCESS = 2
    SUBSYSTEM = 3
    CATEGORY = 4
    MESSAGE = 5


@dataclass(frozen=True, slots=True)
class Spec:
    """One column's presentation."""

    column: Column
    title: str
    #: Width in average character widths. ``None`` means "take what is left",
    #: which exactly one column may do.
    characters: int | None
    #: Blank the cell when it repeats the row above. Cheap in a delegate, and
    #: it transforms scannability on a log where a process emits hundreds of
    #: consecutive records.
    collapse_repeats: bool = False


COLUMNS: tuple[Spec, ...] = (
    Spec(Column.TIME, "Time", 13),
    Spec(Column.LEVEL, "Level", 12),
    Spec(Column.PROCESS, "Process", 22, collapse_repeats=True),
    Spec(Column.SUBSYSTEM, "Subsystem", 26, collapse_repeats=True),
    Spec(Column.CATEGORY, "Category", 18, collapse_repeats=True),
    Spec(Column.MESSAGE, "Message", None),
)


def column_spec(column: Column) -> Spec:
    """The spec for one column."""
    return COLUMNS[int(column)]
