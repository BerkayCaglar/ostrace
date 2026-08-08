# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Listing devices and reading their identity.

Everything here goes through usbmux. Pair records are never read from disk:
``/var/db/lockdown`` is root-only and TCC-protected on macOS, so reading it
would make elevation a requirement for an operation that does not need it.
Asking usbmuxd over its socket needs no privileges at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from ostrace.errors import NoDeviceFoundError, translate
from ostrace.model import DeviceInfo

if TYPE_CHECKING:
    from pymobiledevice3.lockdown import LockdownClient

__all__ = [
    "DeviceSummary",
    "list_devices",
    "open_lockdown",
    "read_device_info",
    "require_device",
]


@dataclass(frozen=True, slots=True)
class DeviceSummary:
    """What usbmux knows before a lockdown session is established."""

    udid: str
    connection: str

    @property
    def is_network(self) -> bool:
        return self.connection == "network"


async def list_devices() -> list[DeviceSummary]:
    """Every device usbmux can see, USB and network.

    Network devices are listed even though capturing from them is not supported
    yet. Hiding them would turn "not supported yet" into "your device is
    invisible and you do not know why".
    """
    from pymobiledevice3.usbmux import list_devices as _list  # noqa: PLC0415

    try:
        found = await _list()
    except Exception as exc:
        raise translate(exc) from exc

    return [
        DeviceSummary(
            udid=device.serial,
            connection="network" if device.is_network else "usb",
        )
        for device in found
    ]


async def open_lockdown(udid: str | None = None) -> LockdownClient:
    """Establish a lockdown session over usbmux.

    No tunnel and no elevation: ``com.apple.os_trace_relay`` is an ordinary
    lockdown service and remains one on iOS 26, which was verified on hardware
    rather than assumed from the iOS 17 RemoteXPC changes.
    """
    from pymobiledevice3.lockdown import create_using_usbmux  # noqa: PLC0415

    try:
        return await create_using_usbmux(serial=udid)
    except Exception as exc:
        raise translate(exc) from exc


async def read_device_info(
    lockdown: LockdownClient,
    *,
    connection: str = "usb",
) -> DeviceInfo:
    """Read identity and clock from an open lockdown session.

    The clock matters more than it looks. Records arrive with naive local
    timestamps, so the device's own UTC offset is what makes them meaningful --
    the host's offset is a different clock and frequently a different zone.
    """
    values = {
        key: await _value(lockdown, key)
        for key in (
            "DeviceName",
            "ProductType",
            "ProductVersion",
            "BuildVersion",
            "TimeZone",
            "TimeZoneOffsetFromUTC",
            "TimeIntervalSince1970",
        )
    }

    offset_raw = values["TimeZoneOffsetFromUTC"]
    utc_offset = timedelta(seconds=int(offset_raw)) if offset_raw is not None else None

    device_epoch = values["TimeIntervalSince1970"]
    clock_skew = None
    if device_epoch is not None:
        device_now = datetime.fromtimestamp(float(device_epoch), tz=UTC)
        clock_skew = device_now - datetime.now(tz=UTC)

    return DeviceInfo(
        # Typed as optional upstream. An open session without one would be
        # surprising, but it is an identifying field rather than a functional
        # one, so an empty string beats failing a capture over it.
        udid=lockdown.udid or "",
        name=str(values["DeviceName"] or "iPhone"),
        product_type=str(values["ProductType"] or "unknown"),
        product_version=str(values["ProductVersion"] or "unknown"),
        build_version=_optional_str(values["BuildVersion"]),
        connection=connection,
        timezone_name=_optional_str(values["TimeZone"]),
        utc_offset=utc_offset,
        clock_skew=clock_skew,
    )


async def require_device(udid: str | None = None) -> DeviceSummary:
    """Pick a device, or explain precisely why there is none to pick."""
    devices = await list_devices()
    if not devices:
        msg = "no device found"
        raise NoDeviceFoundError(msg)

    if udid is not None:
        for device in devices:
            if device.udid == udid:
                return device
        msg = f"device {udid} is not connected"
        raise NoDeviceFoundError(msg)

    usb = [d for d in devices if not d.is_network]
    if usb:
        return usb[0]

    msg = (
        f"found {len(devices)} device(s), but all of them are attached over the "
        "network, which is not supported yet"
    )
    raise NoDeviceFoundError(
        msg,
        hint="Connect the device over USB. Network capture is planned; see docs/adr/0006.",
    )


async def _value(lockdown: LockdownClient, key: str) -> Any:  # noqa: ANN401
    """Read one lockdown value, treating an absent key as absent rather than fatal.

    Which keys a device exposes varies by iOS version and by pairing state.
    ``UsesTwentyFourHourClock`` raises ``MissingValueError`` on iOS 26, for
    instance. None of these are worth failing a capture over.
    """
    try:
        return await lockdown.get_value(key=key)
    except Exception:
        return None


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)
