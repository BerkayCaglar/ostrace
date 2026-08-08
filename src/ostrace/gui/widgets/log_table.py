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
keep the titles. Measured here, PySide6 6.11.1, 200k rows x 6 columns,
``selectAll()``, best of three after two discarded warm-up runs:

===================  ========  ================
header               time      ``flags()`` calls
===================  ========  ================
stock QHeaderView    3.896 s          1,200,689
``FastHeader``       0.007 s                683
===================  ========  ================

584x, with the header still visible. Note what the call counts say: that
million-plus ``flags()`` calls is *caused* by the header, so this also removes
most of what the ``flags()``-caching rule was treating.

**Row height must be fixed, and cannot be fixed the obvious way.**
``QTableView`` has no ``setUniformRowHeights()`` -- that is ``QTreeView``-only,
verified absent in 6.11.1 -- so it comes from the vertical header instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QAbstractItemModel, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QStyle,
    QStyleOptionHeader,
    QTableView,
)

from ostrace.gui.columns import COLUMNS

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

__all__ = ["FastHeader", "LogTable"]

#: Extra pixels above and below the text. Small, because the whole point of the
#: table is how many records fit on screen at once.
_ROW_PADDING = 4


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
        # Deliberately *not* calling super(): the base implementation is the
        # cost. It asks the selection model whether this column is selected,
        # and that question is what makes header painting O(rows). Everything
        # else it sets is selection state we are discarding anyway.
        del logical_index
        option.state &= ~QStyle.StateFlag.State_Sunken
        option.state &= ~QStyle.StateFlag.State_On
        option.selectedPosition = QStyleOptionHeader.SelectedPosition.NotAdjacent


class LogTable(QTableView):
    """The record table."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setHorizontalHeader(FastHeader(Qt.Orientation.Horizontal, self))

        # Whole rows, extended selection: a log is read by row, and copying a
        # range of rows is the single most common thing done with one.
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        # Wrapping forces a per-row height computation, which defeats the fixed
        # row height below and reintroduces the cost it exists to avoid.
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setCornerButtonEnabled(False)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        vertical = self.verticalHeader()
        vertical.setVisible(False)
        vertical.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vertical.setDefaultSectionSize(self.fontMetrics().height() + _ROW_PADDING)

        horizontal = self.horizontalHeader()
        horizontal.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        horizontal.setHighlightSections(False)
        horizontal.setStretchLastSection(True)

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
        """
        unit = self.fontMetrics().horizontalAdvance("0")
        for spec in COLUMNS:
            if spec.characters is not None:
                self.setColumnWidth(int(spec.column), spec.characters * unit)
