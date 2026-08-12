# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the jump arrows jump between.

The two chevrons in the toolbar were wired to `Find.ERROR` and nothing else,
which is the right default and a poor answer to "I am reading a capture for
gaps today". The alternative kinds already existed -- the model has found gaps
and marked rows since it was written, and the menu has always had keys for them
-- so what was missing was not a capability but a way to point the *arrows* at
one, which is where a reader's hand already is.

The keyboard keeps its explicit per-kind bindings. Choosing a target here moves
`F3` and nothing else, so nobody loses ``Ctrl+Shift+G`` by having picked errors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QMenu, QToolButton

from ostrace.gui.finding import Find

if TYPE_CHECKING:
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QWidget

__all__ = ["JumpButton"]


class JumpButton(QToolButton):
    """A label naming the current target, and a menu of the others."""

    #: The user picked a kind. Carries the `Find`.
    changed = Signal(object)

    def __init__(self, target: Find = Find.ERROR, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.target = target
        self._menu = QMenu(self)
        self._actions: dict[Find, QAction] = {}

        # Exclusive, so the menu cannot show two targets checked at once even
        # if something sets one directly. The arrows have exactly one meaning
        # at a time and the menu is where that is visible.
        group = QActionGroup(self)
        group.setExclusive(True)
        for kind in Find:
            action = self._menu.addAction(kind.label)
            action.setCheckable(True)
            action.setChecked(kind is target)
            action.setActionGroup(group)
            action.triggered.connect(lambda _checked=False, k=kind: self.set_target(k))
            self._actions[kind] = action

        self.setMenu(self._menu)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.setToolTip("What the jump arrows move between")
        # Its text is the *value* -- `Errors`, `Gaps` -- so read out on its own
        # it names a thing rather than a control, and gives no clue that the
        # thing is settable or what setting it would change.
        self.setAccessibleName("Jump target")
        self.setAccessibleDescription("What the jump arrows move between")
        self.setText(target.label)

    def set_target(self, target: Find) -> None:
        """Point the arrows at ``target``."""
        self.target = target
        for kind, action in self._actions.items():
            action.setChecked(kind is target)
        self.setText(target.label)
        self.changed.emit(target)
