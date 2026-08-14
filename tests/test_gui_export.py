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

import pytest

from ostrace.exporters import EXPORTERS
from ostrace.storage.capture import open_capture
from ostrace.storage.session import SPOOL_NAME
from ostrace.storage.spool import SpoolWriter
from tests.helpers import ERRORS, MIXED, make_gap, make_record

pytest.importorskip("PySide6", reason="the gui extra is not installed")

from pathlib import Path

from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QLabel

from ostrace.gui.widgets.export_dialog import DEFAULT_FORMAT, ExportDialog
from ostrace.gui.windows.main import MainWindow

pytestmark = pytest.mark.gui


def run_and_wait(dialog: ExportDialog) -> None:
    """Press Export and wait for it.

    The export runs on its own thread now -- measured at 1.5 to 2.3 seconds on
    a 61,190 record capture, which is a frozen window with nothing on it if it
    runs here. `wait()` blocks this thread; the worker's signals are queued, so
    they need one turn of the loop afterwards to be delivered.
    """
    dialog.run_export()
    worker = dialog._worker
    if worker is not None:
        assert worker.wait(30_000), "the export did not finish"
    QApplication.processEvents()


@pytest.fixture
def dialog(qt_app: object) -> ExportDialog:
    del qt_app
    return ExportDialog(open_capture(ERRORS))


@pytest.fixture
def written_session(tmp_path: Path) -> Path:
    """A capture with a finalised sidecar, which the fixtures deliberately are
    not: they are bare spools, so nothing in the tree carries real counts."""
    import asyncio

    from ostrace.capture import capture as run_capture
    from tests.helpers import ScriptedSource

    destination = tmp_path / "finished"
    result = asyncio.run(
        run_capture(
            ScriptedSource([make_record(index) for index in range(3)]),
            destination=destination,
        )
    )
    return result.path


def test_the_default_loses_nothing(dialog: ExportDialog) -> None:
    """Everything else is a summary, and a default that quietly discards data
    is the wrong default -- the same reason the CLI defaults to it."""
    assert dialog.format_name == DEFAULT_FORMAT


def test_every_registered_exporter_is_offered(dialog: ExportDialog) -> None:
    """Registering an exporter is all it should take to expose it, in the GUI
    as in the CLI."""
    offered = {button.property("format") for button in dialog.formats.buttons()}
    assert offered == set(EXPORTERS)


def test_the_budget_is_offered_only_where_it_means_something(dialog: ExportDialog) -> None:
    """One format has a token budget. A control that does nothing on five of
    six choices teaches the user to ignore it."""
    dialog.choose_format("ai-report")
    assert dialog.budget.isVisibleTo(dialog)

    dialog.choose_format("jsonl")
    assert not dialog.budget.isVisibleTo(dialog)


def test_the_destination_defaults_beside_the_capture(dialog: ExportDialog) -> None:
    """An export that lands somewhere the user has to go looking for gets
    regenerated rather than found."""
    assert dialog.destination.text().startswith(str(ERRORS.parent))


def test_the_destination_follows_the_format(dialog: ExportDialog) -> None:
    dialog.choose_format("markdown")
    assert dialog.destination.text().endswith(EXPORTERS["markdown"].suffix)


def test_exporting_writes_the_file_and_says_where(dialog: ExportDialog, tmp_path: Path) -> None:
    destination = tmp_path / "out.md"
    dialog.choose_format("markdown")
    dialog.destination.setText(str(destination))

    run_and_wait(dialog)

    assert destination.is_file()
    assert str(destination) in dialog.report.text()
    assert "3,000 records" in dialog.report.text()


def test_a_clean_capture_gets_no_alarming_notes(dialog: ExportDialog, tmp_path: Path) -> None:
    """Measured: both fixtures hold no gaps and drop no patterns.

    Saying nothing when there is nothing to say is the other half of declaring
    omissions. A warning that always appears is one nobody reads.
    """
    dialog.choose_format("text")
    dialog.destination.setText(str(tmp_path / "clean.log"))

    run_and_wait(dialog)

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
    dialog.choose_format("text")
    dialog.destination.setText(str(tmp_path / "holed.log"))
    run_and_wait(dialog)

    assert "cannot tell you" in dialog.report.text()
    assert "gap" in dialog.report.text()


