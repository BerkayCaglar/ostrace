# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Choosing a format, and being told what it left out.

Every exporter in this package declares its own omissions. That principle is
what this dialog exists to carry into the GUI: it is easy to write an export
button that reports success and nothing else, and a summary that quietly
stopped at a token budget reads as complete. A reader then draws conclusions
from an absence that is an artefact of truncation rather than a fact about the
device.

So the dialog does not close on success. It stays, says what was written and
where, and lists what could not be said -- using `exporters.notes`, the same
sentences `ostrace export` prints, because the reader should be told the same
truth whichever way they asked.

The default is the agent bundle, for the reason the CLI defaults to it: it is
the only format that loses nothing, and a default that quietly discards data is
the wrong default.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ostrace.errors import OstraceError
from ostrace.exporters import EXPORTERS
from ostrace.exporters.ai_report import AiReportExporter
from ostrace.exporters.base import ExportResult
from ostrace.exporters.notes import export_notes
from ostrace.paths import check_export_destination, export_path, export_stem
from ostrace.storage.session import SPOOL_NAME

if TYPE_CHECKING:
    from PySide6.QtGui import QCloseEvent

    from ostrace.exporters.base import Exporter
    from ostrace.storage.capture import Capture

__all__ = ["DEFAULT_FORMAT", "ExportDialog", "ExportWorker"]

#: The only format that loses nothing. Everything else is a summary.
DEFAULT_FORMAT = "agent-bundle"

#: How long to wait for an export to finish when the dialog is closing. It is
#: bounded work on a file, not a network round trip.
_EXPORT_WAIT_MS = 30_000

#: Slim: it is a state, not a chart.
_PROGRESS_HEIGHT = 4

#: Token budget shown for the one format that has one. The CLI spells "no
#: limit" as zero, and so does this.
_DEFAULT_BUDGET = 30_000
_MAX_BUDGET = 1_000_000


class ExportWorker(QThread):
    """One export, off the interface thread.

    Opens the capture again rather than sharing the dialog's. A `Capture` is a
    lazy reader over a file, and handing one to a second thread while the first
    may still be iterating it is the shape of bug this package has already paid
    for once at the socket level. Reopening costs a file handle.
    """

    #: The finished `ExportResult`. Typed loosely because Qt's signal signatures
    #: do not carry dataclasses; the receiver narrows it.
    done = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        source: Path,
        exporter: Exporter,
        destination: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._source = source
        self._exporter = exporter
        self._destination = destination

    def run(self) -> None:
        from ostrace.storage.capture import open_capture  # noqa: PLC0415

        try:
            capture = open_capture(self._source)
            outcome = self._exporter.export(
                capture.items(), self._destination, device=capture.device
            )
        except (OstraceError, OSError) as exc:
            # OSError as well as our own: exporting into a path that is not a
            # directory, or onto a read-only volume, is an ordinary mistake and
            # not one this package raises. An exception out of `run` would take
            # the process rather than the export.
            self.failed.emit(str(exc))
            return
        self.done.emit(outcome)


