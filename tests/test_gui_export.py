# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The export dialog, and the one thing it exists to do.

An export button that reports success and nothing else is easy to write and
quietly wrong: a summary that stopped at a token budget reads as complete, and
the reader draws conclusions from an absence that is an artefact of truncation
rather than a fact about the device. Every test here is about the dialog saying
what it could not say.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ostrace.exporters import EXPORTERS
from ostrace.storage.capture import open_capture
from ostrace.storage.spool import SpoolWriter
from tests.helpers import ERRORS, MIXED, make_gap, make_record

pytest.importorskip("PySide6", reason="the gui extra is not installed")

from ostrace.gui.widgets.export_dialog import DEFAULT_FORMAT, ExportDialog
from ostrace.gui.windows.main import MainWindow

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.gui


@pytest.fixture
def dialog(qt_app: object) -> ExportDialog:
    del qt_app
    return ExportDialog(open_capture(ERRORS))


def test_the_default_loses_nothing(dialog: ExportDialog) -> None:
    """Everything else is a summary, and a default that quietly discards data
    is the wrong default -- the same reason the CLI defaults to it."""
    assert dialog.format_name == DEFAULT_FORMAT


def test_every_registered_exporter_is_offered(dialog: ExportDialog) -> None:
    """Registering an exporter is all it should take to expose it, in the GUI
    as in the CLI."""
    offered = {dialog.format_box.itemData(row) for row in range(dialog.format_box.count())}
    assert offered == set(EXPORTERS)


def test_the_budget_is_offered_only_where_it_means_something(dialog: ExportDialog) -> None:
    """One format has a token budget. A control that does nothing on five of
    six choices teaches the user to ignore it."""
    dialog.format_box.setCurrentIndex(dialog.format_box.findData("ai-report"))
    assert dialog.budget.isVisibleTo(dialog)

    dialog.format_box.setCurrentIndex(dialog.format_box.findData("jsonl"))
    assert not dialog.budget.isVisibleTo(dialog)


def test_the_destination_defaults_beside_the_capture(dialog: ExportDialog) -> None:
    """An export that lands somewhere the user has to go looking for gets
    regenerated rather than found."""
    assert dialog.destination.text().startswith(str(ERRORS.parent))


def test_the_destination_follows_the_format(dialog: ExportDialog) -> None:
    dialog.format_box.setCurrentIndex(dialog.format_box.findData("markdown"))
    assert dialog.destination.text().endswith(EXPORTERS["markdown"].suffix)


def test_exporting_writes_the_file_and_says_where(dialog: ExportDialog, tmp_path: Path) -> None:
    destination = tmp_path / "out.md"
    dialog.format_box.setCurrentIndex(dialog.format_box.findData("markdown"))
    dialog.destination.setText(str(destination))

    dialog.run_export()

    assert destination.is_file()
    assert str(destination) in dialog.report.text()
    assert "3,000 records" in dialog.report.text()


def test_a_clean_capture_gets_no_alarming_notes(dialog: ExportDialog, tmp_path: Path) -> None:
    """Measured: both fixtures hold no gaps and drop no patterns.

    Saying nothing when there is nothing to say is the other half of declaring
    omissions. A warning that always appears is one nobody reads.
    """
    dialog.format_box.setCurrentIndex(dialog.format_box.findData("text"))
    dialog.destination.setText(str(tmp_path / "clean.log"))

    dialog.run_export()

    assert "cannot tell you" not in dialog.report.text()


def test_the_report_declares_a_gap_in_the_capture(qt_app: object, tmp_path: Path) -> None:
    """The whole reason this dialog does not simply close on success.

    Nothing follows from an absence across a gap, and a dialog that reported
    only "done" would leave the reader believing the device was quiet during
    it. Built from a capture with a real hole in it, since both fixtures are
    intact.
    """
    del qt_app
    spool = tmp_path / "holed.jsonl.gz"
    with SpoolWriter(spool) as writer:
        writer.write(make_record(0))
        writer.write_gap(make_gap())
        writer.write(make_record(1))

    dialog = ExportDialog(open_capture(spool))
    dialog.format_box.setCurrentIndex(dialog.format_box.findData("text"))
    dialog.destination.setText(str(tmp_path / "holed.log"))
    dialog.run_export()

    assert "cannot tell you" in dialog.report.text()
    assert "gap" in dialog.report.text()


def test_the_notes_are_the_same_sentences_the_cli_prints(qt_app: object, tmp_path: Path) -> None:
    """Two spellings of "this capture has a gap in it" would eventually
    disagree about which one mattered."""
    del qt_app
    from ostrace.exporters.notes import export_notes

    dialog = ExportDialog(open_capture(MIXED))
    dialog.format_box.setCurrentIndex(dialog.format_box.findData("text"))
    dialog.destination.setText(str(tmp_path / "out.log"))
    dialog.run_export()

    exporter = EXPORTERS["text"]
    outcome = exporter.export(open_capture(MIXED).items(), tmp_path / "again.log")
    for note in export_notes(outcome, truncated=False):
        assert note in dialog.report.text()


def test_a_failed_export_is_reported_rather_than_raised(
    dialog: ExportDialog, tmp_path: Path
) -> None:
    """A dialog that raises out of a button handler takes the window with it."""
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("in the way", encoding="utf-8")
    dialog.format_box.setCurrentIndex(dialog.format_box.findData("markdown"))
    dialog.destination.setText(str(blocked / "child" / "out.md"))

    dialog.run_export()  # must not raise

    assert dialog.report.text()


def test_the_window_refuses_to_export_nothing(qt_app: object) -> None:
    """With no capture open there is nothing to write, and saying so with a way
    forward beats an empty file or a disabled button with no explanation."""
    del qt_app
    window = MainWindow()
    window.export_capture()

    assert "nothing to export" in window.banner.text
