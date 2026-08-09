# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""``ostrace export``.

No device anywhere in this file. Export is the one command that needs none, and
the committed captures are its real input -- so these tests run the actual
command against real data on all three operating systems in CI.
"""

from __future__ import annotations

import datetime as dt
import shutil
from typing import TYPE_CHECKING

import pytest

from ostrace import cli
from ostrace.exporters import EXPORTERS
from tests.helpers import ERRORS, MIXED, plain

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def capture(tmp_path: Path) -> Path:
    """A capture file somewhere writable, so exports land beside it."""
    destination = tmp_path / "ios26-mixed.jsonl.gz"
    shutil.copy(MIXED, destination)
    return destination


class TestDefaults:
    def test_it_writes_a_bundle_beside_the_capture(
        self, capture: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The default is the one format that loses nothing. Everything else is
        a summary, and a default that quietly discards data is a bad default."""
        assert cli.main(["export", str(capture)]) == cli.EXIT_OK

        bundle = capture.parent / "ios26-mixed-bundle"
        assert bundle.is_dir()
        assert (bundle / "session.log").exists()
        out = capsys.readouterr().out
        assert "5,000 records" in out
        assert str(bundle) in out

    def test_the_capture_suffix_is_not_carried_into_the_name(self, capture: Path) -> None:
        """`Path.stem` would take `ios26-mixed.jsonl.gz` down to
        `ios26-mixed.jsonl` and name the export after a file extension."""
        assert cli.main(["export", str(capture), "-q"]) == cli.EXIT_OK
        assert (capture.parent / "ios26-mixed-bundle").is_dir()

    @pytest.mark.parametrize(
        ("fmt", "expected"),
        [
            ("jsonl", "ios26-mixed.jsonl"),
            ("text", "ios26-mixed.log"),
            ("markdown", "ios26-mixed.md"),
            ("ai-report", "ios26-mixed-report.md"),
            ("trace", "ios26-mixed-trace.md"),
        ],
    )
    def test_each_format_names_its_own_output(self, capture: Path, fmt: str, expected: str) -> None:
        assert cli.main(["export", str(capture), "-f", fmt, "-q"]) == cli.EXIT_OK
        assert (capture.parent / expected).exists()

    def test_an_explicit_output_wins(self, capture: Path, tmp_path: Path) -> None:
        target = tmp_path / "somewhere" / "else.md"
        assert cli.main(["export", str(capture), "-f", "markdown", "-o", str(target), "-q"]) == (
            cli.EXIT_OK
        )
        assert target.exists()

    def test_quiet_prints_only_the_destination(
        self, capture: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """So `ostrace export ... -q` composes with a shell."""
        assert cli.main(["export", str(capture), "-q"]) == cli.EXIT_OK
        out = capsys.readouterr().out.splitlines()
        assert out == [str(capture.parent / "ios26-mixed-bundle")]


class TestRegistryDrivesTheInterface:
    def test_every_registered_format_is_accepted(self, capture: Path) -> None:
        """Registering an exporter is all it should take to expose it."""
        for name in EXPORTERS:
            assert cli.main(["export", str(capture), "-f", name, "-q"]) == cli.EXIT_OK

    def test_an_unknown_format_is_rejected_by_the_parser(self, capture: Path) -> None:
        with pytest.raises(SystemExit) as excinfo:
            cli.main(["export", str(capture), "-f", "nonsense"])
        assert excinfo.value.code == 2

    def test_the_help_describes_each_format(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit):
            cli.main(["export", "--help"])
        help_text = plain(capsys.readouterr().out)
        for name, exporter in EXPORTERS.items():
            assert name in help_text
            assert exporter.description in help_text


class TestWarnings:
    def test_a_missing_capture_is_an_error_with_a_hint(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.main(["export", str(tmp_path / "nope.jsonl.gz")]) == cli.EXIT_ERROR
        err = capsys.readouterr().err
        assert "no capture at" in err
        assert "session directory or a .jsonl.gz" in err

    def test_gaps_are_reported_to_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A hole in the capture changes what an absence in the export means,
        so it cannot be left for the reader to notice."""
        from ostrace.model import DeviceInfo
        from ostrace.storage.session import SessionWriter
        from tests.helpers import make_gap, make_record

        session = tmp_path / "gappy.ostrace"
        device = DeviceInfo(udid="u", name="Test", product_type="iPhone18,2", product_version="26")
        started = dt.datetime(2026, 8, 8, 13, 0, tzinfo=dt.UTC)
        with SessionWriter(session, device=device, source="replay", started_at=started) as writer:
            writer.write(make_record(0))
            writer.write_gap(make_gap(0))
            writer.write(make_record(1))

        assert cli.main(["export", str(session)]) == cli.EXIT_OK
        assert "1 gap(s) in the capture" in capsys.readouterr().err

    def test_an_empty_capture_says_so(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Nought records and a successful export look identical otherwise."""
        from ostrace.model import DeviceInfo
        from ostrace.storage.session import SessionWriter

        session = tmp_path / "empty.ostrace"
        device = DeviceInfo(udid="u", name="Test", product_type="iPhone18,2", product_version="26")
        started = dt.datetime(2026, 8, 8, 13, 0, tzinfo=dt.UTC)
        with SessionWriter(session, device=device, source="replay", started_at=started):
            pass

        assert cli.main(["export", str(session)]) == cli.EXIT_OK
        assert "contains no records" in capsys.readouterr().err

    def test_the_budget_flag_says_when_it_does_nothing(
        self, capture: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Silently ignoring a flag teaches the user it worked."""
        assert cli.main(["export", str(capture), "-f", "text", "--budget-tokens", "500"]) == (
            cli.EXIT_OK
        )
        assert "does not apply to 'text'" in capsys.readouterr().err

    def test_the_budget_is_applied_to_the_report(self, capture: Path, tmp_path: Path) -> None:
        small = tmp_path / "small.md"
        large = tmp_path / "large.md"
        cli.main(
            [
                "export",
                str(capture),
                "-f",
                "ai-report",
                "--budget-tokens",
                "1000",
                "-o",
                str(small),
                "-q",
            ]
        )
        cli.main(
            [
                "export",
                str(capture),
                "-f",
                "ai-report",
                "--budget-tokens",
                "0",
                "-o",
                str(large),
                "-q",
            ]
        )
        assert small.stat().st_size < large.stat().st_size


class TestSessionsAndSpools:
    def test_a_session_directory_supplies_the_device(self, tmp_path: Path) -> None:
        """A session has metadata and a bare spool does not. Both must export."""
        from ostrace.model import DeviceInfo
        from ostrace.storage.session import SessionWriter
        from tests.helpers import make_record

        session = tmp_path / "named.ostrace"
        device = DeviceInfo(
            udid="00008030-001A2B3C4D5E6F70",
            name="Test iPhone",
            product_type="iPhone18,2",
            product_version="26.5.2",
        )
        started = dt.datetime(2026, 8, 8, 13, 0, tzinfo=dt.UTC)
        with SessionWriter(
            session, device=device, source="os_trace_relay", started_at=started
        ) as writer:
            writer.write(make_record(0))

        assert cli.main(["export", str(session), "-f", "markdown", "-q"]) == cli.EXIT_OK
        exported = (tmp_path / "named.md").read_text(encoding="utf-8")
        assert "iPhone18,2" in exported
        assert "00008030-001A2B3C4D5E6F70" in exported

    def test_a_bare_spool_exports_without_a_device(self, capture: Path) -> None:
        assert cli.main(["export", str(capture), "-f", "markdown", "-q"]) == cli.EXIT_OK
        exported = (capture.parent / "ios26-mixed.md").read_text(encoding="utf-8")
        assert "| UDID |" not in exported

    def test_the_error_heavy_capture_exports_too(self, tmp_path: Path) -> None:
        destination = tmp_path / "ios26-errors.jsonl.gz"
        shutil.copy(ERRORS, destination)
        assert cli.main(["export", str(destination), "-f", "trace", "-q"]) == cli.EXIT_OK
        assert (tmp_path / "ios26-errors-trace.md").exists()


class TestItNeverEatsTheCapture:
    """The worst thing this package can do, and it did it silently.

    ``.jsonl`` is both an ending `paths` strips from a capture name and the
    jsonl exporter's suffix, so the default destination for
    ``ostrace export capture.jsonl -f jsonl`` was the input path. The exporter
    opened it for writing while the reader was still a lazy iterator over it.
    Measured before the fix: a 2.2 MB capture became zero bytes, the command
    printed ``0 records -> jsonl`` and exited successfully.
    """

    @pytest.fixture
    def plain_capture(self, tmp_path: Path) -> Path:
        """The same fixture, uncompressed, so its name ends in ``.jsonl``."""
        import gzip

        destination = tmp_path / "capture.jsonl"
        destination.write_bytes(gzip.decompress(MIXED.read_bytes()))
        return destination

    def test_the_default_destination_never_lands_on_the_input(
        self, plain_capture: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        before = plain_capture.read_bytes()

        assert cli.main(["export", str(plain_capture), "-f", "jsonl"]) == cli.EXIT_ERROR

        assert plain_capture.read_bytes() == before, "the capture was modified"
        assert "over the capture" in plain(capsys.readouterr().err)

    def test_an_explicit_output_at_the_input_is_refused_too(self, plain_capture: Path) -> None:
        before = plain_capture.read_bytes()

        assert (
            cli.main(["export", str(plain_capture), "-f", "markdown", "-o", str(plain_capture)])
            == cli.EXIT_ERROR
        )

        assert plain_capture.read_bytes() == before

    def test_the_same_file_spelled_differently_is_still_the_same_file(
        self, plain_capture: Path
    ) -> None:
        """A relative path and an absolute one name one file, and truncating it
        does not care which spelling asked."""
        indirect = plain_capture.parent / "." / plain_capture.name
        assert (
            cli.main(["export", str(plain_capture), "-f", "markdown", "-o", str(indirect)])
            == cli.EXIT_ERROR
        )

    def test_a_different_format_beside_the_same_capture_still_works(
        self, plain_capture: Path
    ) -> None:
        """The guard must not refuse the ordinary case."""
        assert cli.main(["export", str(plain_capture), "-f", "markdown", "-q"]) == cli.EXIT_OK
        assert (plain_capture.parent / "capture.md").is_file()


class TestItSaysWhatItCouldNotRead:
    def test_a_damaged_line_is_declared(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The one omission the package did not declare.

        The readers have always counted lines they could not decode, and until
        now nothing read the count -- so an export quietly missing records was
        indistinguishable from a device that had been quiet.
        """
        import gzip

        good = gzip.decompress(MIXED.read_bytes()).split(b"\n")[:40]
        damaged = tmp_path / "damaged.jsonl.gz"
        damaged.write_bytes(gzip.compress(b"\n".join([*good[:20], b"{not json", *good[20:]])))

        assert cli.main(["export", str(damaged), "-f", "markdown"]) == cli.EXIT_OK

        assert "could not be decoded" in plain(capsys.readouterr().err)

    def test_quiet_still_says_the_capture_was_incomplete(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`--quiet` means "print only the destination", which is a statement
        about stdout. Silencing the notes made the quiet form the one that
        hides the bad news."""
        import gzip

        good = gzip.decompress(MIXED.read_bytes()).split(b"\n")[:40]
        damaged = tmp_path / "damaged.jsonl.gz"
        damaged.write_bytes(gzip.compress(b"\n".join([*good[:20], b"{not json", *good[20:]])))

        cli.main(["export", str(damaged), "-f", "markdown", "-q"])

        captured = capsys.readouterr()
        assert "could not be decoded" in plain(captured.err)
        assert captured.out.strip().endswith("damaged.md")


class TestRefusalsRatherThanTracebacks:
    def test_an_impossible_destination_is_an_error_not_a_traceback(
        self, capture: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Every command here writes files, so the filesystem's refusals are
        ordinary. They arrived as a twelve-frame traceback."""
        blocked = capture.parent / "in-the-way"
        blocked.write_text("not a directory", encoding="utf-8")

        assert (
            cli.main(["export", str(capture), "-f", "markdown", "-o", str(blocked / "out.md")])
            == cli.EXIT_ERROR
        )
        assert plain(capsys.readouterr().err).startswith("error:")

    @pytest.mark.parametrize("value", ["0", "-3"])
    def test_a_meaningless_record_limit_is_rejected(self, value: str) -> None:
        """``--max-records 0`` captured exactly one record: the limit is tested
        after a record has been written, so the first comparison was 1 >= 0."""
        with pytest.raises(SystemExit) as exit_info:
            cli.main(["capture", "--max-records", value])
        assert exit_info.value.code == 2
