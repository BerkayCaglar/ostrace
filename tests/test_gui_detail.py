# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The detail pane, checked against real device output.

Real records rather than synthetics, because what this pane is *for* is showing
fields whose meaning came from the device: which of two paths is the executable
and which is the loaded library, whether a subsystem was present, what the
device's UTC offset actually was. A hand-written record would agree with
whatever the pane happened to do.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from ostrace.model import Gap, Record
from ostrace.storage.spool import SpoolReader
from tests.helpers import MIXED

pytest.importorskip("PySide6", reason="the gui extra is not installed")

from ostrace.gui.widgets.detail_pane import ABSENT, DetailPane

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def records() -> list[Record]:
    return [item for item in SpoolReader(MIXED).items() if isinstance(item, Record)]


@pytest.fixture
def pane(qt_app: object) -> DetailPane:
    del qt_app
    return DetailPane()


def test_nothing_is_selected_to_begin_with(pane: DetailPane) -> None:
    """An empty pane says so, rather than showing a form full of dashes."""
    assert pane.field("Nothing selected") is not None


def test_both_clocks_and_their_difference(pane: DetailPane, records: list[Record]) -> None:
    """The pane is where this project's timestamp rule becomes visible.

    A record's timestamp carries the *device's* UTC offset, because the host is
    a different clock in a frequently different zone. Nothing on screen says so
    until the two are shown together with the delta between them.
    """
    record = records[0]
    host_now = record.timestamp - timedelta(seconds=1.5)
    pane.show_record(record, host_now)

    assert pane.field("Device time") is not None
    assert pane.field("Host time") is not None
    assert pane.field("Difference") == "+1.500 s"


def test_the_device_offset_is_not_silently_dropped(pane: DetailPane, records: list[Record]) -> None:
    """The rendered device time carries an offset, not a bare local time."""
    record = records[0]
    pane.show_record(record)
    shown = pane.field("Device time")
    assert shown is not None
    assert shown[-5:].lstrip("+-").isdigit(), f"no UTC offset in {shown!r}"


def test_the_two_paths_are_shown_as_different_things(
    pane: DetailPane, records: list[Record]
) -> None:
    """``process_path`` is the executable; ``image_path`` is the library loaded
    into it. They read backwards and differ in about nine records in ten, which
    is exactly why both are on screen with distinct labels."""
    with_both = next(r for r in records if r.image_path and r.process_path)
    pane.show_record(with_both)
    assert pane.field("Process path") != pane.field("Image")


def test_absent_fields_use_the_exporters_spelling(pane: DetailPane, records: list[Record]) -> None:
    """A value copied out of this pane should match what a bundle would hold."""
    without_subsystem = next(r for r in records if r.subsystem is None)
    pane.show_record(without_subsystem)
    assert pane.field("Subsystem") == ABSENT


def test_a_gap_says_plainly_that_the_records_are_unrecoverable(pane: DetailPane) -> None:
    """A gap is a fact about the capture, not an apologetic aside.

    It gets the same treatment as a record, and it states the one thing a
    reader most needs to know: that nothing buffered what is missing, so there
    is nowhere else to look for it.
    """
    records = [item for item in SpoolReader(MIXED).items() if isinstance(item, Record)]
    gap = Gap(
        start=records[0].timestamp,
        end=records[0].timestamp + timedelta(seconds=4),
        reason="connection dropped",
    )
    pane.show_gap(gap)

    assert pane.field("Reason") == "connection dropped"
    assert pane.field("Duration") == "4.000 s"
    recoverable = pane.field("Recoverable")
    assert recoverable is not None
    assert recoverable.startswith("No.")


def test_show_item_dispatches_on_the_kind(pane: DetailPane, records: list[Record]) -> None:
    """``Gap`` travels in the stream alongside records, so whatever the table
    hands the pane is one of two types and the pane sorts it out itself."""
    pane.show_item(records[0])
    assert pane.field("Message") is not None

    pane.show_item(
        Gap(
            start=records[0].timestamp,
            end=records[0].timestamp + timedelta(seconds=1),
            reason="device disconnected",
        )
    )
    assert pane.field("Message") is None
    assert pane.field("Reason") == "device disconnected"
