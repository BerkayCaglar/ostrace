# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every field of the selected record, including the ones the table cannot fit.

The table shows six of `Record`'s eleven fields. This shows all of them, and
it is where two of this project's less obvious invariants finally become
visible to a human:

- **The device's clock, and its offset.** A timestamp carries the *device's*
  UTC offset, because the host is a different clock in a frequently different
  zone, and the offset is shown as a field of its own so the rule is visible
  rather than implied.

  The host clock joins it only for a *live* capture, where the two are
  readings of the same moment -- lnav's overlay content model. Reading a file,
  there is no second reading: a record captured this morning is not "36,000
  seconds out", it is from this morning, and calling that a clock difference
  would invent a problem the device does not have.
- **`process_path` and `image_path` are different things.** `filename` is the
  process executable and `image_name` is the library loaded into it; they read
  backwards and differ in about nine records in ten.

**The shape is two columns and a message block**, which is a correction. It was
a single-column form of twelve short rows, and against a real window that reads
as a mostly empty panel with a wall of labels down the left: the message -- the
one field with anything to say -- got the same narrow strip as ``PID``, and the
rest of the width was nothing at all. The fields are short and the message is
long, so they are laid out as what they are.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ostrace.gui.fonts import monospace
from ostrace.gui.markers import Eviction
from ostrace.model import Gap, Record

if TYPE_CHECKING:
    from datetime import datetime

    from PySide6.QtGui import QResizeEvent

__all__ = ["DetailPane"]

#: What an absent optional field reads as. The same spelling the exporters use,
#: so a value copied out of here matches what a bundle would contain.
ABSENT = "-"

#: How many field columns the grid has. Two, because the fields are short: at
#: one column a dozen of them leave most of the pane empty and push the message
#: below the fold, and at three the labels stop lining up with anything.
_COLUMNS = 2

#: Between a label and its value, and between the two columns.
_GAP = 10


