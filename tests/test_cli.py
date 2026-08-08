# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The command line, with the device layer stubbed."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import pytest

from ostrace import cli
from ostrace.devices import doctor
from ostrace.devices.discovery import DeviceSummary
from ostrace.errors import DeviceNotPairedError, NoDeviceFoundError
from ostrace.model import DeviceInfo, Platform

if TYPE_CHECKING:
    from pathlib import Path

DEVICE = DeviceInfo(
    udid="00000000-000000000000000A",
    name="Test iPhone",
    product_type="iPhone18,2",
    product_version="26.5.2",
    utc_offset=dt.timedelta(hours=3),
    clock_skew=dt.timedelta(seconds=1),
    platform=Platform.IOS,
)


@pytest.fixture
def stub_devices(monkeypatch: pytest.MonkeyPatch) -> list[DeviceSummary]:
    """Stub the discovery layer that every subcommand starts from."""
    found = [DeviceSummary("00000000-000000000000000A", "usb")]

    async def fake_list() -> list[DeviceSummary]:
        return found

    async def fake_open(udid: str | None = None) -> object:
        class Session:
            async def close(self) -> None:
                return

        return Session()

    async def fake_info(lockdown: object, connection: str = "usb") -> DeviceInfo:
        return DEVICE

    for module in (cli, doctor):
        for name, value in (
            ("list_devices", fake_list),
            ("open_lockdown", fake_open),
            ("read_device_info", fake_info),
        ):
            monkeypatch.setattr(f"ostrace.devices.discovery.{name}", value, raising=True)
            if hasattr(module, name):
                monkeypatch.setattr(module, name, value, raising=True)
    return found


class TestTopLevel:
    def test_no_command_prints_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main([]) == cli.EXIT_OK
        assert "usage: ostrace" in capsys.readouterr().out.replace("\x1b", "")

    def test_an_unknown_command_is_rejected(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            cli.main(["nonsense"])
        assert excinfo.value.code == 2

    def test_a_device_error_prints_its_hint_and_exits_non_zero(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The hint is the actionable half. A traceback here would bury it."""

        async def boom() -> list[DeviceSummary]:
            raise DeviceNotPairedError("not paired")

        monkeypatch.setattr("ostrace.devices.discovery.list_devices", boom)

        assert cli.main(["devices"]) == cli.EXIT_ERROR
        stderr = capsys.readouterr().err
        assert "not paired" in stderr
        assert "Trust This Computer" in stderr


class TestDevices:
    def test_listing(
        self,
        stub_devices: list[DeviceSummary],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert cli.main(["devices"]) == cli.EXIT_OK
        out = capsys.readouterr().out
        assert "00000000-000000000000000A" in out
        assert "usb" in out

    def test_verbose_adds_the_device_label(
        self,
        stub_devices: list[DeviceSummary],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert cli.main(["devices", "--verbose"]) == cli.EXIT_OK
        assert "Test iPhone (iPhone18,2, iOS 26.5.2)" in capsys.readouterr().out

    def test_nothing_connected_points_at_doctor(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        async def empty() -> list[DeviceSummary]:
            return []

        monkeypatch.setattr("ostrace.devices.discovery.list_devices", empty)
        assert cli.main(["devices"]) == cli.EXIT_ERROR
        assert "doctor" in capsys.readouterr().out


class TestDoctor:
    def test_a_healthy_environment_exits_zero(
        self,
        stub_devices: list[DeviceSummary],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(doctor, "local_usbmux_endpoint", lambda: None)
        assert cli.main(["doctor"]) == cli.EXIT_OK

        out = capsys.readouterr().out
        assert "[ ok ]" in out
        assert "Test iPhone" in out

    def test_no_usbmux_fails_and_stops_asking_downstream_questions(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """ "No device listed" under "there is no usbmux" is noise, not a
        second problem."""
        monkeypatch.setattr(doctor, "local_usbmux_endpoint", lambda: ("127.0.0.1", 1))

        assert cli.main(["doctor"]) == cli.EXIT_ERROR
        out = capsys.readouterr().out
        assert "[FAIL] usbmux" in out
        assert "Apple Mobile Device Service" in out
        assert "[skip] devices" in out

    def test_a_clock_far_out_of_step_is_a_warning_not_a_failure(
        self,
        stub_devices: list[DeviceSummary],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        skewed = DeviceInfo(
            udid=DEVICE.udid,
            name=DEVICE.name,
            product_type=DEVICE.product_type,
            product_version=DEVICE.product_version,
            utc_offset=DEVICE.utc_offset,
            clock_skew=dt.timedelta(minutes=9),
        )

        async def fake_info(lockdown: object, connection: str = "usb") -> DeviceInfo:
            return skewed

        monkeypatch.setattr(doctor, "read_device_info", fake_info)
        monkeypatch.setattr(doctor, "local_usbmux_endpoint", lambda: None)

        assert cli.main(["doctor"]) == cli.EXIT_OK
        assert "[warn] clock" in capsys.readouterr().out

    def test_pairing_failure_is_reported_with_its_remedy(
        self,
        stub_devices: list[DeviceSummary],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        async def refuse(udid: str | None = None) -> object:
            raise DeviceNotPairedError("not paired")

        monkeypatch.setattr(doctor, "open_lockdown", refuse)
        monkeypatch.setattr(doctor, "local_usbmux_endpoint", lambda: None)

        assert cli.main(["doctor"]) == cli.EXIT_ERROR
        out = capsys.readouterr().out
        assert "[FAIL] pairing" in out
        assert "Trust This Computer" in out

    def test_a_network_only_device_is_named_as_the_reason(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        async def only_network() -> list[DeviceSummary]:
            return [DeviceSummary("net-udid", "network")]

        monkeypatch.setattr(doctor, "list_devices", only_network)
        monkeypatch.setattr(doctor, "local_usbmux_endpoint", lambda: None)

        assert cli.main(["doctor"]) == cli.EXIT_ERROR
        assert "[FAIL] transport" in capsys.readouterr().out


class TestCapture:
    def test_it_writes_a_session_and_prints_where(
        self,
        mixed_fixture: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The CLI is wired to a real source object, so a recorded session can
        stand in for the device here too."""
        from ostrace.sources.replay import ReplaySource

        monkeypatch.setattr(
            "ostrace.sources.os_trace.OsTraceSource",
            lambda *args, **kwargs: ReplaySource(mixed_fixture),
        )
        out = tmp_path / "cap"
        assert cli.main(["capture", "-o", str(out), "-n", "50", "--quiet"]) == cli.EXIT_OK

        printed = capsys.readouterr().out
        assert "50 records" in printed
        assert str(out.with_name("cap.ostrace")) in printed

    def test_a_missing_device_surfaces_the_hint(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Patched where it is *used*, not where it is defined.

        `os_trace` binds `open_lockdown` at import, so patching the discovery
        module leaves the source calling the real one -- and this test then
        passes or fails according to whether the machine running it happens to
        have a usbmux, which is precisely the dependency the suite must not
        have. It passed on Windows and failed on Linux CI for that reason.
        """

        async def missing(udid: str | None = None) -> object:
            raise NoDeviceFoundError("no device found")

        monkeypatch.setattr("ostrace.sources.os_trace.open_lockdown", missing)
        assert cli.main(["capture", "--quiet"]) == cli.EXIT_ERROR

        stderr = capsys.readouterr().err
        assert "no device found" in stderr
        assert "charge-only cables" in stderr