def test_the_notes_are_the_same_sentences_the_cli_prints(qt_app: object, tmp_path: Path) -> None:
    """Two spellings of "this capture has a gap in it" would eventually
    disagree about which one mattered.

    Driven from a capture with a hole in it, and with a guard that the hole
    actually produces a note. Run against a fixture it proved nothing: both
    fixtures are intact, `export_notes` returns `[]` for them, and the loop
    body never executed -- so emptying `export_notes` entirely left this
    passing.
    """
    del qt_app
    from ostrace.exporters.notes import export_notes

    spool = tmp_path / "holed.jsonl.gz"
    with SpoolWriter(spool) as writer:
        writer.write(make_record(0))
        writer.write_gap(make_gap())
        writer.write(make_record(1))

    dialog = ExportDialog(open_capture(spool))
    dialog.choose_format("text")
    dialog.destination.setText(str(tmp_path / "out.log"))
    run_and_wait(dialog)

    exporter = EXPORTERS["text"]
    outcome = exporter.export(open_capture(spool).items(), tmp_path / "again.log")
    notes = export_notes(outcome, truncated=False)
    assert notes, "the capture must actually produce a note for this to mean anything"
    for note in notes:
        assert note in dialog.report.text()


def test_a_failed_export_is_reported_rather_than_raised(
    dialog: ExportDialog, tmp_path: Path
) -> None:
    """A dialog that raises out of a button handler takes the window with it."""
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("in the way", encoding="utf-8")
    dialog.choose_format("markdown")
    dialog.destination.setText(str(blocked / "child" / "out.md"))

    run_and_wait(dialog)

    assert dialog.report.text()


def test_the_window_refuses_to_export_nothing(qt_app: object) -> None:
    """With no capture open there is nothing to write, and saying so with a way
    forward beats an empty file or a disabled button with no explanation."""
    del qt_app
    window = MainWindow()
    window.export_capture()

    assert "nothing to export" in window.banner.text


class TestItNeverEatsTheCapture:
    """The CLI's `TestItNeverEatsTheCapture`, from the other way in.

    `paths.check_export_destination` was written for the command line and only
    ever called from it. The dialog computes its default destination through
    the same `export_path`, so it inherited the same collision and none of the
    guard: opening a `.jsonl` capture and pressing Export with the offered
    destination truncated the capture while the exporter was still iterating
    over it, then reported ``0 records`` in the same place a success goes.

    Measured before the fix, against a capture recorded off the device:
    10,718,395 bytes to 0, and the dialog said it had worked.
    """

    @pytest.fixture
    def plain_capture(self, tmp_path: Path) -> Path:
        """The fixture uncompressed, so that its name ends in ``.jsonl``."""
        import gzip

        destination = tmp_path / "capture.jsonl"
        destination.write_bytes(gzip.decompress(MIXED.read_bytes()))
        return destination

    def test_the_offered_destination_is_refused_rather_than_taken(
        self, qt_app: object, plain_capture: Path
    ) -> None:
        del qt_app
        before = plain_capture.read_bytes()
        dialog = ExportDialog(open_capture(plain_capture))
        dialog.choose_format("jsonl")

        # No edit: this is the destination the dialog itself put in the field.
        assert dialog.destination.text() == str(plain_capture)
        dialog.run_export()

        assert plain_capture.read_bytes() == before, "the capture was modified"
        assert "over the capture" in dialog.report.text()
        assert dialog.result_path is None, "a refused export must not report a path"

    def test_a_destination_chosen_at_the_capture_is_refused_too(
        self, qt_app: object, plain_capture: Path
    ) -> None:
        """`Choose…` opens a save dialog, which will happily point back."""
        del qt_app
        before = plain_capture.read_bytes()
        dialog = ExportDialog(open_capture(plain_capture))
        dialog.choose_format("markdown")
        dialog.destination.setText(str(plain_capture))

        dialog.run_export()

        assert plain_capture.read_bytes() == before

    def test_an_ordinary_export_beside_the_capture_still_works(
        self, qt_app: object, plain_capture: Path
    ) -> None:
        """The guard must not refuse the case it was reached through."""
        del qt_app
        dialog = ExportDialog(open_capture(plain_capture))
        dialog.choose_format("markdown")

        run_and_wait(dialog)

        assert dialog.result_path is not None
        assert (plain_capture.parent / "capture.md").is_file()


