# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Why the device cannot be reached, in the window rather than in a terminal.

The checks have existed since phase 1 and only `ostrace doctor` could run them,
so somebody who installed this for the window met a dead end at exactly the
moment something was wrong -- and the answer is almost never in the program.
It is a service that was never installed, a device that was never trusted, or a
cable that only carries power.

Two things here are deliberate.

**It runs on a thread.** `devices.doctor.run` opens a lockdown session and waits
on sockets with a two-second timeout apiece; on the interface thread that is a
window frozen for as long as the diagnosis takes, which is longest in exactly
the case somebody is running it.

**The report can be copied out.** The reason to run this is usually to tell
somebody else what it said, and a wall of text nobody can select is one that
gets photographed.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ostrace.devices.doctor import Status

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from ostrace.devices.doctor import Report

__all__ = ["MARKS", "DoctorThread", "DoctorWindow"]

#: A word beside each check, never a colour alone. `docs/design/gui.md` §10's
#: rule, and the reason it exists is here as much as anywhere: this window is
#: read by somebody already having a bad time, often over a screen share.
MARKS: dict[Status, str] = {
    Status.OK: "ok",
    Status.WARN: "warn",
    Status.FAIL: "FAIL",
    Status.SKIP: "skipped",
}

_RUNNING = "Checking…"
_HEADINGS = ("Check", "", "Detail")


class DoctorThread(QThread):
    """Run the checks off the interface thread.

    The same shape as `gui.live.CaptureThread` and `DeviceScanner`, and for the
    same reason: the device layer is asynchronous and the interface is not.
    """

    #: The diagnosis finished. Carries a `devices.doctor.Report`.
    reported = Signal(object)
    #: It did not. Carries a message fit to show a user.
    failed = Signal(str)

    def __init__(self, udid: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._udid = udid

    def run(self) -> None:
        from ostrace.devices import doctor  # noqa: PLC0415 - forty packages, only for this

        try:
            self.reported.emit(asyncio.run(doctor.run(self._udid)))
        except Exception as exc:  # a diagnosis that dies silently is the worst kind
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class DoctorWindow(QDialog):
    """One row per check: what was tried, how it went, and what to do."""

    def __init__(self, udid: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._udid = udid
        self._thread: DoctorThread | None = None
        self.report: Report | None = None

        self.setWindowTitle("Doctor — ostrace")
        self.setModal(False)
        self.resize(720, 420)

        layout = QVBoxLayout(self)
        self._summary = QLabel(_RUNNING, self)
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)

        self.checks = QTreeWidget(self)
        self.checks.setColumnCount(len(_HEADINGS))
        self.checks.setHeaderLabels(list(_HEADINGS))
        self.checks.setRootIsDecorated(False)
        self.checks.setAlternatingRowColors(True)
        self.checks.setAccessibleName("Diagnostic checks")
        layout.addWidget(self.checks, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        self.again = QPushButton("Run Again", self)
        self.copy = QPushButton("Copy", self)
        buttons.addButton(self.again, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(self.copy, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        self.again.clicked.connect(self.start)
        self.copy.clicked.connect(self.copy_report)
        layout.addWidget(buttons)

    def start(self) -> None:
        """Run the checks, unless a run is already in flight.

        Guarded rather than queued: `Run Again` pressed twice would otherwise
        open two lockdown sessions against the same device, and a second
        session against a device is the thing this project already knows stalls
        the first.
        """
        if self._thread is not None and self._thread.isRunning():
            return
        self._summary.setText(_RUNNING)
        self.checks.clear()
        self.again.setEnabled(False)
        self._thread = DoctorThread(self._udid, self)
        self._thread.reported.connect(self._show_report)
        self._thread.failed.connect(self._show_failure)
        self._thread.start()

    def _show_report(self, report: object) -> None:
        from ostrace.devices.doctor import Report as _Report  # noqa: PLC0415

        if not isinstance(report, _Report):  # pragma: no cover - signal carries what it is given
            return
        self.report = report
        self.again.setEnabled(True)
        # Here as well as in `start`, and the two are not the same act: that
        # one empties the list because a diagnosis is *running* and the old
        # answer is no longer true, and this one because the method that fills
        # the rows is the method that has to own emptying them. Only `start`
        # cleared, so a second report reached through any other path -- a test,
        # a retry wired up later -- appended to the first.
        self.checks.clear()
        failures = [check for check in report.checks if check.status is Status.FAIL]
        self._summary.setText(
            "Everything needed for a capture is in place."
            if report.ok
            else f"{len(failures)} of {len(report.checks)} checks failed."
        )
        for check in report.checks:
            item = QTreeWidgetItem([check.name, MARKS[check.status], check.detail])
            if check.hint:
                # A child row rather than a third column: the hints are
                # sentences and the details are phrases, and putting them in
                # one column makes every row as tall as the longest hint.
                item.addChild(QTreeWidgetItem(["", "", check.hint]))
                item.setExpanded(True)
            self.checks.addTopLevelItem(item)
        for column in range(len(_HEADINGS) - 1):
            self.checks.resizeColumnToContents(column)

    def _show_failure(self, message: str) -> None:
        self.again.setEnabled(True)
        self._summary.setText(f"The checks could not be run: {message}")

    def as_text(self) -> str:
        """The report as something that can be pasted into an issue."""
        if self.report is None:
            return ""
        lines = []
        for check in self.report.checks:
            lines.append(f"{MARKS[check.status]:>7}  {check.name}: {check.detail}")
            if check.hint:
                lines.append(f"{'':>7}  {check.hint}")
        return "\n".join(lines)

    def copy_report(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.as_text())

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt's name
        """Wait for the thread before letting Python drop the last reference.

        A `QThread` still running when its wrapper is collected aborts the
        process -- 0xC0000409 on Windows, which is not an exception and cannot
        be caught. This window is closable at any moment, including two seconds
        into a socket timeout.
        """
        thread = self._thread
        if thread is not None and thread.isRunning():
            thread.wait(_SHUTDOWN_MS)
        super().closeEvent(event)  # type: ignore[arg-type]


#: How long to wait for a diagnosis to finish when the window is closed under
#: it. Longer than the checks' own socket timeouts, so the ordinary case is a
#: thread that has already finished by the time this is asked.
_SHUTDOWN_MS = 6_000


def open_doctor(udid: str | None = None, parent: QWidget | None = None) -> DoctorWindow:
    """Build the window, start the checks, and show it.

    Non-modal, and `show` rather than `exec`: the answer is often "unlock the
    phone", which is a thing to do while the window stays open, and a modal
    dialog would have to be dismissed to act on what it says.
    """
    window = DoctorWindow(udid, parent)
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    window.start()
    window.show()
    return window
