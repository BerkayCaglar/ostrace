# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The record table, configured against measurements rather than defaults.

Every setting here is in `docs/design/gui.md` §11 with the number that put it
there. The two worth understanding before changing anything:

**The horizontal header is quadratic.** QTBUG-59478 has been open since 2017 --
its fix was posted and then abandoned the same year -- and the header's repaint
asks the selection model, per section, whether that whole column is selected.

Hiding the header fixes it and costs the user the column titles, which is a bad
trade in a table of six columns of similar-looking text. `FastHeader` below
takes the documented third option instead: override
``initStyleOptionForIndex`` so the per-index selection query never runs, and
keep the titles. Measured on PySide6 6.11.1, 200k rows x 6 columns,
``selectAll()`` plus the repaint it triggers, best of three:

=========================================  ========  ================
header                                     time      ``flags()`` calls
=========================================  ========  ================
stock ``QHeaderView``, real model           5.98 s          1,200,689
``FastHeader``, real model                  2.92 s                683
stock ``QHeaderView``, stand-in model       4.06 s          1,200,689
``FastHeader``, stand-in model              0.008 s               683
=========================================  ========  ================

**Read the first two rows, not the last two.** This was published as "541x, the
single biggest lever", which is the bottom pair -- measured against a stand-in
model whose ``flags()`` returns a constant and whose ``data()`` returns ``"x"``.
Against the model that ships it is **about 2x**, because the remaining ~2.9 s is
the selection model and the repaint rather than the header, and because
`RecordModel._flags` is prebuilt: a million cheap calls cost far less than a
million expensive ones. The two optimisations were treating the same wound and
their savings do not add up.

Still worth having -- halving `selectAll()` on a large capture is real, and the
call counts show the header is genuinely what *causes* those calls. But it is
not the biggest lever, and the figure that said so described a table nobody
ships. ``setHighlightSections(False)`` was measured separately and does nothing
at all here: 5.93 s against 5.98 s.

The first version of this class skipped ``super()`` outright and was faster
still -- and painted a header with no titles, because the base implementation
is also what fills in the section text. It went unnoticed until a screenshot
showed the empty strip. Reimplementing the cheap half is the actual fix, and
the numbers above are from that version.

**Row height must be fixed, and cannot be fixed the obvious way.**
``QTableView`` has no ``setUniformRowHeights()`` -- that is ``QTreeView``-only,
verified absent in 6.11.1 -- so it comes from the vertical header instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QAbstractItemModel,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QFont,
    QFontMetrics,
    QPainter,
    QPaintEvent,
    QPalette,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionHeader,
    QStyleOptionViewItem,
    QTableView,
)

from ostrace.gui.columns import COLUMNS, Column
from ostrace.gui.fonts import monospace
from ostrace.gui.theme import Scheme, palette_for, selection_row, token

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

__all__ = ["FastHeader", "LogTable", "MiddleElidingDelegate", "SeverityDelegate"]

_Index = QModelIndex | QPersistentModelIndex

#: Extra pixels above and below the text. Small, because the whole point of the
#: table is how many records fit on screen at once.
_ROW_PADDING = 6

#: A floor under the row height, so that the rhythm does not collapse on a
#: platform whose UI font happens to be short. The measured Windows default
#: lands at 21, so this bites rarely and only in the direction of legibility.
_MIN_ROW_HEIGHT = 22

#: The empty-state heading, in points above the body. Big enough to read as a
#: statement rather than as a stray record.
_PLACEHOLDER_POINT_BONUS = 3.0

#: Between the heading and the sentence under it.
_PLACEHOLDER_GAP = 8

#: Taller than a row, so the titles read as a header rather than as the first
#: record. Fixed rather than derived, because the header carries the smaller of
#: the two type sizes and would otherwise shrink below the row it labels.
_HEADER_HEIGHT = 26

#: Characters the Message column is never squeezed below.
#:
#: The budgets in `columns` are what each column wants; this is what the table
#: is *for*. Measured on the shipped set at a 1,280-pixel window: five fixed
#: columns of 91 characters come to 1,183 pixels of a 1,254-pixel viewport, so
#: the message got 71 -- about five characters -- and the columns overflowed
#: the window besides, which is a horizontal scrollbar on a table with no rows
#: in it. Every budget is a want and this is a floor, so the floor wins.
MESSAGE_MINIMUM = 30

