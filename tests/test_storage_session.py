# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Session directories and their metadata sidecar."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ostrace.errors import (
    DestinationInUseError,
    StorageError,
    UnsupportedFormatVersionError,
)
from ostrace.storage.session import (
    FORMAT_VERSION,
    META_NAME,
    SPOOL_NAME,
    SessionReader,
    SessionWriter,
)
from tests.helpers import make_gap, make_record

if TYPE_CHECKING:
    from pathlib import Path

    from ostrace.model import DeviceInfo

STARTED = datetime(2026, 8, 8, 13, 0, tzinfo=UTC)


def write_session(path: Path, device: DeviceInfo, *, records: int = 3, gaps: int = 1) -> Path:
    with SessionWriter(
        path,
        device=device,
        source="os_trace_relay",
        started_at=STARTED,
        flags={"historical": True},
    ) as writer:
        writer.write_many([make_record(i) for i in range(records)])
        for index in range(gaps):
            writer.write_gap(make_gap(index))
        return writer.path


class TestWriter:
    def test_the_suffix_is_applied(self, tmp_path: Path, device: DeviceInfo) -> None:
        path = write_session(tmp_path / "capture", device)
        assert path.name == "capture.ostrace"
        assert (path / SPOOL_NAME).is_file()
        assert (path / META_NAME).is_file()

    def test_an_explicit_suffix_is_not_doubled(self, tmp_path: Path, device: DeviceInfo) -> None:
        path = write_session(tmp_path / "capture.ostrace", device)
        assert path.name == "capture.ostrace"

    def test_the_sidecar_exists_before_anything_is_written(
        self,
        tmp_path: Path,
        device: DeviceInfo,
    ) -> None:
        """An interrupted capture must still be identifiable."""
        writer = SessionWriter(
            tmp_path / "c",
            device=device,
            source="os_trace_relay",
            started_at=STARTED,
        )
        try:
            meta = json.loads((writer.path / META_NAME).read_text(encoding="utf-8"))
            assert meta["device"]["product_type"] == "iPhone18,2"
            assert meta["record_count"] == 0
            assert meta["ended_at"] is None
        finally:
            writer.close()

    def test_the_context_manager_stamps_when_the_session_ended(
        self,
        tmp_path: Path,
        device: DeviceInfo,
    ) -> None:
        """`ended_at` used to stay null for every session closed with `with`,
        which is how the sidecar tells a finished capture from a killed one."""
        with SessionWriter(
            tmp_path / "c",
            device=device,
            source="os_trace_relay",
            started_at=STARTED,
        ) as writer:
            writer.write(make_record(0))
            path = writer.path

        meta = json.loads((path / META_NAME).read_text(encoding="utf-8"))
        assert meta["ended_at"] is not None
        assert SessionReader(path).meta is not None

    def test_a_session_killed_before_close_has_no_end(
        self,
        tmp_path: Path,
        device: DeviceInfo,
    ) -> None:
        """The other half of the distinction: the sidecar written at open must
        stay null until close, or the two cases are indistinguishable."""
        writer = SessionWriter(
            tmp_path / "c",
            device=device,
            source="os_trace_relay",
            started_at=STARTED,
        )
        try:
            writer.write(make_record(0))
            meta = json.loads((writer.path / META_NAME).read_text(encoding="utf-8"))
            assert meta["ended_at"] is None
        finally:
            writer.close()

    def test_closing_records_the_final_counts(self, tmp_path: Path, device: DeviceInfo) -> None:
        ended = STARTED + timedelta(minutes=5)
        with SessionWriter(
            tmp_path / "c",
            device=device,
            source="os_trace_relay",
            started_at=STARTED,
        ) as writer:
            writer.write_many([make_record(i) for i in range(4)])
            writer.write_gap(make_gap())
            path = writer.path
            writer.close(ended_at=ended)

        meta = json.loads((path / META_NAME).read_text(encoding="utf-8"))
        assert meta["record_count"] == 4
        assert meta["gap_count"] == 1
        assert meta["ended_at"] == ended.isoformat()
        assert meta["format_version"] == FORMAT_VERSION
        assert meta["flags"] == {}


