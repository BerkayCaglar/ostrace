# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading a capture into the model without freezing the window.

A capture is routinely hundreds of thousands of records. Reading one in a
single pass holds the GUI thread for the whole read: no repaint, no scrolling,
no cancel, and on Windows the title bar goes grey and the operating system
offers to close the program.

So it is read in batches from a zero-delay `QTimer`, which hands control back
to the event loop between them. No thread and no lock -- the reader and the
model both live on the GUI thread and never touch each other concurrently.
That is the right shape for a file, which is fast and finite; a *device* is
neither, and phase 4's live path uses a producer thread and a queue instead.

The batch size is a trade between the two things that go wrong: too small and
the timer overhead dominates the read, too large and one batch is long enough
to be felt as a stutter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal

from ostrace.errors import OstraceError

if TYPE_CHECKING:
    from ostrace.gui.markers import Row
    from ostrace.gui.models import RecordModel
    from ostrace.storage.capture import Capture

__all__ = ["BATCH_SIZE", "CaptureLoader"]

#: Records per batch. At the ~1,600/s a device delivers, this is a couple of
#: seconds of log per tick -- fast enough that a large file finishes quickly,
#: small enough that no single batch is visible as a pause.
BATCH_SIZE = 2048


class CaptureLoader(QObject):
    """Feed a capture into a model, a batch at a time."""

    #: Records read so far. Emitted per batch, not per record.
    progressed = Signal(int)
    finished = Signal()
    #: A message fit to show a user, not a traceback.
    failed = Signal(str)

    def __init__(
        self,
        capture: Capture,
        model: RecordModel,
        *,
        batch_size: int = BATCH_SIZE,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.capture = capture
        self.model = model
        self.batch_size = batch_size
        self.loaded = 0

        self._items = capture.items()
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._step)

    def start(self) -> None:
        self._timer.start()

    def cancel(self) -> None:
        """Stop reading. What was already loaded stays loaded.

        A half-read capture is not a failure state: the records that arrived
        are as true as they would have been at the end, and the user asked for
        the reading to stop rather than for the rows to go away.
        """
        self._timer.stop()

    def _step(self) -> None:
        batch: list[Row] = []
        try:
            # Pulled one at a time on purpose, rather than with `islice` or a
            # comprehension. Both would discard the records already read when
            # the next line raises -- and a capture that ends badly is exactly
            # the case a log viewer exists to look at, so the good records
            # before the bad line are the ones that matter most.
            for _ in range(self.batch_size):
                batch.append(next(self._items))  # noqa: PERF401
        except StopIteration:
            self._timer.stop()
            self._flush(batch)
            self.finished.emit()
            return
        except OstraceError as exc:
            # A corrupt or truncated capture. Whatever was read before the bad
            # line is real and is kept -- the alternative is discarding good
            # records because the file ends badly, which is exactly the case a
            # log viewer exists to look at.
            self._timer.stop()
            self._flush(batch)
            self.failed.emit(str(exc))
            return

        self._flush(batch)

    def _flush(self, batch: list[Row]) -> None:
        if not batch:
            return
        self.model.append(batch)
        self.loaded += len(batch)
        self.progressed.emit(self.loaded)
