# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Diagnosing why a device cannot be reached.

Almost every problem in this domain is environmental rather than logical: a
service that was never installed, a device that was never trusted, a cable that
only carries power. Those cost far more time than bugs do, so working out which
one it is deserves a command of its own.

The checks run in dependency order and stop reporting downstream failures once
an upstream one is found -- "no device listed" under "usbmux is unreachable" is
noise, not a second problem.
"""

from __future__ import annotations

import contextlib
import socket
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from ostrace import __version__
from ostrace.compat import local_usbmux_endpoint
from ostrace.devices.discovery import list_devices, open_lockdown, read_device_info
from ostrace.errors import OstraceError

if TYPE_CHECKING:
    from ostrace.model import DeviceInfo

__all__ = ["Check", "Report", "Status", "run"]

#: A device clock further out than this makes correlating device logs
#: against host events misleading rather than merely imprecise.
NOTABLE_SKEW_SECONDS = 60


class Status(Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    status: Status
    detail: str
    hint: str = ""


@dataclass(slots=True)
class Report:
    checks: list[Check] = field(default_factory=list)
    device: DeviceInfo | None = None

    @property
    def ok(self) -> bool:
        return not any(check.status is Status.FAIL for check in self.checks)

    def add(self, name: str, status: Status, detail: str, hint: str = "") -> None:
        self.checks.append(Check(name=name, status=status, detail=detail, hint=hint))


async def run(udid: str | None = None) -> Report:
    """Work out what is wrong, in dependency order."""
    report = Report()
    _check_runtime(report)

    if not _check_usbmux(report):
        report.add(
            "devices",
            Status.SKIP,
            "not checked: there is no usbmux to ask",
        )
        return report

    devices = await _check_devices(report, udid)
    if devices is None:
        return report

    await _check_lockdown(report, devices)
    return report


def _check_runtime(report: Report) -> None:
    report.add(
        "ostrace",
        Status.OK,
        f"{__version__} on Python {sys.version.split()[0]} ({sys.platform})",
    )
    if sys.flags.optimize:  # pragma: no cover - depends on interpreter flags
        report.add(
            "interpreter",
            Status.FAIL,
            "running under -O / PYTHONOPTIMIZE",
            "The device stream protocol depends on assert statements that "
            "optimisation removes. Capturing would produce garbage records.",
        )


def _check_usbmux(report: Report) -> bool:
    """Is there a usbmux to talk to at all?

    On Windows this is a TCP probe rather than a service query: it is the same
    thing the library will do moments later, it needs no subprocess, and it
    answers "can we actually connect" instead of "is something named correctly".
    """
    endpoint = local_usbmux_endpoint()
    if endpoint is None:
        # usbmuxd is part of the OS on macOS and a package on Linux, both
        # reached over a unix socket. Probing the socket path adds a failure
        # mode of its own, so this defers to the device listing. Confirmed on
        # macOS 26.3.1: `/var/run/usbmuxd` is present and owned by root with
        # nothing installed, and the listing below found the attached iPhone.
        report.add("usbmux", Status.OK, "provided by the operating system")
        return True

    host, port = endpoint
    try:
        with socket.create_connection(endpoint, timeout=2.0):
            report.add("usbmux", Status.OK, f"Apple Mobile Device Service on {host}:{port}")
    except OSError as exc:
        report.add(
            "usbmux",
            Status.FAIL,
            f"nothing listening on {host}:{port} ({exc.strerror or exc})",
            "Apple Mobile Device Service is not running. It ships with iTunes "
            "from apple.com -- not the Microsoft Store build -- and a silent "
            "winget install skips it. See docs/troubleshooting.md.",
        )
        return False
    return True


async def _check_devices(report: Report, udid: str | None) -> list[str] | None:
    try:
        found = await list_devices()
    except OstraceError as exc:
        report.add("devices", Status.FAIL, exc.message, exc.hint)
        return None

    if not found:
        report.add(
            "devices",
            Status.FAIL,
            "none connected",
            "Connect the device over USB and unlock it. A charge-only cable "
            "gives exactly this symptom.",
        )
        return None

    usb = [device.udid for device in found if not device.is_network]
    network = [device.udid for device in found if device.is_network]

    report.add(
        "devices",
        Status.OK,
        f"{len(found)} connected: {len(usb)} USB, {len(network)} network",
    )
    if network and not usb:
        report.add(
            "transport",
            Status.FAIL,
            "every device is attached over the network",
            "Network capture is not supported yet; see docs/adr/0006. Connect over USB.",
        )
        return None
    if network:
        report.add("transport", Status.WARN, f"{len(network)} network device(s) will be ignored")

    if udid is not None and udid not in usb:
        report.add("selection", Status.FAIL, f"{udid} is not connected over USB")
        return None
    return [udid] if udid is not None else usb


async def _check_lockdown(report: Report, devices: list[str]) -> None:
    """Pairing and identity: the step that fails when Trust was never answered."""
    udid = devices[0]
    try:
        lockdown = await open_lockdown(udid)
    except OstraceError as exc:
        report.add("pairing", Status.FAIL, exc.message, exc.hint)
        return

    try:
        info = await read_device_info(lockdown)
    except OstraceError as exc:  # pragma: no cover - identity rarely fails alone
        report.add("identity", Status.FAIL, exc.message, exc.hint)
        return
    finally:
        # Closing a socket that has already gone away is not a finding.
        with contextlib.suppress(Exception):
            await lockdown.close()

    report.add("pairing", Status.OK, f"trusted by this host ({udid})")
    report.device = info
    report.add("device", Status.OK, info.label)

    if info.utc_offset is None:
        report.add(
            "clock",
            Status.WARN,
            "the device did not report a UTC offset; timestamps will be stored as UTC",
        )
    elif (
        info.clock_skew is not None and abs(info.clock_skew.total_seconds()) > NOTABLE_SKEW_SECONDS
    ):
        report.add(
            "clock",
            Status.WARN,
            f"device clock differs from this host by {info.clock_skew}",
            "Correlating device logs against events on this machine will be off by that much.",
        )
    else:
        report.add("clock", Status.OK, f"offset {info.utc_offset}, in step with this host")
