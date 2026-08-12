# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""What is worth finding in a log, and how the view says where it is.

Two spellings of nearly one list. :class:`Find` is what the chevrons, the key
bindings and the target picker step between; :class:`Band` is what the minimap
paints a stripe for. Both come down to the same short answer -- what went
wrong, where records are missing, and where the reader left a note -- which is
why they live together and not with the model that searches or the widget that
draws.

Apart from ``models.py`` because everything that names these otherwise imports
a five-hundred-line table model to get at an enum: the minimap, the jump
button, the toolbar, the window and the settings store all want the vocabulary
and none of them wants ``RecordModel``.
"""

from __future__ import annotations

from enum import IntFlag, StrEnum
from typing import TYPE_CHECKING

from ostrace.model import Level, Record

if TYPE_CHECKING:
    from collections.abc import Callable

    from ostrace.gui.models import RecordModel

__all__ = ["MATCHERS", "Band", "Find"]


class Band(IntFlag):
    """What one stripe of the minimap has in it.

    A flag set rather than a count: the strip is a few hundred pixels tall, and
    a number it has no room to draw is a number nobody asked for.
    """

    NONE = 0
    ERROR = 1
    MARKER = 2
    MARK = 4


class Find(StrEnum):
    """What `RecordModel.find` looks for.

    What went wrong, where data is missing, and where the reader left a note to
    themselves -- the three things worth jumping between in a log. Named rather
    than passed as a predicate so the key bindings, the menu and the toolbar's
    target picker can all refer to the same thing.

    The severity entries are *thresholds*, not equalities: `Level` is ordered
    on purpose (Apple's own values are not, which is why this project keeps its
    own enum), so `NOTICE` finds everything a reader would call interesting
    without them having to know which of four names the device chose. Jumping
    to a level exactly would be a filter, and there is already a filter.
    """

    ERROR = "error"
    FAULT = "fault"
    NOTICE = "notice"
    MARKER = "marker"
    MARK = "mark"

    @property
    def label(self) -> str:
        """How the target picker names it."""
        return _FIND_LABELS[self]


#: Beside the enum rather than in the window, so that adding a target and
#: naming it are one edit. A member with no label raises here rather than
#: rendering as its own lowercase value in a menu.
_FIND_LABELS: dict[Find, str] = {
    Find.ERROR: "Errors and Faults",
    Find.FAULT: "Faults",
    Find.NOTICE: "Notices and above",
    Find.MARKER: "Gaps",
    Find.MARK: "Marked rows",
}


def _at_least(level: Level) -> Callable[[RecordModel, int], bool]:
    """Match records at or above ``level``. Markers are never records."""

    def matches(model: RecordModel, row: int) -> bool:
        record = model.row_at(row)
        return isinstance(record, Record) and record.level >= level

    return matches


#: The predicate per target. The model is passed in rather than imported, which
#: is what keeps this module free of it at runtime.
MATCHERS: dict[Find, Callable[[RecordModel, int], bool]] = {
    # `Record.is_error` is `level >= ERROR`, so this is the same predicate it
    # always was, spelled once instead of twice.
    Find.ERROR: _at_least(Level.ERROR),
    Find.FAULT: _at_least(Level.FAULT),
    Find.NOTICE: _at_least(Level.NOTICE),
    Find.MARKER: lambda model, row: not isinstance(model.row_at(row), Record),
    Find.MARK: lambda model, row: model.is_marked(row),
}
