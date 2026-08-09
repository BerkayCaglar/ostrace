# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Draining the capture queue into the model, on the GUI thread.

One timer, one batch, one ``beginInsertRows``. At 1,600 records a second a
50 ms tick is about eighty rows per batch and twenty model updates a second --
against sixteen hundred if each record were inserted on arrival. Never one
signal per record.

**Pause freezes this and nothing else.** It does not touch the capture thread,
the device, or the session file. That distinction is not stylistic here: this
project already learned that releasing a device releases the lockdown session
*and* the ``os_trace_relay`` service together, so a pause that reached the
source would be a disconnect wearing a friendlier label, and everything that
arrived during it would be gone. Paused, the capture keeps running and keeps
writing every record to disk.

What a long pause cannot do is hold every record in memory, so the queue is
bounded while paused. When the bound bites, the oldest are dropped from the
*view* -- and they are still in the capture file, which is why they are
announced as an eviction and not as a gap. The two look alike on screen and
mean opposite things.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from PySide6.QtCore import QElapsedTimer, QObject, QTimer, Signal

from ostrace.model import Record

if TYPE_CHECKING:
    from ostrace.gui.markers import Row
    from ostrace.gui.models import RecordModel

__all__ = ["PAUSE_LIMIT", "RATE_WINDOW_MS", "TICK_MS", "Pump"]

#: Drain interval. Twenty updates a second reads as continuous, and is few
#: enough that the model work per second is bounded by the tick rather than by
#: how talkative the device is.
TICK_MS = 50

#: How long a window the rate is averaged over.
#:
#: A device does not deliver evenly. It hands over a batch and then says nothing
#: for several ticks, so the rate computed from a single 50 ms tick is **zero**
#: more often than it is anything else -- and a readout that spends most of its
#: time on 0 while a capture is plainly streaming is worse than no readout,
#: because it is not obviously broken. It reads as the device having stopped.
#:
#: One second is also the unit the label is spelled in. "1,200 rec/s" derived
#: from a twentieth of a second is a projection; derived from the last second it
#: is a count, and the number on screen is one the user could have counted
#: themselves.
RATE_WINDOW_MS = 1_000

#: How many records may pile up while paused before the oldest are dropped from
#: the view. Generous -- about a minute of a busy device -- because the point of
#: pausing is to read something without losing your place, and a pause that
#: silently starts discarding after five seconds is not a pause.
PAUSE_LIMIT = 100_000


class Pump(QObject):
    """Move items from a capture queue into a model, in batches."""

    #: Records per second, recomputed each tick, for the status bar.
    rate_changed = Signal(float)
    #: Emitted when the paused queue overflowed, with how many were dropped.
    overflowed = Signal(int)

    def __init__(
        self,
        queue: deque[Row],
        model: RecordModel,
        *,
        interval_ms: int = TICK_MS,
        pause_limit: int = PAUSE_LIMIT,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.queue = queue
        self.model = model
        self.pause_limit = pause_limit
        self.paused = False
        self.delivered = 0

        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.drain)
        #: Measured rather than assumed. `QTimer` defaults to a coarse timer,
        #: and on Windows that snaps to the 15.625 ms scheduler tick: a 50 ms
        #: interval measured 62.5 ms. Deriving the rate from the nominal
        #: interval over-read a 1,600 rec/s device as 2,000.
        self._clock = QElapsedTimer()
        self._clock.start()
        #: ``(when, how many)`` per batch, kept for `RATE_WINDOW_MS`. A window
        #: rather than the last tick -- see that constant.
        self._samples: deque[tuple[int, int]] = deque()

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        """Stop draining, after taking whatever is already queued.

        A final drain rather than an abrupt one: those records were captured,
        and dropping them at the moment the user pressed stop would make the
        end of the view disagree with the end of the file.
        """
        self._timer.stop()
        self.paused = False
        self.drain()

    def set_paused(self, paused: bool) -> None:
        """Freeze or resume the *view*. The capture is not consulted."""
        self.paused = paused
        if not paused:
            self.drain()

    def drain(self) -> None:
        """Take everything queued and give it to the model in one batch."""
        if self.paused:
            self._enforce_pause_limit()
            return

        now = self._clock.elapsed()
        batch: list[Row] = []
        queue = self.queue
        while queue:
            batch.append(queue.popleft())

        if batch:
            self.model.append(batch)
            self.delivered += sum(1 for item in batch if isinstance(item, Record))
            self._samples.append((now, len(batch)))

        # Emitted on every tick, including the empty ones. An empty tick is not
        # a rate of zero -- it is one twentieth of a second in which nothing
        # happened to arrive -- but a *second* of them is, and letting the
        # window empty is how that gets said. A device that stops still reads
        # 0 rec/s a second later; it just no longer says so between bursts.
        self.rate_changed.emit(self._rate(now))

    def _rate(self, now: int) -> float:
        """Records a second, over the last `RATE_WINDOW_MS`."""
        horizon = now - RATE_WINDOW_MS
        while self._samples and self._samples[0][0] <= horizon:
            self._samples.popleft()
        if not self._samples:
            return 0.0
        # Before a full window has elapsed the divisor is what has actually
        # passed, or the first second of every capture would read low.
        span_ms = min(now, RATE_WINDOW_MS)
        return sum(count for _, count in self._samples) * 1000.0 / max(span_ms, 1)

    def _enforce_pause_limit(self) -> None:
        """Bound what a pause may hold, and say so when it bites."""
        excess = len(self.queue) - self.pause_limit
        if excess <= 0:
            return
        dropped = 0
        newest = None
        for _ in range(excess):
            item = self.queue.popleft()
            if isinstance(item, Record):
                dropped += 1
                newest = item.timestamp
        if dropped and newest is not None:
            # An eviction, not a gap: every one of these is in the session file
            # on disk. Saying "gap" would be the view lying about the capture.
            self.model.note_eviction(dropped, newest)
            self.overflowed.emit(dropped)
