# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the window remembers between sessions, and what it deliberately does not.

Nine keys across three namespaces. Qt decides where they are kept, per
platform, which is why this is not a decision ``paths`` owns: no file of ours is
being placed. ``gui.app`` sets the organisation and application names, which is
what stops Qt filing them under a vendor called "Unknown".

**Only geometry.** Not the open capture and not the applied filter: a viewer
that reopened yesterday's file would be guessing, and a filter that survived a
restart is one the user has to remember they set -- which is the "where did my
logs go" failure with a longer fuse.

The recent and saved filters *are* remembered, and that is the same rule rather
than an exception to it. A filter that is merely **offered** changes nothing
about what the window shows until somebody picks it.

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

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from PySide6.QtCore import QByteArray, QSettings

from ostrace.gui.columns import COLUMNS
from ostrace.gui.filters import RECENT_KEPT, Filter, SavedFilter
from ostrace.gui.finding import Find

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["Layout", "WindowSettings"]

_THEME = "window/theme"
_GEOMETRY = "window/geometry"
_STATE = "window/state"
_SPLIT = "window/split"
_DETAIL = "window/detail"
_COLUMNS = "table/columns"
_JUMP = "table/jump"
_RECENT = "filters/recent"
_SAVED = "filters/saved"


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
