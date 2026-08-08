# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""In-view notices for states that would otherwise be invisible.

A paused stream looks exactly like a quiet device. An over-narrow filter looks
exactly like a dead one. Both are states the user put the program into and then
forgot, and both generate the same support question everywhere they are not
signalled.

So each one gets a banner in the view -- not a toolbar icon, which is where a
state goes to be ignored -- and each banner carries the action that undoes it.
Android Studio ships exactly this pair (`Logcat is paused`, `All log entries
are hidden by the filter`) with a one-click way out, and it is the piece other
log viewers most consistently lack.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

__all__ = ["Banner"]


class Banner(QFrame):
    """A one-line notice with an optional recovery action."""

    #: The user asked for the way out.
    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        layout = QHBoxLayout(self)
        # Margins in layout units rather than pixels: High DPI cannot be turned
        # off on macOS, and macOS reports an integer device pixel ratio where
        # Windows allows fractional, so a hardcoded pixel margin is wrong on
        # one of them by construction.
        layout.setContentsMargins(8, 4, 8, 4)

        self._label = QLabel(self)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._label.setWordWrap(True)
        layout.addWidget(self._label, stretch=1)

        self._action = QPushButton(self)
        self._action.clicked.connect(self.dismissed)
        layout.addWidget(self._action)

        self.hide()

    def show_message(self, text: str, action: str | None = None) -> None:
        """Display ``text``, with ``action`` as the way out if there is one."""
        self._label.setText(text)
        self._action.setText(action or "")
        self._action.setVisible(action is not None)
        self.show()

    @property
    def text(self) -> str:
        """What the banner currently says. Empty when it is hidden.

        Keyed on ``isHidden()`` rather than ``isVisible()``. The two are not
        opposites: a widget inside a window that has never been shown is not
        visible but has not been hidden either, so ``isVisible()`` would report
        an unshown banner and a dismissed one identically.
        """
        return "" if self.isHidden() else self._label.text()
