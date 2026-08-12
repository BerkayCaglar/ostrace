# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which device a capture will come from, and how to choose another.

Until this existed the viewer captured from whichever device `list_devices`
returned first and never said which one that was -- `OsTraceSource` has always
taken a udid and nothing ever passed one. On a desk with a phone and an iPad
attached that is a coin toss the user cannot see, let alone lose.

Enumeration is the part that needs care. Listing devices is cheap; *identifying*
one is a lockdown session and a round trip, which on a sleeping device takes
long enough to freeze a toolbar. So the menu is built in two passes: the udids
appear immediately, and each row upgrades to a name when the identity arrives.

The scan never touches a device a capture is holding. Two lockdown sessions
against one device is not an error the library reports -- it is a stall, in the
generator the capture thread is blocked on.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QMenu, QToolButton

from ostrace.gui import icons
from ostrace.gui.theme import Scheme

if TYPE_CHECKING:
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QWidget

    from ostrace.devices.discovery import DeviceSummary
    from ostrace.model import DeviceInfo

__all__ = ["DeviceButton", "DeviceScanner"]

#: What the button says with nothing attached. Not an empty label: a control
#: with no text reads as a rendering fault rather than as an answer.
NO_DEVICE = "No device"

#: What it says when devices are attached and the user has not picked one.
#:
#: It used to name the first device found, on the reasoning that a capture
#: would use it and the name should therefore be on screen. That is true and it
#: is not worth what it cost: pressing the button to *see* the devices changed
#: the label to a device, which reads as the control having connected to it
#: rather than having answered a question. Opening a menu is not choosing from
#: it. What a capture is really using is named in the status bar, by the device
#: that answered, which is a better place for it -- it is a fact about the
#: capture rather than about this control.
CHOOSE = "Choose device"

#: What the menu holds while a scan is in flight. Its job is to exist: an
#: `InstantPopup` button whose menu has no actions pops up nothing at all, so a
#: press looked like a control that did not work -- and then the scan landed,
#: chose the first device and changed the label, which looked like a control
#: that had skipped its own menu. Both readings were of the same empty popup.
SCANNING = "Scanning…"

#: What it holds when the scan came back with nothing.
NONE_ATTACHED = "No device attached"

#: How long to wait for a scan to notice it was interrupted. It is blocked on a
#: socket read at worst, not on the network.
_SCAN_STOP_TIMEOUT_MS = 2_000


