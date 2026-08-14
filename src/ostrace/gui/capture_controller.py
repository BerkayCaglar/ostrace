# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Running a live capture: the thread, the pump, and letting go of the device.

The window used to own this, interleaved with the sentences it says about it,
and the two are different jobs. What is here is mechanism -- start the thread,
drain the queue, wait, park what will not stop, join it later. What is not here
is a single word a user reads: the banners, the title, the placeholder and the
enable/disable fan-out all stay on the window, which is the only thing that
knows how to say them.

**One structural rule holds this together: the pump outlives the thread, never
the reverse.** The thread produces into a `deque` and the pump drains it, so a
pump torn down while the thread still runs leaves records accumulating in a
queue nobody reads -- against a device delivering 1,600 records a second. That
is why a stop-timeout parks the thread and leaves the pump running, and why
`shutdown` waits for the thread before letting go of either.

The reconnect loop, gap synthesis, dedupe and every socket mechanic stay in
`OsTraceSource` and `capture()`. The command line needs them identically and
they are provable without Qt, which is where they are proved.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from ostrace.gui.live import CaptureThread
from ostrace.gui.pump import Pump
from ostrace.sources.base import CaptureState

if TYPE_CHECKING:
    from pathlib import Path

    from ostrace.gui.models import RecordModel
    from ostrace.sources.base import LogSource

__all__ = ["STOP_TIMEOUT_MS", "CaptureController", "Lifecycle"]

#: How long Disconnect waits for the capture to let go before parking it.
#: Bounded because the capture's own teardown is a socket close, not a network
#: round trip -- and waiting at all is what stops a second capture starting
#: while the first still holds the device.
STOP_TIMEOUT_MS = 5_000


class Lifecycle(Enum):
    """Where a capture is, as one value.

    Distinct from :class:`~ostrace.sources.base.CaptureState`, and the names
    say why: that one is what the *device link* is doing, reported by the
    source; this is what the *capture* is doing, which includes states no link
    has -- being parked, or never having started.

    A plain ``Enum`` rather than a ``StrEnum``: nothing carries this across a
    ``Signal(str)``, so there is no conversion to survive.
    """

    IDLE = auto()
    STARTING = auto()
    IDENTIFIED = auto()
    STREAMING = auto()
    RECONNECTING = auto()
    STOPPING = auto()
    #: The thread outlived the stop wait. The device is still held.
    PARKED = auto()


