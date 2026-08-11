# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Builders shared across the suite."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from ostrace.model import DeviceInfo, Gap, Level, Platform, Record
from ostrace.sources.base import SourceCloseMixin

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from ostrace.gui.windows.main import MainWindow

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(text: str) -> str:
    """Strip ANSI styling.

    Python 3.14's argparse colourises help output and CI sets FORCE_COLOR, so
    ``usage: ostrace`` arrives with escape sequences between the two words.
    Assertions are about what the CLI says, not how a terminal was asked to
    paint it.
    """
    return _ANSI.sub("", text)


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


class ScriptedSource(SourceCloseMixin):
    """A source that yields what it is told, and remembers being closed.

    ``delay`` is what makes it useful beyond a canned list: a real source can
    take arbitrarily long between records -- measured, up to forty seconds --
    and anything asserting what happens *while* a capture is still running
    needs a source that has not finished yet.
    """

    name = "scripted"

    def __init__(self, items: list[Record | Gap], *, delay: float = 0.0) -> None:
        self.items = items
        self.delay = delay
        self.closed = False

    async def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            udid="00000000-000000000000000A",
            name="Test iPhone",
            product_type="iPhone18,2",
            product_version="26.5.2",
            utc_offset=DEVICE_TZ,
            platform=Platform.IOS,
        )

    async def stream(self) -> AsyncGenerator[Record | Gap, None]:
        for item in self.items:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield item

    async def aclose(self) -> None:
        self.closed = True


def load(window: MainWindow, path: object) -> None:
    """Open a capture and read all of it, with no event loop to read it for us.

    The loader runs from a timer in the program and there is no timer offscreen,
    so tests step it by hand. Shared rather than written out again at each site:
    three copies of "drive the loader" drift, and a test that drives it slightly
    differently from its neighbours is a test whose failure means something
    slightly different.

    Two of the three callers used to take a single step, needing rows to exist
    rather than all of them. Reading the whole error fixture instead costs them
    about 10 ms apiece, measured, which is not worth a parameter on the one
    function that says how a capture is loaded.

    Typing-only import of ``MainWindow``: this module is imported by the
    interpreter sweep, which installs the package without Qt.
    """
    window.open_capture(path)  # type: ignore[arg-type]
    loader = window._loader
    assert loader is not None
    while loader.loaded < 10**9:
        before = loader.loaded
        loader._step()
        if loader.loaded == before:
            break


def make_gap(index: int = 0) -> Gap:
    start = datetime(2026, 8, 8, 13, 5, 0, tzinfo=UTC)
    return Gap(
        start=start,
        end=start + timedelta(seconds=4 + index),
        reason="the connection to the device was lost",
    )
