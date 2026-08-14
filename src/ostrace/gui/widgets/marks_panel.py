# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The rows you marked, in a list you can get back to.

Marking has existed since phase 4 and the only way back to a mark was to step
through them with a key. That works while there are three; at twenty it is a
tour of the whole capture to find the one you meant, and the marks stop being
worth setting.

Hidden by default, and a dock rather than a pane in the splitter: it is the one
part of this window that is *sometimes* wanted, and a splitter section starts
occupying width the table needs whether or not anybody asked for it.

The panel holds no marks. It reads them off the model when the model says they
changed, which is what keeps the one copy in the one place ADR 0009 puts it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDockWidget, QListWidget, QListWidgetItem

from ostrace.gui.columns import Column

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from ostrace.gui.models import RecordModel

__all__ = ["NO_MARKS", "MarksPanel"]

#: What the list says with nothing in it. Present rather than blank: an empty
#: list is a panel that has been opened and answered nothing, and the reader is
#: left wondering whether it broke or whether they have not marked anything.
NO_MARKS = "No marked rows"

#: How much of the message each entry carries. Enough to recognise a row by,
#: short enough that the panel can be narrow -- it is a way back to a row, not
#: a second table.
_MESSAGE_HEAD = 60


class MarksPanel(QDockWidget):
    """A list of marked rows. Choosing one asks the window to go there."""

    #: A row was chosen. Carries the *view* row, which is what a view scrolls
    #: to -- and which is why the list is rebuilt whenever the filter moves
    #: them: a stale row number is a jump to the wrong record.
    row_chosen = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Marks", parent)
        self.setObjectName("marks")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.list = QListWidget(self)
        self.list.setAccessibleName("Marked rows")
        self.list.itemActivated.connect(self._on_activated)
        self.list.itemClicked.connect(self._on_activated)
        self.setWidget(self.list)
        self._model: RecordModel | None = None
        self.rebuild()

    def set_model(self, model: RecordModel | None) -> None:
        """Watch a different model, and forget the one before it.

        The window replaces its model whenever a capture is opened or started.
        A panel still connected to the old one would keep listing marks against
        rows that no longer exist, which is a jump into whatever now occupies
        that number.
        """
        if self._model is not None:
            self._model.marks_changed.disconnect(self.rebuild)
        self._model = model
        if model is not None:
            model.marks_changed.connect(self.rebuild)
        self.rebuild()

    def rebuild(self) -> None:
        """Read the marks off the model, newest last, as the log reads."""
        self.list.clear()
        rows = self._model.marked_view_rows() if self._model is not None else []
        if not rows:
            placeholder = QListWidgetItem(NO_MARKS, self.list)
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            return
        for row in rows:
            item = QListWidgetItem(self._describe(row), self.list)
            # The row travels on the item rather than being inferred from the
            # item's position: a filter change rebuilds this list and the two
            # orderings would have to be kept in step by hand otherwise.
            item.setData(Qt.ItemDataRole.UserRole, row)

    def _describe(self, row: int) -> str:
        """One line: when, how bad, from what, and the start of what it said."""
        model = self._model
        if model is None:  # pragma: no cover - rows come from a model
            return ""
        time = model.cell_text(row, int(Column.TIME))
        level = model.cell_text(row, int(Column.LEVEL))
        process = model.cell_text(row, int(Column.PROCESS))
        message = model.cell_text(row, int(Column.MESSAGE))
        head = message[:_MESSAGE_HEAD].rstrip()
        if len(message) > _MESSAGE_HEAD:
            head += "…"
        return f"{time}  {level}  {process}  {head}"

    def _on_activated(self, item: QListWidgetItem) -> None:
        row = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(row, int):
            self.row_chosen.emit(row)

    @property
    def entries(self) -> list[str]:
        """What the panel is offering, for a test to read."""
        return [self.list.item(index).text() for index in range(self.list.count())]
