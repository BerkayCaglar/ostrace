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
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QToolButton,
    QWidget,
)

from ostrace.gui import icons
from ostrace.gui.filters import Filter, SavedFilter
from ostrace.gui.theme import Scheme
from ostrace.model import Level

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["NO_RECENT", "NO_SAVED", "FilterBar"]

#: What the recent menu says before there is anything in it. Disabled, and
#: present rather than absent: a button that opens an empty menu has been
#: pressed and answered nothing, and the reader is left wondering whether it
#: broke or whether they have simply not used it yet.
NO_RECENT = "No recent filters"

#: The same, for the half that has to be asked for. It says *named* rather than
#: repeating "saved", because a reader who has just found the section under a
#: heading reading Saved learns nothing from a row that says the same word.
NO_SAVED = "No named filters yet"


class FilterBar(QWidget):
    """Level threshold, three text fields, and three in-field toggles.

    The toggles live inside the fields they modify rather than beside them,
    which is `QLineEdit.addAction` and is the arrangement every current search
    box uses. It is not decoration: a `Regex` checkbox sitting after three
    fields does not say *which* field it applies to, and the `≠` has no
    unambiguous place at all -- a bar reading ``Process [ ] Subsystem [ ] ≠``
    has one toggle and two candidates.
    """

    changed = Signal()
    #: One of the offered filters was chosen, recent or named. Carries the
    #: `Filter` itself, so the window never has to map a menu position back
    #: onto a list that may have moved underneath it while the menu was open.
    recent_chosen = Signal(object)
    #: The two verbs at the foot of that menu. The bar raises them rather than
    #: handling them: naming a filter is a prompt and managing them is a
    #: dialog, and both are the window's to own -- a control that opened its
    #: own modal windows would be untestable without one.
    save_requested = Signal()
    manage_requested = Signal()

    def __init__(self, parent: QWidget | None = None, *, scheme: Scheme = Scheme.LIGHT) -> None:
        super().__init__(parent)
        self._scheme = scheme
        #: Every in-field toggle with the glyph it draws, so a theme switch can
        #: re-tint them without naming each one and forgetting the next.
        self._toggles: list[tuple[QAction, str]] = []

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

        self._process_exclude = self._add_toggle(
            self._process,
            "exclude",
            "Exclude this process",
            "Show every record except this process, rather than only this one",
        )
        self._subsystem_exclude = self._add_toggle(
            self._subsystem,
            "exclude",
            "Exclude this subsystem",
            "Show every record except this subsystem, rather than only this one",
        )
        #: Named `_regex` because it was a `QCheckBox` of that name and two
        #: tests set it. A checkable `QAction` answers `setChecked` the same
        #: way, so the move is an implementation change rather than an API one.
        self._regex = self._add_toggle(
            self._search,
            "regex",
            "Regular expression",
            "Read the search text as a regular expression rather than literally",
        )

        #: Both halves of going back to a filter, under one button. The last
        #: few are kept without asking, because the research this came from
        #: ranks naming as the expensive half and going back as the useful one,
        #: and a viewer that asks for a name before it will remember anything
        #: gets asked for nothing. Naming is offered underneath, for the handful
        #: somebody returns to for weeks.
        self._recent_menu = QMenu(self)
        self.recent = QToolButton(self)
        self.recent.setText("Filters")
        self.recent.setToolTip("Filters you have used, and the ones you named")
        self.recent.setAccessibleName("Recent and saved filters")
        self.recent.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.recent.setMenu(self._recent_menu)
        layout.addWidget(self.recent)
        self._recent: list[Filter] = []
        self._saved: list[SavedFilter] = []
        self._recent_actions: list[QAction] = []
        self._saved_actions: list[QAction] = []
        self._rebuild_menu()
        # The `Save current filter…` row is enabled only when there is
        # something to save, so the menu has to be rebuilt when the bar
        # changes rather than only when a list does.
        self.changed.connect(self._rebuild_menu)

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

    def _add_toggle(self, field: QLineEdit, glyph: str, name: str, tooltip: str) -> QAction:
        """A checkable button inside ``field``, at its trailing edge.

        The name is the accessible name as well as the tooltip's first line:
        an in-field action has no visible label at all, so anything reading the
        window gets the icon's name or nothing.

        Added *after* `setClearButtonEnabled`, which is itself a trailing
        action, so the clear cross stays outermost -- the control that empties
        the field is the one the hand goes to without looking, and moving it
        would cost more than the toggle gains.
        """
        action = QAction(name, self)
        action.setCheckable(True)
        action.setToolTip(tooltip)
        action.setIcon(icons.icon(glyph, self._scheme, ratio=self.devicePixelRatioF()))
        action.toggled.connect(self.changed)
        field.addAction(action, QLineEdit.ActionPosition.TrailingPosition)
        self._toggles.append((action, glyph))
        return action

    def set_scheme(self, scheme: Scheme) -> None:
        """Re-tint the in-field glyphs. Their pixmaps are scheme-specific."""
        self._scheme = scheme
        ratio = self.devicePixelRatioF()
        for action, glyph in self._toggles:
            action.setIcon(icons.icon(glyph, scheme, ratio=ratio))

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

    @property
    def process_exclude(self) -> bool:
        return self._process_exclude.isChecked()

    @property
    def subsystem_exclude(self) -> bool:
        return self._subsystem_exclude.isChecked()

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
            process_exclude=self.process_exclude,
            subsystem_exclude=self.subsystem_exclude,
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
        """Rebuild the menu: the unnamed ones, then the named, then the verbs."""
        self._recent = list(recent)
        self._rebuild_menu()

    def set_saved(self, saved: Sequence[SavedFilter]) -> None:
        """Rebuild the menu with a different set of named filters."""
        self._saved = list(saved)
        self._rebuild_menu()

    def _rebuild_menu(self) -> None:
        """One menu from both lists.

        Rebuilt whole rather than patched, because the two halves share a
        separator and the position of everything below the recent list moves
        whenever an entry is added to it.
        """
        self._recent_menu.clear()
        self._recent_actions = []
        self._saved_actions = []

        self._recent_menu.addSection("Recent")
        if not self._recent:
            self._recent_actions.append(self._disabled_row(NO_RECENT))
        for entry in self._recent:
            # `entry=entry` binds now rather than at click time. A closure over
            # the loop variable would give every item the last filter, which is
            # the one bug this pattern exists to prevent.
            self._recent_actions.append(
                self._recent_menu.addAction(
                    entry.summary, lambda entry=entry: self.recent_chosen.emit(entry)
                )
            )

        self._recent_menu.addSection("Saved")
        if not self._saved:
            self._saved_actions.append(self._disabled_row(NO_SAVED))
        for named in self._saved:
            self._saved_actions.append(
                self._recent_menu.addAction(
                    named.name, lambda named=named: self.recent_chosen.emit(named.terms)
                )
            )

        self._recent_menu.addSeparator()
        # Offered even with nothing to save. A menu whose last two rows appear
        # only once you have used the feature is one nobody discovers, and the
        # disabled state below says why rather than hiding the fact.
        save = self._recent_menu.addAction("Save current filter…", self.save_requested.emit)
        save.setEnabled(not self.is_empty)
        manage = self._recent_menu.addAction("Manage saved filters…", self.manage_requested.emit)
        manage.setEnabled(bool(self._saved))

    def _disabled_row(self, text: str) -> QAction:
        """A row that says why a section is empty rather than leaving it blank."""
        action = self._recent_menu.addAction(text)
        action.setEnabled(False)
        return action

    @property
    def recent_entries(self) -> list[str]:
        """What the unnamed half of the menu is offering, for a test to read.

        Read off the menu's own actions rather than off the list they were
        built from, so that it answers whether the menu was *rebuilt* and not
        merely whether the list changed.
        """
        return [action.text() for action in self._recent_actions]

    @property
    def saved_entries(self) -> list[str]:
        """What the named half is offering."""
        return [action.text() for action in self._saved_actions]

    def clear(self) -> None:
        """Reset to showing everything. Wired to the banner's way out."""
        self._set_fields(Filter())

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
        process, both of which set several controls at once. Seven separate
        edits would be seven `changed` signals and, through the debounce, up to
        seven rescans of the entire capture on the way to the one that was
        asked for.
        """
        self._set_fields(wanted)

    def _set_fields(self, wanted: Filter) -> None:
        """Write a whole filter into the controls, silently, then say so once.

        Takes the value rather than a field per parameter. The parameter list
        was the thing that had to be edited in three places every time `Filter`
        grew a term, and it had already grown past the point where the call
        site read as anything.
        """
        blocked = [
            self._level,
            self._process,
            self._subsystem,
            self._search,
            self._regex,
            self._process_exclude,
            self._subsystem_exclude,
        ]
        for control in blocked:
            control.blockSignals(True)
        self._level.setCurrentIndex(self._level.findData(wanted.minimum_level))
        self._process.setText(wanted.process)
        self._subsystem.setText(wanted.subsystem)
        self._search.setText(wanted.search)
        self._regex.setChecked(wanted.regex)
        self._process_exclude.setChecked(wanted.process_exclude)
        self._subsystem_exclude.setChecked(wanted.subsystem_exclude)
        for control in blocked:
            control.blockSignals(False)
        # One signal for the whole change, not seven.
        self.changed.emit()
