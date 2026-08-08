# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""A strip beside the table showing where the interesting rows are.

Wireshark calls its version the Intelligent Scrollbar and klogg calls its an
overview; this is the same idea and it is the only mechanism in the program
that reveals a discontinuity *outside* the viewport. Without one, a gap forty
thousand rows above where somebody is reading is something they never learn
about -- and the whole reason a gap is a first-class row is that its position
means something.

Clicking jumps there, which is what makes it a control rather than a decoration.

It is deliberately not a `QScrollBar` subclass. A scrollbar is drawn by the
platform style, and painting into its groove means fighting a different set of
metrics on each platform -- on the one platform that cannot be tested here,
blind. A plain strip is drawn entirely by us and looks the same everywhere,
which is the same argument that chose Qt in the first place.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from ostrace.gui.models import Band
from ostrace.gui.theme import Scheme, mark_accent, palette_for, severity_for
from ostrace.model import Level

if TYPE_CHECKING:
    from PySide6.QtGui import QMouseEvent, QPaintEvent, QResizeEvent

    from ostrace.gui.models import RecordModel

__all__ = ["REFRESH_MS", "Minimap"]

#: How often the summary is recomputed while records are arriving. Measured,
#: the summary itself costs about 0.6 ms over 200,000 rows -- cheap because the
#: model keeps it in row-anchored buckets -- so this is about not repainting
#: more often than an eye can use, rather than about affording it.
REFRESH_MS = 250

#: Width, in character widths rather than pixels: macOS cannot have High DPI
#: scaling turned off and reports an integer device pixel ratio where Windows
#: allows fractional, so a pixel width chosen on one is wrong on the other.
_WIDTH_CHARS = 2.0

#: Each stripe is drawn at least this tall so a single gap in a million rows is
#: still something the eye can catch. Two device-independent pixels.
_MIN_STRIPE = 2


class Minimap(QWidget):
    """One stripe per band of rows, coloured by what is in it."""

    #: The user asked to go to a row.
    row_requested = Signal(int)

    def __init__(self, scheme: Scheme = Scheme.LIGHT, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.scheme = scheme
        self.model: RecordModel | None = None
        self._bands: list[Band] = []
        self.setToolTip("Errors, gaps and marks across the whole capture. Click to jump.")

        self._refresh = QTimer(self)
        self._refresh.setInterval(REFRESH_MS)
        self._refresh.timeout.connect(self.rebuild)

        self._colours = self._build_colours()
        self.setFixedWidth(int(self.fontMetrics().horizontalAdvance("0") * _WIDTH_CHARS))

    def _build_colours(self) -> dict[Band, QColor]:
        """One prebuilt colour per kind. Never allocate inside ``paintEvent``."""
        return {
            Band.ERROR: severity_for(Level.ERROR, self.scheme).foreground,
            Band.MARKER: severity_for(Level.USER_ACTION, self.scheme).foreground,
            Band.MARK: mark_accent(self.scheme),
        }

    def set_scheme(self, scheme: Scheme) -> None:
        self.scheme = scheme
        self._colours = self._build_colours()
        self.update()

    def set_model(self, model: RecordModel | None) -> None:
        """Attach the model whose rows this summarises."""
        self.model = model
        self.rebuild()

    def start(self) -> None:
        """Keep up with a capture in progress."""
        self._refresh.start()

    def stop(self) -> None:
        self._refresh.stop()
        self.rebuild()

    def rebuild(self) -> None:
        """Recompute the summary, if it would look any different."""
        bands = self.model.overview(self._band_count()) if self.model is not None else []
        if bands != self._bands:
            self._bands = bands
            self.update()

    def _band_count(self) -> int:
        return max(1, self.height() // _MIN_STRIPE)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.rebuild()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        palette = palette_for(self.scheme)
        painter.fillRect(self.rect(), palette.base().color())
        if not self._bands:
            return

        height = self.height()
        width = self.width()
        stripe = max(_MIN_STRIPE, height // len(self._bands))
        # Marks last: a mark is the user's own annotation and outranks every
        # colour rule, here as in the table.
        for kind in (Band.ERROR, Band.MARKER, Band.MARK):
            colour = self._colours[kind]
            for index, flags in enumerate(self._bands):
                if flags & kind:
                    painter.fillRect(0, index * height // len(self._bands), width, stripe, colour)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._jump(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._jump(event)

    def _jump(self, event: QMouseEvent) -> None:
        """Ask for the row under the cursor. Dragging scrubs."""
        if self.model is None or self.height() <= 0:
            return
        rows = self.model.rowCount()
        if rows == 0:
            return
        fraction = min(max(event.position().y() / self.height(), 0.0), 1.0)
        self.row_requested.emit(min(int(fraction * rows), rows - 1))