def test_the_export_does_not_block_the_interface(dialog: ExportDialog, tmp_path: Path) -> None:
    """Measured on a 61,190 record capture off a device: every format takes
    between 1.5 and 2.3 seconds, and the cap is 200,000.

    Run on the interface thread that is a frozen window with nothing on it to
    say why, which is what "there is no indication anything happened" means.
    The dialog says what it is doing, shows a bar, and refuses a second press
    until the first has landed.
    """
    dialog.choose_format("markdown")
    dialog.destination.setText(str(tmp_path / "out.md"))

    dialog.run_export()

    assert dialog._worker is not None, "the export ran on the interface thread"
    assert dialog.progress.isVisibleTo(dialog)
    assert not dialog.export_button.isEnabled(), "a second press would start a second export"
    assert "Writing" in dialog.report.text()

    assert dialog._worker.wait(30_000)
    QApplication.processEvents()

    assert dialog.progress.isHidden()
    assert dialog.export_button.isEnabled()
    assert "3,000 records" in dialog.report.text()


def test_closing_mid_export_waits_rather_than_aborting(
    dialog: ExportDialog, tmp_path: Path
) -> None:
    """A `QThread` still running when Python drops its last reference takes the
    process down without a message."""
    dialog.choose_format("text")
    dialog.destination.setText(str(tmp_path / "out.log"))
    dialog.run_export()

    dialog.close()

    assert dialog._worker is not None
    assert not dialog._worker.isRunning()


class TestChoosingAFormat:
    """Six rows, all visible. A combo hid five of them behind a click."""

    def test_every_format_is_on_screen_without_opening_anything(self, dialog: ExportDialog) -> None:
        assert {button.property("format") for button in dialog.formats.buttons()} == set(EXPORTERS)

    def test_exactly_one_is_chosen(self, dialog: ExportDialog) -> None:
        """A radio group with nothing checked is a dialog whose Export button
        has no answer to give."""
        checked = [button for button in dialog.formats.buttons() if button.isChecked()]

        assert len(checked) == 1
        assert checked[0].property("format") == DEFAULT_FORMAT

    def test_the_button_says_which_format_it_will_write(self, dialog: ExportDialog) -> None:
        """So `Enter` on the default path is a complete answer, and nothing has
        to be read twice to check what it will do."""
        assert dialog.export_button.text() == f"Export {DEFAULT_FORMAT}"

        dialog.choose_format("markdown")

        assert dialog.export_button.text() == "Export markdown"

    def test_choosing_by_name_survives_the_widget_changing(self, dialog: ExportDialog) -> None:
        """This control has been a combo and is now a list of radios. What did
        not change is which format, which is what callers say."""
        dialog.choose_format("jsonl")

        assert dialog.format_name == "jsonl"

    def test_a_format_that_does_not_exist_is_refused(self, dialog: ExportDialog) -> None:
        """Rather than silently leaving the previous one checked, which would
        export something other than what was asked for."""
        with pytest.raises(KeyError):
            dialog.choose_format("yaml")

    def test_each_row_is_named_for_something_that_cannot_see_it(self, dialog: ExportDialog) -> None:
        """The visible label carries the description too, which read aloud is a
        sentence before the answer."""
        for button in dialog.formats.buttons():
            assert button.accessibleName() == button.property("format")

    def test_the_rows_are_frozen_while_an_export_runs(self, dialog: ExportDialog) -> None:
        """Changing the format under a running export would leave the report
        naming one format and the file being another."""
        dialog._set_running(running=True)

        assert not any(button.isEnabled() for button in dialog.formats.buttons())

        dialog._set_running(running=False)
        assert all(button.isEnabled() for button in dialog.formats.buttons())


