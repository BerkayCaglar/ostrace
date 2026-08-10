# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the user is asking to see.

A `Filter` is a value: immutable, comparable, and cheap to build. That matters
because the model rescans only when the filter *changes*, and "changed" has to
mean something exact -- typing and deleting a character must leave the model
alone rather than throwing away a scan of the whole capture.

An invalid regular expression is a `ValueError` at construction, never a filter
that quietly matches nothing. A user halfway through typing ``[com`` has an
incomplete pattern, not an empty log, and a view that empties itself while they
type is indistinguishable from a device that stopped talking.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ostrace.model import Level

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ostrace.model import Record

__all__ = ["RECENT_KEPT", "Filter", "remember"]

#: How many filters back the recent list goes. Ten is about a session's worth
#: of narrowing and short enough to read without scrolling a menu, which is the
#: whole reason for offering the last ones rather than all of them.
RECENT_KEPT = 10


@dataclass(frozen=True, slots=True)
class Filter:
    """A conjunction: every non-empty term must match.

    Level is a **threshold** rather than an equality, and it is only expressible
    as one because `Level` is this project's own ordered enum. Apple's values
    are not severity-ordered -- ``NOTICE=0, INFO=1, DEBUG=2, USER_ACTION=3,
    ERROR=16, FAULT=17`` -- so the same idea written against the device's own
    numbers would match nearly everything.
    """

    minimum_level: Level = Level.DEBUG
    process: str = ""
    subsystem: str = ""
    search: str = ""
    regex: bool = False

    #: Compiled once at construction. Rebuilding it per record would put a regex
    #: compile in the innermost loop of the whole program.
    _pattern: re.Pattern[str] | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.search:
            return
        try:
            pattern = re.compile(self.search if self.regex else re.escape(self.search), re.I)
        except re.error as exc:
            msg = f"invalid regular expression: {exc}"
            raise ValueError(msg) from exc
        object.__setattr__(self, "_pattern", pattern)

    @property
    def is_empty(self) -> bool:
        """Whether this filter would exclude anything at all.

        The window needs this to tell "the device is quiet" from "your filter
        hides everything" -- the same picture otherwise, and the second one is
        the reason people file bugs about the first.
        """
        return (
            self.minimum_level is Level.DEBUG
            and not self.process
            and not self.subsystem
            and not self.search
        )

    @property
    def summary(self) -> str:
        """This filter as one line, for a menu of the recent ones.

        Every term that is set and nothing about the ones that are not: a list
        of ten entries each carrying four fields, most of them empty, is a list
        nobody reads. The level is written `Error+` because it is a threshold
        rather than an equality, and that is the single most misread thing
        about this filter.
        """
        parts = []
        if self.minimum_level is not Level.DEBUG:
            parts.append(f"{self.minimum_level.title}+")
        if self.process:
            parts.append(f"process {self.process}")
        if self.subsystem:
            parts.append(f"subsystem {self.subsystem}")
        if self.search:
            parts.append(f"{'regex' if self.regex else 'text'} {self.search!r}")
        return " · ".join(parts) if parts else "everything"

    def as_stored(self) -> str:
        """This filter as one line of text, for `QSettings`.

        JSON rather than a field order, because the recent list outlives the
        version that wrote it: a stored entry from an older release has to be
        readable by a newer one, and an entry a newer one cannot read has to be
        droppable rather than fatal. `_pattern` is derived and is not stored.
        """
        return json.dumps(
            {
                "minimum_level": int(self.minimum_level),
                "process": self.process,
                "subsystem": self.subsystem,
                "search": self.search,
                "regex": self.regex,
            }
        )

    @classmethod
    def from_stored(cls, text: str) -> Filter | None:
        """One stored line back, or ``None`` if it cannot be read.

        Never raises. This is settings written by a previous version of the
        program, possibly a future one, possibly edited by hand -- and a window
        that refuses to open because a remembered filter is malformed has
        turned a convenience into a way of losing the application.
        """
        try:
            stored = json.loads(text)
            return cls(
                minimum_level=Level(int(stored["minimum_level"])),
                process=str(stored["process"]),
                subsystem=str(stored["subsystem"]),
                search=str(stored["search"]),
                regex=bool(stored["regex"]),
            )
        except (TypeError, ValueError, KeyError):
            return None

    def matches(self, record: Record) -> bool:
        """Whether ``record`` should be shown.

        Ordered cheapest first: an integer comparison rejects most records
        under a raised level threshold before any string work happens.
        """
        if record.level < self.minimum_level:
            return False
        if self.process and not self._matches_process(record):
            return False
        if self.subsystem and self.subsystem.casefold() not in (record.subsystem or "").casefold():
            return False
        return not (self._pattern is not None and not self._pattern.search(record.message))

    def _matches_process(self, record: Record) -> bool:
        """Match a process by name or by pid.

        Both, because both are what people have in front of them: a name read
        off the table, or a pid copied out of a crash report. ``97`` matching
        ``dasd[97]`` and not ``launchd[9712]`` is why the pid comparison is
        exact where the name comparison is a substring.
        """
        needle = self.process.casefold()
        if needle.isdigit():
            return record.pid == int(needle)
        return needle in record.process.casefold()


def remember(recent: Sequence[Filter], filter_: Filter) -> list[Filter]:
    """``recent`` with ``filter_`` at the front, newest first.

    Moved rather than added when it is already there: a filter somebody comes
    back to twice is one entry they used twice, and a list that grew a second
    copy would push the other nine out with duplicates of one.

    An empty filter is not remembered. "Show everything" is the state you get
    by clearing the bar, and offering it as something to return to is offering
    a way back to where you already are.

    Pure, so the window can hold the list and this can be tested without one.
    """
    if filter_.is_empty:
        return list(recent)
    return [filter_, *(entry for entry in recent if entry != filter_)][:RECENT_KEPT]
