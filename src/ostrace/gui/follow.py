# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Staying at the bottom of a log that is still growing.

`docs/design/gui.md` §4's rule is the whole of this file: **follow is derived
on every read, never stored.** A stored bit can disagree with the view, and
Console.app kept one and shipped an eleven-month bug where selecting a row
silently stopped the tail. The indicator in the status bar and the scrolling
itself therefore ask the same question of the same object, and cannot come to
different answers.

An object bound to a table rather than a pure function, and that is the point
rather than a compromise. There are two things a person does that mean "I have
stopped tailing" -- scrolling up, and selecting a row -- and only one of them
can be read from the view at any moment: `actionTriggered` fires *before* the
scrollbar's value changes, so a scroll can only be noted and read later. Noting
is state, and state needs somewhere to live. What is not stored is the
*answer*.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QElapsedTimer, QModelIndex, QObject, Signal

if TYPE_CHECKING:
    from ostrace.gui.models import RecordModel
    from ostrace.gui.widgets.log_table import LogTable

__all__ = ["FOLLOW_MIN_MS", "FOLLOW_SLACK", "FollowController"]

#: How near the bottom still counts as "at the bottom". A few pixels of slack,
#: because a scrollbar rarely lands exactly on its maximum.
FOLLOW_SLACK = 4

#: How often the tail may actually scroll. Ten times a second still reads as
#: continuous, and it is the difference between a third of the GUI thread going
#: into repaints and a fifth: at device throughput every drain scrolls further
#: than the viewport is tall, so each one is a full repaint of every visible
#: cell -- measured at 20 ms, 15 times a second. Draining stays at 50 ms so the
#: queue never builds; only the scrolling is coalesced, and no record is lost by
#: coalescing it. `docs/design/gui.md` §9 asks for this to be a preference; a
#: measured constant is what ships.
FOLLOW_MIN_MS = 100


class FollowController(QObject):
    """Whether the tail is being followed, and the scrolling that follows it."""

    #: The answer may have changed. Carries nothing: whoever shows it asks.
    changed = Signal()

    def __init__(
        self,
        table: LogTable,
        model: RecordModel,
        parent: QObject | None = None,
        *,
        min_ms: int = FOLLOW_MIN_MS,
    ) -> None:
        super().__init__(parent)
        self._table = table
        self._model = model
        #: How long between scrolls. Public and settable because a test
        #: asserting the *rule* -- does the tail follow, does it let go of a
        #: reader who scrolled up -- has to defeat the coalescing to see the
        #: rule at all, and reaching into a clock to do it is a test that knows
        #: more about this object than the rule needs.
        self.min_ms = min_ms
        #: Whether the view was at the bottom when a person last moved it. Not
        #: the answer -- an input to it. See `following`.
        self._at_bottom = True
        #: A scroll has happened and has not been read yet. `actionTriggered`
        #: arrives before the value changes, so this is all that can be known
        #: at the moment it fires.
        self._user_scrolled = False
        self._scrolled = QElapsedTimer()

    # ------------------------------------------------------------------
    # The two derived answers
    # ------------------------------------------------------------------

    @property
    def following(self) -> bool:
        """Whether the next batch of records will be scrolled to.

        Derived, and this is the *only* derivation -- `tick` acts on it and the
        status bar shows it, so the indicator cannot disagree with the
        behaviour.

        A selection that is not the last row is the evidence of a reader who
        has stopped tailing, and it is read from the view rather than stored.
        This window has a detail pane, so selection is the primary interaction:
        a tail that survived it would drag the row out from under whoever just
        clicked it, which is the Console.app bug from the other direction.
        """
        last = self._model.rowCount() - 1
        current = self._table.currentIndex()
        if last >= 0 and current.isValid() and current.row() < last:
            return False
        return self._at_bottom

    @property
    def behind(self) -> int:
        """How many records sit below the bottom of the viewport, unseen.

        Read off the *bottom row* rather than by counting arrivals, which makes
        it O(1) and makes it right after a filter change, a trim or a jump --
        each of which moves the reader relative to the end without a record
        arriving at all. A partially visible row at the bottom edge counts as
        behind, which errs towards "you have not read this one".
        """
        _, bottom = self._table.visible_rows()
        return max(0, self._model.rowCount() - 1 - bottom)

    # ------------------------------------------------------------------
    # What a person did
    # ------------------------------------------------------------------

    def note_scroll(self) -> None:
        """The user moved the view themselves.

        ``actionTriggered`` fires for a drag, a wheel, an arrow and a page --
        and *not* for ``setValue``, which is how everything the window does
        moves the view. That distinction is the whole mechanism: leaving the
        bottom is something a person does, and nothing else can be mistaken for
        it.
        """
        self._user_scrolled = True

    def set_following(self, *, follow: bool) -> None:
        """Turn the tail on or off, from the status bar or the keyboard.

        Turning it back on lets go of the selected row as well as returning to
        the end: asking to watch the newest records is not asking to keep one
        old record open while they race past. That is what the second press of
        `Go to Bottom` does, for the same reason.
        """
        self._user_scrolled = False
        self._at_bottom = follow
        if follow:
            self._table.clearSelection()
            self._table.setCurrentIndex(QModelIndex())
        self.changed.emit()
        if follow:
            self._table.scrollToBottom()

    def set_model(self, model: RecordModel) -> None:
        """A new capture or a newly opened file built a new model.

        The tail starts on with it: a window that opened a file with follow
        already off would show the top of it and no indication why.
        """
        self._model = model
        self._at_bottom = True

    # ------------------------------------------------------------------
    # Every tick
    # ------------------------------------------------------------------

    def tick(self) -> None:
        """Stay at the bottom, but only if that is where the user already is."""
        if self._user_scrolled:
            # Read once, when a person has just moved the view. Reading it on
            # every tick instead is what broke this: appending raises the
            # maximum and leaves the value alone, so a view that had simply not
            # been scrolled *yet* -- or one whose scroll had just been skipped
            # by the throttle below -- looked exactly like a reader who had gone
            # up, and follow died on the first batch and stayed dead.
            bar = self._table.verticalScrollBar()
            self._at_bottom = bar.value() >= bar.maximum() - FOLLOW_SLACK
            self._user_scrolled = False
        self.changed.emit()
        if self._model.rowCount() == 0 or not self.following:
            return
        if self._scrolled.isValid() and self._scrolled.elapsed() < self.min_ms:
            return
        self._scrolled.restart()
        self._table.scrollToBottom()
