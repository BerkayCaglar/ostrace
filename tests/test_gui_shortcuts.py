# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The key bindings, and the four traps klogg's own bug list documents.

Each of these is a rule that is easy to state and easy to break silently. They
are asserted rather than remembered.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the gui extra is not installed")

from PySide6.QtGui import QAction, QKeySequence

from ostrace.gui.shortcuts import BINDINGS, key_table, sequences, unbound
from ostrace.gui.windows.main import MainWindow

pytestmark = pytest.mark.gui


@pytest.fixture
def window(qt_app: object) -> MainWindow:
    del qt_app
    return MainWindow()


def test_the_module_imports_without_an_application() -> None:
    """Constructing a `QKeySequence` with no `QApplication` **segfaults**.

    Not raises -- crashes the interpreter. An import-time check would therefore
    turn a mistake in the table into a dead test run with no traceback, which
    is how this rule was found. The table is data; only the functions touch Qt.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", "import ostrace.gui.shortcuts as s; print(len(s.BINDINGS))"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, f"importing crashed: {result.returncode}"
    assert result.stdout.strip() == str(len(BINDINGS))


def test_every_binding_has_a_key(qt_app: object) -> None:
    """An action with no default binding is unreachable from the keyboard and
    invisible in the help. klogg shipped several and had to go back for them."""
    del qt_app
    assert unbound() == []


def test_no_destructive_verb_sits_on_an_editing_chord(qt_app: object) -> None:
    """klogg binds `Ctrl+X` to *truncating the file on disk* — its issue #714.

    Nothing here may take a chord whose muscle memory means something else
    entirely, because the hand gets there before the eye does.
    """
    del qt_app
    editing = {
        QKeySequence(key).toString()
        for key in (
            QKeySequence.StandardKey.Cut,
            QKeySequence.StandardKey.Paste,
            QKeySequence.StandardKey.Undo,
            QKeySequence.StandardKey.Save,
        )
    }
    destructive = {"disconnect", "clear_marks"}
    for binding in BINDINGS:
        if binding.name not in destructive:
            continue
        for sequence in sequences(binding):
            assert sequence.toString() not in editing, binding.name


def test_the_two_keyboard_traditions_are_both_bound(qt_app: object) -> None:
    """Aliased rather than chosen between.

    `Ctrl+End` is what a desktop user reaches for and `Shift+G` is what a log
    reader reaches for. klogg binds both and ships on Windows and macOS —
    exactly this project's target pair — and picking one would be right for
    half the users at no saving.
    """
    del qt_app
    by_name = {binding.name: binding for binding in BINDINGS}
    assert "Shift+G" in by_name["bottom"].aliases
    assert "E" in by_name["next_error"].aliases
    assert "]" in by_name["next_marker"].aliases


def test_the_documented_table_comes_from_the_bindings(qt_app: object) -> None:
    """klogg's fourth trap is a key table in a manual that drifted from the
    code. Rendering it from the same list makes drift impossible."""
    del qt_app
    table = key_table()
    assert len(table) == len(BINDINGS)
    for (label, keys, description), binding in zip(table, BINDINGS, strict=True):
        assert label == binding.text.replace("&", "")
        assert keys, f"{binding.name} documented with no keys"
        assert description, f"{binding.name} documented with no description"


def test_every_binding_becomes_an_attribute_and_a_menu_item(window: MainWindow) -> None:
    """The declared attributes and the table cannot drift.

    The attributes are declared on the class for the type checker and filled
    from the table at run time; this is what stops the two lists disagreeing.
    """
    items = {action.text() for action in window.menu_items()}
    for binding in BINDINGS:
        action = getattr(window, f"action_{binding.name}", None)
        assert isinstance(action, QAction), f"no action_{binding.name}"
        assert action.text() in items, f"{binding.name} is not in any menu"


def test_aliases_are_registered_not_merely_documented(window: MainWindow) -> None:
    """A key in the help sheet that does nothing is worse than no help sheet."""
    bound = {sequence.toString() for sequence in window.action_bottom.shortcuts()}
    assert "Shift+G" in bound
    assert QKeySequence(QKeySequence.StandardKey.MoveToEndOfDocument).toString() in bound


def test_pause_is_bound_which_neither_logcat_nor_console_manages(window: MainWindow) -> None:
    """Both are asked for it. It is one line."""
    assert not window.action_pause.shortcut().isEmpty()
    assert window.action_pause.isCheckable()
