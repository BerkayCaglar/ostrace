# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the window remembers between sessions, and what it deliberately does not.

Eleven keys across four namespaces. Qt decides where they are kept, per
platform, which is why this is not a decision ``paths`` owns: no file of ours is
being placed. ``gui.app`` sets the organisation and application names, which is
what stops Qt filing them under a vendor called "Unknown".

**Nothing that changes what the window shows on the way up.** Not the open
capture and not the applied filter: a viewer that reopened yesterday's file
would be guessing, and a filter that survived a restart is one the user has to
remember they set -- which is the "where did my logs go" failure with a longer
fuse.

The recent and saved filters *are* remembered, and that is the same rule rather
than an exception to it. A filter that is merely **offered** changes nothing
about what the window shows until somebody picks it.

**So are the marks, per capture**, and that is the same rule again read
carefully. A restored mark hides nothing and moves nothing; it puts back an
annotation about a file the user has just chosen to open, which is the one
moment they are certainly thinking about that file. The rule being kept is
"do not decide what the reader is looking at", not "forget everything".

Everything read back is treated as untrusted. It was written by some version of
this program, possibly not this one, and a settings store is also a file a
person can edit. So a value of the wrong type is absent, a list of column
widths that no longer matches the columns is absent, and one unreadable recent
filter costs that entry rather than the other nine. What this module will not do
is decide what a *usable* window is: a geometry can be perfectly well-formed and
still put the window on a monitor that is no longer attached, and only the window
can see the screens.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QByteArray, QSettings

from ostrace.gui.columns import COLUMNS
from ostrace.gui.filters import RECENT_KEPT, Filter, SavedFilter
from ostrace.gui.finding import Find

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

__all__ = ["MARKED_CAPTURES", "Layout", "WindowSettings"]

_THEME = "window/theme"
_GEOMETRY = "window/geometry"
_STATE = "window/state"
_SPLIT = "window/split"
_DETAIL = "window/detail"
_COLUMNS = "table/columns"
_SHOWN = "table/shown"
_JUMP = "table/jump"
_RECENT = "filters/recent"
_SAVED = "filters/saved"
_MARKS = "marks/captures"

#: How many captures keep their marks. One entry per capture ever opened would
#: grow without bound, and most captures are read once and never again.
#:
#: A cap rather than dropping entries whose file has gone: a capture on an
#: external disk or a network share is missing while the disk is unplugged and
#: is not gone, and a viewer that answered a temporarily absent path by
#: discarding the notes made about it would be destroying work on the strength
#: of a guess. Twenty is the recent-filter argument scaled to a thing kept for
#: longer: enough to cover a session's worth of captures several times over.
MARKED_CAPTURES = 20


def _capture_key(capture: Path) -> str:
    """How a capture is named in the store, so that two names cannot disagree.

    ``resolve`` rather than ``str``: the same file reached by its bare name from
    the directory holding it and by its full path from anywhere else is one
    capture with one set of notes, and a viewer that filed them separately would
    appear to lose them depending on how the file was opened. It also settles
    the separator, which differs by platform in the *stored* string.

    Spelled without an example on purpose. `test_paths.py` refuses a Windows
    path literal anywhere under the package, prose included, and that bluntness
    is the point -- a guard that learned an exception for comments is one the
    next literal hides behind.

    Non-existent paths resolve without complaint, which matters because this is
    also asked about a capture that has since been deleted -- the answer wanted
    there is "no marks", not an exception on the way to the window opening.
    """
    return str(Path(capture).resolve())


@dataclass(frozen=True, slots=True)
class Layout:
    """Where a session left the window.

    Every piece is optional because every piece can be missing on the first
    run, damaged, or written by a version that spelled it differently -- and
    because they are restored independently: a window whose split is
    unreadable still opens at the size the user left it.

    ``jump`` and ``detail_visible`` carry their defaults rather than ``None``:
    both have an answer that is right when nothing was stored, and pushing that
    decision to the caller would put it in two places.
    """

    geometry: QByteArray | None = None
    state: QByteArray | None = None
    split: QByteArray | None = None
    columns: list[int] | None = None
    #: Which columns are shown, by `Column` value. ``None`` for "all of them",
    #: which is both the first-run answer and what an unreadable entry falls
    #: back to: a window that opened with a column missing because a settings
    #: line was damaged would look like a rendering fault rather than like
    #: stale settings.
    shown_columns: list[int] | None = None
    #: The kind the chevrons step through. A way of reading rather than a
    #: property of a capture, so it belongs with the geometry and not with the
    #: filter, which is deliberately not remembered.
    jump: Find = Find.ERROR
    detail_visible: bool = True


