# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every field of the selected record, including the ones the table cannot fit.

The table shows six of `Record`'s thirteen fields. This shows all of them, and
it is where two of this project's less obvious invariants finally become
visible to a human:

- **Both clocks, and their difference.** A timestamp carries the *device's* UTC
  offset, because the host is a different clock in a frequently different zone.
  That rule is invisible until the two are on screen together, so this pane
  shows the device time, the host time and the delta -- lnav's overlay content
  model, applied to the field this project actually has.
- **`process_path` and `image_path` are different things.** `filename` is the
  process executable and `image_name` is the library loaded into it; they read
  backwards and differ in about nine records in ten.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QLabel, QScrollArea, QWidget

from ostrace.model import Gap, Record

if TYPE_CHECKING:
    from datetime import datetime

__all__ = ["DetailPane"]

#: What an absent optional field reads as. The same spelling the exporters use,
#: so a value copied out of here matches what a bundle would contain.
ABSENT = "-"


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

    def clear(self) -> None:
        self._set([("Nothing selected", "Select a record to see every field of it.")])

    def show_record(self, record: Record, host_now: datetime | None = None) -> None:
        """Display one record."""
        fields: list[tuple[str, str]] = [
            ("Device time", f"{record.timestamp:%Y-%m-%d %H:%M:%S.%f%z}"),
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

    def show_item(self, item: Record | Gap, host_now: datetime | None = None) -> None:
        """Display whichever of the two kinds this is."""
        if isinstance(item, Gap):
            self.show_gap(item)
        else:
            self.show_record(item, host_now)

    def field(self, name: str) -> str | None:
        """The displayed value of one field, or ``None`` if it is not shown."""
        label = self._rows.get(name)
        return label.text() if label is not None else None