class TestTheHeader:
    """What is being exported, before what it will be exported as."""

    def test_it_names_the_capture(self, dialog: ExportDialog) -> None:
        assert "ios26-errors" in dialog.header.text()

    def test_a_capture_with_no_sidecar_is_named_and_not_counted(self, dialog: ExportDialog) -> None:
        """The fixtures are bare spools. A zero printed beside `records` would
        be read as a fact about the capture rather than as an absence of one."""
        assert open_capture(ERRORS).meta is None

        assert "records" not in dialog.header.text()

    def test_a_finished_capture_carries_its_counts(
        self, qt_app: object, written_session: Path
    ) -> None:
        del qt_app
        dialog = ExportDialog(open_capture(written_session))

        assert "3 records" in dialog.header.text()
        assert "no gaps" in dialog.header.text()

    def test_a_capture_still_recording_is_not_counted(
        self, qt_app: object, written_session: Path
    ) -> None:
        """Its sidecar is written at open with zeroes in it and finalised at
        close, so the counts are only true once `ended_at` is set."""
        del qt_app
        capture = open_capture(written_session)
        meta = capture.meta
        assert meta is not None
        object.__setattr__(meta, "ended_at", None)

        assert "records" not in ExportDialog(capture)._describe(capture)


class TestFindingTheExport:
    """The answer to "where did it go" that the report could only give as a
    path somebody then has to retype."""

    def test_there_is_nowhere_to_go_before_an_export(self, dialog: ExportDialog) -> None:
        """`isHidden` rather than `isVisible`: a widget inside a window that has
        never been shown is not visible and has not been hidden either, so
        `isVisible` reports an unshown control and a deliberately hidden one
        identically. The banner learned this first."""
        assert dialog.reveal.isHidden()
        assert dialog.result_path is None

    def test_it_appears_once_something_has_been_written(
        self, dialog: ExportDialog, tmp_path: Path
    ) -> None:
        dialog.choose_format("jsonl")
        dialog.destination.setText(str(tmp_path / "out.jsonl"))

        run_and_wait(dialog)

        assert dialog.result_path is not None
        assert not dialog.reveal.isHidden()

    def test_it_opens_the_folder_rather_than_the_file(
        self, dialog: ExportDialog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An agent bundle *is* a directory and a jsonl export is a file, and
        opening the containing folder is the one behaviour right for both."""
        opened: list[str] = []
        # The class, not the name the dialog imported: patching through the
        # module reaches an attribute the module does not declare, which a type
        # checker is right to refuse.
        monkeypatch.setattr(
            QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile())
        )
        dialog.choose_format("jsonl")
        dialog.destination.setText(str(tmp_path / "out.jsonl"))
        run_and_wait(dialog)

        dialog.reveal_export()

        assert [Path(where) for where in opened] == [tmp_path]


class TestTheSnapshotPreamble:
    """A snapshot is a prefix of a capture, and the dialog says so before the
    decision as well as in the notes afterwards."""

    def test_it_says_how_much_would_be_written(self, qt_app: object, written_session: Path) -> None:
        """The size on disk rather than a record count. The count is the number
        anybody would rather have and getting it means decompressing the whole
        spool, on the interface thread, for a file that is still growing."""
        del qt_app
        dialog = ExportDialog(open_capture(written_session), running=True)

        text = " ".join(widget.text() for widget in dialog.findChildren(QLabel) if widget.text())
        assert "still recording" in text
        assert "MB" in text

    def test_a_size_that_cannot_be_read_is_left_out_rather_than_guessed(
        self, qt_app: object, written_session: Path
    ) -> None:
        """It is a parenthesis in a sentence that reads correctly without one,
        so an unmeasurable file costs the number and not the sentence."""
        del qt_app
        capture = open_capture(written_session)
        (capture.path / SPOOL_NAME).unlink()

        assert ExportDialog._so_far(capture) == ""
