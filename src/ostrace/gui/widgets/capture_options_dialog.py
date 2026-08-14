# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The four controls the command line has and the viewer did not.

`ostrace capture` takes ``--duration``, ``--max-records``, ``--no-reconnect``
and ``--output``. Everything but the last already reaches the capture unchanged
-- `ostrace.capture.capture` takes the two limits and `OsTraceSource` takes the
reconnect policy -- and ``--output`` reached `MainWindow.start_capture` as a
parameter nothing in the interface ever supplied.

**Nothing here is remembered between sessions**, and that is the same rule the
applied filter follows rather than an omission. A duration restored from
yesterday would stop today's capture after thirty seconds and look exactly like
a device that dropped off USB -- the "where did my logs go" failure with a
longer fuse. A capture that ends because of a limit says so when it ends, which
is the other half of the same care.

The dialog is a `QDialog` over a value. It holds no capture and starts none:
the window asks it for options and does what it likes with them, which is what
lets every rule here be tested without a device.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

__all__ = ["CaptureOptions", "CaptureOptionsDialog"]

#: The largest limit each spin box offers, and the value at which it reads as
#: "no limit" instead of a number. A spin box needs a maximum, and one that
#: silently capped a capture at whatever that maximum happened to be would be a
#: limit the user never asked for.
_MAX_SECONDS = 86_400.0
_MAX_RECORDS = 100_000_000


@dataclass(frozen=True, slots=True)
class CaptureOptions:
    """How the next capture should run. Every field is off by default."""

    #: Where the session goes. ``None`` leaves the decision to `paths`, which
    #: is the only module allowed to make it.
    destination: Path | None = None
    duration: float | None = None
    max_records: int | None = None
    #: Reconnect after an outage and record a `Gap`, rather than failing on the
    #: first one. On by default because that is what `ReconnectPolicy()` does
    #: and what a phone on a desk needs.
    reconnect: bool = True

    @property
    def is_default(self) -> bool:
        """Whether this would behave exactly as pressing Capture always has."""
        return (
            self.destination is None
            and self.duration is None
            and self.max_records is None
            and self.reconnect
        )

    @property
    def summary(self) -> str:
        """What is set, for the sentence a limited capture ends with."""
        parts = []
        if self.duration is not None:
            parts.append(f"{self.duration:g} seconds")
        if self.max_records is not None:
            parts.append(f"{self.max_records:,} records")
        if not self.reconnect:
            parts.append("no reconnect")
        if self.destination is not None:
            parts.append(f"into {self.destination}")
        return ", ".join(parts)


class CaptureOptionsDialog(QDialog):
    """Set the four, or leave them alone."""

    def __init__(self, options: CaptureOptions, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Capture options")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        # Each limit is a checkbox plus a value rather than a sentinel in the
        # value itself. A duration box reading `0` has to mean either "stop
        # immediately" or "no limit", and whichever is chosen the other reading
        # is the one somebody will expect.
        self.limit_duration = QCheckBox("Stop after", self)
        self.duration = QDoubleSpinBox(self)
        self.duration.setRange(0.1, _MAX_SECONDS)
        self.duration.setSuffix(" seconds")
        self.duration.setDecimals(1)
        self.duration.setValue(options.duration if options.duration is not None else 60.0)
        self.duration.setAccessibleName("Stop after this long")
        form.addRow(self.limit_duration, self.duration)

        self.limit_records = QCheckBox("Stop after", self)
        self.max_records = QSpinBox(self)
        self.max_records.setRange(1, _MAX_RECORDS)
        self.max_records.setSuffix(" records")
        self.max_records.setGroupSeparatorShown(True)
        self.max_records.setValue(
            options.max_records if options.max_records is not None else 100_000
        )
        self.max_records.setAccessibleName("Stop after this many records")
        form.addRow(self.limit_records, self.max_records)

        self.reconnect = QCheckBox("Reconnect after an outage, and record a gap", self)
        self.reconnect.setChecked(options.reconnect)
        form.addRow("", self.reconnect)

        self.destination = QLineEdit(self)
        self.destination.setPlaceholderText("a timestamped directory, chosen for you")
        self.destination.setText(str(options.destination) if options.destination else "")
        self.destination.setAccessibleName("Session directory")
        choose = QPushButton("Choose…", self)
        choose.clicked.connect(self._choose_destination)
        # Beside the field rather than under it, which reads as an unrelated
        # control -- the same correction the export dialog needed.
        row = QHBoxLayout()
        row.addWidget(self.destination)
        row.addWidget(choose)
        form.addRow("Write session to", row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.limit_duration.setChecked(options.duration is not None)
        self.limit_records.setChecked(options.max_records is not None)
        self.limit_duration.toggled.connect(self.duration.setEnabled)
        self.limit_records.toggled.connect(self.max_records.setEnabled)
        self.duration.setEnabled(self.limit_duration.isChecked())
        self.max_records.setEnabled(self.limit_records.isChecked())

    def _choose_destination(self) -> None:  # pragma: no cover - a modal file dialog
        chosen = QFileDialog.getExistingDirectory(self, "Write the session to")
        if chosen:
            self.destination.setText(chosen)

    def options(self) -> CaptureOptions:
        """What the controls are saying, as one value."""
        written = self.destination.text().strip()
        return CaptureOptions(
            destination=Path(written) if written else None,
            duration=self.duration.value() if self.limit_duration.isChecked() else None,
            max_records=self.max_records.value() if self.limit_records.isChecked() else None,
            reconnect=self.reconnect.isChecked(),
        )
