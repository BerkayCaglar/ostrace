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
    #: Which run of related items inside that menu. A separator is drawn where
    #: this changes, so the grouping is a property of the table rather than a
    #: list of insertion points kept in step with it by hand. The View menu had
    #: eleven items in one undivided column -- four pairs of Next/Previous, two
    #: jumps and a theme toggle -- which is a list nobody reads to the end of.
    group: str = ""
    checkable: bool = False
    #: One line for the help sheet. Says what it is *for*, not what it does.
    description: str = ""


BINDINGS: tuple[Binding, ...] = (
    Binding(
        "capture",
        "&Capture",
        "Ctrl+R",
        menu="capture",
        group="device",
        description="Start capturing from the attached device",
    ),
    Binding(
        "pause",
        "&Pause",
        "Ctrl+P",
        menu="capture",
        group="device",
        checkable=True,
        description="Freeze the view. The capture keeps running and keeps writing to disk",
    ),
    Binding(
        "disconnect",
        "&Disconnect",
        "Ctrl+D",
        menu="capture",
        group="device",
        description="Release the device and end the capture",
    ),
    Binding(
        "open",
        "&Open Capture…",
        QKeySequence.StandardKey.Open,
        menu="capture",
        group="file",
        description="Open a session directory or a .jsonl.gz capture",
    ),
    Binding(
        "close",
        "&Close Capture",
        QKeySequence.StandardKey.Close,
        menu="capture",
        group="file",
        description="Empty the window: no capture, no filter, no selection",
    ),
    Binding(
        "export",
        "&Export…",
        "Ctrl+E",
        menu="capture",
        group="file",
        description="Write the capture out in one of the six formats",
    ),
    Binding(
        "copy",
        "&Copy",
        QKeySequence.StandardKey.Copy,
        menu="edit",
        group="clipboard",
        description="Copy the selected rows as tab-separated text",
    ),
    Binding(
        "find",
        "&Find",
        QKeySequence.StandardKey.Find,
        aliases=("/",),
        menu="edit",
        group="selection",
        description="Jump to the search box",
    ),
    Binding(
        "deselect",
        "Dese&lect",
        "Esc",
        menu="edit",
        group="selection",
        description="Let go of the selected row, without moving the view",
    ),
    Binding(
        "mark",
        "&Mark Row",
        "Ctrl+M",
        aliases=("M",),
        menu="edit",
        group="marks",
        description="Mark the current row, or unmark it",
    ),
    Binding(
        "clear_marks",
        "Clear &Marks",
        "Ctrl+Shift+M",
        menu="edit",
        group="marks",
        description="Remove every mark",
    ),
    Binding(
        "top",
        "Go to &Top",
        QKeySequence.StandardKey.MoveToStartOfDocument,
        aliases=("G, G",),
        group="ends",
        description="First row",
    ),
    Binding(
        "bottom",
        "Go to &Bottom",
        QKeySequence.StandardKey.MoveToEndOfDocument,
        aliases=("Shift+G",),
        group="ends",
        description="Last row. Press again at the bottom to resume following",
    ),
    Binding(
        "go_time",
        "Go to &Time…",
        "Ctrl+J",
        group="ends",
        description="Jump to a clock reading, or to an offset from where you are",
    ),
    Binding(
        "follow",
        "&Follow the Tail",
        "Ctrl+Shift+F",
        group="ends",
        checkable=True,
        description="Stay on the newest records. The status bar shows whether it is on",
    ),
    # `F3` is the find-next key on Windows and the one klogg binds, which is
    # exactly the meaning wanted here: *next of whatever I am looking for*. The
    # per-kind bindings below keep their own keys, so choosing a target in the
    # toolbar never takes a key away from somebody who knows the explicit one.
    Binding(
        "next_jump",
        "&Next Jump",
        "F3",
        aliases=("N",),
        group="jump",
        description="Next row of the kind the toolbar is set to jump between",
    ),
    Binding(
        "previous_jump",
        "&Previous Jump",
        "Shift+F3",
        aliases=("Shift+N",),
        group="jump",
        description="Previous row of the kind the toolbar is set to jump between",
    ),
    Binding(
        "next_error",
        "Next &Error",
        "Ctrl+Shift+E",
        aliases=("E",),
        group="kinds",
        description="Next Error or Fault, wrapping at the end",
    ),
    Binding(
        "previous_error",
        "Previous Erro&r",
        "Ctrl+Alt+Shift+E",
        aliases=("Shift+E",),
        group="kinds",
        description="Previous Error or Fault",
    ),
    Binding(
        "next_marker",
        "Next &Gap",
        "Ctrl+Shift+G",
        aliases=("]",),
        group="kinds",
        description="Next gap or eviction notice — where records are missing",
    ),
    Binding(
        "previous_marker",
        "Previous Ga&p",
        "Ctrl+Alt+Shift+G",
        aliases=("[",),
        group="kinds",
        description="Previous gap or eviction notice",
    ),
    Binding(
        "next_mark",
        "Next Mar&k",
        "Ctrl+Shift+N",
        group="kinds",
        description="Next marked row",
    ),
    Binding(
        "previous_mark",
        "Previous Mar&k",
        "Ctrl+Shift+P",
        group="kinds",
        description="Previous marked row",
    ),
    Binding(
        "step_down",
        "Next Row",
        "F8",
        group="rows",
        description="Next row, even when the detail pane has focus",
    ),
    Binding(
        "step_up",
        "Previous Row",
        "F7",
        group="rows",
        description="Previous row, even when the detail pane has focus",
    ),
    Binding(
        "dark_mode",
        "&Dark Mode",
        "Ctrl+Shift+T",
        menu="view",
        group="theme",
        checkable=True,
        description="Use the dark theme regardless of what the system is set to",
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
