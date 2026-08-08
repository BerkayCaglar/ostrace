# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The single-file exporters: JSON Lines, plain text and markdown.

None of these is a contract in the sense the agent bundle is, so the tests are
about the properties that would make them useless if they broke: that the JSON
round-trips through the same decoder the session file uses, that a message
cannot escape its line or its code fence, and that the document says the true
thing about levels rather than the predecessor's inherited mistake.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from ostrace.exporters import EXPORTERS
from ostrace.exporters.jsonl import JsonLinesExporter
from ostrace.exporters.markdown import MarkdownExporter
from ostrace.exporters.plaintext import PlaintextExporter, line
from ostrace.model import Gap, Level, Record
from ostrace.storage.codec import decode
from ostrace.storage.spool import SpoolReader
from tests.helpers import MIXED, make_gap, make_record

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


def fixture_items() -> list[Record | Gap]:
    return list(SpoolReader(MIXED).items())


class TestJsonLines:
    def test_every_line_decodes_with_the_session_decoder(self, tmp_path: Path) -> None:
        """The whole point of reusing the encoder. If this file needed its own
        decoder, there would be two record shapes and one of them would rot."""
        items = fixture_items()
        result = JsonLinesExporter().export(items, tmp_path / "out.jsonl")

        decoded = [
            decode(json.loads(entry))
            for entry in result.destination.read_text(encoding="utf-8").splitlines()
        ]
        assert len(decoded) == len(items)
        assert [type(d) for d in decoded] == [type(i) for i in items]

    def test_records_round_trip_intact(self, tmp_path: Path) -> None:
        original = make_record(0, level=Level.FAULT, message="a\tb\nc")
        result = JsonLinesExporter().export([original], tmp_path / "out.jsonl")
        (back,) = [
            decode(json.loads(entry))
            for entry in result.destination.read_text(encoding="utf-8").splitlines()
        ]
        assert back == original

    def test_there_is_no_metadata_line(self, tmp_path: Path) -> None:
        """A first line shaped differently from every other breaks `jq`,
        `pandas.read_json(lines=True)` and every short script -- which is the
        entire audience for a `.jsonl` file."""
        result = JsonLinesExporter().export([make_record(0)], tmp_path / "out.jsonl")
        entries = result.destination.read_text(encoding="utf-8").splitlines()
        assert len(entries) == 1
        assert "_meta" not in entries[0]

    def test_gaps_survive_as_gaps(self, tmp_path: Path) -> None:
        result = JsonLinesExporter().export([make_record(0), make_gap(0)], tmp_path / "out.jsonl")
        decoded = [
            decode(json.loads(entry))
            for entry in result.destination.read_text(encoding="utf-8").splitlines()
        ]
        assert isinstance(decoded[1], Gap)
        assert result.records == 1

    def test_non_ascii_is_written_readably(self, tmp_path: Path) -> None:
        result = JsonLinesExporter().export(
            [make_record(0, message="session opened 接続完了")], tmp_path / "out.jsonl"
        )
        assert "session opened 接続完了" in result.destination.read_text(encoding="utf-8")


class TestPlaintext:
    def test_a_record_is_one_line(self, tmp_path: Path) -> None:
        result = PlaintextExporter().export(fixture_items(), tmp_path / "out.txt")
        text = result.destination.read_text(encoding="utf-8")
        assert len(text.splitlines()) == result.records

    def test_a_message_cannot_break_its_line(self, tmp_path: Path) -> None:
        result = PlaintextExporter().export(
            [make_record(0, message="first\nsecond\tthird")], tmp_path / "out.txt"
        )
        (only,) = result.destination.read_text(encoding="utf-8").splitlines()
        assert "first\\nsecond\\tthird" in only

    def test_the_columns_line_up(self) -> None:
        """A ragged edge destroys the only thing this format offers over the
        others."""
        prefixes = {
            line(make_record(0, level=level)).index("com.apple.cloudkit")
            for level in (Level.DEBUG, Level.USER_ACTION, Level.FAULT)
        }
        assert len(prefixes) == 1

    def test_an_overlong_value_is_truncated_visibly(self) -> None:
        rendered = line(make_record(0, process="a" * 60))
        assert "…" in rendered

    def test_truncating_the_process_never_costs_the_pid(self) -> None:
        """The pid is the last thing on the label and the field most often
        needed to correlate records. `duetexpertd(AppPredictionInternal…` names
        a process this capture contains eight of."""
        rendered = line(make_record(0, process="duetexpertd" + "x" * 40))
        assert "[147]" in rendered
        assert "…[147]" in rendered
        assert rendered.startswith("13:00:00")

    def test_a_gap_is_visible(self, tmp_path: Path) -> None:
        """A hole read as a quiet device is the wrong conclusion drawn from the
        right data."""
        result = PlaintextExporter().export(
            [make_record(0), make_gap(0), make_record(1)], tmp_path / "out.txt"
        )
        lines = result.destination.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3
        assert lines[1].startswith("---- gap ")

    def test_there_is_no_header(self, tmp_path: Path) -> None:
        result = PlaintextExporter().export([make_record(0)], tmp_path / "out.txt")
        (only,) = result.destination.read_text(encoding="utf-8").splitlines()
        assert only.startswith("13:00:00")


