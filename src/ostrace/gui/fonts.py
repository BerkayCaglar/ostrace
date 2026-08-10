# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The face log text is read in.

Here rather than on the table because the detail pane needs the same one: a
message shown in the table in a monospaced face and in the pane in a
proportional one is the same string rendered as two different things, and the
pane is where people go to read the awkward messages -- the ones with alignment
in them, or with a hex dump, or with a stack address that has to be compared
against another.

Not in `theme`, which is a function from a scheme to colours and has no reason
to know about fonts.
"""

from __future__ import annotations

from PySide6.QtGui import QFont

__all__ = ["MONO_FAMILIES", "MONO_POINT_BONUS", "monospace"]

#: Fixed-width faces, most-wanted first; Qt takes the first that resolves. Not
#: a platform branch -- the list is the same on all three, which is precisely
#: why it can live here rather than in `compat`. `Cascadia Mono` ships with
#: Windows 11 and the tail is what Linux distributions actually install.
#:
#: `SF Mono` was listed here as the macOS first choice and is not one: a stock
#: Mac never resolves it. The file ships, as `/System/Library/Fonts/
#: SFNSMono.ttf`, but Apple registers the SF faces under a restricted family
#: name and keeps them out of the font list, so neither `QFontDatabase` nor
#: `system_profiler` offers `SF Mono` -- measured on macOS 26.3.1 with PySide6
#: 6.11.1, 181 families and that not among them. It is kept ahead of `Menlo`
#: because it does resolve for anyone who installed Apple's separately
#: distributed copy, and `Menlo` is what everybody else gets.
MONO_FAMILIES = (
    "Cascadia Mono",
    "SF Mono",
    "Menlo",
    "DejaVu Sans Mono",
    "Noto Sans Mono",
    "Liberation Mono",
    "Consolas",
    "Courier New",
)

#: Points added to the interface font. A monospaced face at the same nominal
#: size reads noticeably smaller than a proportional one, and this is the text
#: the user is actually here to read.
MONO_POINT_BONUS = 0.5


def monospace(point_bonus: float = MONO_POINT_BONUS) -> QFont:
    """A fixed-width font, sized against the interface font."""
    font = QFont()
    font.setFamilies(list(MONO_FAMILIES))
    font.setStyleHint(QFont.StyleHint.Monospace)
    size = font.pointSizeF()
    if size > 0:
        # Negative means the font was specified in pixels, where adding points
        # would silently switch units and resize everything using it.
        font.setPointSizeF(size + point_bonus)
    return font