#: Columns whose content has a known length, and which therefore do not give
#: any of it up. A timestamp missing its last digits is a timestamp nobody can
#: use, and `Level` has to fit ``User Action`` and its glyph. Everything else
#: is an identifier that elides into something still recognisable.
_UNTRIMMABLE = (Column.TIME, Column.LEVEL)

#: And a floor under the ones that do give room up, so that trimming never
#: reduces a column to punctuation.
_MINIMUM_CHARACTERS = 8


class FastHeader(QHeaderView):
    """A horizontal header that does not ask which columns are selected.

    ``QHeaderView::initStyleOptionForIndex`` is what makes header painting
    O(rows): for each section it asks the selection model whether that whole
    column is selected, and ``isColumnSelected`` walks the selection. Dropping
    the question entirely costs a visual cue almost nothing else in the table
    provides -- the highlighted column header -- and buys back three orders of
    magnitude on any large selection.
    """

    def initStyleOptionForIndex(self, option: QStyleOptionHeader, logical_index: int) -> None:  # noqa: N802
        """Fill in the style option without asking about the selection.

        Deliberately *not* calling ``super()``: the selection query is the
        cost. But the base implementation also fills in the section's text and
        position, so skipping it entirely paints a header with no titles at all
        -- which is what this class exists to avoid, and what it did until a
        screenshot showed an empty header strip. Everything the base sets is
        set here except the part that walks the selection.
        """
        # Annotated optional deliberately: the stubs type `model()` as always
        # returning one, and at run time a header that has not been given a
        # model returns None.
        model: QAbstractItemModel | None = self.model()
        option.section = logical_index
        option.orientation = self.orientation()
        option.textAlignment = self.defaultAlignment()
        option.text = (
            str(model.headerData(logical_index, self.orientation(), Qt.ItemDataRole.DisplayRole))
            if model is not None
            else ""
        )
        option.position = self._section_position(logical_index)

        # The two pieces of state that only exist to say "a cell in this column
        # is selected" -- the whole point of the override.
        option.state &= ~QStyle.StateFlag.State_Sunken
        option.state &= ~QStyle.StateFlag.State_On
        option.selectedPosition = QStyleOptionHeader.SelectedPosition.NotAdjacent

    def _section_position(self, logical_index: int) -> QStyleOptionHeader.SectionPosition:
        """Which end of the header this section sits at, for the frame drawing."""
        visible = self.count() - self.hiddenSectionCount()
        if visible <= 1:
            return QStyleOptionHeader.SectionPosition.OnlyOneSection
        visual = self.visualIndex(logical_index)
        if visual == 0:
            return QStyleOptionHeader.SectionPosition.Beginning
        if visual == visible - 1:
            return QStyleOptionHeader.SectionPosition.End
        return QStyleOptionHeader.SectionPosition.Middle


class SeverityDelegate(QStyledItemDelegate):
    """Keep the level's colour on the row the user selected.

    ``QStyledItemDelegate.initStyleOption`` puts the model's ``ForegroundRole``
    into the palette's ``Text``, and the style then draws a *selected* row with
    ``HighlightedText`` instead -- so selecting a row discarded its severity
    colour and an Error stopped looking like an Error at exactly the moment
    somebody clicked it to read it. The glyph survived, which is the only reason
    the row was still identifiable at all.

    Both roles get the same brush here, so severity is a property of the record
    rather than of whether it happens to be selected. What makes that safe is
    the table's own `Highlight`, which is `theme.selection_row` rather than the
    saturated application highlight: every severity foreground clears WCAG AA
    against it, asserted in `test_gui_theme.py`.

    ``initStyleOption`` only -- no ``paint`` override. This runs for every
    visible cell on every repaint, and a Python ``paint`` on that path is the
    one thing the table cannot afford.
    """

    def initStyleOption(self, option: QStyleOptionViewItem, index: _Index) -> None:  # noqa: N802
        super().initStyleOption(option, index)
        foreground = index.data(Qt.ItemDataRole.ForegroundRole)
        if foreground is not None:
            option.palette.setBrush(QPalette.ColorRole.HighlightedText, QBrush(foreground))


