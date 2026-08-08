# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Replaying a recorded session, and what the recording proves about the mapping.

The fixtures are real device output. The assertions here are chosen so that they
could only pass if the mapping from ``SyslogEntry`` onto :class:`Record` is
right -- particularly the two fields that read backwards, where ``filename`` is
the process and ``image_name`` is the library loaded into it. Swap them and this
file fails loudly rather than the viewer showing plausible nonsense.
"""

from __future__ import annotations

import asyncio
import collections
from typing import TYPE_CHECKING

import pytest

from ostrace.errors import StorageError
from ostrace.model import Level, Platform, Record
from ostrace.sources.replay import ReplaySource
from ostrace.storage.session import SessionWriter
from tests.helpers import DEVICE_TZ, make_gap, make_record

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from ostrace.model import DeviceInfo


async def collect(source: ReplaySource) -> list[Record]:
    return [record async for record in source.records()]


@pytest.fixture
def mixed(mixed_fixture: Path) -> list[Record]:
    return asyncio.run(collect(ReplaySource(mixed_fixture)))


class TestReplayMechanics:
    def test_a_bare_spool_replays(self, mixed: list[Record]) -> None:
        assert len(mixed) == 5000
        assert all(isinstance(record, Record) for record in mixed)

    def test_a_missing_path_is_an_error_not_an_empty_stream(self, tmp_path: Path) -> None:
        with pytest.raises(StorageError, match="no session or spool"):
            ReplaySource(tmp_path / "nope.jsonl.gz")

    def test_a_session_directory_replays_with_its_device_metadata(
        self,
        tmp_path: Path,
        device: DeviceInfo,
        mixed: list[Record],
    ) -> None:
        started: datetime = mixed[0].timestamp
        with SessionWriter(
            tmp_path / "cap",
            device=device,
            source="os_trace_relay",
            started_at=started,
        ) as writer:
            writer.write_many(mixed[:50])
            writer.write_gap(make_gap())

        source = ReplaySource(tmp_path / "cap.ostrace")
        info = asyncio.run(source.device_info())
        assert info.product_type == "iPhone18,2"
        assert info.utc_offset == DEVICE_TZ
        assert source.started_at == started
        assert len(asyncio.run(collect(source))) == 50
        assert len(source.gaps()) == 1

    def test_stream_includes_gaps_in_position(self, tmp_path: Path, device: DeviceInfo) -> None:
        with SessionWriter(
            tmp_path / "cap",
            device=device,
            source="os_trace_relay",
            started_at=make_record(0).timestamp,
        ) as writer:
            writer.write(make_record(0))
            writer.write_gap(make_gap())
            writer.write(make_record(1))

        async def kinds() -> list[str]:
            source = ReplaySource(tmp_path / "cap.ostrace")
            return [type(item).__name__ async for item in source.stream()]

        assert asyncio.run(kinds()) == ["Record", "Gap", "Record"]


class TestWhatTheCaptureProvesAboutTheMapping:
    def test_process_is_the_basename_of_the_process_path(self, mixed: list[Record]) -> None:
        for record in mixed:
            assert record.process == record.process_path.rsplit("/", 1)[-1]

    def test_a_shared_library_is_never_the_process(self, mixed: list[Record]) -> None:
        """The decisive check on the two fields that read backwards.

        ``entry.filename`` is the process executable; ``entry.image_name`` is the
        binary that emitted the record, often a dylib or framework loaded into
        it. Mapped the wrong way round, plugin output is attributed to whichever
        host process loaded it.

        A ``.dylib`` cannot be a process image, so its appearance in
        ``process_path`` would prove the swap. Note that the enclosing directory
        is *not* a discriminator: plenty of real daemons live inside a framework
        bundle, as in ``CloudKitDaemon.framework/Support/cloudd``.
        """
        assert not [r for r in mixed if r.process_path.endswith(".dylib")]
        assert [r for r in mixed if (r.image_path or "").endswith(".dylib")]

    def test_more_libraries_than_processes(self, mixed: list[Record]) -> None:
        """One process loads many libraries, so the distinct counts run this way
        round. Swapping the fields inverts the ratio."""
        processes = {record.process_path for record in mixed}
        images = {record.image_path for record in mixed if record.image_path}
        assert len(images) > len(processes)

    def test_the_two_paths_differ_for_most_records(self, mixed: list[Record]) -> None:
        differ = sum(1 for r in mixed if r.image_path and r.image_path != r.process_path)
        assert differ / len(mixed) > 0.5

    def test_one_pid_maps_to_one_process_name(self, mixed: list[Record]) -> None:
        """A pid is reused only after a process exits, which does not happen
        inside a five-second capture. Two names for one pid would mean the
        process field is coming from somewhere per-record."""
        names: dict[int, set[str]] = collections.defaultdict(set)
        for record in mixed:
            names[record.pid].add(record.process)
        ambiguous = {pid: found for pid, found in names.items() if len(found) > 1}
        assert ambiguous == {}

    def test_every_level_is_one_we_map(self, mixed: list[Record]) -> None:
        assert set(collections.Counter(r.level for r in mixed)) <= set(Level)

    def test_subsystem_coverage_matches_what_was_measured(self, mixed: list[Record]) -> None:
        """Documented as 96.8% on this device. A mapping bug shows up here first."""
        with_subsystem = sum(1 for record in mixed if record.subsystem)
        assert 0.9 < with_subsystem / len(mixed) <= 1.0

    def test_a_record_with_a_subsystem_also_has_a_category(self, mixed: list[Record]) -> None:
        """They arrive together in one label object; one without the other means
        the label was unpacked wrongly."""
        for record in mixed:
            assert (record.subsystem is None) == (record.category is None)

    def test_timestamps_carry_the_device_offset_not_the_hosts(self, mixed: list[Record]) -> None:
        for record in mixed[:200]:
            assert record.timestamp.tzinfo is not None
            assert record.timestamp.utcoffset() == DEVICE_TZ

    def test_timestamps_have_sub_second_resolution(self, mixed: list[Record]) -> None:
        """os_trace gives microseconds. If they were all zero we would have
        silently fallen back to the legacy one-second text format."""
        assert any(record.timestamp.microsecond for record in mixed)

    def test_platform_is_recorded(self, mixed: list[Record]) -> None:
        assert {record.platform for record in mixed} == {Platform.IOS}

    def test_messages_survive_with_their_newlines(self, mixed: list[Record]) -> None:
        """Around 1.5% of real records are multi-line. The record model keeps
        them intact; folding onto one line is an export concern, not a capture
        concern."""
        multiline = [r for r in mixed if "\n" in r.message]
        assert multiline, "the capture should contain multi-line messages"

    def test_apple_redaction_is_preserved_verbatim(self, mixed: list[Record]) -> None:
        """``<private>`` is applied by iOS before the data leaves the device.
        Nothing here may strip or rewrite it."""
        assert any("<private>" in record.message for record in mixed)


class TestErrorFixture:
    def test_it_contains_errors_and_faults(self, errors_fixture: Path) -> None:
        records = asyncio.run(collect(ReplaySource(errors_fixture)))
        levels = collections.Counter(record.level for record in records)
        assert levels[Level.ERROR] > 100
        assert levels[Level.FAULT] > 0
        assert all(record.is_error for record in records if record.level >= Level.ERROR)

    def test_is_error_agrees_with_the_level(self, errors_fixture: Path) -> None:
        records = asyncio.run(collect(ReplaySource(errors_fixture)))
        for record in records:
            assert record.is_error == (record.level in (Level.ERROR, Level.FAULT))
