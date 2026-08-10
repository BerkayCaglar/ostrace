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
from ostrace.gui.theme import Scheme, mark_accent, palette_for, severity_for, viewport_marker
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

#: The viewport marker is never drawn thinner than this. Forty rows on screen
#: out of two hundred thousand is a third of a pixel, and a marker that rounds
#: away is worse than none: the reader concludes the strip does not have one.
_MIN_MARKER = 3


class Minimap(QWidget):
    """One stripe per band of rows, coloured by what is in it."""

    #: The user asked to go to a row.
    row_requested = Signal(int)

    def __init__(self, scheme: Scheme = Scheme.LIGHT, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.scheme = scheme
        self.model: RecordModel | None = None
        self._bands: list[Band] = []
        #: The rows on screen in the table beside this, inclusive, or an empty
        #: range. Pushed in rather than pulled, because a widget that reached
        #: for the table would be a strip that only works next to one.
        self._viewport = (0, -1)
        self.setToolTip(
            "Errors, gaps and marks across the whole capture, and where you are in it. "
            "Click to jump."
        )
        # It is a control -- clicking it jumps -- drawn entirely by us, so it
        # has no text, no icon and nothing else an assistive technology could
        # read a purpose out of.
        self.setAccessibleName("Capture overview")
        self.setAccessibleDescription(
            "Errors, gaps and marks across the whole capture, and where you are in it"
        )

        self._refresh = QTimer(self)
        self._refresh.setInterval(REFRESH_MS)
        self._refresh.timeout.connect(self.rebuild)

        self._colours = self._build_colours()
        self._marker_fill, self._marker_edge = viewport_marker(self.scheme)
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
        self._marker_fill, self._marker_edge = viewport_marker(self.scheme)
        self.update()

    def set_viewport(self, first: int, last: int) -> None:
        """Which rows the table beside this is showing.

        Repainted only when the answer changes. It is asked on every scroll,
        every resize and every batch of arrivals, and a reader who has stopped
        on one screen of a capture that is still growing gets the same answer
        every time.
        """
        if (first, last) != self._viewport:
            self._viewport = (first, last)
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
        self._paint_marker(painter)

    def _paint_marker(self, painter: QPainter) -> None:
        """Draw where the reader is, over the stripes rather than among them.

        Last, so nothing is drawn on top of it. Without this the strip says
        *what* is in the capture and not *where you are in it*, which makes it
        a picture rather than a map -- and the click-to-jump it already has is
        aiming at a target the reader cannot see themselves on.
        """
        first, last = self._viewport
        if self.model is None or last < first:
            return
        rows = self.model.rowCount()
        if rows <= 0:
            return
        height = self.height()
        top = min(first * height // rows, max(0, height - _MIN_MARKER))
        bottom = max((last + 1) * height // rows, top + _MIN_MARKER)
        painter.fillRect(0, top, self.width(), bottom - top, self._marker_fill)
        painter.setPen(self._marker_edge)
        # `drawRect` puts the pen *on* the boundary, so the right and bottom
        # edges land one pixel outside a rectangle given the full width.
        painter.drawRect(0, top, self.width() - 1, bottom - top - 1)

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
