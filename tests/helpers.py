# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Builders shared across the suite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from ostrace.model import Gap, Level, Platform, Record

FIXTURES = Path(__file__).parent / "fixtures"
MIXED = FIXTURES / "ios26-mixed.jsonl.gz"
ERRORS = FIXTURES / "ios26-errors.jsonl.gz"

#: The offset the test device reported (Europe/Istanbul at capture time).
DEVICE_TZ = timedelta(hours=3)


def make_record(
    index: int = 0,
    *,
    level: Level = Level.NOTICE,
    message: str | None = None,
    process: str = "cloudd",
) -> Record:
    """A synthetic record, for tests about *storage* rather than about parsing.

    Legitimate here because the session file format is ours: a round-trip test
    needs a value to round-trip, not evidence of what a device emits. Anything
    asserting how device output is *interpreted* uses the captured fixtures --
    see the note in ``conftest.py``.
    """
    return Record(
        timestamp=datetime(2026, 8, 8, 13, 0, index % 60, index, tzinfo=UTC),
        level=level,
        pid=147,
        process=process,
        process_path=f"/usr/libexec/{process}",
        subsystem="com.apple.cloudkit",
        category="default",
        thread_id=13570622 + index,
        image_path="/System/Library/PrivateFrameworks/CloudKit.framework/CloudKit",
        message=message if message is not None else f"record number {index}",
        platform=Platform.IOS,
    )


def make_gap(index: int = 0) -> Gap:
    start = datetime(2026, 8, 8, 13, 5, 0, tzinfo=UTC)
    return Gap(
        start=start,
        end=start + timedelta(seconds=4 + index),
        reason="ConnectionTerminatedError",
    )
