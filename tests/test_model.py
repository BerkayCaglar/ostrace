# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The shared vocabulary."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

import pytest

from ostrace.model import DeviceInfo, Gap, Level, Platform, Record
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
        )
        assert record.image == "ColourSensorFilterPlugin"
        assert record.process_label == "backboardd(ColourSensorFilterPlugin)[70]"

    def test_is_error(self) -> None:
        assert not make_record(level=Level.NOTICE).is_error
        assert make_record(level=Level.ERROR).is_error
        assert make_record(level=Level.FAULT).is_error

    def test_platform_defaults_to_ios_and_is_a_plain_string_on_the_wire(self) -> None:
        assert make_record().platform is Platform.IOS
        assert str(Platform.IOS) == "ios"


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


def test_gap_duration() -> None:
    start = datetime(2026, 8, 8, 13, 0, 0, tzinfo=UTC)
    gap = Gap(start=start, end=start + timedelta(seconds=9), reason="drop")
    assert gap.duration == timedelta(seconds=9)
