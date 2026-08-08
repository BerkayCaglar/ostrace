# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The table model: a plain list, its own filtered index, and a bounded head.

Three decisions here are load-bearing, and each has a measurement or a shipped
bug behind it.

**Filtering is our own index list, not `QSortFilterProxyModel`.** Measured here
on PySide6 6.11.1, 100,000 records, changing the filter to a message substring,
best of three with a view attached:

===================================================  ========
approach                                             time
===================================================  ========
this model                                            0.130 s
`QSortFilterProxyModel`, built-in regex over a role   0.607 s
`QSortFilterProxyModel`, `filterAcceptsRow` in Python  0.642 s
===================================================  ========

About 4.7x, in both proxy styles. ADR 0004 records 66x and calls the proxy
"a frozen window"; that does not reproduce -- every option here is well under
a second. The decision survives on the smaller margin and on control, not on
the original number. Arriving records test only themselves and append, so the
steady state is O(batch); only a filter *change* rescans.

**A marker is never filtered out.** The exemption is a type test at the single
choke point, before any predicate runs -- see `markers.is_marker` and
`docs/design/gui.md` §3.

**The row cap trims in one operation, not per tick.** Retention is a plain list
with a hard cap, trimmed only once it overflows, and never `deque(maxlen=)`,
which evicts silently and desynchronises the view. Whatever it drops is
announced as an `Eviction` row, because a viewer that quietly discards is
indistinguishable from a device that stopped talking.

