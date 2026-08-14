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

from enum import Enum, auto
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAccessible, QAccessibleEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtWidgets import QWidget

__all__ = ["Banner", "Notice"]


class Notice(Enum):
    """Which notice is showing, for the code that has to ask.

    Only the ones somebody *identifies* are named. Twenty messages are raised
    here and most are shown and then dismissed by the user; naming those too
    would be a vocabulary nobody reads. A notice with no key is a notice no
    code asks about.

    A plain ``Enum`` rather than a ``StrEnum`` like
    :class:`~ostrace.sources.base.CaptureState`: nothing carries this across a
    Qt signal, so there is no conversion to survive and no reason to let it
    compare equal to a string.
    """

    RECONNECTING = auto()
    PAUSED = auto()
    FILTER_HIDES_EVERYTHING = auto()
    #: A capture is being read from disk. Identified because the reading ends
    #: on its own, and the notice offering to stop it has to come down when it
    #: does -- but only if it is still the one showing.
    LOADING = auto()


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
        self._action.clicked.connect(self.act)
        layout.addWidget(self._action)

        self._handler: Callable[[], None] | None = None
        self._key: Notice | None = None
        self.hide()

    def show_message(
        self,
        text: str,
        action: str | None = None,
        *,
        on_action: Callable[[], None] | None = None,
        key: Notice | None = None,
    ) -> None:
        """Display ``text``, with ``action`` as the way out if there is one.

        The button carries *what it does* rather than the caller inferring it
        from the wording afterwards. There are several of these messages now --
        a filter hiding everything, a paused view, a capture that stopped --
        and matching on the text to decide what the button meant is a bug
        waiting for someone to reword a sentence.

        ``key`` is that argument's other half. One strip shows one notice at a
        time, so a caller that raised one and later wants to take it down has
        to know whether it is still the one showing -- and the two answers
        invented for that, a string comparison and a flag on the window, were
        both wrong in the same direction: they recorded what had been *raised*
        rather than what is *there*. Pass a key and ask
        :attr:`current_key`.
        """
        self._key = key
        self._label.setText(text)
        self._action.setText(action or "")
        self._action.setVisible(action is not None)
        self._handler = on_action
        self.show()
        # A screen reader follows focus, and nothing here takes it: a paused
        # stream, a filter hiding everything and a capture that died all
        # appear silently for anyone not looking at this strip. `Alert` is the
        # one event that is announced without being focused, which is exactly
        # what this widget is for -- `docs/design/gui.md` §6 calls every one of
        # these a state that must be visible, and visible is not the same as
        # perceivable.
        self.setAccessibleName(text)
        QAccessible.updateAccessibility(QAccessibleEvent(self, QAccessible.Event.Alert))

    def act(self) -> None:
        """Take the way out, whatever it was, and dismiss."""
        handler, self._handler = self._handler, None
        self.hide()
        if handler is not None:
            handler()
        self.dismissed.emit()

    @property
    def text(self) -> str:
        """What the banner currently says. Empty when it is hidden.

        Keyed on ``isHidden()`` rather than ``isVisible()``. The two are not
        opposites: a widget inside a window that has never been shown is not
        visible but has not been hidden either, so ``isVisible()`` would report
        an unshown banner and a dismissed one identically.
        """
        return "" if self.isHidden() else self._label.text()

    @property
    def current_key(self) -> Notice | None:
        """Which notice is on screen, or ``None`` if none is.

        Read from the same ``isHidden()`` as :attr:`text`, which is what makes
        it answer about the strip rather than about the last call: a notice
        replaced by another, dismissed by the user, or taken down with the
        capture stops being the current one without anybody having to remember
        to say so.
        """
        return None if self.isHidden() else self._key
