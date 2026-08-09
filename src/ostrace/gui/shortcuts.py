# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every key binding, in one table that is also the documentation.

klogg's fourth trap is a key table in a manual that drifted from the code. This
avoids it structurally: the window builds its actions from this list and the
help sheet renders the same list, so they cannot disagree.

**Both traditions are aliased rather than chosen between.** ostrace targets
Windows and macOS desktops, where `Ctrl+End` and `F3` are what people reach
for, and it is a log viewer, where `G` and `n` are what people reach for. klogg
binds both and ships on both platforms; picking one would be right for half the
users and wrong for the other half, at no saving.

`QKeySequence.StandardKey` is used wherever one exists rather than a literal.
It maps `Ctrl` to `⌘` on macOS *and* knows the places the two platforms
genuinely differ, which a hardcoded string cannot.

Two rules from klogg's own bug list are enforced here rather than remembered:
every action has at least one binding (an action with none is unreachable and
undiscoverable), and no destructive verb sits on a standard editing chord --
klogg's `Ctrl+X` truncates the file on disk.

**Everything here needs a `QApplication`.** Constructing a `QKeySequence`
without one segfaults the interpreter -- not an exception, a crash -- so this
module holds data at import time and touches Qt only inside functions.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QKeySequence

__all__ = ["BINDINGS", "Binding", "key_table", "sequences", "unbound"]


@dataclass(frozen=True, slots=True)
class Binding:
    """One action: what it is called, what it does, and how to reach it."""

    #: Attribute name on the window, as ``action_{name}``.
    name: str
    #: Menu text, with its accelerator.
    text: str
    #: The binding a menu shows. A `StandardKey` where one fits.
    primary: QKeySequence.StandardKey | str
    #: Additional bindings, for the other tradition. Not shown in menus, which
    #: have room for one, but real and documented.
    aliases: tuple[str, ...] = ()
    #: Which menu it belongs to.
    menu: str = "view"
    checkable: bool = False
    #: One line for the help sheet. Says what it is *for*, not what it does.
    description: str = ""


BINDINGS: tuple[Binding, ...] = (
    Binding(
        "capture",
        "&Capture",
        "Ctrl+R",
        menu="capture",
        description="Start capturing from the attached device",
    ),
    Binding(
        "pause",
        "&Pause",
        "Ctrl+P",
        menu="capture",
        checkable=True,
        description="Freeze the view. The capture keeps running and keeps writing to disk",
    ),
    Binding(
        "disconnect",
        "&Disconnect",
        "Ctrl+D",
        menu="capture",
        description="Release the device and end the capture",
    ),
    Binding(
        "open",
        "&Open Capture…",
        QKeySequence.StandardKey.Open,
        menu="capture",
        description="Open a session directory or a .jsonl.gz capture",
    ),
    Binding(
        "export",
        "&Export…",
        "Ctrl+E",
        menu="capture",
        description="Write the capture out in one of the six formats",
    ),
    Binding(
        "copy",
        "&Copy",
        QKeySequence.StandardKey.Copy,
        menu="edit",
        description="Copy the selected rows as tab-separated text",
    ),
    Binding(
        "find",
        "&Find",
        QKeySequence.StandardKey.Find,
        aliases=("/",),
        menu="edit",
        description="Jump to the search box",
    ),
    Binding(
        "mark",
        "&Mark Row",
        "Ctrl+M",
        aliases=("M",),
        menu="edit",
        description="Mark the current row, or unmark it",
    ),
    Binding(
        "clear_marks", "Clear &Marks", "Ctrl+Shift+M", menu="edit", description="Remove every mark"
    ),
    Binding(
        "top",
        "Go to &Top",
        QKeySequence.StandardKey.MoveToStartOfDocument,
        aliases=("G, G",),
        description="First row",
    ),
    Binding(
        "bottom",
        "Go to &Bottom",
        QKeySequence.StandardKey.MoveToEndOfDocument,
        aliases=("Shift+G",),
        description="Last row. Press again at the bottom to resume following",
    ),
    Binding(
        "next_error",
        "Next &Error",
        "Ctrl+Shift+E",
        aliases=("E",),
        description="Next Error or Fault, wrapping at the end",
    ),
    Binding(
        "previous_error",
        "Previous Erro&r",
        "Ctrl+Alt+Shift+E",
        aliases=("Shift+E",),
        description="Previous Error or Fault",
    ),
    Binding(
        "next_marker",
        "Next &Gap",
        "Ctrl+Shift+G",
        aliases=("]",),
        description="Next gap or eviction notice — where records are missing",
    ),
    Binding(
        "previous_marker",
        "Previous Ga&p",
        "Ctrl+Alt+Shift+G",
        aliases=("[",),
        description="Previous gap or eviction notice",
    ),
    Binding("next_mark", "Next Mar&k", "Ctrl+Shift+N", description="Next marked row"),
    Binding("previous_mark", "Previous Mar&k", "Ctrl+Shift+P", description="Previous marked row"),
    Binding(
        "step_down", "Next Row", "F8", description="Next row, even when the detail pane has focus"
    ),
    Binding(
        "step_up",
        "Previous Row",
        "F7",
        description="Previous row, even when the detail pane has focus",
    ),
    Binding("keys", "&Keyboard Shortcuts", "F1", menu="help", description="This list"),
)

#: Actions Qt relocates on macOS by matching their text, and should. They are
#: built separately because their roles, not their bindings, are the point.
#:
#: No Settings. There is nothing to configure in this release -- the theme
#: follows the system, the row cap and the drain interval are measured
#: constants -- and a menu item that opens nothing is worse than an absent one,
#: especially on macOS where Qt moves it into the application menu and calls it
#: Preferences, which is the item people press without looking.
RELOCATED = ("quit", "about")


def sequences(binding: Binding) -> list[QKeySequence]:
    """Every key that reaches this action, primary first.

    ``QKeySequence`` accepts a `StandardKey` and a string through the same
    constructor, so the two kinds of primary need no branch here.
    """
    return [QKeySequence(binding.primary), *(QKeySequence(alias) for alias in binding.aliases)]


def key_table() -> list[tuple[str, str, str]]:
    """The documented table: label, keys, description.

    Rendered from `BINDINGS`, so a binding that changes changes the help sheet
    in the same commit or not at all.
    """
    rows = []
    for binding in BINDINGS:
        keys = "  ·  ".join(
            sequence.toString(QKeySequence.SequenceFormat.NativeText)
            for sequence in sequences(binding)
            if not sequence.isEmpty()
        )
        rows.append((binding.text.replace("&", ""), keys, binding.description))
    return rows


def unbound() -> list[str]:
    """Bindings with no key at all.

    An action with no default binding is unreachable from the keyboard and
    invisible in the help sheet -- klogg shipped several and had to go back for
    them. Asserted by `test_gui_shortcuts.py` rather than at import time,
    because everything in this module needs a `QApplication`: constructing a
    `QKeySequence` without one **segfaults the interpreter**, which an
    import-time check would turn into a crash rather than a failure.
    """
    return [binding.name for binding in BINDINGS if not sequences(binding)[0].toString()]