class TestReader:
    def test_round_trip(self, tmp_path: Path, device: DeviceInfo) -> None:
        path = write_session(tmp_path / "c", device, records=5, gaps=2)
        reader = SessionReader(path)

        assert reader.meta is not None
        assert reader.meta.device.udid == device.udid
        assert reader.meta.device.utc_offset == device.utc_offset
        assert reader.meta.source == "os_trace_relay"
        assert reader.meta.started_at == STARTED
        assert reader.meta.flags == {"historical": True}
        assert len(list(reader.records())) == 5
        assert len(list(SessionReader(path).gaps())) == 2

    def test_the_source_is_recorded_because_it_changes_interpretation(
        self,
        tmp_path: Path,
        device: DeviceInfo,
    ) -> None:
        """A session captured over the legacy relay has no subsystem on any
        record and nothing below the notice tier. Without knowing which service
        produced it, a reader cannot tell that from a quiet device."""
        with SessionWriter(
            tmp_path / "legacy",
            device=device,
            source="syslog_relay",
            started_at=STARTED,
        ) as writer:
            writer.write(make_record(0))
        assert SessionReader(writer.path).meta is not None
        assert SessionReader(writer.path).meta.source == "syslog_relay"  # type: ignore[union-attr]

    def test_a_missing_sidecar_loses_metadata_not_data(
        self,
        tmp_path: Path,
        device: DeviceInfo,
    ) -> None:
        path = write_session(tmp_path / "c", device, records=4)
        (path / META_NAME).unlink()

        reader = SessionReader(path)
        assert reader.meta is None
        assert len(list(reader.records())) == 4

    def test_a_corrupt_sidecar_loses_metadata_not_data(
        self,
        tmp_path: Path,
        device: DeviceInfo,
    ) -> None:
        """A capture killed mid-write leaves a half-written sidecar. Refusing to
        open the records because their description is damaged would be the wrong
        trade for a diagnostic tool."""
        path = write_session(tmp_path / "c", device, records=4)
        (path / META_NAME).write_text('{"format_version": 1, "dev', encoding="utf-8")

        reader = SessionReader(path)
        assert reader.meta is None
        assert len(list(reader.records())) == 4

    def test_a_newer_format_version_is_refused_loudly(
        self,
        tmp_path: Path,
        device: DeviceInfo,
    ) -> None:
        """The one metadata failure that must not degrade quietly: a file we do
        not understand may need fields we would silently ignore."""
        path = write_session(tmp_path / "c", device)
        meta = json.loads((path / META_NAME).read_text(encoding="utf-8"))
        meta["format_version"] = FORMAT_VERSION + 1
        (path / META_NAME).write_text(json.dumps(meta), encoding="utf-8")

        with pytest.raises(UnsupportedFormatVersionError, match="newer"):
            SessionReader(path)

    def test_a_directory_that_is_not_a_session(self, tmp_path: Path) -> None:
        (tmp_path / "empty").mkdir()
        with pytest.raises(StorageError, match=r"has no session\.jsonl\.gz"):
            SessionReader(tmp_path / "empty")

    def test_a_path_that_is_not_a_directory(self, tmp_path: Path) -> None:
        with pytest.raises(StorageError, match="not a session directory"):
            SessionReader(tmp_path / "nope")

    def test_a_session_still_being_written_reads_as_truncated(
        self,
        tmp_path: Path,
        device: DeviceInfo,
    ) -> None:
        writer = SessionWriter(
            tmp_path / "live",
            device=device,
            source="os_trace_relay",
            started_at=STARTED,
        )
        try:
            writer.write_many([make_record(i) for i in range(6)])
            writer.flush()

            reader = SessionReader(writer.path)
            assert len(list(reader.records())) == 6
            assert reader.truncated is True
        finally:
            writer.close()

        assert SessionReader(writer.path).truncated is False


def test_a_second_capture_refuses_to_overwrite_the_first(
    tmp_path: Path, device: DeviceInfo
) -> None:
    """`gzip.open(..., "wb")` truncates, so `capture -o ~/logs/today` run twice
    replaced the first run's records with no warning and exited successfully.

    A capture is the one thing here that cannot be regenerated -- the device has
    moved on -- so overwriting one by accident is the most expensive thing this
    package can do.
    """
    session = tmp_path / "today.ostrace"

    with SessionWriter(session, device=device, source="scripted", started_at=STARTED) as writer:
        writer.write(make_record(0))

    with pytest.raises(DestinationInUseError, match="already holds a capture"):
        SessionWriter(session, device=device, source="scripted", started_at=STARTED)

    assert len(list(SessionReader(session).records())) == 1, "the first capture survived"