`multiData()` is deliberately **not** overridden. Qt does query about seven
roles per visible cell and a Python override is called -- but the span has to
be iterated from Python, so seven inbound crossings become one inbound plus
about fourteen outbound. Measured at 400k rows: 0.96-0.99x, marginally slower.
It is the right advice in C++ and the wrong advice here.
"""

from __future__ import annotations

from bisect import bisect_left
from typing import TYPE_CHECKING

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt

from ostrace.gui.columns import COLUMNS, Column
from ostrace.gui.filters import Filter
from ostrace.gui.markers import Eviction, is_record
from ostrace.gui.theme import Scheme, Severity, severity_for
from ostrace.model import Gap, Level, Record

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from PySide6.QtCore import QObject

    from ostrace.gui.markers import Row

__all__ = ["MARKER_LEVEL", "MAX_ROWS", "TRIM_MARGIN", "RecordModel"]

#: Markers borrow a severity so their colour comes from the theme rather than
#: from a literal here. NOTICE is plain body text in both schemes, which is
#: what a marker should be: a statement of fact, not an alarm.
MARKER_LEVEL = Level.NOTICE

#: How many items are retained. Beyond this the oldest are dropped and an
#: `Eviction` row says so. The capture on disk keeps everything regardless.
MAX_ROWS = 200_000

#: Trimming starts only once the cap is exceeded by this fraction, so a stream
#: sitting exactly at the limit does not trigger a removal on every batch.
TRIM_MARGIN = 0.1

#: What an absent optional field reads as -- the exporters' spelling, so a value
#: copied out of the table matches what a bundle would contain.
ABSENT = "-"

_Index = QModelIndex | QPersistentModelIndex


def _field(record: Record, column: Column) -> str:
    """The raw value behind a collapsible column, before any blanking."""
    if column is Column.PROCESS:
        return record.process_label
    if column is Column.SUBSYSTEM:
        return record.subsystem or ABSENT
    return record.category or ABSENT


class RecordModel(QAbstractTableModel):
    """Records and markers, filtered, bounded, and coloured by severity."""

    def __init__(
        self,
        scheme: Scheme = Scheme.LIGHT,
        *,
        row_cap: int = MAX_ROWS,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._rows: list[Row] = []
        #: Indices into ``_rows`` that survive the filter, in order.
        self._visible: list[int] = []
        self._filter = Filter()
        self._row_cap = row_cap
        self._evicted = 0
        self.scheme = scheme

        # Prebuilt once. Measured at 800k calls, `Qt.ItemFlag.A | Qt.ItemFlag.B`
        # costs 0.754 s against 0.051 s for a prebuilt attribute -- the enum
        # __or__ and the attribute chain are the cost, not the flags themselves.
        self._flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        self._severity: dict[Level, Severity] = {}
        self._rebuild_severity()

    def _rebuild_severity(self) -> None:
        """Cache one `Severity` per level.

        ``severity_for`` constructs `QColor` objects, and `data()` runs once
        per cell per role -- so calling it there would allocate a colour for
        every cell of every repaint. Colours are built here and handed out.
        """
        self._severity = {level: severity_for(level, self.scheme) for level in Level}

    # -- Qt interface ----------------------------------------------------

    def rowCount(self, parent: _Index | None = None) -> int:  # noqa: N802
        return 0 if parent is not None and parent.isValid() else len(self._visible)

    def columnCount(self, parent: _Index | None = None) -> int:  # noqa: N802
        return 0 if parent is not None and parent.isValid() else len(COLUMNS)

    def flags(self, index: _Index) -> Qt.ItemFlag:
        del index
        return self._flags

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> str | None:
        if orientation is not Qt.Orientation.Horizontal or role != Qt.ItemDataRole.DisplayRole:
            return None
        return COLUMNS[section].title if 0 <= section < len(COLUMNS) else None

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid():
            return None
        row = self.row_at(index.row())
        column = Column(index.column())

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(row, column, index.row())
        if role == Qt.ItemDataRole.ForegroundRole:
            return self._foreground(row)
        if role == Qt.ItemDataRole.BackgroundRole:
            return self._background(row)
        if role == Qt.ItemDataRole.ToolTipRole and column is Column.MESSAGE:
            # The one column that is routinely elided, so the one that needs a
            # way to read the rest without opening the detail pane.
            return row.message if isinstance(row, Record) else self._marker_text(row)
        return None

    # -- content ---------------------------------------------------------

    def row_at(self, view_row: int) -> Row:
        """The item behind a view row, filter and all."""
        return self._rows[self._visible[view_row]]

    def source_index(self, view_row: int) -> int:
        """A handle on a row that survives a filter change.

        View rows are renumbered by every rescan; the position in the retained
        list is not, so this is what an anchor holds. See `nearest_view_row`.
        """
        return self._visible[view_row]

    def nearest_view_row(self, source: int) -> int | None:
        """Where a retained item is now, or where it would have been.

        This is the anchoring half of the rule in `docs/design/gui.md` §5: a
        filter change re-attaches selection and viewport to a *record*, not to
        a row number. If the anchored record did not survive the new filter,
        the nearest survivor after it is the answer -- the user was reading at
        that point in the log, and that point still exists even when the record
        they clicked does not.

        Nobody surveyed does this: Wireshark has had it open since 3.0.7, lnav
        clamps row ordinals and teleports, and Logcat re-appends its whole
        document so every keystroke in the filter field jumps to the bottom.

        ``_visible`` is ascending by construction, so this is a binary search
        rather than the scan the rescan just did.
        """
        if not self._visible:
            return None
        position = bisect_left(self._visible, source)
        return min(position, len(self._visible) - 1)

    def _display(self, row: Row, column: Column, view_row: int) -> str:
        if not isinstance(row, Record):
            return self._marker_cell(row, column)

        if column is Column.TIME:
            return f"{row.timestamp:%H:%M:%S.%f}"[:-3]
        if column is Column.LEVEL:
            glyph = self._severity[row.level].glyph
            return f"{glyph} {row.level.title}" if glyph else row.level.title
        if column is Column.MESSAGE:
            return row.message

        value = _field(row, column)
        return "" if self._repeats_previous(view_row, column, value) else value

    def _repeats_previous(self, view_row: int, column: Column, value: str) -> bool:
        """Whether the row above holds the same thing in this column.

        Blanking a repeat is what makes a log where one process emits hundreds
        of consecutive records scannable at all. Compared against the previous
        *visible* row rather than the previous item, because with a filter
        applied those are different rows and the user only ever sees one of
        them.

        Against the row's **field**, never against what that row *displays*.
        Asking what the row above displays means asking whether *it* was a
        repeat, which asks the row above that, all the way to the top of the
        run -- unbounded recursion whose depth is the length of the run. A real
        capture with 100,000 consecutive records from one process exhausted the
        stack; the tests had runs of three and saw nothing.
        """
        if view_row == 0 or not COLUMNS[column].collapse_repeats:
            return False
        above = self.row_at(view_row - 1)
        if not isinstance(above, Record):
            # A marker breaks the run: what follows it is a fresh start, and
            # blanking across one would imply a continuity that is exactly what
            # the marker denies.
            return False
        return _field(above, column) == value

    def _marker_cell(self, row: Gap | Eviction, column: Column) -> str:
        if column is Column.TIME:
            moment = row.start if isinstance(row, Gap) else row.through
            return f"{moment:%H:%M:%S.%f}"[:-3]
        if column is Column.LEVEL:
            return "GAP" if isinstance(row, Gap) else "TRIMMED"
        if column is Column.MESSAGE:
            return self._marker_text(row)
        return ""

    def _marker_text(self, row: Gap | Eviction) -> str:
        if isinstance(row, Gap):
            # The plaintext exporter's wording, because docs/formats/ wins and
            # the same event should read the same in both places.
            return f"---- gap {row.start} to {row.end} ({row.reason}) ----"
        return row.text

    def _foreground(self, row: Row) -> object:
        level = row.level if isinstance(row, Record) else MARKER_LEVEL
        return self._severity[level].foreground

    def _background(self, row: Row) -> object:
        level = row.level if isinstance(row, Record) else MARKER_LEVEL
        return self._severity[level].tint

    # -- ingestion -------------------------------------------------------

    def append(self, batch: Sequence[Row]) -> None:
        """Add a batch, testing only the new items.

        One `beginInsertRows` for the batch, never one per record: at 1,600
        records a second the per-record version is 1,600 model resets a second
        and a view that cannot keep up with a device that is merely idling.
        """
        if not batch:
            return

        first = len(self._rows)
        newly_visible = [first + offset for offset, row in enumerate(batch) if self._passes(row)]

        if newly_visible:
            start = len(self._visible)
            self.beginInsertRows(QModelIndex(), start, start + len(newly_visible) - 1)
            self._rows.extend(batch)
            self._visible.extend(newly_visible)
            self.endInsertRows()
        else:
            # Nothing to show, but the items are still retained: a filter hides
            # rows, it does not discard the capture.
            self._rows.extend(batch)

        self._trim()

    def extend_from(self, items: Iterable[Row], *, batch_size: int = 4096) -> None:
        """Load an existing capture, in batches.

        Batched rather than appended one at a time for the same reason the live
        path is, and rather than in one go because a single insert of a million
        rows holds the GUI thread for the whole read.
        """
        batch: list[Row] = []
        for item in items:
            batch.append(item)
            if len(batch) >= batch_size:
                self.append(batch)
                batch = []
        self.append(batch)

    def _passes(self, row: Row) -> bool:
        """The one choke point, and the only place a filter is consulted.

        The type test comes first and returns before any predicate runs, so a
        marker cannot be hidden by a filter term added later somewhere else.
        """
        if is_record(row):
            return self._filter.matches(row)
        return True

    def _trim(self) -> None:
        """Drop the oldest rows once the cap is exceeded, in one operation."""
        limit = int(self._row_cap * (1 + TRIM_MARGIN))
        if len(self._rows) <= limit:
            return

        drop = len(self._rows) - self._row_cap
        # Never cut in the middle of anything: whatever is dropped, the row
        # boundary is where it is dropped.
        dropped = self._rows[:drop]
        newest = max(
            (row.timestamp for row in dropped if isinstance(row, Record)),
            default=None,
        )
        self._evicted += sum(1 for row in dropped if isinstance(row, Record))

        self.beginResetModel()
        self._rows = self._rows[drop:]
        if newest is not None:
            self._rows.insert(0, Eviction(count=self._evicted, through=newest))
        self._rescan()
        self.endResetModel()

    # -- filtering -------------------------------------------------------

    @property
    def filter(self) -> Filter:
        return self._filter

    def set_filter(self, new: Filter) -> None:
        """Apply a filter, rescanning everything retained.

        The only O(n) operation in the model, and it runs on a human action
        rather than on arriving data. An identical filter is not a change --
        typing and deleting one character must not cost a full rescan.
        """
        if new == self._filter:
            return
        self._filter = new
        self.beginResetModel()
        self._rescan()
        self.endResetModel()

    def _rescan(self) -> None:
        self._visible = [index for index, row in enumerate(self._rows) if self._passes(row)]

    def set_scheme(self, scheme: Scheme) -> None:
        """Recolour in place after a theme switch. No row changes."""
        if scheme == self.scheme:
            return
        self.scheme = scheme
        self._rebuild_severity()
        if self._visible:
            top = self.index(0, 0)
            bottom = self.index(len(self._visible) - 1, len(COLUMNS) - 1)
            self.dataChanged.emit(top, bottom)

    # -- what the window needs to say ------------------------------------

    @property
    def retained(self) -> int:
        """Items held, filtered or not."""
        return len(self._rows)

    @property
    def evicted(self) -> int:
        """Records dropped from the view. They remain in the capture."""
        return self._evicted

    @property
    def gaps(self) -> int:
        return sum(1 for row in self._rows if isinstance(row, Gap))

    @property
    def hidden_by_filter(self) -> int:
        return len(self._rows) - len(self._visible)