class DetailPane(QScrollArea):
    """A read-only form. Selectable text, because the point is to copy from it."""

    #: The close control was pressed. The window turns this into a deselect,
    #: rather than the pane hiding itself: a pane that can disappear is a pane
    #: the user has to discover how to get back.
    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)

        self._body = QWidget(self)
        self._root = QVBoxLayout(self._body)
        self._root.setSpacing(_GAP)
        self.setWidget(self._body)

        self._title = QLabel(self._body)
        self._title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._close = QToolButton(self._body)
        self._close.setText("✕")
        self._close.setAutoRaise(True)
        self._close.setToolTip("Close this record (Esc)")
        self._close.clicked.connect(self.closed)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self._title, stretch=1)
        header.addWidget(self._close)
        self._root.addLayout(header)

        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(_GAP)
        self._grid.setVerticalSpacing(2)
        # The value columns take the width; the label columns take what their
        # text needs. Without this the four columns divide the pane evenly and
        # `PID` is given as much room as a process path.
        for column in range(_COLUMNS):
            self._grid.setColumnStretch(column * 2 + 1, 1)
        self._root.addLayout(self._grid)

        self._message_heading = QLabel("Message", self._body)
        self._message = QLabel(self._body)
        self._message.setFont(monospace())
        self._message.setWordWrap(True)
        self._message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._message.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._message.setFrameShape(QFrame.Shape.StyledPanel)
        self._message.setMargin(_GAP // 2)
        # `setWordWrap` is what turns a label's height-for-width on, by editing
        # its size policy. Replacing that policy afterwards -- which an explicit
        # `setSizePolicy` does -- switches it back off, and a message block that
        # does not report a height for its width is given one line's worth and
        # clips the rest. Set the flag on the policy the label already has.
        policy = self._message.sizePolicy()
        policy.setVerticalPolicy(QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        self._message.setSizePolicy(policy)
        self._root.addWidget(self._message_heading)
        self._root.addWidget(self._message)
        self._root.addStretch(1)

        self._rows: dict[str, QLabel] = {}
        self.clear()

    # -- building --------------------------------------------------------

    def _set(
        self,
        fields: list[tuple[str, str]],
        *,
        title: str = "",
        message: str | None = None,
    ) -> None:
        """Rebuild the pane. Called on selection, which is a human action."""
        self._title.setText(title)
        self._close.setVisible(bool(title))
        self._fill(fields)

        self._message.setText(message or "")
        self._message.setVisible(message is not None)
        self._message_heading.setVisible(message is not None)
        if message is not None:
            self._rows["Message"] = self._message

        self._fit_body()

    def _fill(self, fields: list[tuple[str, str]]) -> None:
        """Lay the label/value pairs out down one column and then the next.

        Column-major rather than row-major: the pairs arrive in a meaningful
        order -- the clock fields together, then what emitted the record -- and
        reading left-to-right across two columns would interleave them.
        """
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                # Hidden as well as deleted, and the hiding is the load-bearing
                # half. `takeAt` removes the row from the *layout*, which stops
                # the layout positioning it and nothing else; `deleteLater`
                # then defers the destruction to whenever the event loop next
                # drains. In between, the widget is still a visible child at
                # its old geometry, painting straight over the rows that
                # replaced it. An interactive session hides that -- the loop
                # drains before the next paint -- but anything that rebuilds
                # and renders in one pass sees it, which is every `grab()` in
                # the suite and `tools/capture_screens.py`, whose entire job is
                # to show what this looks like on macOS.
                widget.hide()
                widget.deleteLater()
        self._rows.clear()

        per_column = -(-len(fields) // _COLUMNS)  # ceiling, so the last column is the short one
        for index, (name, value) in enumerate(fields):
            row, column = (index % per_column, index // per_column) if per_column else (0, 0)
            label = QLabel(f"{name}:", self._body)
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            shown = QLabel(value, self._body)
            shown.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            shown.setWordWrap(True)
            self._grid.addWidget(label, row, column * 2)
            self._grid.addWidget(shown, row, column * 2 + 1)
            # Shown explicitly, and this is load-bearing rather than tidy. A
            # widget added to the layout of an already-visible parent is not
            # made visible until the event loop next runs, and a layout ignores
            # a hidden item entirely: `QGridLayout.hasHeightForWidth` was
            # therefore false and `heightForWidth` returned -1, so the height
            # computed for the pane a line later left the whole grid out of it.
            # Measured: 189 pixels for contents that need 433.
            label.show()
            shown.show()
            self._rows[name] = shown

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_body()

    def _fit_body(self) -> None:
        """Give the contents the height their wrapped text actually needs.

        A word-wrapped `QLabel` reports a minimum height of about one line,
        because it can always wrap harder. Inside a scroll area that is taken
        as permission to compress: the pane squeezes the form below the height
        its text needs and the rows overlap and clip, instead of the scroll
        area doing what a scroll area is for.

        Asking the layout for its ``heightForWidth`` at the viewport's width
        turns "how short could this be" into "how tall is this actually", which
        is the question a scrollable pane needs answered.

        ``activate()`` first, because the question is asked immediately after
        the rows are replaced and a layout answers it from what it last laid
        out. Without it the pane sizes the new record against the *previous*
        one's height -- measured, twelve fields given 8 pixels each where they
        need 16, so every row rendered as its own top half.

        The other half of that is in `_fill`, which has to *show* the rows it
        adds: a layout skips hidden items, so an unshown grid reports no
        height-for-width at all and this measures the pane without it.
        """
        width = self.viewport().width()
        if width <= 0:
            return
        # Invalidate before activating, and the *nested* layout as well as the
        # root. A layout caches what it last worked out, and `activate()` alone
        # recomputes the root from children that are still holding cached
        # answers for the rows they had a moment ago -- measured here as 189
        # pixels where the same call returns 433 one event loop later, which
        # renders every row as its own top half. The single-layout version of
        # this pane needed only `activate()`; the two-layer one needs both.
        self._root.activate()
        needed = self._root.heightForWidth(width)
        if needed > 0:
            self._body.setMinimumHeight(needed)

    # -- what to show ----------------------------------------------------

    def clear(self) -> None:
        self._set([("Nothing selected", "Select a record to see every field of it.")])

    def show_record(self, record: Record, host_now: datetime | None = None) -> None:
        """Display one record.

        ``host_now`` is for a *live* capture, where the host's clock and the
        device's are two readings of the same moment and the difference between
        them is worth seeing. It is deliberately not supplied when reading a
        file: a record captured this morning is not "36,000 seconds out", it is
        simply from this morning, and presenting that as a clock difference
        would invent a problem the device does not have.

        The device's UTC offset is shown either way, because that is the fact
        this project's timestamp rule turns on and it is true of a saved
        capture as much as of a live one.
        """
        fields: list[tuple[str, str]] = [
            ("Device time", f"{record.timestamp:%Y-%m-%d %H:%M:%S.%f%z}"),
            ("Device UTC offset", _offset(record.timestamp)),
        ]
        if host_now is not None:
            delta = record.timestamp - host_now
            fields.append(("Host time", f"{host_now:%Y-%m-%d %H:%M:%S.%f%z}"))
            fields.append(("Difference", f"{delta.total_seconds():+.3f} s"))

        fields += [
            ("Level", record.level.title),
            ("Process", record.process),
            ("PID", str(record.pid)),
            ("Process path", record.process_path or ABSENT),
            ("Subsystem", record.subsystem or ABSENT),
            ("Category", record.category or ABSENT),
            ("Thread", str(record.thread_id) if record.thread_id is not None else ABSENT),
            ("Image", record.image_path or ABSENT),
            ("Platform", record.platform.display_name),
        ]
        self._set(
            fields,
            title=f"{record.level.title} · {record.process_label}",
            message=record.message,
        )

    def show_gap(self, gap: Gap) -> None:
        """Display a gap.

        A gap gets the same treatment as a record rather than an apologetic
        aside, because what is missing is as much a fact about the capture as
        what is present.
        """
        self._set(
            [
                ("Gap start", f"{gap.start:%Y-%m-%d %H:%M:%S.%f%z}"),
                ("Gap end", f"{gap.end:%Y-%m-%d %H:%M:%S.%f%z}"),
                ("Duration", f"{gap.duration.total_seconds():,.3f} s"),
                ("Reason", gap.reason),
                (
                    "Recoverable",
                    (
                        "No. Records the device emitted during this window were "
                        "never received and nothing buffers them."
                    ),
                ),
            ],
            title="Gap in the capture",
        )

    def show_eviction(self, eviction: Eviction) -> None:
        """Display the view's own trimming.

        Deliberately worded against `show_gap`. The two look alike in a table
        and mean opposite things, and this is the pane where the difference has
        room to be stated rather than implied: the records are still in the
        capture, and there is somewhere to go and read them.
        """
        self._set(
            [
                ("Records not shown", f"{eviction.count:,}"),
                ("Visible log starts after", f"{eviction.through:%Y-%m-%d %H:%M:%S.%f%z}"),
                (
                    "Recoverable",
                    (
                        "Yes. These records are in the capture on disk; the view "
                        "holds a bounded number of rows and dropped its oldest. "
                        "Export the capture, or open it again, to read them."
                    ),
                ),
            ],
            title="Trimmed from the view",
        )

    def show_item(self, item: Record | Gap | Eviction, host_now: datetime | None = None) -> None:
        """Display whichever kind of row this is."""
        if isinstance(item, Gap):
            self.show_gap(item)
        elif isinstance(item, Eviction):
            self.show_eviction(item)
        else:
            self.show_record(item, host_now)

    def field(self, name: str) -> str | None:
        """The displayed value of one field, or ``None`` if it is not shown."""
        label = self._rows.get(name)
        return label.text() if label is not None else None


def _offset(moment: datetime) -> str:
    """The UTC offset a timestamp carries, spelled out.

    A naive timestamp is rejected on read rather than guessed at, so this
    should never be ``ABSENT`` -- but it says so rather than crashing if one
    ever gets through, because a detail pane that raises is worse than one
    that admits it does not know.
    """
    delta = moment.utcoffset()
    if delta is None:
        return ABSENT
    total = int(delta.total_seconds())
    sign = "+" if total >= 0 else "-"
    hours, remainder = divmod(abs(total), 3600)
    return f"UTC{sign}{hours:02d}:{remainder // 60:02d}"
