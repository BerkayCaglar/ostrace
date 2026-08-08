# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The status bar: rate, device, size, and the gap count.

The gap count is rendered **always, including when it is zero**. Wireshark bug
12005 is the reason: a `Dropped` counter shown only when non-zero regressed to
never being shown, and nobody could tell "no drops" from "the counter broke".
A number that is always present is falsifiable; one that appears only on bad
news is indistinguishable from a bug.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QLabel, QStatusBar

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from ostrace.model import DeviceInfo

__all__ = ["StatusBar"]

#: Shown before anything has been captured, so the fields have a resting state
#: rather than appearing from nowhere on the first record.
_IDLE = "idle"
_NO_DEVICE = "no device"


class StatusBar(QStatusBar):
    """Four independent readouts, each owning one fact."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizeGripEnabled(False)
        # Without a right margin the last readout sits flush against the window
        # edge and loses its final character to the frame -- which is how "0
        # gaps" renders as "0 gap", the one reading that must never be wrong.
        self.setContentsMargins(6, 0, 8, 0)

        self._rate = QLabel(_IDLE, self)
        self._device = QLabel(_NO_DEVICE, self)
        self._volume = QLabel("0 records", self)
        self._gaps = QLabel("", self)

        # addPermanentWidget puts these at the right and keeps them there when
        # a transient message is posted on the left, which is what showMessage
        # is for. A readout that a status message can push off the bar is not
        # a readout.
        for widget in (self._rate, self._device, self._volume, self._gaps):
            self.addPermanentWidget(widget)

        self.set_gap_count(0)

    def set_rate(self, records_per_second: float | None) -> None:
        """Live throughput, or ``None`` when nothing is streaming."""
        if records_per_second is None:
            self._rate.setText(_IDLE)
        else:
            self._rate.setText(f"{records_per_second:,.0f} rec/s")

    def set_device(self, device: DeviceInfo | None) -> None:
        self._device.setText(_NO_DEVICE if device is None else device.label)

    def set_volume(self, records: int, bytes_on_disk: int | None = None) -> None:
        text = f"{records:,} records"
        if bytes_on_disk is not None:
            text += f" · {bytes_on_disk / 1_000_000:,.1f} MB"
        self._volume.setText(text)

    def set_gap_count(self, gaps: int) -> None:
        """Always rendered -- see the module docstring."""
        self._gaps.setText(f"{gaps:,} gap" if gaps == 1 else f"{gaps:,} gaps")

    @property
    def gap_text(self) -> str:
        return self._gaps.text()
