# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The gzip spool.

The tests that matter here are the ones about a file that is *not* closed.
Reading a completed gzip file is unremarkable; reading one that is still being
written, or one whose process was killed, is what this format exists for and
where it has gone wrong before.
"""

from __future__ import annotations

import gzip
import json
from typing import TYPE_CHECKING

import pytest

from ostrace.model import Gap, Level, Record
from ostrace.storage.codec import decode, encode_gap, encode_record
from ostrace.storage.spool import SpoolReader, SpoolWriter
from tests.helpers import make_gap, make_record

if TYPE_CHECKING:
    from pathlib import Path


def test_round_trip_preserves_every_field(tmp_path: Path) -> None:
    original = make_record(7, level=Level.FAULT)
    path = tmp_path / "s.jsonl.gz"
    with SpoolWriter(path) as writer:
        writer.write(original)

    (restored,) = SpoolReader(path).records()
    assert restored == original


def test_round_trip_of_awkward_messages(tmp_path: Path) -> None:
    """Newlines, tabs, backslashes, non-ASCII and Apple's own redaction marker.

    1.5% of real records contain a newline or a tab, and two in twenty-five
    thousand contain a literal backslash-n sequence, so the distinction between
    the two is not hypothetical.
    """
    messages = [
        "plain",
        "two\nlines",
        "tab\there",
        "windows\r\nnewline",
        "literal backslash-n: \\n not a newline",
        "backslash at end \\",
        "unicode: Berkay'ın iPhone'u — ölçüm",  # noqa: RUF001 - the point is non-ASCII
        "redacted <private> value",
        "",
        "   leading and trailing   ",
    ]
    path = tmp_path / "s.jsonl.gz"
    with SpoolWriter(path) as writer:
        for index, message in enumerate(messages):
            writer.write(make_record(index, message=message))

    restored = [record.message for record in SpoolReader(path).records()]
    assert restored == messages


def test_gaps_are_written_in_stream_order(tmp_path: Path) -> None:
    path = tmp_path / "s.jsonl.gz"
    with SpoolWriter(path) as writer:
        writer.write(make_record(0))
        writer.write_gap(make_gap())
        writer.write(make_record(1))

    items = list(SpoolReader(path))
    assert [type(item) for item in items] == [Record, Gap, Record]
    assert len(list(SpoolReader(path).records())) == 2
    assert len(list(SpoolReader(path).gaps())) == 1


def test_scanning_for_gaps_does_not_decode_every_record(tmp_path: Path) -> None:
    """A capture holds millions of records and a handful of gaps.

    ``gaps()`` filters on the raw object before decoding; building a full
    Record for each line only to discard it more than doubled the cost of this
    scan. The behaviour must stay identical, which is what this asserts --
    including that a damaged *record* does not disturb a gap scan.
    """
    path = tmp_path / "s.jsonl.gz"
    with gzip.open(path, "wb") as raw:
        for index in range(20):
            raw.write(json.dumps(encode_record(make_record(index))).encode() + b"\n")
        raw.write(b'{"ts": "nonsense", "level": "NOTICE"}\n')
        raw.write(json.dumps(encode_gap(make_gap())).encode() + b"\n")

    gaps = list(SpoolReader(path).gaps())
    assert len(gaps) == 1
    assert gaps[0] == make_gap()


def test_counts(tmp_path: Path) -> None:
    path = tmp_path / "s.jsonl.gz"
    with SpoolWriter(path) as writer:
        writer.write_many([make_record(i) for i in range(5)])
        writer.write_gap(make_gap())
        assert writer.record_count == 5
        assert writer.gap_count == 1


class TestReadableWhileWriting:
    """Live export during capture depends on this, and so does crash recovery."""

    def test_records_are_readable_before_close(self, tmp_path: Path) -> None:
        path = tmp_path / "s.jsonl.gz"
        writer = SpoolWriter(path, flush_every=1000)
        try:
            writer.write_many([make_record(i) for i in range(10)])
            writer.flush()

            reader = SpoolReader(path)
            assert len(list(reader.records())) == 10
            assert reader.truncated is True, "an unclosed spool has no gzip trailer"

            writer.write_many([make_record(i) for i in range(10, 15)])
            writer.flush()
            assert len(list(SpoolReader(path).records())) == 15
        finally:
            writer.close()

        closed = SpoolReader(path)
        assert len(list(closed.records())) == 15
        assert closed.truncated is False

    def test_the_last_flushed_record_is_not_dropped(self, tmp_path: Path) -> None:
        """The regression this structure exists to prevent.

        An earlier implementation caught the missing-trailer error before its
        final ``yield``, so every unclosed file silently lost its last record --
        the most recent one, which is the one a live view is showing.
        """
        path = tmp_path / "s.jsonl.gz"
        writer = SpoolWriter(path, flush_every=1000)
        try:
            for index in range(20):
                writer.write(make_record(index, message=f"line {index}"))
            writer.flush()

            messages = [record.message for record in SpoolReader(path).records()]
        finally:
            writer.close()

        assert messages[-1] == "line 19"
        assert len(messages) == 20

    def test_truncated_answers_correctly_before_anything_is_read(self, tmp_path: Path) -> None:
        """Asking "is this capture still being written?" is a question you ask
        *before* reading it. It used to be a plain attribute assigned at the end
        of a full pass, so the natural order always got False."""
        path = tmp_path / "s.jsonl.gz"
        writer = SpoolWriter(path, flush_every=1)
        try:
            writer.write(make_record(0))
            assert SpoolReader(path).truncated is True
        finally:
            writer.close()

        assert SpoolReader(path).truncated is False

    def test_truncated_is_correct_when_iteration_stops_early(self, tmp_path: Path) -> None:
        path = tmp_path / "s.jsonl.gz"
        with SpoolWriter(path, flush_every=1) as writer:
            writer.write_many([make_record(i) for i in range(10)])

        reader = SpoolReader(path)
        next(iter(reader.records()))
        assert reader.truncated is False

    def test_unflushed_records_are_simply_absent(self, tmp_path: Path) -> None:
        """Not an error: they are still in the compressor, not on disk."""
        path = tmp_path / "s.jsonl.gz"
        writer = SpoolWriter(path, flush_every=10_000)
        try:
            writer.write_many([make_record(i) for i in range(5)])
            count = len(list(SpoolReader(path).records()))
        finally:
            writer.close()
        assert count <= 5


class TestDamagedFiles:
    def test_a_file_cut_mid_stream_yields_what_survives(self, tmp_path: Path) -> None:
        path = tmp_path / "s.jsonl.gz"
        with SpoolWriter(path, flush_every=10) as writer:
            writer.write_many([make_record(i) for i in range(200)])

        cut = tmp_path / "cut.jsonl.gz"
        cut.write_bytes(path.read_bytes()[: int(path.stat().st_size * 0.6)])

        reader = SpoolReader(cut)
        survived = list(reader.records())
        assert 0 < len(survived) < 200
        assert reader.truncated is True

    def test_a_malformed_line_is_skipped_and_counted(self, tmp_path: Path) -> None:
        path = tmp_path / "s.jsonl.gz"
        with gzip.open(path, "wb") as raw:
            raw.write(json.dumps(encode_record(make_record(0))).encode() + b"\n")
            raw.write(b"{ this is not json\n")
            raw.write(json.dumps(encode_record(make_record(1))).encode() + b"\n")

        reader = SpoolReader(path)
        assert len(list(reader.records())) == 2
        assert reader.malformed == 1

    def test_the_malformed_count_describes_the_file_not_the_reader(
        self,
        tmp_path: Path,
    ) -> None:
        """It used to accumulate, so a second scan reported twice the damage."""
        path = tmp_path / "s.jsonl.gz"
        with gzip.open(path, "wb") as raw:
            raw.write(b"{ not json\n")
            raw.write(json.dumps(encode_record(make_record(0))).encode() + b"\n")

        reader = SpoolReader(path)
        for _ in range(3):
            list(reader.records())
            assert reader.malformed == 1

    def test_a_line_that_is_not_an_object_is_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "s.jsonl.gz"
        with gzip.open(path, "wb") as raw:
            raw.write(b"[1, 2, 3]\n")
            raw.write(json.dumps(encode_record(make_record(0))).encode() + b"\n")

        reader = SpoolReader(path)
        assert len(list(reader.records())) == 1
        assert reader.malformed == 1

    def test_a_record_with_a_naive_timestamp_is_rejected(self, tmp_path: Path) -> None:
        """No writer of ours produces one, so it means something else wrote it.

        Guessing a zone would turn a visibly wrong file into a plausibly wrong
        one, which is worse.
        """
        obj = encode_record(make_record(0))
        obj["ts"] = "2026-08-08T13:00:00"

        path = tmp_path / "s.jsonl.gz"
        with gzip.open(path, "wb") as raw:
            raw.write(json.dumps(obj).encode() + b"\n")

        reader = SpoolReader(path)
        assert list(reader.records()) == []
        assert reader.malformed == 1


def test_unknown_keys_are_ignored_so_the_format_can_grow() -> None:
    obj = encode_record(make_record(0))
    obj["a_field_from_the_future"] = {"nested": True}
    assert isinstance(decode(obj), Record)


def test_writing_after_close_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "s.jsonl.gz"
    writer = SpoolWriter(path)
    writer.close()
    with pytest.raises(ValueError, match="closed"):
        writer.write(make_record(0))
