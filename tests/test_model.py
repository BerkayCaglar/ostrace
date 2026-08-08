# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The shared vocabulary."""

from __future__ import annotations

import dataclasses
import sys
from datetime import UTC, datetime, timedelta

import pytest

from ostrace.model import DeviceInfo, Gap, Level, Platform, Record, basename, optional_str
from tests.helpers import make_record


class TestLevel:
    def test_ordering_is_by_severity(self) -> None:
        """The whole reason this enum exists rather than reusing Apple's.

        ``SyslogLogLevel`` on iOS 26 is NOTICE=0, INFO=1, DEBUG=2, USER_ACTION=3,
        ERROR=16, FAULT=17 -- so DEBUG sorts above NOTICE and every record
        satisfies ``>= NOTICE``. A filter written against those values is
        silently wrong.
        """
        assert Level.DEBUG < Level.INFO < Level.NOTICE
        assert Level.NOTICE < Level.USER_ACTION < Level.ERROR < Level.FAULT

    def test_error_and_above_excludes_the_chatty_tiers(self) -> None:
        above = [level for level in Level if level >= Level.ERROR]
        assert above == [Level.ERROR, Level.FAULT]

    def test_values_leave_room_for_new_levels(self) -> None:
        """Android's WARN has to land between NOTICE and ERROR without a renumber."""
        assert Level.ERROR - Level.NOTICE >= 20

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("debug", Level.DEBUG),
            ("DEBUG", Level.DEBUG),
            ("  Error  ", Level.ERROR),
            ("user action", Level.USER_ACTION),
            ("user-action", Level.USER_ACTION),
            ("USER_ACTION", Level.USER_ACTION),
            ("e", Level.ERROR),
            ("default", Level.NOTICE),
            ("critical", Level.FAULT),
        ],
    )
    def test_parse(self, text: str, expected: Level) -> None:
        assert Level.parse(text) == expected

    def test_parse_rejects_nonsense_and_says_what_is_valid(self) -> None:
        with pytest.raises(ValueError, match="unknown level") as excinfo:
            Level.parse("verbose")
        assert "NOTICE" in str(excinfo.value)

    def test_title(self) -> None:
        assert Level.DEBUG.title == "Debug"
        assert Level.USER_ACTION.title == "User Action"


class TestRecord:
    def test_repeated_strings_are_interned(self) -> None:
        """Two records from the same process must share one string object."""
        first = make_record(1)
        second = make_record(2)
        assert first.process is second.process
        assert first.subsystem is second.subsystem

    def test_interning_survives_a_non_interned_input(self) -> None:
        name = "".join(["cloud", "d"])  # a fresh object, not the literal
        assert make_record(process=name).process is sys.intern("cloudd")

    def test_is_frozen(self) -> None:
        with pytest.raises(AttributeError):
            make_record().message = "no"  # type: ignore[misc]

    def test_process_label_without_an_image(self) -> None:
        record = Record(
            timestamp=datetime(2026, 8, 8, tzinfo=UTC),
            level=Level.NOTICE,
            pid=83,
            process="dasd",
            process_path="/usr/libexec/dasd",
            subsystem=None,
            category=None,
            thread_id=None,
            image_path="/usr/libexec/dasd",
            message="x",
            platform=Platform.IOS,
        )
        assert record.image is None
        assert record.process_label == "dasd[83]"

    def test_process_label_names_the_emitting_library(self) -> None:
        """The point of carrying image_path at all.

        A plugin's output would otherwise be attributed to whichever host
        process happened to load it.
        """
        record = Record(
            timestamp=datetime(2026, 8, 8, tzinfo=UTC),
            level=Level.NOTICE,
            pid=70,
            process="backboardd",
            process_path="/usr/libexec/backboardd",
            subsystem="com.apple.CoreBrightness",
            category="default",
            thread_id=1,
            image_path=(
                "/System/Library/HIDPlugins/ColourSensorFilterPlugin.plugin/"
                "ColourSensorFilterPlugin"
            ),
            message="x",
            platform=Platform.IOS,
        )
        assert record.image == "ColourSensorFilterPlugin"
        assert record.process_label == "backboardd(ColourSensorFilterPlugin)[70]"

    def test_is_error(self) -> None:
        assert not make_record(level=Level.NOTICE).is_error
        assert make_record(level=Level.ERROR).is_error
        assert make_record(level=Level.FAULT).is_error

    def test_platform_has_no_default(self) -> None:
        """A source always knows what it is reading. A default would let a
        second platform's records silently claim to be iOS."""
        fields = {f.name: f for f in dataclasses.fields(Record)}
        assert fields["platform"].default is dataclasses.MISSING

    def test_platform_is_a_plain_string_on_the_wire(self) -> None:
        assert str(Platform.IOS) == "ios"


