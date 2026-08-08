# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The shared vocabulary: :class:`Level`, :class:`Record`, :class:`DeviceInfo`.

Everything downstream of ``ostrace.sources`` speaks in these types and never
learns which device, transport or library produced them.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from enum import IntEnum, StrEnum
from pathlib import PurePosixPath
from typing import Any

__all__ = ["DeviceInfo", "Gap", "Level", "Platform", "Record"]


class Platform(StrEnum):
    """Which kind of device a record came from."""

    IOS = "ios"


class Level(IntEnum):
    """Severity, ordered.

    This is deliberately *our* enum rather than Apple's, for a reason that is
    sharper than portability: Apple's values are not severity-ordered.
    ``SyslogLogLevel`` on iOS 26 is ``NOTICE=0, INFO=1, DEBUG=2,
    USER_ACTION=3, ERROR=16, FAULT=17`` -- so ``level >= NOTICE`` is true of
    every record, and sorting by the raw value puts DEBUG above NOTICE. Any
    comparison has to go through a mapping, so the mapping may as well produce
    something that compares correctly.

    Values are spaced by ten. Android's ``WARN`` will land at 50 when a logcat
    source is added, and other levels can be inserted without renumbering.
    Nothing on disk stores these numbers -- session files and exports store the
    names -- so adding a level is not a format change.
    """

    DEBUG = 10
    INFO = 20
    NOTICE = 30
    USER_ACTION = 40
    ERROR = 60
    FAULT = 70

    @property
    def title(self) -> str:
        """Display form: ``Debug``, ``User Action``."""
        return self.name.replace("_", " ").title()

    @classmethod
    def parse(cls, text: str) -> Level:
        """Parse a level from user input or from a session file.

        Accepts the canonical name in any case, the display form, and the
        common abbreviations people actually type at a command line.
        """
        key = text.strip().upper().replace(" ", "_").replace("-", "_")
        if key in cls.__members__:
            return cls[key]
        alias = _LEVEL_ALIASES.get(key)
        if alias is not None:
            return alias
        msg = f"unknown level {text!r}; expected one of {', '.join(m.name for m in cls)}"
        raise ValueError(msg)


_LEVEL_ALIASES: dict[str, Level] = {
    "D": Level.DEBUG,
    "DBG": Level.DEBUG,
    "I": Level.INFO,
    "N": Level.NOTICE,
    "DEFAULT": Level.NOTICE,  # what Apple's own tooling calls this tier
    "E": Level.ERROR,
    "ERR": Level.ERROR,
    "F": Level.FAULT,
    "CRITICAL": Level.FAULT,
}


def _intern(value: str | None) -> str | None:
    """Intern a repeated string field, tolerating ``None``.

    Process names, subsystems and categories repeat across nearly every record;
    at a few hundred thousand retained records the saving is real.
    """
    return sys.intern(value) if value is not None else None


@dataclass(frozen=True, slots=True)
class Record:
    """One log record, from any platform.

    ``timestamp`` is timezone-aware. The device reports naive local time, so the
    source attaches the device's own UTC offset -- not the host's, which is a
    different clock and frequently a different zone.
    """

    timestamp: datetime
    level: Level
    pid: int
    #: Basename of :attr:`process_path`.
    process: str
    #: Absolute path of the process executable on the device.
    process_path: str
    subsystem: str | None
    category: str | None
    thread_id: int | None
    #: The binary that emitted the record, when it is not the process itself --
    #: a framework or plugin loaded into it. Differs from ``process_path`` in
    #: roughly nine records out of ten.
    image_path: str | None
    message: str
    platform: Platform = Platform.IOS

    def __post_init__(self) -> None:
        for name in ("process", "process_path", "subsystem", "category", "image_path"):
            object.__setattr__(self, name, _intern(getattr(self, name)))

    @property
    def is_error(self) -> bool:
        return self.level >= Level.ERROR

    @property
    def image(self) -> str | None:
        """Basename of :attr:`image_path`, when it differs from the process."""
        if self.image_path is None:
            return None
        name = PurePosixPath(self.image_path).name
        return None if name == self.process else name

    @property
    def process_label(self) -> str:
        """``dasd[83]``, or ``backboardd(ColourSensorFilterPlugin)[70]``.

        The parenthesised part names the emitting library. It is what makes a
        record attributable to a plugin rather than to whatever host process
        happened to load it.
        """
        image = self.image
        if image is None:
            return f"{self.process}[{self.pid}]"
        return f"{self.process}({image})[{self.pid}]"


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Identity and clock of the device a session came from."""

    udid: str
    name: str
    product_type: str
    product_version: str
    build_version: str | None = None
    #: ``usb`` or ``network``.
    connection: str = "usb"
    #: IANA zone name as the device reports it, e.g. ``Europe/Istanbul``.
    timezone_name: str | None = None
    #: The device's offset from UTC at the moment the session started.
    utc_offset: timedelta | None = None
    #: Difference between the device clock and this host's, if measured.
    clock_skew: timedelta | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def tzinfo(self) -> timezone:
        """The timezone to attach to the device's naive timestamps.

        A fixed offset rather than a named zone. Named zones would handle a
        capture that crosses a daylight-saving boundary more correctly, but the
        device reports naive local time, so the hour that repeats at the
        boundary is genuinely ambiguous in the data -- a named zone would
        resolve it silently and arbitrarily. A fixed offset is wrong in the same
        place but obviously so.

        Falls back to UTC when the device did not report an offset, which is
        visible in the data rather than plausible-looking.
        """
        return timezone(self.utc_offset) if self.utc_offset is not None else UTC

    @property
    def label(self) -> str:
        """``Berkay's iPhone (iPhone18,2, iOS 26.5.2)``."""
        return f"{self.name} ({self.product_type}, iOS {self.product_version})"


@dataclass(frozen=True, slots=True)
class Gap:
    """A stretch of the capture that was lost.

    Written into the session file when a dropped connection is re-established.
    Records the device emitted during the gap are unrecoverable -- nothing
    buffers them -- so exports state the gap rather than close over it. A log
    with an unlabelled hole is worse than one with a labelled hole, because a
    reader draws conclusions from the absence.
    """

    start: datetime
    end: datetime
    reason: str

    @property
    def duration(self) -> timedelta:
        return self.end - self.start