class DeviceScanner(QThread):
    """Enumerate attached devices without blocking the interface.

    The same shape as `gui.live.CaptureThread`, and for the same reason: the
    device layer is asynchronous and the interface is not, so each needs its own
    loop. Every lockdown this opens is closed in a ``finally``, including when
    the thread is asked to stop midway.
    """

    #: Every attached device, as soon as usbmux answers. Names are not known yet.
    found = Signal(list)
    #: One device's identity, once the round trip to it has finished.
    identified = Signal(str, object)

    def __init__(self, skip: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        #: A device a capture already holds. Opening a second lockdown against
        #: it stalls the stream the capture thread is blocked on reading.
        self._skip = skip

    def run(self) -> None:
        try:
            asyncio.run(self._scan())
        except Exception:
            self.found.emit([])

    async def _scan(self) -> None:
        from ostrace.devices.discovery import (  # noqa: PLC0415
            list_devices,
            open_lockdown,
            read_device_info,
        )

        summaries = await list_devices()
        self.found.emit(list(summaries))

        for summary in summaries:
            if self.isInterruptionRequested():
                return
            if summary.udid == self._skip:
                continue
            try:
                lockdown = await open_lockdown(summary.udid)
            except Exception:
                continue
            try:
                info = await read_device_info(lockdown, connection=summary.connection)
            except Exception:
                continue
            finally:
                # Always, and before anything else can open a second one: this
                # scan must leave the device exactly as it found it.
                with contextlib.suppress(Exception):
                    await lockdown.close()
            self.identified.emit(summary.udid, info)


class DeviceButton(QToolButton):
    """The toolbar's leftmost control: which device, and which others there are.

    Rescans when it is opened rather than on a timer. A device is attached by
    hand, so the moment the user asks is exactly the moment the answer is worth
    paying for, and a poll would hold a lockdown session open against a phone
    nobody is using.
    """

    #: The user picked a device. Carries the udid, or ``None`` for "whichever is
    #: attached", which is what the command line does with no ``--udid``.
    chosen = Signal(object)

    def __init__(self, scheme: Scheme = Scheme.LIGHT, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scheme = scheme
        self._menu = QMenu(self)
        self._scanner: DeviceScanner | None = None
        self._actions: dict[str, QAction] = {}
        self._names: dict[str, str] = {}
        self.udid: str | None = None
        #: Which device a capture is holding, so a scan leaves it alone. Read
        #: directly; written through `set_busy`.
        self.busy_udid: str | None = None

        self.setMenu(self._menu)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setText(NO_DEVICE)
        self.setToolTip("Choose which attached device to capture from")
        # Same reason as the jump button: the text is the current answer and
        # not the question, so on its own it reads as a device name rather than
        # as the control that picks one.
        self.setAccessibleName("Device")
        self.setAccessibleDescription("Choose which attached device to capture from")
        self._menu.aboutToShow.connect(self.rescan)
        # Before the first press, not in response to it. `aboutToShow` fires
        # after Qt has decided whether there is a menu worth showing, so a menu
        # filled from the scan that press starts is filled too late.
        self._place_holder(SCANNING)
        self.set_scheme(scheme)

    def _place_holder(self, text: str) -> QAction:
        """Put one disabled row in the menu, so that it is never empty."""
        action = self._menu.addAction(text)
        action.setEnabled(False)
        return action

    def set_scheme(self, scheme: Scheme) -> None:
        self._scheme = scheme
        self.setIcon(icons.icon("smartphone", scheme, ratio=self.devicePixelRatioF()))

    def set_busy(self, udid: str | None) -> None:
        """Say which device a capture is holding, or ``None`` for none.

        A method rather than an assignment at each call site because it is one
        idea -- leave this one alone -- reached from two places that arrive at
        the answer differently: the window knows a capture has *started*, and
        the capture itself says later which device it actually got, which are
        not always the same one.
        """
        self.busy_udid = udid

    def rescan(self) -> None:
        """Ask usbmux again. Safe to call while a scan is already running."""
        if not self._actions:
            # Nothing real to show yet, so say what is happening rather than
            # leave the last answer up. A menu still reading "No device
            # attached" while the scan that would contradict it is running is
            # the one moment this control is guaranteed to be out of date.
            stale = self._menu.actions()
            self._place_holder(SCANNING)
            for action in stale:
                self._menu.removeAction(action)
        if self._scanner is not None and self._scanner.isRunning():
            return
        self._scanner = DeviceScanner(skip=self.busy_udid, parent=self)
        self._scanner.found.connect(self._on_found)
        self._scanner.identified.connect(self._on_identified)
        self._scanner.start()

    def stop(self) -> None:
        """Release the scanning thread, if there is one.

        Called from the window's close handler. A ``QThread`` still running when
        Python drops its last reference aborts the process without a message.
        """
        scanner = self._scanner
        if scanner is None:
            return
        scanner.requestInterruption()
        scanner.wait(_SCAN_STOP_TIMEOUT_MS)
        self._scanner = None

    def _on_found(self, summaries: list[DeviceSummary]) -> None:
        """Replace the menu's contents without it ever being empty.

        The new rows go in before the old ones come out, deliberately. This
        signal arrives while the popup is very likely open -- a scan is started
        by opening it -- and a `QMenu` emptied under a user who is looking at it
        closes itself. Building first and removing after means the list changes
        under the cursor instead of vanishing from it.
        """
        stale = self._menu.actions()
        self._actions.clear()

        if not summaries:
            self.udid = None
            self._place_holder(NONE_ATTACHED)
        else:
            for summary in summaries:
                label = self._names.get(summary.udid, summary.udid)
                action = self._menu.addAction(f"{label}  ({summary.connection})")
                action.setCheckable(True)
                action.setChecked(summary.udid == self.udid)
                action.triggered.connect(lambda _checked=False, u=summary.udid: self.choose(u))
                self._actions[summary.udid] = action

        for action in stale:
            self._menu.removeAction(action)

        if self.udid is not None and self.udid not in self._actions:
            # The device that was chosen has been unplugged. Nothing is chosen
            # now, and picking its replacement is the user's to do.
            self.udid = None
        self._refresh_label()

    def _on_identified(self, udid: str, info: DeviceInfo) -> None:
        self._names[udid] = info.name
        action = self._actions.get(udid)
        if action is not None:
            action.setText(f"{info.label}")
        self._refresh_label()

    def choose(self, udid: str | None) -> None:
        """Pick a device. The only thing that does -- see `CHOOSE`."""
        self.udid = udid
        for candidate, action in self._actions.items():
            action.setChecked(candidate == udid)
        self._refresh_label()
        self.chosen.emit(udid)

    def _refresh_label(self) -> None:
        """What the button says, from what is attached and what is chosen."""
        if not self._actions:
            self._show(NO_DEVICE)
        elif self.udid is None:
            self._show(CHOOSE)
        else:
            self._show(self._names.get(self.udid, self.udid))

    def _show(self, label: str) -> None:
        self.setText(label)
