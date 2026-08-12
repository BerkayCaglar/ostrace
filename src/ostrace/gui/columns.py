# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the table shows, and in what order.

`Record` has eleven fields and the table shows six. The split is not about
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

__all__ = [
    "COLUMNS",
    "MESSAGE_MINIMUM",
    "MINIMUM_CHARACTERS",
    "UNTRIMMABLE",
    "Column",
    "column_spec",
    "fit_budgets",
    "wanted_widths",
]


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


#: Characters the Message column is never squeezed below.
#:
#: The budgets above are what each column *wants*; this is what the table is
#: *for*. Measured on the shipped set at a 1,280-pixel window: five fixed
#: columns of 91 characters come to 1,183 pixels of a 1,254-pixel viewport, so
#: the message got 71 -- about five characters -- and the columns overflowed the
#: window besides, which is a horizontal scrollbar on a table with no rows in
#: it. Every budget is a want and this is a floor, so the floor wins.
MESSAGE_MINIMUM = 30

#: Columns whose content has a known length, and which therefore do not give any
#: of it up. A timestamp missing its last digits is a timestamp nobody can use,
#: and `Level` has to fit ``User Action`` and its glyph. Everything else is an
#: identifier that elides into something still recognisable.
UNTRIMMABLE = (Column.TIME, Column.LEVEL)

#: And a floor under the ones that do give room up, so that trimming never
#: reduces a column to punctuation.
MINIMUM_CHARACTERS = 8


def wanted_widths(unit: int, margins: int) -> dict[Column, int]:
    """What each fixed column asks for, in pixels.

    ``unit`` is the width of a ``0`` in the table's font and ``margins`` is what
    the style insets the text by, doubled. The margins are **added** rather than
    absorbed: a column is a budget of characters, and spending the budget on the
    column while the style spends the margins on the text elides the last
    character of a value sized to fit exactly.

    That did not show while the body font was proportional -- ``09:14:02.118``
    is mostly colons and full stops, narrower than the ``0`` the budget counts
    in, and Time had nine pixels of slack. In a monospaced face every character
    is the unit, the slack falls to one pixel, and the timestamp is the first
    thing to lose its last digit.
    """
    return {
        spec.column: spec.characters * unit + margins
        for spec in COLUMNS
        if spec.characters is not None
    }


def fit_budgets(budgets: dict[Column, int], unit: int, available: int) -> dict[Column, int]:
    """The budgets, trimmed until the message has room to be read.

    ``stretchLastSection`` only *grows* the last section into space that is left
    over. When the columns before it have already used the window there is
    nothing left, so it keeps its default hundred pixels and the table scrolls
    sideways -- with no rows in it, which is how this was noticed. Growing is
    the easy half; deciding what to give up is this.

    Nothing happens without a width, and nothing happens if the budgets already
    fit. When they do not, the shortfall comes out of the identifier columns in
    proportion to what they asked for, never out of the two whose content has a
    known length, and never below :data:`MINIMUM_CHARACTERS`. If even that is
    not enough the budgets stand and the scrollbar appears, which at that width
    is the honest answer.

    Arithmetic rather than a method, so that it can be asked about a fractional
    unit without a display: ``unit`` is where the device pixel ratio arrives --
    macOS reports an integer ratio and Windows allows fractional -- and it is
    the one input this has never been testable against.
    """
    room = available - MESSAGE_MINIMUM * unit
    if available <= 0 or sum(budgets.values()) <= room:
        return budgets

    untrimmable = sum(budgets[column] for column in UNTRIMMABLE if column in budgets)
    flexible = {column: width for column, width in budgets.items() if column not in UNTRIMMABLE}
    spare = room - untrimmable
    floor = MINIMUM_CHARACTERS * unit
    if not flexible or spare < floor * len(flexible):
        return budgets

    scale = spare / sum(flexible.values())
    return {
        column: (width if column in UNTRIMMABLE else max(floor, int(width * scale)))
        for column, width in budgets.items()
    }