class TestHelpers:
    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("/usr/libexec/dasd", "dasd"),
            ("/usr/lib/system/libxpc.dylib", "libxpc.dylib"),
            ("dasd", "dasd"),
            ("", ""),
            # Real device paths include directory-style entries. A bare
            # rpartition returns "" for these, which is how a process ends up
            # nameless in the viewer.
            (
                "/System/Library/DriverExtensions/AppleCentauriAlpha.dext/",
                "AppleCentauriAlpha.dext",
            ),
            ("/a/b/", "b"),
        ],
    )
    def test_basename(self, path: str, expected: str) -> None:
        assert basename(path) == expected

    def test_basename_matches_pathlib_on_real_captured_paths(self) -> None:
        """The string form replaced PurePosixPath for speed; it must not have
        replaced its behaviour."""
        from pathlib import PurePosixPath

        for path in (
            "/usr/libexec/nsurlsessiond",
            "/System/Library/PrivateFrameworks/CloudKitDaemon.framework/Support/cloudd",
            "/System/Library/DriverExtensions/AppleCentauriAlpha.dext/",
            "/usr/lib/system/libxpc.dylib",
        ):
            assert basename(path) == PurePosixPath(path).name

    def test_optional_str(self) -> None:
        assert optional_str(None) is None
        assert optional_str("x") == "x"
        assert optional_str(3) == "3"


class TestDeviceInfo:
    def test_tzinfo_uses_the_device_offset(self) -> None:
        device = DeviceInfo(
            udid="x",
            name="n",
            product_type="t",
            product_version="v",
            utc_offset=timedelta(hours=3),
        )
        assert datetime(2026, 1, 1, tzinfo=device.tzinfo).utcoffset() == timedelta(hours=3)

    def test_tzinfo_falls_back_to_utc_rather_than_to_the_host(self) -> None:
        """A wrong-but-visible answer beats a plausible one."""
        device = DeviceInfo(udid="x", name="n", product_type="t", product_version="v")
        assert datetime(2026, 1, 1, tzinfo=device.tzinfo).utcoffset() == timedelta(0)

    def test_label(self) -> None:
        device = DeviceInfo(
            udid="x",
            name="Test iPhone",
            product_type="iPhone18,2",
            product_version="26.5.2",
        )
        assert device.label == "Test iPhone (iPhone18,2, iOS 26.5.2)"

    def test_label_reads_the_platform_rather_than_assuming_one(self) -> None:
        """The device object describes the subject, so the platform belongs on
        it. Hardcoding 'iOS' here would render 'Pixel 8 (Pixel 8, iOS 15)' in
        every window title the day a second source lands, with no field to fix
        it from."""
        device = DeviceInfo(
            udid="x",
            name="Test iPhone",
            product_type="iPhone18,2",
            product_version="26.5.2",
        )
        assert device.platform is Platform.IOS
        assert device.platform.display_name in device.label

    def test_platform_display_name_is_written_for_humans(self) -> None:
        assert Platform.IOS.display_name == "iOS"


def test_gap_duration() -> None:
    start = datetime(2026, 8, 8, 13, 0, 0, tzinfo=UTC)
    gap = Gap(start=start, end=start + timedelta(seconds=9), reason="drop")
    assert gap.duration == timedelta(seconds=9)
