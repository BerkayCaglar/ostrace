# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every field of the selected record, including the ones the table cannot fit.

The table shows six of `Record`'s thirteen fields. This shows all of them, and
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
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QLabel, QScrollArea, QWidget

from ostrace.gui.markers import Eviction
from ostrace.model import Gap, Record

if TYPE_CHECKING:
    from datetime import datetime

    from PySide6.QtGui import QResizeEvent

__all__ = ["DetailPane"]

#: What an absent optional field reads as. The same spelling the exporters use,
#: so a value copied out of here matches what a bundle would contain.
ABSENT = "-"


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


class DetailPane(QScrollArea):
    """A read-only form. Selectable text, because the point is to copy from it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)

        self._body = QWidget(self)
        self._form = QFormLayout(self._body)
        self._form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self.setWidget(self._body)

        self._rows: dict[str, QLabel] = {}
        self.clear()

    def _set(self, fields: list[tuple[str, str]]) -> None:
        """Rebuild the form. Called on selection, which is a human action."""
        while self._form.rowCount():
            self._form.removeRow(0)
        self._rows.clear()
        for name, value in fields:
            label = QLabel(value, self._body)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setWordWrap(True)
            self._form.addRow(f"{name}:", label)
            self._rows[name] = label
        self._fit_body()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_body()

    def _fit_body(self) -> None:
        """Give the form the height its wrapped text actually needs.

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
        """
        width = self.viewport().width()
        if width <= 0:
            return
        self._form.activate()
        needed = self._form.heightForWidth(width)
        if needed > 0:
            self._body.setMinimumHeight(needed)

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
            ("Message", record.message),
        ]
        self._set(fields)

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
            ]
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
            ]
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