class TestMarkdown:
    def test_it_states_the_levels_ios_actually_emits(self, tmp_path: Path) -> None:
        """The predecessor documented `Warning` and `Critical`, which iOS does
        not emit -- it was reading a text stream that used different names. A
        reader who trusts that filters for a level that never appears."""
        result = MarkdownExporter().export([make_record(0)], tmp_path / "out.md")
        text = result.destination.read_text(encoding="utf-8")
        assert "`User Action`" in text
        assert "Warning" not in text.split("## Records")[0].replace("there is no `Warning`", "")

    def test_the_summary_counts_match_the_body(self, tmp_path: Path) -> None:
        items = fixture_items()
        result = MarkdownExporter().export(items, tmp_path / "out.md")
        text = result.destination.read_text(encoding="utf-8")

        _preamble, _, body = text.partition("```log\n")
        records = [entry for entry in body.splitlines() if entry != "```"]
        assert len(records) == result.records
        assert f"| Records | {result.records:,} |" in text

    def test_a_backtick_in_a_message_cannot_close_the_fence(self, tmp_path: Path) -> None:
        """Safe by construction rather than by escaping: a closing fence has to
        be a line of nothing but backticks, and every line here starts with a
        timestamp."""
        result = MarkdownExporter().export(
            [make_record(0, message="```"), make_record(1, message="after")],
            tmp_path / "out.md",
        )
        text = result.destination.read_text(encoding="utf-8")
        _, _, body = text.partition("```log\n")
        assert body.count("\n```") == 1
        assert "after" in body

    def test_the_working_file_is_removed(self, tmp_path: Path) -> None:
        """The body is streamed to a sidecar so the summary can be written
        first without holding the capture in memory. It must not survive."""
        result = MarkdownExporter().export(fixture_items(), tmp_path / "out.md")
        assert list(tmp_path.iterdir()) == [result.destination]

    def test_the_working_file_is_removed_even_when_the_stream_fails(self, tmp_path: Path) -> None:
        def exploding() -> Iterator[Record]:
            yield make_record(0)
            msg = "device went away"
            raise RuntimeError(msg)

        with pytest.raises(RuntimeError, match="device went away"):
            MarkdownExporter().export(exploding(), tmp_path / "out.md")
        assert not list(tmp_path.glob("*.part"))

    def test_the_device_is_named_when_it_is_known(self, tmp_path: Path) -> None:
        from ostrace.model import DeviceInfo

        device = DeviceInfo(
            udid="00008030-001A2B3C4D5E6F70",
            name="Test iPhone",
            product_type="iPhone18,2",
            product_version="26.5.2",
        )
        result = MarkdownExporter().export([make_record(0)], tmp_path / "out.md", device=device)
        text = result.destination.read_text(encoding="utf-8")
        assert "iPhone18,2" in text
        assert "00008030-001A2B3C4D5E6F70" in text

    def test_a_bare_spool_exports_without_a_device(self, tmp_path: Path) -> None:
        """A session file has metadata and a bare spool does not. Requiring it
        would make the offline path fail on exactly the files it exists for."""
        result = MarkdownExporter().export(fixture_items(), tmp_path / "out.md")
        assert "| UDID |" not in result.destination.read_text(encoding="utf-8")


class TestRegistry:
    @pytest.mark.parametrize("name", ["agent-bundle", "jsonl", "text", "markdown"])
    def test_every_exporter_is_registered_under_its_name(self, name: str) -> None:
        assert EXPORTERS[name].name == name

    def test_each_has_a_description_for_the_help_text(self) -> None:
        for exporter in EXPORTERS.values():
            assert exporter.description
            assert not exporter.description.endswith(".")