@dataclass(slots=True)
class WindowSettings:
    """The stored layout, encoded and decoded.

    Wraps ``QSettings`` rather than subclassing it: what is worth testing is
    the decoding, and a plain object can be handed a store built anywhere.
    """

    store: QSettings = field(default_factory=QSettings)

    # -- the theme -------------------------------------------------------

    @property
    def theme(self) -> str | None:
        """The scheme the user chose, or ``None`` for "follow the system"."""
        stored = self.store.value(_THEME)
        return stored if isinstance(stored, str) else None

    @theme.setter
    def theme(self, value: str) -> None:
        self.store.setValue(_THEME, value)

    # -- the layout ------------------------------------------------------

    def read_layout(self) -> Layout:
        """Everything the last session left, minus anything unreadable."""
        return Layout(
            geometry=self._bytes(_GEOMETRY),
            state=self._bytes(_STATE),
            split=self._bytes(_SPLIT),
            columns=self._columns(),
            shown_columns=self._shown_columns(),
            jump=self._jump(),
            detail_visible=self.store.value(_DETAIL, defaultValue=True, type=bool) is not False,
        )

    def write_layout(self, layout: Layout) -> None:
        """Keep it for next time.

        Takes the whole thing rather than a value at a time so that a caller
        cannot save half a layout, and so the keys stay in one place.
        """
        self.store.setValue(_GEOMETRY, layout.geometry)
        self.store.setValue(_STATE, layout.state)
        self.store.setValue(_SPLIT, layout.split)
        self.store.setValue(_COLUMNS, layout.columns)
        self.store.setValue(_SHOWN, layout.shown_columns)
        self.store.setValue(_JUMP, layout.jump.value)
        self.store.setValue(_DETAIL, layout.detail_visible)

    def _bytes(self, key: str) -> QByteArray | None:
        stored = self.store.value(key)
        return stored if isinstance(stored, QByteArray) else None

    def _columns(self) -> list[int] | None:
        """Widths, only if there are still that many columns to apply them to.

        A capture opened by a version with a different set of columns would
        otherwise get widths applied to the wrong ones, which looks like a
        rendering fault rather than like stale settings.
        """
        stored = self.store.value(_COLUMNS)
        if not isinstance(stored, list) or len(stored) != len(COLUMNS):
            return None
        try:
            return [int(width) for width in stored]
        except (TypeError, ValueError):
            return None

    def _shown_columns(self) -> list[int] | None:
        """Which columns to show, or ``None`` for all of them.

        Every rejection ends at "all of them" rather than at a subset, and the
        rejections are strict on purpose: an unknown column value, or a list
        that would hide *every* column, gives back a table with nothing in it
        and no way to see that anything is wrong. Showing a column that was
        meant to be hidden costs a glance; hiding one that was meant to be
        shown is a value somebody concludes the device never emitted.
        """
        stored = self.store.value(_SHOWN)
        if not isinstance(stored, list):
            return None
        try:
            shown = [int(value) for value in stored]
        except (TypeError, ValueError):
            return None
        if not shown or any(value not in range(len(COLUMNS)) for value in shown):
            return None
        return shown

    def _jump(self) -> Find:
        try:
            return Find(self.store.value(_JUMP))
        except ValueError:
            # Absent, or written by a version that offered a kind this one does
            # not. The default is the one every reader wants first.
            return Find.ERROR

    # -- the recent filters ----------------------------------------------

    def read_recent(self) -> list[Filter]:
        """What the last session offered, minus anything unreadable.

        Entry by entry rather than all or nothing: one line written by a
        version that spelled a field differently should cost that line, not the
        other nine.
        """
        stored = self.store.value(_RECENT)
        if not isinstance(stored, list):
            return []
        return list(self._readable(stored))[:RECENT_KEPT]

    def write_recent(self, recent: list[Filter]) -> None:
        self.store.setValue(_RECENT, [entry.as_stored() for entry in recent])

    @staticmethod
    def _readable(stored: list[object]) -> Iterator[Filter]:
        for line in stored:
            if not isinstance(line, str):
                continue
            entry = Filter.from_stored(line)
            if entry is not None:
                yield entry

    # -- the saved filters -----------------------------------------------

    def read_saved(self) -> list[SavedFilter]:
        """The named ones, in the order they were saved.

        Unbounded where the recent list is capped at ten, and that is the
        difference between the two: the cap exists because the recent list is
        written *for* you and would otherwise grow without your asking. A named
        one is something you did on purpose, and a viewer that silently dropped
        the oldest would be discarding work.
        """
        stored = self.store.value(_SAVED)
        if not isinstance(stored, list):
            return []
        return list(self._named(stored))

    def write_saved(self, saved: list[SavedFilter]) -> None:
        self.store.setValue(_SAVED, [entry.as_stored() for entry in saved])

    @staticmethod
    def _named(stored: list[object]) -> Iterator[SavedFilter]:
        for line in stored:
            if not isinstance(line, str):
                continue
            entry = SavedFilter.from_stored(line)
            if entry is not None:
                yield entry

    # -- the marks -------------------------------------------------------

    def read_marks(self, capture: Path) -> list[tuple[datetime, str]]:
        """What was marked in this capture last time, as moments and names.

        Keyed by the capture's path, and stored as one list of entries rather
        than one settings key per capture: ``/`` is the group separator in
        ``QSettings``, so a path used as a key would be filed as a tree of
        directories with a leaf at the end of it, on every platform and
        differently on each.

        Unreadable entries cost themselves and nothing else, and an unreadable
        *moment* costs one mark rather than the capture's whole set -- the same
        rule the recent filters follow, for the same reason.
        """
        key = _capture_key(capture)
        for entry in self._mark_entries():
            if entry.get("capture") != key:
                continue
            stored = entry.get("marks")
            return list(self._moments(stored)) if isinstance(stored, list) else []
        return []

    def write_marks(self, capture: Path, marks: Sequence[tuple[datetime, str]]) -> None:
        """Keep this capture's marks, newest capture first.

        Moved to the front rather than left in place, so the cap drops the
        capture nobody has opened in longest rather than the one that happened
        to be stored first. A capture with no marks left is removed rather than
        stored empty: an entry saying nothing still occupies one of the twenty.
        """
        key = _capture_key(capture)
        kept = [entry for entry in self._mark_entries() if entry.get("capture") != key]
        if marks:
            kept.insert(
                0,
                {
                    "capture": key,
                    "marks": [{"at": moment.isoformat(), "name": name} for moment, name in marks],
                },
            )
        self.store.setValue(_MARKS, [json.dumps(entry) for entry in kept[:MARKED_CAPTURES]])

    def _mark_entries(self) -> list[dict[str, object]]:
        """Every stored capture's marks, minus anything that will not decode."""
        stored = self.store.value(_MARKS)
        if not isinstance(stored, list):
            return []
        entries: list[dict[str, object]] = []
        for line in stored:
            if not isinstance(line, str):
                continue
            try:
                decoded = json.loads(line)
            except ValueError:
                continue
            if isinstance(decoded, dict) and isinstance(decoded.get("capture"), str):
                entries.append(decoded)
        return entries

    @staticmethod
    def _moments(stored: list[object]) -> Iterator[tuple[datetime, str]]:
        for item in stored:
            if not isinstance(item, dict):
                continue
            try:
                moment = datetime.fromisoformat(str(item["at"]))
            except (KeyError, TypeError, ValueError):
                continue
            # A naive moment is refused rather than assumed to be local. That is
            # the project's timestamp rule, and it applies to a value read back
            # off disk exactly as it applies to one read off a device.
            if moment.tzinfo is None:
                continue
            yield moment, str(item.get("name", ""))
