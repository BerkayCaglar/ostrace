# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading the one thing a user types that is a *time*.

`Go to Time` is the only navigation in the program that correlates the log with
the world outside it -- somebody watched their phone misbehave at twenty past
two, and every other way of finding that moment is scrolling. So the input has
to accept what a person actually writes down, which is a clock reading with no
date on it and, just as often, "half a minute before where I am".

**Timezone comes from the anchor, never from the host.** The anchor is the row
the reader is on, and it carries the *device's* offset. Building a target from
the host's clock would silently search a different zone -- the whole reason
`docs/formats/` requires aware timestamps.

**A date-less clock reading means that clock reading on the anchor's day.** A
capture that runs through midnight therefore reads `00:05` as the day the
reader is currently in rather than the day the capture started, which is the
answer that matches where they are looking. `2026-08-10 00:05` says the other
thing when the other thing is meant.

Pure, and Qt-free on purpose: this is the half worth testing exhaustively and
none of it needs a window.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

__all__ = ["EXAMPLES", "parse_jump"]

#: Shown in the dialog. The four shapes, in the order somebody would try them.
EXAMPLES = "14:22:31, 14:22:31.500, +30s, -2m"

#: Seconds in each unit a relative offset may use. Deliberately no `d`: a
#: capture that runs for a day is not one anybody scrolls through by day.
_UNITS = {"s": 1, "m": 60, "h": 3600}

_RELATIVE = re.compile(r"^(?P<sign>[+-])\s*(?P<body>(?:\d+\s*[smh]\s*)+)$", re.IGNORECASE)
_PART = re.compile(r"(\d+)\s*([smh])", re.IGNORECASE)
_DATED = re.compile(r"^(?P<day>\d{4}-\d{2}-\d{2})[ tT]+(?P<clock>.+)$")
_CLOCK = re.compile(
    r"^(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2})(?:\.(?P<fraction>\d{1,6}))?)?$"
)

_UNREADABLE = f"Not a time. Try one of: {EXAMPLES}"
_OUT_OF_RANGE = "That is not a time of day."


def parse_jump(text: str, *, anchor: datetime) -> datetime:
    """What ``text`` means, as an instant on the device's clock.

    ``anchor`` is where the reader is: it supplies the day for a clock reading
    with no date, the offset for every form, and the origin for a relative one.

    Raises `ValueError` carrying a sentence fit to show the user. Every failure
    here is somebody typing, which is not an error condition -- it is the
    normal way a text field is used -- so the message says what would work
    rather than what went wrong.
    """
    value = text.strip()
    if not value:
        raise ValueError(_UNREADABLE)

    relative = _RELATIVE.match(value)
    if relative is not None:
        seconds = sum(
            int(amount) * _UNITS[unit.lower()] for amount, unit in _PART.findall(relative["body"])
        )
        return anchor + timedelta(seconds=-seconds if relative["sign"] == "-" else seconds)

    dated = _DATED.match(value)
    day = date.fromisoformat(dated["day"]) if dated is not None else anchor.date()
    clock = _CLOCK.match(dated["clock"].strip() if dated is not None else value)
    if clock is None:
        raise ValueError(_UNREADABLE)

    hour, minute = int(clock["hour"]), int(clock["minute"])
    second = int(clock["second"] or 0)
    if hour > 23 or minute > 59 or second > 59:  # noqa: PLR2004 - a clock, not a magic number
        raise ValueError(_OUT_OF_RANGE)
    # Left-justified, so `.5` is half a second rather than five microseconds.
    microsecond = int((clock["fraction"] or "").ljust(6, "0") or 0)
    return datetime(
        day.year, day.month, day.day, hour, minute, second, microsecond, tzinfo=anchor.tzinfo
    )
