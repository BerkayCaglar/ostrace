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
from enum import IntFlag, StrEnum
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    Signal,
)

from ostrace.exporters.plaintext import gap_line
from ostrace.gui.columns import COLUMNS, Column
from ostrace.gui.filters import Filter
from ostrace.gui.markers import Eviction, is_record
from ostrace.gui.theme import Scheme, Severity, mark_tint, severity_for
from ostrace.model import Gap, Level, Record

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence
    from datetime import datetime

    from PySide6.QtCore import QObject

    from ostrace.gui.markers import Row

__all__ = ["BUCKET_ROWS", "MARKER_LEVEL", "MAX_ROWS", "TRIM_MARGIN", "Band", "Find", "RecordModel"]

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

#: Rows per minimap bucket. Anchored to row numbers rather than to pixels so
#: that an append touches only the last bucket; see `_rebuild_buckets`.
BUCKET_ROWS = 256

#: What an absent optional field reads as -- the exporters' spelling, so a value
#: copied out of the table matches what a bundle would contain.
ABSENT = "-"

_Index = QModelIndex | QPersistentModelIndex

#: The roles `data()` has an answer for. Everything else returns before it does
#: any work -- see the note there.
_ANSWERED_ROLES = frozenset(
    {
        Qt.ItemDataRole.DisplayRole.value,
        Qt.ItemDataRole.ForegroundRole.value,
        Qt.ItemDataRole.BackgroundRole.value,
        Qt.ItemDataRole.ToolTipRole.value,
    }
)


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

    The three things worth jumping between in a log: what went wrong, where
    data is missing, and where the reader left a note to themselves. Named
    rather than passed as a predicate so the key bindings and the menu can
    refer to them.
    """

    ERROR = "error"
    MARKER = "marker"
    MARK = "mark"


_MATCHERS: dict[Find, Callable[[RecordModel, int], bool]] = {
    Find.ERROR: lambda model, row: (
        isinstance(record := model.row_at(row), Record) and record.is_error
    ),
    Find.MARKER: lambda model, row: not isinstance(model.row_at(row), Record),
    Find.MARK: lambda model, row: model.is_marked(row),
}


def _field(record: Record, column: Column) -> str:
    """The raw value behind a collapsible column, before any blanking."""
    if column is Column.PROCESS:
        return record.process_label
    if column is Column.SUBSYSTEM:
        return record.subsystem or ABSENT
    return record.category or ABSENT


class RecordModel(QAbstractTableModel):
    """Records and markers, filtered, bounded, and coloured by severity."""

    #: How many view rows just left the top, so that a view can keep the same
    #: records under the reader. Qt does not do this: a scroll position is a
    #: pixel offset from the top of the content, and dropping twenty thousand
    #: rows above the viewport moves everything under it while the offset stays
    #: where it was. Measured before this existed: a reader sitting on record
    #: 989 was looking at record 1,588 afterwards, having pressed nothing.
    #:
    #: Emitted as a *net* row delta rather than as the removal and the eviction
    #: notice separately, because it is measured as one -- the difference in
    #: `rowCount` across the whole operation, which cannot disagree with what
    #: the view was told however the branches inside `_trim` fall.
    top_shifted = Signal(int)

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
        #: Retained gaps. Maintained on ingestion and on trim rather than
        #: counted on demand: the status bar asks once per pump tick.
        self._gaps = 0
        #: Source indices the user has marked. Held by source index for the
        #: same reason selection anchors on one: a filter change must move a
        #: mark with its record, not leave it on a row number.
        self._marks: set[int] = set()
        #: Minimap summary of the *dense* kind, one entry per `BUCKET_ROWS`
        #: visible rows. Gaps and evictions are rare and are kept exactly
        #: instead -- see `overview`.
        self._buckets: list[Band] = []
        self._marker_sources: list[int] = []
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
        self._mark_tint = mark_tint(self.scheme)

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
        # The role test comes before any work. Qt queries about seven roles per
        # visible cell and this answers four of them, so three in seven of
        # 1,386 calls per repaint were resolving a row and constructing a
        # `Column` in order to return `None`.
        if role not in _ANSWERED_ROLES or not index.isValid():
            return None
        row = self.row_at(index.row())
        column = Column(index.column())

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(row, column, index.row())
        if role == Qt.ItemDataRole.ForegroundRole:
            return self._foreground(row)
        if role == Qt.ItemDataRole.BackgroundRole:
            return self._background(index.row(), row)
        if role == Qt.ItemDataRole.ToolTipRole and column is Column.MESSAGE:
            # The one column that is routinely elided, so the one that needs a
            # way to read the rest without opening the detail pane.
            return row.message if isinstance(row, Record) else self._marker_text(row)
        return None

    # -- content ---------------------------------------------------------

    def row_at(self, view_row: int) -> Row:
        """The item behind a view row, filter and all."""
        return self._rows[self._visible[view_row]]

    # -- marks -----------------------------------------------------------

    def toggle_mark(self, view_row: int) -> bool:
        """Mark or unmark a row. Returns whether it is now marked.

        Marks are held as *source* indices, the same handle selection anchors
        on, so a filter change moves them with the records rather than leaving
        them pointing at whatever now occupies that row number.
        """
        source = self._visible[view_row]
        if source in self._marks:
            self._marks.discard(source)
            marked = False
        else:
            self._marks.add(source)
            marked = True
        cell = self.index(view_row, 0)
        self.dataChanged.emit(cell, self.index(view_row, len(COLUMNS) - 1))
        return marked

    def is_marked(self, view_row: int) -> bool:
        return self._visible[view_row] in self._marks

    @property
    def marks(self) -> int:
        return len(self._marks)

    def clear_marks(self) -> None:
        if not self._marks:
            return
        self._marks.clear()
        if self._visible:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self._visible) - 1, len(COLUMNS) - 1)
            )

    # -- navigation ------------------------------------------------------

    def find(self, kind: Find, start: int, *, backwards: bool = False) -> int | None:
        """The next row of ``kind`` after ``start``, wrapping around.

        Wrapping rather than stopping: a log is read in a loop, and a "next
        error" that goes quiet at the end of the buffer looks broken rather
        than finished. The caller can tell it wrapped because the answer is
        behind where it started.
        """
        total = len(self._visible)
        if total == 0:
            return None
        step = -1 if backwards else 1
        matches = _MATCHERS[kind]
        for offset in range(1, total + 1):
            row = (start + step * offset) % total
            if matches(self, row):
                return row
        return None

    def cell_text(self, view_row: int, column: int) -> str:
        """What a cell holds, with a blanked repeat filled back in.

        The table blanks a cell that repeats the row above to make a long run
        scannable. That is a reading aid, and carrying it into the clipboard
        would paste a record with holes where the most identifying fields
        should be.
        """
        row = self.row_at(view_row)
        which = Column(column)
        if isinstance(row, Record) and COLUMNS[which].collapse_repeats:
            return _field(row, which)
        return self._display(row, which, view_row)

    def overview(self, bands: int) -> list[Band]:
        """What is worth knowing about, summarised into ``bands`` stripes.

        The input to the scrollbar minimap, and the only mechanism in the
        program that reveals a gap outside the viewport. Without one, a
        discontinuity forty thousand rows above where the user is reading is
        something they simply never learn about.

        A band says *whether* it holds an error, a marker or a mark, not how
        many: the strip is a few hundred pixels tall and a count it cannot draw
        is a count nobody asked for. One pass over the visible rows, which is
        why it is throttled by its caller rather than run per repaint.
        """
        total = len(self._visible)
        if bands <= 0 or total == 0:
            return []

        summary = [Band.NONE] * bands

        # Errors are dense -- three quarters of the error-heavy capture -- so a
        # bucket's worth of smear costs nothing and saves the O(n) walk. Every
        # band the bucket spans is lit, because either may be the coarser of
        # the two: lighting only the band a bucket starts in collapsed a short
        # capture to five lit bands out of a hundred and eighty.
        for index, flags in enumerate(self._buckets):
            if not flags & Band.ERROR:
                continue
            first = index * BUCKET_ROWS * bands // total
            last = min(bands - 1, ((index + 1) * BUCKET_ROWS - 1) * bands // total)
            for band in range(first, last + 1):
                summary[band] |= Band.ERROR

        # Gaps and marks are rare and are the whole reason this strip exists,
        # so they are placed exactly rather than smeared across their bucket.
        # Bucketed, two gaps in a short capture lit seventy-nine bands out of a
        # hundred and eighty -- a picture saying that two fifths of the log was
        # missing. There are a handful of them, so the bisect costs nothing.
        for source in self._marker_sources:
            summary[self._band_of(source, bands, total)] |= Band.MARKER
        for source in self._marks:
            summary[self._band_of(source, bands, total)] |= Band.MARK
        return summary

    def _band_of(self, source: int, bands: int, total: int) -> int:
        """Which stripe a retained row falls in, after filtering."""
        view_row = bisect_left(self._visible, source)
        return min(view_row * bands // total, bands - 1)

    def _rebuild_buckets(self) -> None:
        """Summarise every visible row into fixed-size buckets.

        The whole point of a *fixed* bucket rather than a pixel band: bands
        move as rows arrive, so a summary in band units has to be recomputed
        from scratch on every batch -- measured at 282 ms over 200,000 rows,
        which is a third of a second of frozen window, twenty times a second.
        Buckets are anchored to row numbers instead, so an append touches only
        the last one or two of them and this full pass runs only when the whole
        index is rebuilt anyway.
        """
        self._buckets = []
        self._marker_sources = []
        self._extend_buckets(0)

    def _extend_buckets(self, from_row: int) -> None:
        """Fold visible rows from ``from_row`` onward into the buckets."""
        buckets = self._buckets
        for view_row in range(from_row, len(self._visible)):
            bucket = view_row // BUCKET_ROWS
            if bucket >= len(buckets):
                buckets.append(Band.NONE)
            source = self._visible[view_row]
            row = self._rows[source]
            if isinstance(row, Record):
                if row.is_error:
                    buckets[bucket] |= Band.ERROR
            else:
                self._marker_sources.append(source)

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

        Uncommon rather than unheard of, which is what this comment used to
        say: lnav does it by anchoring on the message timestamp, in the view
        where it parses one. Wireshark has had it open since 3.0.7, and Logcat
        rebuilds its document on each filter change.

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
            # Built by the exporter rather than spelled out again here: the same
            # event should read the same in both places, and the two spellings
            # had already drifted -- this one ended in four dashes where the
            # exporter writes twenty. Full timestamps rather than the
            # exporter's times of day, because a table has a Time column beside
            # it and a text file does not.
            return gap_line(str(row.start), str(row.end), row.reason)
        return row.text

    def _foreground(self, row: Row) -> object:
        level = row.level if isinstance(row, Record) else MARKER_LEVEL
        return self._severity[level].foreground

    def _background(self, view_row: int, row: Row) -> object:
        """Marks outrank every colour rule.

        A mark is the user's own annotation and a severity tint is the
        program's; when they disagree the user's wins, or marking a Fault
        would do nothing visible and the feature would appear broken exactly
        where it matters most.
        """
        if self._visible[view_row] in self._marks:
            return self._mark_tint
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
        self._gaps += sum(1 for row in batch if isinstance(row, Gap))

        if newly_visible:
            start = len(self._visible)
            self.beginInsertRows(QModelIndex(), start, start + len(newly_visible) - 1)
            self._rows.extend(batch)
            self._visible.extend(newly_visible)
            self._extend_buckets(start)
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
        """Drop the oldest rows once the cap is exceeded, in one operation.

        A removal rather than a reset. Resetting is easier and throws away the
        user's selection and scroll position every time the cap is reached --
        which, on a live capture, is every couple of minutes forever, and
        always while they are reading something.

        Amortised in frequency but, until measured, not in cost: one trim drops
        20,000 rows and took **118 ms** -- at 1,600 records a second, a
        two-to-six frame freeze every 12.5 seconds, forever, on a rhythm the
        eye learns. Lowering `TRIM_MARGIN` makes it more frequent, not smaller.

        Most of that was doing the same work twice. The buckets were rebuilt
        here and then rebuilt again by `note_eviction` over the same rows;
        `_visible` was rebased here and walked again there to shift every index
        by one; and the newest dropped timestamp came from a `max()` over
        twenty thousand rows to find a value that is always the last one,
        because they are in arrival order. Folding the eviction notice into
        this pass removes all three: **50 ms**.

        Attempting to keep the surviving buckets rather than recomputing them
        was measured and abandoned -- the notice is re-inserted at the top on
        every trim, which shifts every view row by one and invalidates the
        alignment the reuse depends on. `test_gui_minimap.py` asserts the
        summary matches a full rebuild either way, because a bucket summary
        that drifts out of step with its rows points at the wrong part of the
        log rather than failing.
        """
        limit = int(self._row_cap * (1 + TRIM_MARGIN))
        if len(self._rows) <= limit:
            return

        # Everything this method adds or removes happens at the *top*, so the
        # net change in the row count is exactly how far the surviving rows
        # move. Measured across the whole operation rather than derived from
        # the branches below, which is what makes it impossible for the number
        # the view is given to disagree with what the view was told.
        before = len(self._visible)
        drop = len(self._rows) - self._row_cap
        # Never cut in the middle of anything: whatever is dropped, a row
        # boundary is where it is dropped.
        dropped = self._rows[:drop]
        count = 0
        gaps = 0
        newest: datetime | None = None
        for row in dropped:
            if isinstance(row, Record):
                count += 1
                newest = row.timestamp
            elif isinstance(row, Gap):
                gaps += 1
        self._gaps -= gaps

        notice = (
            Eviction(count=self._evicted + count, through=newest) if newest is not None else None
        )
        # Whether the notice is replacing one already at the top or arriving
        # for the first time, which is the difference between the surviving
        # rows keeping their view positions and all shifting by one.
        replacing = bool(self._rows) and isinstance(self._rows[0], Eviction)

        # `_visible` is ascending, so the visible rows being removed are a
        # contiguous prefix of it -- which is what makes this one removal
        # rather than one per row.
        gone = bisect_left(self._visible, drop)
        if notice is not None and replacing:
            # The old notice is inside the dropped prefix and the new one takes
            # its place, so one fewer row actually leaves the view.
            gone -= 1
        if gone > 0:
            self.beginRemoveRows(QModelIndex(), 0, gone - 1)
        elif notice is not None and not replacing:
            self.beginInsertRows(QModelIndex(), 0, 0)

        offset = drop - 1 if notice is not None else drop
        self._rows = self._rows[drop:]
        self._visible = [
            index - offset for index in self._visible[bisect_left(self._visible, drop) :]
        ]
        # A mark on an evicted record goes with it. Keeping one that points at
        # nothing is worse than losing it: the user would jump to a row that is
        # not the one they marked.
        self._marks = {mark - offset for mark in self._marks if mark >= drop}
        if notice is not None:
            self._rows.insert(0, notice)
            self._visible.insert(0, 0)
            self._evicted += count
        self._rebuild_buckets()

        if gone > 0:
            self.endRemoveRows()
        elif notice is not None and not replacing:
            self.endInsertRows()

        shifted = before - len(self._visible)
        if shifted:
            self.top_shifted.emit(shifted)

    def note_eviction(self, count: int, through: datetime) -> None:
        """Record that ``count`` records left the view but not the capture.

        Called by `_trim` for the model's own cap, and by `gui.pump` for
        records dropped from a paused queue. Both mean the same thing and get
        the same row: those records are on disk, and the view is bounded.

        One notice, updated. Twenty evictions are one fact about the view, not
        twenty rows of noise at the top of it -- and updating in place rather
        than resetting keeps the selection the user is reading with.
        """
        if count <= 0:
            return
        self._evicted += count
        notice = Eviction(count=self._evicted, through=through)

        if self._rows and isinstance(self._rows[0], Eviction):
            self._rows[0] = notice
            top = self.index(0, 0)
            self.dataChanged.emit(top, self.index(0, len(COLUMNS) - 1))
            return

        self.beginInsertRows(QModelIndex(), 0, 0)
        self._rows.insert(0, notice)
        self._visible = [0, *(index + 1 for index in self._visible)]
        self._marks = {mark + 1 for mark in self._marks}
        self._rebuild_buckets()
        self.endInsertRows()

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
        self._rebuild_buckets()

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
        """How many gaps are retained.

        Counted on the way in rather than by scanning. The status bar asks for
        this on every pump tick, and a scan of every retained row costs 6.4 ms
        at 200,000 -- measured as 88% of the drain, growing with the session,
        which is exactly the shape of "fine at first, stuttery after a few
        minutes".
        """
        return self._gaps

    @property
    def hidden_by_filter(self) -> int:
        return len(self._rows) - len(self._visible)
