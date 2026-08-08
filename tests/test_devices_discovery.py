# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Device selection and identity, without a device.

`pymobiledevice3` is stubbed rather than mocked wholesale: these tests are about
our selection rules and our round-trip budget, not about usbmux.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest

from ostrace.devices import discovery
from ostrace.errors import NoDeviceFoundError
from ostrace.model import Platform


class FakeLockdown:
    """Enough of LockdownClient for read_device_info.

    Counts individual `get_value` calls, because avoiding them is the point.
    """

    def __init__(self, all_values: dict[str, Any] | None, extra: dict[str, Any] | None = None):
        self.udid = "00000000-000000000000000A"
        self.all_values = all_values
        self._extra = extra or {}
        self.get_value_calls: list[str] = []

    async def get_value(self, key: str) -> Any:
        self.get_value_calls.append(key)
        if key in self._extra:
            return self._extra[key]
        msg = f"MissingValueError: {key}"
        raise KeyError(msg)


FULL = {
    "DeviceName": "Test iPhone",
    "ProductType": "iPhone18,2",
    "ProductVersion": "26.5.2",
    "BuildVersion": "23F84",
    "TimeZone": "Europe/Istanbul",
    "TimeZoneOffsetFromUTC": 10800.0,
    "TimeIntervalSince1970": 1786186518.0,
}


class TestReadDeviceInfo:
    def test_the_cached_dictionary_costs_no_round_trips(self) -> None:
        """The client already fetched this during the handshake. Asking key by
        key is seven request/response pairs over usbmux before the first record
        can arrive."""
        lockdown = FakeLockdown(dict(FULL))
        info = asyncio.run(discovery.read_device_info(lockdown))  # type: ignore[arg-type]

        assert lockdown.get_value_calls == []
        assert info.name == "Test iPhone"
        assert info.product_type == "iPhone18,2"
        assert info.build_version == "23F84"
        assert info.timezone_name == "Europe/Istanbul"
        assert info.utc_offset == timedelta(hours=3)
        assert info.platform is Platform.IOS

    def test_a_key_missing_from_the_cache_falls_back_to_a_single_read(self) -> None:
        partial = {k: v for k, v in FULL.items() if k != "TimeZone"}
        lockdown = FakeLockdown(partial, extra={"TimeZone": "Europe/Istanbul"})
        info = asyncio.run(discovery.read_device_info(lockdown))  # type: ignore[arg-type]

        assert lockdown.get_value_calls == ["TimeZone"]
        assert info.timezone_name == "Europe/Istanbul"

    def test_a_key_the_device_does_not_expose_is_absent_not_fatal(self) -> None:
        """Which keys exist varies by iOS version and pairing state. None of
        them is worth failing a capture over."""
        lockdown = FakeLockdown({"DeviceName": "Test iPhone"})
        info = asyncio.run(discovery.read_device_info(lockdown))  # type: ignore[arg-type]

        assert info.name == "Test iPhone"
        assert info.product_type == "unknown"
        assert info.build_version is None
        assert info.utc_offset is None

    def test_no_cache_at_all_still_works(self) -> None:
        lockdown = FakeLockdown(None, extra=dict(FULL))
        info = asyncio.run(discovery.read_device_info(lockdown))  # type: ignore[arg-type]

        assert len(lockdown.get_value_calls) == 7
        assert info.product_version == "26.5.2"

    def test_clock_skew_is_measured_when_the_device_reports_its_clock(self) -> None:
        lockdown = FakeLockdown(dict(FULL))
        info = asyncio.run(discovery.read_device_info(lockdown))  # type: ignore[arg-type]
        assert info.clock_skew is not None


class TestRequireDevice:
    @staticmethod
    def patched(
        monkeypatch: pytest.MonkeyPatch,
        devices: list[discovery.DeviceSummary],
    ) -> None:
        async def fake_list() -> list[discovery.DeviceSummary]:
            return devices

        monkeypatch.setattr(discovery, "list_devices", fake_list)

    def test_nothing_connected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.patched(monkeypatch, [])
        with pytest.raises(NoDeviceFoundError, match="no device found") as excinfo:
            asyncio.run(discovery.require_device())
        assert "charge-only cables" in str(excinfo.value)

    def test_a_usb_device_is_preferred_over_a_network_one(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        net = discovery.DeviceSummary("net-udid", "network")
        usb = discovery.DeviceSummary("usb-udid", "usb")
        self.patched(monkeypatch, [net, usb])
        assert asyncio.run(discovery.require_device()) == usb

    def test_network_only_says_so_rather_than_saying_nothing_is_connected(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Hiding it would turn 'not supported yet' into 'your device is
        invisible and you do not know why'."""
        self.patched(monkeypatch, [discovery.DeviceSummary("net-udid", "network")])
        with pytest.raises(NoDeviceFoundError, match="network") as excinfo:
            asyncio.run(discovery.require_device())
        assert "Connect the device over USB" in str(excinfo.value)

    def test_an_explicit_udid_is_honoured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        wanted = discovery.DeviceSummary("wanted", "usb")
        self.patched(monkeypatch, [discovery.DeviceSummary("other", "usb"), wanted])
        assert asyncio.run(discovery.require_device("wanted")) == wanted

    def test_an_unknown_udid_names_itself(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.patched(monkeypatch, [discovery.DeviceSummary("other", "usb")])
        with pytest.raises(NoDeviceFoundError, match="absent-udid is not connected"):
            asyncio.run(discovery.require_device("absent-udid"))


def test_a_summary_knows_its_transport() -> None:
    assert discovery.DeviceSummary("x", "network").is_network is True
    assert discovery.DeviceSummary("x", "usb").is_network is False
