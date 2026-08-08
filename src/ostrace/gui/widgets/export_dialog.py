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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ostrace.errors import OstraceError
from ostrace.exporters import EXPORTERS
from ostrace.exporters.ai_report import AiReportExporter
from ostrace.exporters.notes import export_notes
from ostrace.paths import export_path

if TYPE_CHECKING:
    from ostrace.storage.capture import Capture

__all__ = ["DEFAULT_FORMAT", "ExportDialog"]

#: The only format that loses nothing. Everything else is a summary.
DEFAULT_FORMAT = "agent-bundle"

#: Token budget shown for the one format that has one. The CLI spells "no
#: limit" as zero, and so does this.
_DEFAULT_BUDGET = 30_000
_MAX_BUDGET = 1_000_000


class ExportDialog(QDialog):
    """Pick a format and a destination, then read what was left out."""

    def __init__(self, capture: Capture, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.capture = capture
        self.result_path: Path | None = None
        self.setWindowTitle("Export capture")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.format_box = QComboBox(self)
        for name, exporter in sorted(EXPORTERS.items()):
            self.format_box.addItem(f"{name} — {exporter.description}", name)
        self.format_box.setCurrentIndex(self.format_box.findData(DEFAULT_FORMAT))
        self.format_box.currentIndexChanged.connect(self._on_format_changed)
        form.addRow("Format:", self.format_box)

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

        destination = QWidget(self)
        chooser = QVBoxLayout(destination)
        chooser.setContentsMargins(0, 0, 0, 0)
        self.destination = QLineEdit(destination)
        chooser.addWidget(self.destination)
        browse = QPushButton("Choose…", destination)
        browse.clicked.connect(self._choose_destination)
        chooser.addWidget(browse)
        form.addRow("Write to:", destination)

        self.report = QLabel(self)
        self.report.setWordWrap(True)
        self.report.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.report)

        self.buttons = QDialogButtonBox(self)
        self.export_button = self.buttons.addButton(
            "Export", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.buttons.addButton(QDialogButtonBox.StandardButton.Close)
        self.buttons.accepted.connect(self.run_export)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self._on_format_changed()

    # -- state -----------------------------------------------------------

    @property
    def format_name(self) -> str:
        value = self.format_box.currentData()
        return value if isinstance(value, str) else DEFAULT_FORMAT

    def _on_format_changed(self) -> None:
        """Only one format has a budget, so only it offers one."""
        has_budget = self.format_name == "ai-report"
        self.budget.setVisible(has_budget)
        self.budget_label.setVisible(has_budget)
        self.destination.setText(str(self._default_destination()))

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
        """Write the export and report on it. The dialog stays open."""
        exporter = EXPORTERS[self.format_name]
        if self.format_name == "ai-report":
            # Zero spells "no limit", matching `--budget-tokens 0`.
            exporter = AiReportExporter(budget_tokens=self.budget.value() or None)

        destination = Path(self.destination.text())
        try:
            outcome = exporter.export(self.capture.items(), destination, device=self.capture.device)
        except (OstraceError, OSError) as exc:
            # OSError as well as our own: exporting into a path that is not a
            # directory, or onto a read-only volume, is an ordinary mistake and
            # not one this package raises. An exception escaping a button
            # handler takes the window with it.
            self.report.setText(f"Export failed: {exc}")
            return

        self.result_path = outcome.destination
        notes = export_notes(outcome, truncated=self.capture.truncated)
        lines = [f"{outcome.records:,} records → {outcome.destination}"]
        if notes:
            lines.append("")
            lines.append("What this export cannot tell you:")
            lines += [f"  • {note}" for note in notes]
        self.report.setText("\n".join(lines))
