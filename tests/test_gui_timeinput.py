# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading what somebody types into `Go to Time`.

No Qt anywhere in here on purpose. This is the half of the feature with all the
cases in it, and none of them need a window to be wrong.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ostrace.gui.timeinput import parse_jump

#: The device's offset, deliberately not the host's and deliberately not UTC.
#: Every assertion below that reads the result back is checking that the answer
#: stayed on the device's clock rather than being quietly re-based on the one
#: the test is running on.
DEVICE = timezone(timedelta(hours=3))
ANCHOR = datetime(2026, 8, 10, 14, 30, 15, 500_000, tzinfo=DEVICE)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("14:22:31", datetime(2026, 8, 10, 14, 22, 31, tzinfo=DEVICE)),
        ("14:22:31.500", datetime(2026, 8, 10, 14, 22, 31, 500_000, tzinfo=DEVICE)),
        ("14:22:31.5", datetime(2026, 8, 10, 14, 22, 31, 500_000, tzinfo=DEVICE)),
        ("14:22", datetime(2026, 8, 10, 14, 22, tzinfo=DEVICE)),
        ("9:05", datetime(2026, 8, 10, 9, 5, tzinfo=DEVICE)),
        ("00:00", datetime(2026, 8, 10, 0, 0, tzinfo=DEVICE)),
        ("23:59:59", datetime(2026, 8, 10, 23, 59, 59, tzinfo=DEVICE)),
        ("2026-08-09 14:22:31", datetime(2026, 8, 9, 14, 22, 31, tzinfo=DEVICE)),
        ("2026-08-09T14:22:31", datetime(2026, 8, 9, 14, 22, 31, tzinfo=DEVICE)),
    ],
)
def test_a_clock_reading_lands_on_the_anchors_day(text: str, expected: datetime) -> None:
    """`.5` is half a second, not five microseconds.

    The fraction is left-justified into microseconds, which is the difference
    between landing where the reader meant and landing 499 milliseconds early
    every single time somebody types the short form.
    """
    assert parse_jump(text, anchor=ANCHOR) == expected


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("+30s", 30),
        ("-30s", -30),
        ("+2m", 120),
        ("-2m", -120),
        ("+1h", 3600),
        ("+1m30s", 90),
        ("-1h2m3s", -3723),
        ("+ 30 s", 30),
        ("+30S", 30),
    ],
)
def test_an_offset_is_measured_from_where_the_reader_is(text: str, seconds: int) -> None:
    assert parse_jump(text, anchor=ANCHOR) == ANCHOR + timedelta(seconds=seconds)


def test_the_answer_stays_on_the_devices_clock() -> None:
    """The host is a different clock in a frequently different zone.

    A target built on the host's offset would search a time the device never
    saw -- silently, and by exactly the difference between the two zones.
    """
    result = parse_jump("14:22:31", anchor=ANCHOR)

    assert result.tzinfo is DEVICE
    assert result.utcoffset() == timedelta(hours=3)


def test_a_dateless_reading_uses_the_day_the_reader_is_in() -> None:
    """Not the day the capture started.

    A capture that runs through midnight is the case: somebody reading rows
    from just after midnight and typing `00:05` means the one five minutes
    after where they are looking, not the one twenty-four hours earlier.
    """
    after_midnight = datetime(2026, 8, 11, 0, 2, tzinfo=DEVICE)

    assert parse_jump("00:05", anchor=after_midnight).day == 11
    assert parse_jump("2026-08-10 00:05", anchor=after_midnight).day == 10


@pytest.mark.parametrize(
    "text",
    ["", "   ", "nonsense", "14", "14:2", "1422:31", "+", "+30", "30s", "+30d", "14:22:31+", "::"],
)
def test_what_cannot_be_read_says_what_would_work(text: str) -> None:
    """Typing is not an error condition.

    The message names the shapes that do work, because the user is mid-attempt
    rather than having done something wrong.
    """
    with pytest.raises(ValueError, match="Try one of") as raised:
        parse_jump(text, anchor=ANCHOR)

    assert "+30s" in str(raised.value)


@pytest.mark.parametrize("text", ["24:00", "25:13", "14:60", "14:22:60"])
def test_a_time_that_is_not_a_time_is_refused(text: str) -> None:
    """Shaped like a clock reading and not one.

    Left to `datetime` these raise too, but with "hour must be in 0..23",
    which is a sentence about a constructor rather than about what was typed.
    """
    with pytest.raises(ValueError, match="not a time of day"):
        parse_jump(text, anchor=ANCHOR)