class ExportDialog(QDialog):
    """Pick a format and a destination, then read what was left out."""

    def __init__(
        self, capture: Capture, parent: QWidget | None = None, *, running: bool = False
    ) -> None:
        super().__init__(parent)
        self.capture = capture
        self.running = running
        self.result_path: Path | None = None
        self._worker: ExportWorker | None = None
        self.setWindowTitle("Export snapshot" if running else "Export capture")

        layout = QVBoxLayout(self)
        # What is being exported, before what it will be exported as. A dialog
        # that names only the format leaves the reader to remember which
        # capture they opened, and the answer is in the title bar of a window
        # this one is covering.
        self.header = QLabel(self._describe(capture), self)
        self.header.setWordWrap(True)
        layout.addWidget(self.header)

        if running:
            # Said before the export rather than only after it. The user asked
            # for this while a capture was streaming, and what they get is a
            # prefix of it -- which is useful and is not the same thing as the
            # capture, so the dialog names the difference at the point of the
            # decision as well as in the notes afterwards.
            preamble = QLabel(
                "The capture is still recording. This writes out everything on "
                f"disk so far{self._so_far(capture)} and leaves the capture running.",
                self,
            )
            preamble.setWordWrap(True)
            layout.addWidget(preamble)

        self._build_formats(layout)

        form = QFormLayout()
        layout.addLayout(form)

        self.budget = QSpinBox(self)
        self.budget.setRange(0, _MAX_BUDGET)
        self.budget.setValue(_DEFAULT_BUDGET)
        self.budget.setSingleStep(1_000)
        self.budget.setSpecialValueText("no limit")
        self.budget.setToolTip(
            "How much of the report to keep. Whatever does not fit is counted "
            "and declared rather than silently dropped."
        )
        self.budget_label = QLabel("Token budget:", self)
        form.addRow(self.budget_label, self.budget)

        form.addRow("Write to:", self._build_destination())

        # Indeterminate: an exporter reports no progress, and a bar that
        # invented one would be worse than none. What it honestly says is
        # "still going", which is the fact that was missing.
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(_PROGRESS_HEIGHT)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.report = QLabel(self)
        self.report.setWordWrap(True)
        self.report.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.report)

        # The answer to "where did it go", which the module docstring worries
        # about and which the report could only answer by printing a path
        # somebody then has to retype. Hidden until there is somewhere to go.
        self.reveal = QPushButton("Show in folder", self)
        self.reveal.setVisible(False)
        self.reveal.clicked.connect(self.reveal_export)
        layout.addWidget(self.reveal)

        self.buttons = QDialogButtonBox(self)
        self.export_button = self.buttons.addButton(
            "Export", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.buttons.addButton(QDialogButtonBox.StandardButton.Close)
        self.buttons.accepted.connect(self.run_export)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self._on_format_changed()

    def _build_formats(self, layout: QVBoxLayout) -> None:
        """One row per format, all six visible at once.

        Six is the count where a list beats a dropdown: the formats *are* the
        product, their descriptions are already written on the exporters, and a
        combo hides five of the six behind a click -- so the reader has to open
        it to discover that anything but the default exists.
        """
        self.formats = QButtonGroup(self)
        for name, exporter in sorted(EXPORTERS.items()):
            row = QRadioButton(f"{name} — {exporter.description}", self)
            row.setAccessibleName(name)
            row.setChecked(name == DEFAULT_FORMAT)
            # The name lives on the button rather than in a list beside it, so
            # nothing has to keep two orderings in step.
            row.setProperty("format", name)
            self.formats.addButton(row)
            layout.addWidget(row)
        self.formats.buttonToggled.connect(self._on_format_toggled)

    def _build_destination(self) -> QWidget:
        """The path field and the button that fills it in.

        Beside the field rather than under it. Under, in its own column, it
        read as a control belonging to something else -- which is what a button
        below a text box normally is.
        """
        destination = QWidget(self)
        chooser = QHBoxLayout(destination)
        chooser.setContentsMargins(0, 0, 0, 0)
        self.destination = QLineEdit(destination)
        self.destination.setAccessibleName("Export destination")
        chooser.addWidget(self.destination)
        browse = QPushButton("Choose…", destination)
        browse.clicked.connect(self._choose_destination)
        chooser.addWidget(browse)
        return destination

    def _describe(self, capture: Capture) -> str:
        """What is being exported, in one line.

        The counts come from a *finalised* sidecar or not at all. A capture
        still recording has a sidecar written at open, whose counts are zero
        until it is closed, and a bare spool has no sidecar to ask -- so in both
        cases the honest header is the capture's name and nothing else. A zero
        printed beside `records` would be read as a fact about the capture.
        """
        name = export_stem(capture.path)
        meta = capture.meta
        if meta is None or meta.ended_at is None:
            return name
        gaps = "no gaps" if meta.gap_count == 0 else f"{meta.gap_count:,} gaps"
        return f"{name} · {meta.record_count:,} records · {gaps}"

    @staticmethod
    def _so_far(capture: Capture) -> str:
        """How much a snapshot would be, for somebody deciding whether to take one.

        The size on disk rather than a record count. The count is the number
        anybody would rather have, and getting it means decompressing the whole
        spool -- on the interface thread, at the moment the dialog opens, for a
        file that is still growing. The size is one `stat`, it moves with the
        count, and it is the number that answers "is this worth waiting for".

        Empty rather than a zero when the file cannot be measured: this is a
        parenthesis in a sentence that reads correctly without it.
        """
        try:
            written = (capture.path / SPOOL_NAME).stat().st_size
        except OSError:
            return ""
        return f" ({written / 1_000_000:,.1f} MB)"

    # -- state -----------------------------------------------------------

    @property
    def format_name(self) -> str:
        checked = self.formats.checkedButton()
        value = checked.property("format") if checked is not None else None
        return value if isinstance(value, str) else DEFAULT_FORMAT

    def choose_format(self, name: str) -> None:
        """Pick a format by name.

        A method rather than leaving callers to find the right widget and set
        it. The control has been a combo and is now a list of radios, and the
        thing that does not change is *which format*: a caller that says the
        name survives the next rearrangement, where one that pokes the widget
        has to be rewritten with it.
        """
        for button in self.formats.buttons():
            if button.property("format") == name:
                button.setChecked(True)
                return
        msg = f"unknown format {name!r}"
        raise KeyError(msg)

    def _on_format_toggled(self, _button: QWidget, checked: bool) -> None:
        """`buttonToggled` fires twice per change -- off, then on."""
        if checked:
            self._on_format_changed()

    def _on_format_changed(self) -> None:
        """Only one format has a budget, so only it offers one."""
        has_budget = self.format_name == "ai-report"
        self.budget.setVisible(has_budget)
        self.budget_label.setVisible(has_budget)
        self.destination.setText(str(self._default_destination()))
        # The button says what it will do, so `Enter` on the default path is a
        # complete answer and nothing has to be read twice to check it.
        self.export_button.setText(f"Export {self.format_name}")

    def _default_destination(self) -> Path:
        """Beside the capture, named after it -- as the CLI does.

        An export that lands somewhere the user has to go looking for gets
        regenerated rather than found.
        """
        return export_path(self.capture.path, EXPORTERS[self.format_name].suffix)

    def _choose_destination(self) -> None:
        chosen, _ = QFileDialog.getSaveFileName(
            self,
            "Export to",
            self.destination.text(),
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if chosen:
            self.destination.setText(chosen)

    # -- doing it --------------------------------------------------------

    def run_export(self) -> None:
        """Start the export. The dialog stays open and reports when it lands.

        Off the interface thread, because it is not quick: measured on a 61,190
        record capture off a device, every format takes between 1.5 and 2.3
        seconds, and the cap is 200,000. Run here, that was the window frozen
        with nothing on screen to say why -- which is what "no indication that
        anything happened" means.
        """
        if self._worker is not None and self._worker.isRunning():
            return

        exporter = EXPORTERS[self.format_name]
        if self.format_name == "ai-report":
            # Zero spells "no limit", matching `--budget-tokens 0`.
            exporter = AiReportExporter(budget_tokens=self.budget.value() or None)

        destination = Path(self.destination.text())
        try:
            # On this thread, and before anything is started. `.jsonl` is both
            # an ending `export_stem` strips and the jsonl exporter's suffix, so
            # opening a `.jsonl` capture and pressing Export offered *the
            # capture itself* as the destination -- and the export truncated the
            # file it was still iterating over, then reported "0 records" as
            # success. The CLI has refused this since the day it did the same
            # thing; this dialog is the other way in and was never taught about
            # it. Refusing before the worker starts also means the message
            # arrives immediately rather than after a round trip.
            check_export_destination(destination, self.capture.path)
        except (OstraceError, OSError) as exc:
            self.report.setText(f"Export failed: {exc}")
            return

        self._set_running(running=True)
        self.report.setText(f"Writing {self.format_name} to {destination}…")
        self._worker = ExportWorker(self.capture.path, exporter, destination, self)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _set_running(self, *, running: bool) -> None:
        self.progress.setVisible(running)
        self.export_button.setEnabled(not running)
        for button in self.formats.buttons():
            button.setEnabled(not running)
        self.destination.setEnabled(not running)

    def reveal_export(self) -> None:
        """Open the folder the export landed in.

        The folder rather than the file: an agent bundle *is* a directory, and
        opening the containing folder is the one behaviour that is right for
        both shapes. `QDesktopServices` is `QtGui`, so this costs no dependency.
        """
        if self.result_path is None:  # pragma: no cover - the button is hidden
            return
        folder = self.result_path if self.result_path.is_dir() else self.result_path.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _on_failed(self, message: str) -> None:
        self._set_running(running=False)
        self.report.setText(f"Export failed: {message}")

    def _on_done(self, outcome: object) -> None:
        self._set_running(running=False)
        if not isinstance(outcome, ExportResult):  # pragma: no cover - defensive
            return
        self.result_path = outcome.destination
        self.reveal.setVisible(True)
        meta = self.capture.meta
        notes = export_notes(
            outcome,
            truncated=self.capture.truncated,
            running=self.running,
            source=meta.source if meta is not None else None,
        )
        lines = [f"{outcome.records:,} records → {outcome.destination}"]
        if notes:
            lines.append("")
            lines.append("What this export cannot tell you:")
            lines += [f"  • {note}" for note in notes]
        self.report.setText("\n".join(lines))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """Wait for the worker before the dialog goes.

        A ``QThread`` still running when Python drops its last reference aborts
        the process without a message. An export is bounded work on a file, so
        waiting is short and there is nothing to cancel it into.
        """
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.wait(_EXPORT_WAIT_MS)
        super().closeEvent(event)
