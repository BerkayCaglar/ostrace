# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the GitHub social preview card from the application mark.

The card is the only image most people ever see of this project: GitHub renders
it above the repository name on every topic listing, and every link to the
repository unfurls as it in Slack, on X and in a chat client. It is uploaded in
the repository settings rather than read from the tree, so this script exists to
make the artifact reproducible -- an image nobody can regenerate is an image
nobody dares change.

Colours come from ``gui/theme.py``'s tokens and nowhere else, so the card and
the application it advertises are the same palette by construction rather than
by eye. Drawn at 2x and saved at 2x: GitHub scales the card down to its own
layout, and a 1x source is the most common way a card announces that nobody
checked it.

    python tools/build_social_card.py docs/images/social-card.png
    python tools/build_social_card.py out.png --scheme dark
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NamedTuple

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontInfo, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

#: Straight out of ``TOKENS`` in ``gui/theme.py``.
SCHEMES = {
    "light": {"bg": "#f1f2f4", "fg": "#14161a", "muted": "#5f6773"},
    "dark": {"bg": "#15171c", "fg": "#e7eaf0", "muted": "#99a2b0"},
}


class Line(NamedTuple):
    """One line of the card, in unscaled units."""

    text: str
    px: int
    weight: QFont.Weight
    ink: str
    top: int
    height: int


#: Read top to bottom. The mark sits above them, and the vertical rhythm is the
#: reason these carry explicit tops rather than being laid out in a column: the
#: card is a fixed size and the stack is centred within it by eye, once.
LINES = (
    Line("ostrace", 92, QFont.Weight.DemiBold, "fg", 372, 120),
    Line("Stream, inspect and export iOS device logs", 30, QFont.Weight.Normal, "muted", 492, 60),
    Line("Windows  ·  macOS  ·  Linux", 24, QFont.Weight.Normal, "muted", 548, 50),
)

#: Cascadia Code is SIL OFL 1.1. Its outlines end up inside a committed PNG, and
#: baking a proprietary face -- Segoe UI, Calibri -- into an artifact of a
#: GPL-3.0 project is the sort of trap that is found late. A monospace face is
#: also the honest one for a tool whose other surface is a terminal.
FACE = "Cascadia Code"

#: GitHub's documented recommendation. Rendered at twice this.
CARD = QSize(1280, 640)
SCALE = 2

MARK = Path(__file__).resolve().parent.parent / "src" / "ostrace" / "gui" / "icons" / "app.svg"


def _draw_line(painter: QPainter, line: Line, tokens: dict[str, str], width: int) -> None:
    font = QFont(FACE)
    font.setPixelSize(line.px * SCALE)
    font.setWeight(line.weight)
    # Qt substitutes silently when a family is missing, so the card would still
    # be written -- in whatever face the machine happened to have, and nobody
    # would find out until the two versions were compared side by side.
    if not QFontInfo(font).exactMatch():
        resolved = QFontInfo(font).family()
        message = f"{FACE} is not installed; Qt would substitute {resolved!r}"
        raise SystemExit(message)
    painter.setFont(font)
    painter.setPen(QColor(tokens[line.ink]))
    rect = QRectF(0, line.top * SCALE, width, line.height * SCALE)
    painter.drawText(
        rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter), line.text
    )


def draw(scheme: str) -> QImage:
    """The card, at ``SCALE`` times its nominal size."""
    tokens = SCHEMES[scheme]
    size = QSize(CARD.width() * SCALE, CARD.height() * SCALE)
    image = QImage(size, QImage.Format.Format_ARGB32)
    image.fill(QColor(tokens["bg"]))

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    mark = 200 * SCALE
    QSvgRenderer(MARK.read_bytes()).render(
        painter, QRectF((size.width() - mark) / 2, 132 * SCALE, mark, mark)
    )
    for line in LINES:
        _draw_line(painter, line, tokens, size.width())
    # `end()` explicitly: a QPainter still active when its device is destroyed
    # warns on every platform and leaves the image half drawn on some.
    painter.end()
    return image


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="where to write the PNG")
    parser.add_argument("--scheme", choices=sorted(SCHEMES), default="light")
    args = parser.parse_args(argv)

    QGuiApplication([])
    image = draw(args.scheme)
    if not image.save(str(args.output)):
        message = f"could not write {args.output}"
        raise SystemExit(message)
    written = args.output.stat().st_size
    print(f"{args.output}  {image.width()}x{image.height()}  {written} bytes  ({args.scheme})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
