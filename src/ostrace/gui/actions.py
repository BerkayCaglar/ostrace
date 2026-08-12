# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Building the actions and the menu bar from the bindings table.

The table in ``gui.shortcuts`` is also the help sheet, so a key that changes
there changes the documentation in the same commit or not at all. klogg's
fourth trap is a key table in a manual that drifted from the code.

What lives here is *construction*: one action per binding, in the right menu,
with the right role and the right separators. What does not is the wiring --
which verb each action performs stays with the window, because "every menu,
toolbar and context entry is an action the window already owns" is the rule the
window exists to enforce.

The single constructor is the point. A rule enforced by the only way to make
one survives somebody adding a menu item in a hurry, and there are two such
rules here: an action is built with a menu role rather than left to a
heuristic, and an icon is never drawn in a menu.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMenu

from ostrace.gui.shortcuts import BINDINGS, RELOCATED, sequences

if TYPE_CHECKING:
    from collections.abc import Mapping

    from PySide6.QtWidgets import QMenuBar, QWidget

__all__ = ["build_actions", "build_menus", "menu_items"]

#: The macOS menu role for each relocated action. Here rather than in
#: `shortcuts`, which is Qt-light on purpose and describes keys rather than
#: where a platform decides to put things.
_ROLES = {
    "quit": QAction.MenuRole.QuitRole,
    "about": QAction.MenuRole.AboutRole,
}

#: The menu bar, in order. Ampersands are the access keys Windows and Linux
#: underline; macOS ignores them.
_MENUS = (
    ("capture", "&Capture"),
    ("edit", "&Edit"),
    ("view", "&View"),
    ("help", "&Help"),
)


def build_actions(parent: QWidget) -> dict[str, QAction]:
    """Every action the bindings table describes, by name.

    ``parent`` owns them and is also where they are added, so the shortcuts
    work whether or not the action is in a menu the user has opened.

    Nothing is connected here. The caller decides what each verb does, and a
    factory that also wired them would be deciding for it.
    """
    actions: dict[str, QAction] = {}

    for binding in BINDINGS:
        keys = sequences(binding)
        action = _action(parent, binding.text, keys[0], checkable=binding.checkable)
        # Before anything is connected, so a default state is a default rather
        # than an action taken on a window still being built.
        action.setChecked(binding.checked)
        if len(keys) > 1:
            # Aliases are real bindings, not documentation. A menu shows one;
            # `setShortcuts` registers all of them.
            action.setShortcuts(keys)
        action.setToolTip(binding.description)
        actions[binding.name] = action

    # Qt relocates these on macOS by matching their text, and should: that is
    # the native behaviour a Mac user expects. The role is the reason they are
    # built apart from the loop above; the keys still come from `RELOCATED`, so
    # `unbound` and the help sheet can see them.
    for binding in RELOCATED:
        action = _action(parent, binding.text, role=_ROLES[binding.name])
        keys = [sequence for sequence in sequences(binding) if not sequence.isEmpty()]
        if keys:
            action.setShortcuts(keys)
        action.setToolTip(binding.description)
        actions[binding.name] = action

    return actions


def _action(
    parent: QWidget,
    text: str,
    shortcut: QKeySequence | QKeySequence.StandardKey | None = None,
    *,
    role: QAction.MenuRole = QAction.MenuRole.NoRole,
    checkable: bool = False,
) -> QAction:
    """Build one action. ``role`` defaults to *not moving*, never to the heuristic."""
    action = QAction(text, parent)
    action.setMenuRole(role)
    action.setCheckable(checkable)
    # The toolbar and the menus share these objects, and an icon put on one for
    # the toolbar's sake is drawn by the other in the column a checkmark
    # occupies. The two jump buttons carry chevrons, so `Next Error` and
    # `Previous Error` appeared in the View menu with what reads as a tick and
    # an indicator beside them, next to a `Dark Mode` whose tick is real. Icons
    # belong on the toolbar, where they are the label.
    action.setIconVisibleInMenu(False)
    if shortcut is not None:
        # StandardKey maps Ctrl to Cmd on macOS *and* knows where the two
        # platforms genuinely differ, which a literal string cannot.
        action.setShortcut(QKeySequence(shortcut))
    parent.addAction(action)
    return action


def build_menus(
    bar: QMenuBar,
    actions: Mapping[str, QAction],
    parent: QWidget,
) -> dict[str, QMenu]:
    """Fill the menu bar, and hand back the menus by name."""
    # Each menu is constructed with the window as its parent and added by
    # object, never by `bar.addMenu("title")`. That convenience overload
    # returns a menu Python owns, so the local reference is the only thing
    # keeping it alive and the menu dies at the end of this function. The
    # failure surfaces nowhere near here: the menu bar keeps an action whose
    # `menu()` hands back a fresh wrapper around freed memory, which reports
    # itself valid right up until it is used.
    menus = {name: QMenu(title, parent) for name, title in _MENUS}
    for menu in menus.values():
        bar.addMenu(menu)

    # A separator wherever the group changes. Declared in the bindings table
    # rather than inserted here by name, so a reordered or added item lands in
    # the right run without anybody remembering to move a divider: the View
    # menu is eleven items and was one undivided column of them.
    seen: dict[str, str] = {}
    for binding in BINDINGS:
        menu = menus[binding.menu]
        if binding.menu in seen and seen[binding.menu] != binding.group:
            menu.addSeparator()
        seen[binding.menu] = binding.group
        menu.addAction(actions[binding.name])

    menus["capture"].addSeparator()
    menus["capture"].addAction(actions["quit"])
    menus["help"].addSeparator()
    menus["help"].addAction(actions["about"])
    return menus


def menu_items(bar: QMenuBar) -> list[QAction]:
    """Every clickable item in the menu bar, for the menu-role test.

    Walked from the menu bar rather than filtered out of
    ``findChildren(QAction)``: that returns widget actions too -- each
    ``QLineEdit`` with a clear button contributes one -- and none of those can
    be relocated by a menu heuristic because none of them is in a menu. Asking
    the menu bar what is in it is both narrower and truer.
    """
    items: list[QAction] = []
    # `QAction.menu()` is typed as returning QObject, so every result is
    # narrowed rather than assumed -- and `isinstance` is also the check that
    # separates a submenu from a plain item.
    pending = [menu for action in bar.actions() if (menu := _submenu(action))]
    while pending:
        for action in pending.pop().actions():
            if action.isSeparator():
                continue
            submenu = _submenu(action)
            if submenu is not None:
                pending.append(submenu)
            else:
                items.append(action)
    return items


def _submenu(action: QAction) -> QMenu | None:
    """The submenu an action opens, or ``None`` if it is a plain item."""
    menu = action.menu()
    return menu if isinstance(menu, QMenu) else None