class MiddleElidingDelegate(SeverityDelegate):
    """Elide from the middle, keeping both ends of the value.

    For the Process column, where the cell reads ``name[pid]`` and the pid is
    the part that tells eight instances of one process apart. The table elides
    right, which drops exactly that: ``nsurlsessiond(libqui…`` on a 22-character
    column, with the pid gone. The exporters already take trouble over this --
    `exporters.plaintext` keeps the pid when a value overflows its column --
    and `docs/design/gui.md` §2 says the pid is never what gets truncated.

    A delegate rather than a view setting because `textElideMode` is a property
    of the whole view and the Message column genuinely wants its beginning.
    """

    def initStyleOption(self, option: QStyleOptionViewItem, index: _Index) -> None:  # noqa: N802
        super().initStyleOption(option, index)
        option.textElideMode = Qt.TextElideMode.ElideMiddle


class LogTable(QTableView):
    """The record table."""

    #: Which rows are on screen has changed: scrolled, resized, or the model
    #: grew or was trimmed under it. One signal for all four because the
    #: question anybody asks afterwards is the same one, and a widget that has
    #: to subscribe to four things to answer it will miss the fourth.
    viewport_changed = Signal()

    def __init__(self, parent: QWidget | None = None, *, scheme: Scheme = Scheme.LIGHT) -> None:
        super().__init__(parent)
        self._scheme = scheme
        self._heading = ""
        self._detail = ""
        #: Whether the columns have been sized against a real width yet. They
        #: are first sized when a model arrives, which is before this widget
        #: has been laid out and therefore before there is a width to fit them
        #: to. See `resizeEvent`.
        self._columns_fitted = False

        self.setFont(self._body_font())
        self.setHorizontalHeader(FastHeader(Qt.Orientation.Horizontal, self))
        self.setItemDelegate(SeverityDelegate(self))
        self.setItemDelegateForColumn(int(Column.PROCESS), MiddleElidingDelegate(self))

        # Whole rows, extended selection: a log is read by row, and copying a
        # range of rows is the single most common thing done with one.
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        # Wrapping forces a per-row height computation, which defeats the fixed
        # row height below and reintroduces the cost it exists to avoid.
        # The menu itself is the window's: every entry on it is an action the
        # window already owns, and a table that built its own copy or its own
        # mark would be a second implementation to keep in step with the first.
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setCornerButtonEnabled(False)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        # The scrollbar outlives every model this view will be given, so this
        # is connected once. `valueChanged` rather than `actionTriggered`:
        # this is about where the view *is*, however it got there, and the tail
        # scrolling it programmatically moves it as surely as a hand does.
        # `rangeChanged` is the other half -- appending and trimming both
        # change which rows the same scroll position covers without the
        # position itself moving at all.
        bar = self.verticalScrollBar()
        bar.valueChanged.connect(self.viewport_changed)
        bar.rangeChanged.connect(self.viewport_changed)

        vertical = self.verticalHeader()
        vertical.setVisible(False)
        vertical.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vertical.setDefaultSectionSize(
            max(_MIN_ROW_HEIGHT, self.fontMetrics().height() + _ROW_PADDING)
        )

        horizontal = self.horizontalHeader()
        horizontal.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        horizontal.setHighlightSections(False)
        horizontal.setStretchLastSection(True)
        # Left, against left-aligned data. Qt centres section text by default,
        # which puts every title out of line with the column under it.
        horizontal.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        horizontal.setFixedHeight(_HEADER_HEIGHT)

        self.set_scheme(scheme)

    @staticmethod
    def _body_font() -> QFont:
        """The face the records are read in.

        Monospaced, which is also what makes `apply_column_widths` honest: it
        budgets a column in multiples of the width of ``0``, and in a
        proportional face a digit is nothing like a colon or a lowercase l.
        Shared with the detail pane through `gui.fonts`, so a message reads the
        same in both places.
        """
        return monospace()

    def set_scheme(self, scheme: Scheme) -> None:
        """Recolour the table for ``scheme``.

        Its own palette rather than the application's, for one role: the
        selected row. See `theme.selection_row` for why a log table cannot use
        the saturated highlight that suits a menu.

        **And the viewport's, which is not the same widget.** A scroll area
        paints its background from the viewport's palette, and the viewport
        ends up holding one of its own with every role explicitly resolved --
        after which nothing set on the view reaches it again. Measured: with
        the table's ``Base`` correctly at ``#1b1e24``, the viewport went on
        painting ``#ffffff``. Rows carrying `AlternateBase` came out dark and
        the ones showing the background stayed white, so the dark theme
        rendered as white stripes through a dark table -- and an empty table as
        a white sheet, which is what "dark mode is not working" looked like the
        second time. The first time it was a different bug with the same
        picture, which is the argument for reading a pixel rather than a
        palette.
        """
        self._scheme = scheme
        palette = palette_for(scheme)
        palette.setColor(QPalette.ColorRole.Highlight, selection_row(scheme))
        self.setPalette(palette)
        self.viewport().setPalette(palette)

    def set_placeholder(self, heading: str, detail: str = "") -> None:
        """What an empty table says about being empty.

        Every reason the table has no rows produces the same blank grid: nothing
        opened yet, a device that has not spoken, a capture that recorded
        nothing, a filter one character too narrow. A grid that says nothing is
        the state in which a working program and a broken one look identical,
        and it is where "dated" is most visible -- the window has room for a
        sentence and spends it on ruled lines.
        """
        self._heading = heading
        self._detail = detail
        self.viewport().update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        """Rows if there are any, an explanation if there are not.

        Painted rather than a stacked widget: a widget would have to be raised
        and lowered in step with the row count from several places, and this
        cannot fall out of step with what is actually on screen.
        """
        super().paintEvent(event)
        # Annotated optional for the same reason `FastHeader` does it: the stubs
        # type `model()` as always returning one, and a view that has not been
        # given a model returns None at run time -- which is exactly the state
        # this method exists to draw.
        model: QAbstractItemModel | None = self.model()
        if model is not None and model.rowCount() > 0:
            return
        if not self._heading:
            return

        painter = QPainter(self.viewport())
        area = self.viewport().rect()
        # The interface font, not this widget's. The body is monospaced so that
        # a column budget counted in characters means something, and a sentence
        # of prose set in it reads like a printout rather than like the program
        # talking to you.
        body = QApplication.font()
        heading = QFont(body)
        heading.setPointSizeF(heading.pointSizeF() + _PLACEHOLDER_POINT_BONUS)

        painter.setPen(token("text-secondary", self._scheme))
        painter.setFont(heading)
        metrics = QFontMetrics(heading)
        painter.drawText(
            area.adjusted(0, 0, 0, -metrics.height()),
            Qt.AlignmentFlag.AlignCenter,
            self._heading,
        )

        if self._detail:
            painter.setPen(token("text-muted", self._scheme))
            painter.setFont(body)
            painter.drawText(
                area.adjusted(0, metrics.height() + _PLACEHOLDER_GAP, 0, 0),
                Qt.AlignmentFlag.AlignCenter,
                self._detail,
            )
        painter.end()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        """Size the columns once, the first time there is a width to size to.

        Once, not on every resize: the widths are the user's after they have
        dragged one, and a table that re-sized its columns whenever the window
        moved would undo that continuously. This is the same "first layout"
        moment the window uses to divide its splitter, and for the same reason
        -- a widget that has not been laid out has no width to answer with.
        """
        super().resizeEvent(event)
        self.viewport_changed.emit()
        if self._columns_fitted or self.model() is None or self.viewport().width() <= 0:
            return
        self._columns_fitted = True
        self.apply_column_widths()

    def visible_rows(self) -> tuple[int, int]:
        """The first and last rows with a pixel on screen, both inclusive.

        ``(0, -1)`` when there is nothing to show, which is an empty range on
        the same arithmetic rather than a special case the callers have to test
        for separately.

        The bottom falls back to the last row rather than to nothing: an
        invalid index at the bottom edge means the rows ran out before the
        viewport did, so everything there is *is* on screen. Reading it as
        "nothing is visible" is how a count of what lies below ends up
        reporting the whole capture when the whole capture fits.
        """
        # ``self.model()`` rather than a local, which is the shape
        # ``resizeEvent`` above already uses: the stubs declare it non-optional
        # and it plainly is not -- a view has none until one is set -- and a
        # local would let the checker narrow the guard away as dead code.
        if self.model() is None or self.viewport().height() <= 0:
            return (0, -1)
        rows = self.model().rowCount()
        if rows == 0:
            return (0, -1)
        first = self.indexAt(QPoint(0, 0))
        last = self.indexAt(QPoint(0, self.viewport().height() - 1))
        return (first.row() if first.isValid() else 0, last.row() if last.isValid() else rows - 1)

    def restore_column_widths(self, widths: list[int]) -> None:
        """Put back what a previous session left, and stop fitting.

        Restored widths are a decision the user already made, so the automatic
        fit does not get to overrule them afterwards.
        """
        self._columns_fitted = True
        for index, width in enumerate(widths):
            self.setColumnWidth(index, width)

    def setModel(self, model: QAbstractItemModel | None) -> None:  # noqa: N802
        """Attach a model, then size the columns.

        The widths have to be applied *here* rather than in ``__init__``:
        ``setColumnWidth`` addresses a column that exists, and before a model
        is set there are none, so the call silently does nothing.
        """
        super().setModel(model)
        if model is not None:
            self.apply_column_widths()

    def apply_column_widths(self) -> None:
        """Size the columns from the current font.

        Resolved from ``QFontMetrics`` rather than set in pixels: macOS cannot
        have High DPI scaling disabled at all and reports an integer device
        pixel ratio where Windows allows fractional, so a pixel width chosen on
        one is wrong on the other. Never ``resizeColumnsToContents`` --
        autosizing columns reflow under the cursor as records arrive.

        The margins are added rather than absorbed. A column is a budget of
        *characters*, and the style then insets the text by
        ``PM_FocusFrameHMargin + 1`` on each side, so spending the budget on the
        column and the margins on the text elides the last character of a value
        sized to fit exactly. It did not show while the body font was
        proportional -- ``09:14:02.118`` is mostly colons and full stops, which
        are narrower than the ``0`` the budget is counted in, and Time had nine
        pixels of slack. In a monospaced face every character is the unit, the
        slack falls to one pixel, and the timestamp is the first thing to lose
        its last digit.
        """
        unit = self.fontMetrics().horizontalAdvance("0")
        inset = self.style().pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, None, self) + 1
        margins = 2 * inset
        budgets = {
            spec.column: spec.characters * unit + margins
            for spec in COLUMNS
            if spec.characters is not None
        }
        for column, width in self._fitted(budgets, unit).items():
            self.setColumnWidth(int(column), width)

    def _fitted(self, budgets: dict[Column, int], unit: int) -> dict[Column, int]:
        """The budgets, trimmed until the message has room to be read.

        ``stretchLastSection`` only *grows* the last section into space that is
        left over. When the columns before it have already used the window
        there is nothing left, so it keeps its default 100 pixels and the table
        scrolls sideways -- with no rows in it, which is how this was noticed.
        Growing is the easy half; deciding what to give up is this.

        Nothing happens until the view has a width, and nothing happens if the
        budgets already fit. When they do not, the shortfall comes out of the
        identifier columns in proportion to what they asked for, never out of
        the two whose content has a known length, and never below
        `_MINIMUM_CHARACTERS`. If even that is not enough the budgets stand and
        the scrollbar appears, which at that width is the honest answer.
        """
        available = self.viewport().width()
        room = available - MESSAGE_MINIMUM * unit
        if available <= 0 or sum(budgets.values()) <= room:
            return budgets

        untrimmable = sum(budgets[column] for column in _UNTRIMMABLE if column in budgets)
        flexible = {
            column: width for column, width in budgets.items() if column not in _UNTRIMMABLE
        }
        spare = room - untrimmable
        floor = _MINIMUM_CHARACTERS * unit
        if not flexible or spare < floor * len(flexible):
            return budgets

        scale = spare / sum(flexible.values())
        return {
            column: (width if column in _UNTRIMMABLE else max(floor, int(width * scale)))
            for column, width in budgets.items()
        }
