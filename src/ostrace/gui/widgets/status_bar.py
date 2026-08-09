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

from PySide6.QtWidgets import QLabel, QStatusBar, QToolButton

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from ostrace.model import DeviceInfo

__all__ = ["FOLLOWING", "NOT_FOLLOWING", "StatusBar"]

#: Shown before anything has been captured, so the fields have a resting state
#: rather than appearing from nowhere on the first record.
_IDLE = "idle"
_NO_DEVICE = "no device"

#: The tail control says which state it is in rather than what pressing it
#: would do. A button labelled with its action has to be read together with
#: something else to know what is happening now, and "am I still seeing the
#: newest records" is a question asked at a glance.
FOLLOWING = "Following"
NOT_FOLLOWING = "Not following"


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
        self._shown = QLabel("", self)
        self._volume = QLabel("0 records", self)
        self._gaps = QLabel("", self)

        #: Whether the view is still showing the newest records, and the way
        #: back when it is not.
        #:
        #: `docs/design/gui.md` §4 asked for this indicator and phase 4 did not
        #: build it, which left the state derived correctly and shown nowhere:
        #: clicking a row stops the tail on purpose, and the only ways back
        #: were a key nobody had been told about and a menu item two levels
        #: down. Logcat, Wireshark, DebugView and klogg all carry the same
        #: control, and all four put the state on it rather than the verb.
        self.follow = QToolButton(self)
        self.follow.setCheckable(True)
        self.follow.setAutoRaise(True)
        self.follow.setToolTip("Keep the view on the newest records")

        # addPermanentWidget puts these at the right and keeps them there when
        # a transient message is posted on the left, which is what showMessage
        # is for. A readout that a status message can push off the bar is not
        # a readout.
        for widget in (self._rate, self._device, self._shown, self._volume, self._gaps):
            self.addPermanentWidget(widget)
        # Last, so it sits at the end of the bar where the view's own bottom
        # is, which is what it is about.
        self.addPermanentWidget(self.follow)

        self.set_gap_count(0)
        self.set_following(following=True)

    def set_following(self, *, following: bool) -> None:
        """Show whether the tail is being followed.

        ``setChecked`` does not emit ``clicked``, which is the signal this
        control is read through, so syncing it from derived state cannot be
        mistaken for a person pressing it. That distinction is the one this
        project has already got wrong twice with ``toggled``.
        """
        self.follow.setChecked(following)
        self.follow.setText(FOLLOWING if following else NOT_FOLLOWING)

    @property
    def follow_text(self) -> str:
        return self.follow.text()

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

    def set_shown(self, shown: int, retained: int) -> None:
        """How much of what is held is actually on screen.

        The one number every competing tool is missing and the one whose absence
        produces the recurring "where did my logs go". Wireshark has said
        ``Displayed: N`` for twenty years; Console, Xcode and Logcat say nothing,
        so a filter that is one character too narrow looks exactly like a device
        that stopped talking.

        ``hidden_by_filter`` has been on the model since it was written and
        nothing in the application ever read it.

        Silent when nothing is hidden: a count that is always there teaches the
        eye to skip it, and unlike the gap count there is no ambiguity to guard
        against -- "hiding nothing" and "not filtering" are the same state.
        """
        self._shown.setText("" if shown == retained else f"{shown:,} of {retained:,} shown")

    @property
    def shown_text(self) -> str:
        return self._shown.text()

    def set_gap_count(self, gaps: int) -> None:
        """Always rendered -- see the module docstring."""
        self._gaps.setText(f"{gaps:,} gap" if gaps == 1 else f"{gaps:,} gaps")

    @property
    def gap_text(self) -> str:
        return self._gaps.text()
