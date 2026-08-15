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

__all__ = [
    "RECENT_KEPT",
    "Filter",
    "Highlight",
    "SavedFilter",
    "forget",
    "merge_spans",
    "remember",
    "save",
]

#: How many filters back the recent list goes. Ten is about a session's worth
#: of narrowing and short enough to read without scrolling a menu, which is the
#: whole reason for offering the last ones rather than all of them.
RECENT_KEPT = 10

#: What forces a value to be quoted in the text form. Whitespace separates one
#: term from the next, and the quote and the backslash are the escape mechanism
#: itself, so a value carrying any of the three cannot be written bare.
_MUST_QUOTE = re.compile(r'[\s"\\]')


def _quote(value: str) -> str:
    """One term's value: bare where it can be, quoted where it must be."""
    if not _MUST_QUOTE.search(value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _compile(text: str, *, regex: bool) -> re.Pattern[str] | None:
    """One term's pattern, or ``None`` when there is no term.

    Shared by the two verbs because they compile the same way and must fail the
    same way: a literal is `re.escape`d so that one `finditer` serves both
    kinds, and a half-written pattern raises here rather than becoming a term
    that quietly matches nothing.
    """
    if not text:
        return None
    try:
        return re.compile(text if regex else re.escape(text), re.I)
    except re.error as exc:
        msg = f"invalid regular expression: {exc}"
        raise ValueError(msg) from exc


def _spans(pattern: re.Pattern[str] | None, text: str) -> list[tuple[int, int]]:
    """Where a pattern sits in ``text``, for whoever is drawing it.

    Zero-width matches are dropped. A pattern like ``a*`` matches the empty
    string between every pair of characters, and a highlight of nothing at every
    position is a row painted solid.
    """
    if pattern is None:
        return []
    return [match.span() for match in pattern.finditer(text) if match.end() > match.start()]


def merge_spans(
    left: Sequence[tuple[int, int]], right: Sequence[tuple[int, int]]
) -> Sequence[tuple[int, int]]:
    """Two sets of ranges as one, overlaps folded together, in order.

    The two verbs are drawn in one wash, and a wash is translucent: painting the
    same pixels twice makes them darker than the colour that was held to a
    contrast floor. Searching for ``err`` while highlighting ``error`` overlaps
    on every hit, which is not a corner case -- it is what somebody narrowing
    and then looking within the narrowing actually types.

    Two arguments rather than one already-joined sequence, so that the ordinary
    case can be handed back untouched. This runs per visible message cell per
    repaint and only one of the two fields is usually filled in; building a
    joined list and sorting it there would be two allocations and a sort to
    arrive at the list that came in. Both sides are already ordered and
    non-overlapping within themselves, `finditer` being what produced them.
    """
    if not left:
        return right
    if not right:
        return left
    merged: list[tuple[int, int]] = []
    for start, end in sorted([*left, *right]):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


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

    #: Turn the process and subsystem terms into exclusions. Only those two:
    #: shutting up one chatty daemon is the case people have, where "messages
    #: not containing X" is rare and reads better as a narrowing of what to
    #: highlight than as a filter.
    #:
    #: A flag set over an empty field excludes nothing, which is why `is_empty`
    #: asks about the fields and not about these.
    process_exclude: bool = False
    subsystem_exclude: bool = False

    #: Compiled once at construction. Rebuilding it per record would put a regex
    #: compile in the innermost loop of the whole program.
    _pattern: re.Pattern[str] | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_pattern", _compile(self.search, regex=self.regex))

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
            # The same glyph the toggle in the bar carries, so a menu entry and
            # the control that produced it read as the same thing.
            parts.append(f"process {'≠ ' if self.process_exclude else ''}{self.process}")
        if self.subsystem:
            parts.append(f"subsystem {'≠ ' if self.subsystem_exclude else ''}{self.subsystem}")
        if self.search:
            parts.append(f"{'regex' if self.regex else 'text'} {self.search!r}")
        return " · ".join(parts) if parts else "everything"

    def as_text(self) -> str:
        """This filter as one line somebody can paste into an issue.

        `summary` is for a person reading a menu; this is for a person
        reproducing what somebody else was looking at. The spelling is fixed in
        `docs/formats/filter-text-form.md` before anything reads it, on the same
        argument the on-disk contracts are written before they are implemented:
        a format nobody specified is one every reader guesses at differently.

        Two places where the obvious spelling was wrong and the measurement
        settled it. The research proposed marking a pattern by prefixing its
        value with ``~``, which cannot express a literal search for a string
        that *starts* with one -- and `~` is in real device output, twice in
        8,000 committed fixture messages, one of them the banner ``~~~~~ PCS
        Cache ~~~~~`` that somebody would plausibly search for. The marker is a
        key here instead, so no value is ever inspected for a prefix. And the
        level is written by its enum name rather than its title, because
        `Level.USER_ACTION.title` contains a space, which is the one character
        the term separator claims.
        """
        terms: list[str] = []
        if self.minimum_level is not Level.DEBUG:
            terms.append(f"level:{self.minimum_level.name.lower()}")
        if self.process:
            terms.append(f"{'-' if self.process_exclude else ''}process:{_quote(self.process)}")
        if self.subsystem:
            terms.append(
                f"{'-' if self.subsystem_exclude else ''}subsystem:{_quote(self.subsystem)}"
            )
        if self.search:
            terms.append(f"{'regex' if self.regex else 'search'}:{_quote(self.search)}")
        return " ".join(terms)

    def as_stored(self) -> str:
        """This filter as one line of text, for `QSettings`.

        JSON rather than a field order, because the recent list outlives the
        version that wrote it: a stored entry from an older release has to be
        readable by a newer one, and an entry a newer one cannot read has to be
        droppable rather than fatal. `_pattern` is derived and is not stored.

        Not `as_text`, which is the other direction of the same argument. That
        form exists to be read by a person and is lossy about exactly the thing
        settings must not be lossy about -- it omits every term that does not
        narrow -- and a round trip through it would need the reader this
        release deliberately does not ship.
        """
        return json.dumps(self.as_fields())

    def as_fields(self) -> dict[str, object]:
        """Every term as plain data, for whoever does the encoding.

        Separate from `as_stored` because a *named* filter stores this nested
        under its name, and getting there by decoding the string `as_stored`
        would have produced is a round trip through JSON to arrive back at what
        was already in hand.
        """
        return {
            "minimum_level": int(self.minimum_level),
            "process": self.process,
            "subsystem": self.subsystem,
            "search": self.search,
            "regex": self.regex,
            "process_exclude": self.process_exclude,
            "subsystem_exclude": self.subsystem_exclude,
        }

    @classmethod
    def from_fields(cls, stored: object) -> Filter | None:
        """Plain data back to a filter, or ``None`` if it cannot be read.

        The `dict` check is what lets everything below be read without a cast:
        this is decoded JSON, so it is as likely to be a list or a bare string
        as a mapping.

        The exclusion flags are read with a default rather than required. Every
        line written before they existed is missing both, and requiring them
        would silently empty the recent list of anyone upgrading -- a loss they
        would read as the feature having broken, on the release that improved
        it.
        """
        if not isinstance(stored, dict):
            return None
        try:
            return cls(
                minimum_level=Level(int(stored["minimum_level"])),
                process=str(stored["process"]),
                subsystem=str(stored["subsystem"]),
                search=str(stored["search"]),
                regex=bool(stored["regex"]),
                process_exclude=bool(stored.get("process_exclude", False)),
                subsystem_exclude=bool(stored.get("subsystem_exclude", False)),
            )
        except (TypeError, ValueError, KeyError):
            return None

    @classmethod
    def from_stored(cls, text: str) -> Filter | None:
        """One stored line back, or ``None`` if it cannot be read.

        Never raises. This is settings written by a previous version of the
        program, possibly a future one, possibly edited by hand -- and a window
        that refuses to open because a remembered filter is malformed has
        turned a convenience into a way of losing the application.
        """
        try:
            decoded = json.loads(text)
        except ValueError:
            return None
        return cls.from_fields(decoded)

    def matches(self, record: Record) -> bool:
        """Whether ``record`` should be shown.

        Ordered cheapest first: an integer comparison rejects most records
        under a raised level threshold before any string work happens.

        A term rejects when its hit and its exclusion flag agree: a match under
        `≠` is the record being excluded, and a miss under an ordinary term is
        the record failing to be included. One comparison covers both, and it
        costs an excluding term nothing over an including one.
        """
        if record.level < self.minimum_level:
            return False
        if self.process and self._matches_process(record) == self.process_exclude:
            return False
        if self.subsystem and self._matches_subsystem(record) == self.subsystem_exclude:
            return False
        return not (self._pattern is not None and not self._pattern.search(record.message))

    def spans(self, text: str) -> list[tuple[int, int]]:
        """Where the search term sits in ``text``, for whoever is drawing it.

        Here rather than in the delegate because the pattern is here: a literal
        search is `re.escape`d at construction, so one `finditer` covers both
        kinds and the drawing side never has to know which it has.
        """
        return _spans(self._pattern, text)

    def _matches_subsystem(self, record: Record) -> bool:
        """Match a subsystem by substring, on a record that may not have one.

        A record with no subsystem is a miss rather than an error -- and under
        `≠` that makes it a *hit*, which is the answer somebody excluding a
        noisy subsystem wants: they asked to see everything else, and a record
        with no subsystem at all is everything else.
        """
        return self.subsystem.casefold() in (record.subsystem or "").casefold()

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


@dataclass(frozen=True, slots=True)
class Highlight:
    """A term marked where it stands, rather than one that removes rows.

    The second of the two verbs `docs/design/gui.md` §5 has asked for since
    before phase 4, and the reason they are two rather than one: they *compose*.
    Narrow to Error, then find ``404`` within what is left. A single field can
    only do one of those at a time, which is why 0.2.0's wash over the *filter's*
    search term was described as the cheap eighty per cent rather than as the
    feature.

    Its own value rather than two more fields on `Filter`, because `Filter`
    equality is what decides whether the model rescans the whole capture.
    Changing what is highlighted must not do that: nothing about which rows
    survive has changed, and a rescan at 200,000 rows to repaint forty is the
    cost this separation exists to refuse.
    """

    text: str = ""
    regex: bool = False

    #: Compiled once, for the same reason `Filter` compiles once: this is asked
    #: about every visible row on every repaint.
    _pattern: re.Pattern[str] | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_pattern", _compile(self.text, regex=self.regex))

    @property
    def is_empty(self) -> bool:
        return not self.text

    def hits(self, text: str) -> bool:
        """Whether ``text`` carries the term at all.

        Separate from `spans` and not written in terms of it: the counter and
        the jump target ask only whether there is a hit, and `search` stops at
        the first one where `finditer` builds a list of all of them. On a
        message that mentions a term twenty times that is nineteen match objects
        nobody reads.
        """
        return self._pattern is not None and self._pattern.search(text) is not None

    def spans(self, text: str) -> list[tuple[int, int]]:
        """Where the term sits in ``text``, for whoever is drawing it."""
        return _spans(self._pattern, text)


@dataclass(frozen=True, slots=True)
class SavedFilter:
    """A filter somebody gave a name to.

    The expensive half of remembering a filter, and the one worth having only
    for the handful somebody comes back to for weeks -- `remember` covers the
    rest, unnamed and automatic. Kept apart from `Filter` because a name is not
    a term: two saved filters with the same terms and different names are two
    entries, and `Filter` equality is what decides whether the model rescans.
    """

    name: str
    terms: Filter

    def as_stored(self) -> str:
        """One line for `QSettings`, with the terms nested under the name.

        Nested rather than beside them, so that a term called ``name`` some
        release from now cannot collide with this one.
        """
        return json.dumps({"name": self.name, "filter": self.terms.as_fields()})

    @classmethod
    def from_stored(cls, text: str) -> SavedFilter | None:
        """One stored line back, or ``None``. Never raises, as `Filter` does not."""
        try:
            decoded = json.loads(text)
        except ValueError:
            return None
        if not isinstance(decoded, dict):
            return None
        name = decoded.get("name")
        terms = Filter.from_fields(decoded.get("filter"))
        # An unnamed saved filter is unreachable: the menu offers it by name,
        # so a blank one is a row nobody can tell from the row above it.
        if not isinstance(name, str) or not name.strip() or terms is None:
            return None
        return cls(name=name, terms=terms)


def save(saved: Sequence[SavedFilter], entry: SavedFilter) -> list[SavedFilter]:
    """``saved`` with ``entry`` in it, replacing any entry of the same name.

    Replacing rather than appending, and *in place* rather than at the front:
    saving over a name is how somebody corrects one, and a list that reordered
    itself under them each time would make the menu a different shape after
    every correction. Names are compared as they read -- case and surrounding
    space folded -- because two entries a menu shows identically are two nobody
    can choose between.

    Pure, so the window can hold the list and this can be tested without one.
    """
    key = _name_key(entry.name)
    if any(_name_key(item.name) == key for item in saved):
        return [entry if _name_key(item.name) == key else item for item in saved]
    return [*saved, entry]


def forget(saved: Sequence[SavedFilter], name: str) -> list[SavedFilter]:
    """``saved`` without the entry of that name."""
    key = _name_key(name)
    return [item for item in saved if _name_key(item.name) != key]


def _name_key(name: str) -> str:
    """A name as the menu shows it, for deciding whether two are the same one."""
    return name.strip().casefold()


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
