# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The filter row.

Level is a **threshold**, not an equality: "Error and above" is what someone
actually wants, and it is only expressible as a threshold because `Level` is
this project's own enum. Apple's values are not severity-ordered -- ``NOTICE=0,
INFO=1, DEBUG=2, USER_ACTION=3, ERROR=16, FAULT=17`` -- so a threshold written
against the device's own numbers would match nearly everything.

`changed` is emitted on every edit and the window debounces it. Re-filtering on
each keystroke of a process name is the behaviour that makes Android Studio's
Logcat throw the user to the bottom of the buffer on every character typed.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QWidget

from ostrace.model import Level

__all__ = ["FilterBar"]


class FilterBar(QWidget):
    """Level threshold, three text fields, and a regex toggle."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)

        self._level = QComboBox(self)
        for level in Level:
            # userData carries the enum itself, so nothing has to parse the
            # label back into a level -- and the label can be changed freely.
            self._level.addItem(f"{level.title} and above", level)
        self._level.setCurrentIndex(0)
        self._level.currentIndexChanged.connect(self.changed)
        layout.addWidget(QLabel("Level", self))
        layout.addWidget(self._level)

        self._process = self._add_field(layout, "Process", "name or pid")
        self._subsystem = self._add_field(layout, "Subsystem", "com.apple.…")
        self._search = self._add_field(layout, "Search", "message text", stretch=1)

        self._regex = QCheckBox("Regex", self)
        self._regex.toggled.connect(self.changed)
        layout.addWidget(self._regex)

    def _add_field(
        self, layout: QHBoxLayout, label: str, placeholder: str, *, stretch: int = 0
    ) -> QLineEdit:
        field = QLineEdit(self)
        field.setPlaceholderText(placeholder)
        field.setClearButtonEnabled(True)
        field.textChanged.connect(self.changed)
        layout.addWidget(QLabel(label, self))
        layout.addWidget(field, stretch=stretch)
        return field

    @property
    def minimum_level(self) -> Level:
        value = self._level.currentData()
        return value if isinstance(value, Level) else Level.DEBUG

    @property
    def process(self) -> str:
        return self._process.text().strip()

    @property
    def subsystem(self) -> str:
        return self._subsystem.text().strip()

    @property
    def search(self) -> str:
        return self._search.text()

    @property
    def regex(self) -> bool:
        return self._regex.isChecked()

    @property
    def is_empty(self) -> bool:
        """Whether this bar would exclude anything at all.

        The window needs this to tell "the device is quiet" apart from "your
        filter hides everything", which are the same picture otherwise.
        """
        return (
            self.minimum_level is Level.DEBUG
            and not self.process
            and not self.subsystem
            and not self.search
        )

    def clear(self) -> None:
        """Reset to showing everything. Wired to the banner's way out."""
        blocked = [self._level, self._process, self._subsystem, self._search, self._regex]
        for widget in blocked:
            widget.blockSignals(True)
        self._level.setCurrentIndex(0)
        self._process.clear()
        self._subsystem.clear()
        self._search.clear()
        self._regex.setChecked(False)
        for widget in blocked:
            widget.blockSignals(False)
        # One signal for the whole reset, not five.
        self.changed.emit()
