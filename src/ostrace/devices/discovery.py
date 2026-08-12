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
from ostrace.model import DeviceInfo, Platform, optional_str

if TYPE_CHECKING:
    from pymobiledevice3.lockdown import LockdownClient

__all__ = [
    "DeviceSummary",
    "list_devices",
    "open_lockdown",
    "read_device_info",
    "require_device",
]

#: What `datetime.timezone` will accept, in seconds. Anything at or beyond a
#: day is not an offset any device has; carrying one forward turns a bad
#: lockdown value into an exception from the first timestamp that uses it.
_MAX_UTC_OFFSET_SECONDS = 24 * 60 * 60

_WANTED = (
    "DeviceName",
    "ProductType",
    "ProductVersion",
    "BuildVersion",
    "TimeZone",
    "TimeZoneOffsetFromUTC",
    "TimeIntervalSince1970",
)


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
    values = await _values(lockdown, _WANTED)

    # Lockdown values are plists and the same key can come back as a number on
    # one iOS version and a string on another. A malformed clock is a reason to
    # fall back, never a reason to abort a capture with a bare ValueError that
    # carries none of the guidance the rest of this layer provides.
    offset_seconds = _as_float(values.get("TimeZoneOffsetFromUTC"))
    # Range-checked as well as parsed. `timedelta` accepts any number of
    # seconds but `timezone` does not, so an out-of-range value that leaves
    # this function detonates later in `DeviceInfo.tzinfo` -- reached from
    # `device.now()` at the top of `capture()`, before a single record, as a
    # bare ValueError naming neither the device nor the key.
    utc_offset = (
        timedelta(seconds=offset_seconds)
        if offset_seconds is not None and abs(offset_seconds) < _MAX_UTC_OFFSET_SECONDS
        else None
    )

    device_epoch = _as_float(values.get("TimeIntervalSince1970"))
    clock_skew = None
    if device_epoch is not None:
        device_now = datetime.fromtimestamp(device_epoch, tz=UTC)
        clock_skew = device_now - datetime.now(tz=UTC)

    return DeviceInfo(
        # Typed as optional upstream. An open session without one would be
        # surprising, but it is an identifying field rather than a functional
        # one, so an empty string beats failing a capture over it.
        udid=lockdown.udid or "",
        name=str(values.get("DeviceName") or "iPhone"),
        product_type=str(values.get("ProductType") or "unknown"),
        product_version=str(values.get("ProductVersion") or "unknown"),
        build_version=optional_str(values.get("BuildVersion")),
        connection=connection,
        timezone_name=optional_str(values.get("TimeZone")),
        utc_offset=utc_offset,
        clock_skew=clock_skew,
        platform=Platform.IOS,
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

    usb = [device for device in devices if not device.is_network]
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


async def _values(lockdown: LockdownClient, keys: tuple[str, ...]) -> dict[str, Any]:
    """Read several lockdown values with as few round trips as possible.

    The client already holds the device's root value dictionary: it fetches it
    during the handshake and keeps it on ``all_values``. Reading from there
    costs nothing, where asking key by key is one request/response over usbmux
    each -- seven round trips before the first record can arrive, with the clock
    reading last and absorbing the latency of the six before it.

    Keys absent from that dictionary still fall back to an individual read, and
    a key the device does not expose at all is treated as absent rather than
    fatal: which keys exist varies by iOS version and pairing state, and none of
    them is worth failing a capture over.
    """
    cached = getattr(lockdown, "all_values", None)
    # Read through, never copied: this is the device's whole root plist, over a
    # hundred keys including binary blobs, and seven membership tests do not
    # justify duplicating it.
    bulk: dict[str, Any] = cached if isinstance(cached, dict) else {}

    values: dict[str, Any] = {}
    for key in keys:
        if key in bulk:
            values[key] = bulk[key]
            continue
        try:
            values[key] = await lockdown.get_value(key=key)
        except Exception:
            values[key] = None
    return values


def _as_float(value: object) -> float | None:
    """Coerce a lockdown value to a float, or report that it is unusable."""
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
