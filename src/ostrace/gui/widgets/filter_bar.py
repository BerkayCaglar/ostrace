# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The filter row.

Level is a **threshold**, not an equality: "Error and above" is what someone
actually wants, and it is only expressible as a threshold because `Level` is
this project's own enum. Apple's values are not severity-ordered -- ``NOTICE=0,
INFO=1, DEBUG=2, USER_ACTION=3, ERROR=16, FAULT=17`` -- so a threshold written
against the device's own numbers would match nearly everything.

`changed` is emitted on every edit and the window debounces it. Re-filtering on
each keystroke of a process name is the behaviour that makes Android Studio's
Logcat throw the user to the bottom of the buffer on every character typed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QToolButton,
    QWidget,
)

from ostrace.gui.filters import Filter
from ostrace.model import Level

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["NO_RECENT", "FilterBar"]

#: What the recent menu says before there is anything in it. Disabled, and
#: present rather than absent: a button that opens an empty menu has been
#: pressed and answered nothing, and the reader is left wondering whether it
#: broke or whether they have simply not used it yet.
NO_RECENT = "No recent filters"


class FilterBar(QWidget):
    """Level threshold, three text fields, and a regex toggle."""

    changed = Signal()
    #: One of the recent filters was chosen. Carries the `Filter` itself, so
    #: the window never has to map a menu position back onto a list that may
    #: have moved underneath it while the menu was open.
    recent_chosen = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)

        self._level = QComboBox(self)
        for level in Level:
            # userData carries the enum itself, so nothing has to parse the
            # label back into a level -- and the label can be changed freely.
            self._level.addItem(f"{level.title} and above", level)
        self._level.setCurrentIndex(0)
        self._level.currentIndexChanged.connect(self.changed)
        self._level.setAccessibleName("Level")
        level_caption = QLabel("Level", self)
        level_caption.setBuddy(self._level)
        layout.addWidget(level_caption)
        layout.addWidget(self._level)

        self._process = self._add_field(layout, "Process", "name or pid")
        self._subsystem = self._add_field(layout, "Subsystem", "com.apple.…")
        self._search = self._add_field(layout, "Search", "message text", stretch=1)

        self._regex = QCheckBox("Regex", self)
        self._regex.toggled.connect(self.changed)
        layout.addWidget(self._regex)

        #: The last few filters, to go back to without retyping them. No
        #: naming: the research this came from ranks naming as the expensive
        #: half and the going-back as the useful one, and a viewer that asks
        #: for a name before it will remember anything gets asked for nothing.
        self._recent_menu = QMenu(self)
        self.recent = QToolButton(self)
        self.recent.setText("Recent")
        self.recent.setToolTip("Filters you have used, newest first")
        self.recent.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.recent.setMenu(self._recent_menu)
        layout.addWidget(self.recent)
        self.set_recent([])

    def _add_field(
        self, layout: QHBoxLayout, label: str, placeholder: str, *, stretch: int = 0
    ) -> QLineEdit:
        field = QLineEdit(self)
        field.setPlaceholderText(placeholder)
        field.setClearButtonEnabled(True)
        field.textChanged.connect(self.changed)
        caption = QLabel(label, self)
        # A `QLabel` beside a field is a label to somebody looking at it and
        # nothing at all to anything reading the window: the association has to
        # be declared. `setBuddy` also gives the label's accelerator somewhere
        # to go, and the accessible name is belt and braces for the platforms
        # whose bridge reads one and not the other.
        caption.setBuddy(field)
        field.setAccessibleName(label)
        layout.addWidget(caption)
        layout.addWidget(field, stretch=stretch)
        return field

    @property
    def minimum_level(self) -> Level:
        value = self._level.currentData()
        return value if isinstance(value, Level) else Level.DEBUG

    @property
    def process(self) -> str:
        return self._process.text().strip()

    @property
    def subsystem(self) -> str:
        return self._subsystem.text().strip()

    @property
    def search(self) -> str:
        return self._search.text()

    @property
    def regex(self) -> bool:
        return self._regex.isChecked()

    def current(self) -> Filter:
        """What the bar is displaying, as one value.

        Raises ``ValueError`` for a half-typed regular expression, which the
        caller answers by leaving the previous filter applied and saying why --
        half a pattern is not an empty log.

        A method rather than five properties read in a row: the caller was
        naming every field, so adding one meant editing the bar and then
        remembering to edit whoever assembles it.
        """
        return Filter(
            minimum_level=self.minimum_level,
            process=self.process,
            subsystem=self.subsystem,
            search=self.search,
            regex=self.regex,
        )

    @property
    def is_empty(self) -> bool:
        """Whether this bar would exclude anything at all.

        The window needs this to tell "the device is quiet" apart from "your
        filter hides everything", which are the same picture otherwise.

        Asked of the filter rather than of the fields, so the two cannot
        disagree about what empty means. A half-typed pattern is not empty: it
        is a narrowing the user is in the middle of writing.
        """
        try:
            return self.current().is_empty
        except ValueError:
            return False

    def focus_search(self) -> None:
        """Put the cursor in the search box and select what is there.

        Selecting rather than appending: the second press of Find is almost
        always a different search, and a box that keeps the old text is one the
        user has to clear before they can use it.
        """
        self._search.setFocus()
        self._search.selectAll()

    def set_recent(self, recent: Sequence[Filter]) -> None:
        """Rebuild the menu of filters to go back to, newest first."""
        self._recent_menu.clear()
        if not recent:
            self._recent_menu.addAction(NO_RECENT).setEnabled(False)
            return
        for entry in recent:
            # `entry=entry` binds now rather than at click time. A closure over
            # the loop variable would give every item the last filter, which is
            # the one bug this pattern exists to prevent.
            self._recent_menu.addAction(
                entry.summary, lambda entry=entry: self.recent_chosen.emit(entry)
            )

    @property
    def recent_entries(self) -> list[str]:
        """What the menu is offering, for a test to read."""
        return [action.text() for action in self._recent_menu.actions()]

    def clear(self) -> None:
        """Reset to showing everything. Wired to the banner's way out."""
        self._set_fields(Level.DEBUG, "", "", "", regex=False)

    def set_process(self, process: str) -> None:
        """Narrow by process, leaving every other term alone.

        One field, so no signal blocking is needed and none is done: the edit
        the user is watching is the edit that happens.
        """
        self._process.setText(process)

    def set_subsystem(self, subsystem: str) -> None:
        self._subsystem.setText(subsystem)

    def set_filter(self, wanted: Filter) -> None:
        """Put a whole filter into the bar, as one change rather than five.

        The way back from a recent entry and the way a right-click narrows by
        process, both of which set several fields at once. Five separate edits
        would be five `changed` signals and, through the debounce, up to five
        rescans of the entire capture on the way to the one that was asked for.
        """
        self._set_fields(
            wanted.minimum_level,
            wanted.process,
            wanted.subsystem,
            wanted.search,
            regex=wanted.regex,
        )

    def _set_fields(
        self, level: Level, process: str, subsystem: str, search: str, *, regex: bool
    ) -> None:
        blocked = [self._level, self._process, self._subsystem, self._search, self._regex]
        for widget in blocked:
            widget.blockSignals(True)
        self._level.setCurrentIndex(self._level.findData(level))
        self._process.setText(process)
        self._subsystem.setText(subsystem)
        self._search.setText(search)
        self._regex.setChecked(regex)
        for widget in blocked:
            widget.blockSignals(False)
        # One signal for the whole change, not five.
        self.changed.emit()