class CaptureController(QObject):
    """Owns a live capture: the thread that runs it and the pump that drains it."""

    #: Where the capture is now. Carries a :class:`Lifecycle`.
    state_changed = Signal(object)
    #: The device answered. Carries a :class:`~ostrace.model.DeviceInfo`.
    identified = Signal(object)
    #: The session file is finished and complete. Carries its ``Path``, or
    #: ``None`` when the capture was cancelled before it opened one.
    #:
    #: A path rather than an opened capture: opening it can fail, and what a
    #: reader is told when it does is a sentence, which belongs to the window.
    session_at = Signal(object)
    #: The capture died. Carries the reason, unwrapped.
    failed = Signal(str)
    #: The capture ended by itself -- the device was unplugged, or a limit was
    #: reached.
    finished = Signal()
    #: Records a second, from the pump.
    rate_changed = Signal(float)
    #: The paused queue overflowed, with how many records were dropped from the
    #: *view*. They are in the session file.
    overflowed = Signal(int)
    #: How many records are waiting behind a paused view, each tick.
    buffered = Signal(int)

    def __init__(self, model: RecordModel, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._model = model
        self._thread: CaptureThread | None = None
        self._pump: Pump | None = None
        self._state = Lifecycle.IDLE
        #: Threads that outlived their stop wait, each with the pump that was
        #: draining it. Both are held: see the rule in the module docstring.
        self._parked: list[tuple[CaptureThread, Pump | None]] = []

    # ------------------------------------------------------------------
    # What a caller can ask without waiting
    # ------------------------------------------------------------------

    @property
    def state(self) -> Lifecycle:
        return self._state

    @property
    def is_running(self) -> bool:
        """Whether a capture is under way, read without waiting for anything."""
        return self._thread is not None

    @property
    def path(self) -> Path | None:
        """Where the session is being written, or ``None`` if not capturing.

        A plain attribute read, deliberately. The export snapshot asks this
        immediately after joining the capture thread, and a queued signal would
        need an event loop that the joiner is not running.
        """
        return self._thread.path if self._thread is not None else None

    def set_model(self, model: RecordModel) -> None:
        """Point the next capture at a different model.

        The window replaces its model whenever a capture is opened or started,
        and the pump is built against whichever one is current at that moment.
        """
        self._model = model

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(
        self,
        source: LogSource,
        *,
        destination: Path | None = None,
        duration: float | None = None,
        max_records: int | None = None,
    ) -> None:
        """Begin capturing from ``source``.

        Stops whatever was running first: two captures cannot hold one device,
        and the second would fail on a busy relay rather than replace the first.

        The limits are passed through rather than enforced here. A controller
        that counted records itself would be a second implementation of
        something `capture` already does correctly on the one thread that can
        see the stream -- and it would stop the *view* while the device kept
        talking, which is the shape of the memory bug this class exists to
        prevent rather than to reproduce.
        """
        self.stop()

        thread = CaptureThread(
            source, destination=destination, duration=duration, max_records=max_records
        )
        pump = Pump(thread.queue, self._model, parent=self)
        pump.rate_changed.connect(self.rate_changed)
        pump.overflowed.connect(self.overflowed)
        pump.buffered.connect(self.buffered)
        thread.identified.connect(self._on_identified)
        thread.failed.connect(self._on_failed)
        thread.completed.connect(self._on_completed)

        self._thread = thread
        self._pump = pump
        self._advance(Lifecycle.STARTING)
        thread.start()
        pump.start()

    def stop(self) -> None:
        """Release the device, and say where the session went.

        Idempotent: called again with nothing running it does nothing at all,
        which is what lets every path that winds a capture down -- Disconnect,
        a failure, the end of the stream, closing the window -- go through this
        one door.
        """
        thread = self._thread
        if thread is None:
            return
        self._thread = None
        self._advance(Lifecycle.STOPPING)

        thread.stop()
        if thread.wait(STOP_TIMEOUT_MS):
            # Only once it has really ended: until then the session file is
            # still being written and the sidecar is not finalised.
            self._release(self._pump)
            self._pump = None
            self.session_at.emit(thread.path)
            thread.deleteLater()
            self._advance(Lifecycle.IDLE)
            return

        self._park(thread, self._pump)
        self._pump = None

    def link_state(self, state: CaptureState) -> None:
        """What the source says the device link is doing, while it happens.

        Handed in rather than subscribed to, because the source is built by the
        window -- which is where the choice of *which* device belongs -- and
        this object never names a concrete source.
        """
        if not self.is_running:
            # A late notification from a capture that has already been let go
            # of. Recording it would move the lifecycle backwards.
            return
        if state == CaptureState.RECONNECTING:
            self._advance(Lifecycle.RECONNECTING)
        elif state == CaptureState.STREAMING:
            self._advance(Lifecycle.STREAMING)

    def set_paused(self, paused: bool) -> None:
        """Freeze the view. The device is not consulted."""
        if self._pump is not None:
            self._pump.set_paused(paused)

    def shutdown(self) -> None:
        """Let go of everything, waiting once more on anything parked.

        Called when the window closes. A ``QThread`` still running when Python
        drops its last reference aborts the process -- measured here as exit
        ``0xC0000409`` with nothing printed -- so the last thing this object
        does is give each parked thread one more bounded wait.

        **The wait can fail, and then the thread stays parked.** This used to
        clear the list unconditionally, which threw away the last reference to a
        running thread and did the exact thing `_park` exists to prevent: a
        wait that timed out was treated as a wait that succeeded. It is
        `_reap` that knows the difference, so this waits and then asks it,
        rather than keeping a second copy of the rule that disagrees with the
        first.

        Releasing the pumps unconditionally was the same mistake seen from the
        other side. A pump let go while its thread is still producing leaves
        the queue growing with nothing bounding it, which is the rule this file
        exists to keep, stated backwards.
        """
        self.stop()
        for thread, _pump in self._parked:
            thread.wait(STOP_TIMEOUT_MS)
        self._reap()

    # ------------------------------------------------------------------
    # Parking
    # ------------------------------------------------------------------

    def _park(self, thread: CaptureThread, pump: Pump | None) -> None:
        """Keep a capture thread that outlived the stop wait, and its pump.

        The wait is bounded so a device that will not let go cannot freeze the
        window, which means it can time out -- and clearing the reference would
        then drop the last one to a *running* ``QThread``. That is not a leak:
        Qt's destructor calls ``qFatal`` on a running thread, so the window
        would not report a stuck capture, it would take the process down.

        **The pump is parked with it, running and paused**, rather than stopped.
        The thread is still producing into the queue, and a stopped pump leaves
        those records accumulating in memory with nothing bounding them. Paused,
        the pump keeps its own bound and evicts with the notice the model
        already knows how to make -- which is the honest answer: those records
        are in the session file, and no longer in the view.
        """
        self._parked.append((thread, pump))
        if pump is not None:
            pump.set_paused(paused=True)
        # Queued, because this object lives on the GUI thread and the signal is
        # emitted on the capture's: the thread is disposed of by this thread
        # once the other has genuinely ended, never from inside its own `run`.
        thread.finished.connect(self._reap)
        self._advance(Lifecycle.PARKED)

    def _reap(self) -> None:
        """Let go of every parked capture that has actually finished."""
        still_running: list[tuple[CaptureThread, Pump | None]] = []
        for thread, pump in self._parked:
            if thread.isRunning():
                still_running.append((thread, pump))
                continue
            # The thread has stopped producing, so the pump can take what is
            # left and go -- in that order, which is the rule this file exists
            # to keep.
            self._release(pump)
            thread.deleteLater()
        self._parked = still_running
        if not self._parked and self._state is Lifecycle.PARKED:
            self._advance(Lifecycle.IDLE)

    @staticmethod
    def _release(pump: Pump | None) -> None:
        """Final-drain a pump and let it go.

        `Pump.stop` takes whatever is already queued before it stops draining:
        those records were captured, and dropping them at the moment the user
        pressed Disconnect would make the end of the view disagree with the end
        of the file.
        """
        if pump is None:
            return
        pump.stop()
        pump.deleteLater()

    # ------------------------------------------------------------------
    # What the thread reports
    # ------------------------------------------------------------------

    def _advance(self, state: Lifecycle) -> None:
        """Move to ``state`` and say so, once.

        Silent when nothing changed: the window's handler fans out to six
        controls, a title and a placeholder, and repeating that on every
        arriving batch would be work nobody asked for.
        """
        if state is self._state:
            return
        self._state = state
        self.state_changed.emit(state)

    def _on_identified(self, device: object) -> None:
        self._advance(Lifecycle.IDENTIFIED)
        self.identified.emit(device)

    def _on_failed(self, message: str) -> None:
        """The capture died. Wind down as if Disconnect had been pressed,
        because from here on nothing is going to press it."""
        self.stop()
        self.failed.emit(message)

    def _on_completed(self, result: object) -> None:
        """The capture ended by itself.

        The same wind-down, for the same reason: the pump is still draining a
        stream that has stopped, and the session on disk is finished and worth
        picking up. The thread has already ended by the time this queued signal
        arrives, so the wait inside `stop` returns at once.
        """
        del result  # `stop` reads the path off the thread, which is the same one
        self.stop()
        self.finished.emit()
