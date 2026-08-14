# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The way back out of naming a filter.

Small on purpose. Naming one is a prompt and choosing one is a menu row, so the
only thing left that needs a window of its own is *removing* one -- and without
somewhere to do that, a name typed by mistake is on the menu for the life of the
installation, which is the class of dead end this project treats as a defect
rather than as an inconvenience.

Renaming is here for the same reason and at almost no cost: a saved filter is a
name and a value, the value is already reachable by choosing it, and a rename
that meant "choose it, save it again, then remove the old one" is three steps to
fix a typo.

The dialog owns no settings. It is handed a list and returns one, so what is
kept and where is the window's decision and this stays testable with no store
at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from ostrace.gui.filters import SavedFilter, forget, save

if TYPE_CHECKING:
    from collections.abc import Sequence

    from PySide6.QtWidgets import QWidget

__all__ = ["SavedFiltersDialog"]


class SavedFiltersDialog(QDialog):
    """List the named filters, and let one be renamed or removed."""

    def __init__(self, saved: Sequence[SavedFilter], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Saved filters")
        self.saved = list(saved)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Filters you have named. Choosing one is done from the bar."))

        self.list = QListWidget(self)
        self.list.setAccessibleName("Saved filters")
        layout.addWidget(self.list)

        #: The terms of whichever row is selected, so that two filters saved
        #: under different names are told apart by something other than the
        #: name being wrong.
        self.terms = QLabel(self)
        self.terms.setWordWrap(True)
        layout.addWidget(self.terms)

        buttons = QHBoxLayout()
        self.rename = QPushButton("Rename…", self)
        self.remove = QPushButton("Remove", self)
        buttons.addWidget(self.rename)
        buttons.addWidget(self.remove)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        close.rejected.connect(self.reject)
        layout.addWidget(close)

        self.rename.clicked.connect(self._rename_selected)
        self.remove.clicked.connect(self._remove_selected)
        self.list.currentRowChanged.connect(self._show_selected)
        self._fill()

    def _fill(self) -> None:
        """Rebuild the list from `saved`, keeping the selection where it can."""
        row = max(0, min(self.list.currentRow(), len(self.saved) - 1))
        self.list.clear()
        for entry in self.saved:
            QListWidgetItem(entry.name, self.list)
        self.list.setCurrentRow(row if self.saved else -1)
        self._show_selected(self.list.currentRow())

    def _show_selected(self, row: int) -> None:
        """Say what the selected name stands for, and what can be done to it.

        Both buttons are disabled with nothing selected rather than being left
        live to do nothing: a button that responds to a press by doing nothing
        is indistinguishable from one that is broken.
        """
        entry = self._at(row)
        self.terms.setText(entry.terms.as_text() if entry is not None else "")
        self.rename.setEnabled(entry is not None)
        self.remove.setEnabled(entry is not None)

    def _at(self, row: int) -> SavedFilter | None:
        return self.saved[row] if 0 <= row < len(self.saved) else None

    def _rename_selected(self) -> None:
        entry = self._at(self.list.currentRow())
        if entry is None:  # pragma: no cover - the button is disabled
            return
        name, chosen = QInputDialog.getText(self, "Rename filter", "Name", text=entry.name)
        if not chosen or not name.strip() or name.strip() == entry.name:
            return
        # Removed under the old name and saved under the new one, in that
        # order: renaming an entry onto the name of another one is a merge the
        # user asked for, and doing it the other way round would save the new
        # name and then remove what had just replaced it.
        renamed = SavedFilter(name=name.strip(), terms=entry.terms)
        self.saved = save(forget(self.saved, entry.name), renamed)
        self._fill()

    def _remove_selected(self) -> None:
        entry = self._at(self.list.currentRow())
        if entry is None:  # pragma: no cover - the button is disabled
            return
        self.saved = forget(self.saved, entry.name)
        self._fill()
