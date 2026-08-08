# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The main window.

Two things here are not obvious and both come from `docs/design/gui.md`.

**Every action declares its menu role.** On macOS, Qt applies *text heuristics*
to menu items: anything matching ``settings``/``options``/``preferences``/
``config``/``setup`` is moved into the application menu, ``about.*`` into
About, ``quit``/``exit`` into Quit. The default for every action is
``TextHeuristicRole`` -- verified, not assumed -- so an item is opted *into*
being relocated unless it says otherwise. A "Settings…" entry silently
disappears from its own menu on the one platform that cannot be tested here.
`test_gui_window.py` asserts that no action is left on the default.

**Pause and Disconnect are different verbs and must stay that way.** Pause
freezes the view and never touches the source. This project already learned
that releasing a device releases the lockdown session *and* the
``os_trace_relay`` service together, so a pause that reached the source would
be a disconnect wearing a friendlier label, and everything that arrived during
it would be gone. The destructive control is therefore named after its
consequence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QAction, QKeySequence, QShowEvent
from PySide6.QtWidgets import QMainWindow, QMenu, QSplitter, QVBoxLayout, QWidget

from PySide6.QtCore import Qt  # isort: skip -- grouped with the Qt namespace uses below

from ostrace.gui.theme import Scheme
from ostrace.gui.widgets.banner import Banner
from ostrace.gui.widgets.detail_pane import DetailPane
from ostrace.gui.widgets.filter_bar import FilterBar
from ostrace.gui.widgets.log_table import LogTable
from ostrace.gui.widgets.status_bar import StatusBar

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget as QWidgetType

__all__ = ["MainWindow"]

_TITLE = "ostrace"

#: Proportions of the vertical split at first show, as stretch factors rather
#: than pixels: no fixed pixel sizes anywhere, because High DPI cannot be
#: switched off on macOS and its device pixel ratio is an integer where
#: Windows' is fractional.
_TABLE_STRETCH = 3
_DETAIL_STRETCH = 1


def _submenu(action: QAction) -> QMenu | None:
    """The submenu an action opens, or ``None`` if it is a plain item."""
    menu = action.menu()
    return menu if isinstance(menu, QMenu) else None


class MainWindow(QMainWindow):
    """Toolbar, filter bar, table, detail pane, status bar."""

    def __init__(self, scheme: Scheme = Scheme.LIGHT, parent: QWidgetType | None = None) -> None:
        super().__init__(parent)
        self.scheme = scheme
        self.setWindowTitle(_TITLE)

        self.filter_bar = FilterBar(self)
        self.banner = Banner(self)
        self.table = LogTable(self)
        self.detail = DetailPane(self)

        self._split = QSplitter(Qt.Orientation.Vertical, self)
        self._split.addWidget(self.table)
        self._split.addWidget(self.detail)
        self._split.setStretchFactor(0, _TABLE_STRETCH)
        self._split.setStretchFactor(1, _DETAIL_STRETCH)
        self._sized = False
        # The table may be collapsed to nothing by dragging; the detail pane
        # may not, because a pane that can vanish behind a one-pixel handle is
        # a pane the user cannot get back.
        self._split.setChildrenCollapsible(False)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.filter_bar)
        layout.addWidget(self.banner)
        layout.addWidget(self._split, stretch=1)
        self.setCentralWidget(central)

        self.status = StatusBar(self)
        self.setStatusBar(self.status)

        self._build_actions()
        self._build_menus()

        self.filter_bar.changed.connect(self._on_filter_changed)
        self.banner.dismissed.connect(self.filter_bar.clear)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        """Split the panes on first show, when there is a height to divide.

        Stretch factors only govern how *extra* space is shared on a resize;
        the first layout comes from the children's size hints, and neither an
        empty table nor a two-line form has a hint that reflects what the user
        wants to see. Doing it here rather than in the constructor is the
        difference between a ratio and a guess: the window has no height yet
        when it is built.
        """
        super().showEvent(event)
        if self._sized:
            return
        self._sized = True
        total = self._split.height()
        share = _TABLE_STRETCH + _DETAIL_STRETCH
        self._split.setSizes([total * _TABLE_STRETCH // share, total * _DETAIL_STRETCH // share])

    # -- actions ---------------------------------------------------------

    def _build_actions(self) -> None:
        """Every action, each with an explicit menu role.

        ``_action`` refuses to create one without a role, which is the point:
        a rule enforced by the only constructor is a rule that survives someone
        adding a menu item in a hurry.
        """
        self.action_capture = self._action("&Capture", QKeySequence("Ctrl+R"))
        self.action_pause = self._action("&Pause", QKeySequence("Ctrl+P"), checkable=True)
        self.action_disconnect = self._action("&Disconnect", QKeySequence("Ctrl+D"))
        self.action_open = self._action("&Open Capture…", QKeySequence.StandardKey.Open)
        self.action_export = self._action("&Export…", QKeySequence("Ctrl+E"))

        # Qt would relocate these three on macOS by matching their text. Two of
        # them we *want* relocated -- that is the native behaviour a Mac user
        # expects -- so they get the real role rather than NoRole.
        self.action_quit = self._action(
            "&Quit", QKeySequence.StandardKey.Quit, role=QAction.MenuRole.QuitRole
        )
        self.action_about = self._action("&About ostrace", role=QAction.MenuRole.AboutRole)
        self.action_settings = self._action(
            "&Settings…",
            QKeySequence.StandardKey.Preferences,
            role=QAction.MenuRole.PreferencesRole,
        )

        self.action_copy = self._action("&Copy", QKeySequence.StandardKey.Copy)
        self.action_find = self._action("&Find", QKeySequence.StandardKey.Find)
        self.action_bottom = self._action("Go to &Bottom", QKeySequence("Ctrl+End"))
        self.action_top = self._action("Go to &Top", QKeySequence("Ctrl+Home"))
        self.action_next_gap = self._action("Next &Gap", QKeySequence("Ctrl+Shift+G"))

        self.action_quit.triggered.connect(self.close)

    def _action(
        self,
        text: str,
        shortcut: QKeySequence | QKeySequence.StandardKey | None = None,
        *,
        role: QAction.MenuRole = QAction.MenuRole.NoRole,
        checkable: bool = False,
    ) -> QAction:
        """Build one action. ``role`` defaults to *not moving*, never to the heuristic."""
        action = QAction(text, self)
        action.setMenuRole(role)
        action.setCheckable(checkable)
        if shortcut is not None:
            # StandardKey maps Ctrl to Cmd on macOS *and* knows where the two
            # platforms genuinely differ, which a literal string cannot.
            action.setShortcut(QKeySequence(shortcut))
        self.addAction(action)
        return action

    def _build_menus(self) -> None:
        bar = self.menuBar()

        # Each menu is constructed with this window as its parent and added by
        # object, never by `bar.addMenu("title")`. That convenience overload
        # returns a menu Python owns, so the local reference is the only thing
        # keeping it alive and the menu dies at the end of this method. The
        # failure surfaces nowhere near here: the menu bar keeps an action
        # whose `menu()` hands back a fresh wrapper around freed memory, which
        # reports itself valid right up until it is used.
        capture = QMenu("&Capture", self)
        bar.addMenu(capture)
        capture.addAction(self.action_capture)
        capture.addAction(self.action_pause)
        capture.addAction(self.action_disconnect)
        capture.addSeparator()
        capture.addAction(self.action_open)
        capture.addAction(self.action_export)
        capture.addSeparator()
        capture.addAction(self.action_quit)

        edit = QMenu("&Edit", self)
        bar.addMenu(edit)
        edit.addAction(self.action_copy)
        edit.addAction(self.action_find)
        edit.addSeparator()
        edit.addAction(self.action_settings)

        view = QMenu("&View", self)
        bar.addMenu(view)
        view.addAction(self.action_top)
        view.addAction(self.action_bottom)
        view.addSeparator()
        view.addAction(self.action_next_gap)

        help_menu = QMenu("&Help", self)
        bar.addMenu(help_menu)
        help_menu.addAction(self.action_about)

        self.menus = {"capture": capture, "edit": edit, "view": view, "help": help_menu}

    def menu_items(self) -> list[QAction]:
        """Every clickable item in the menu bar, for the menu-role test.

        Walked from the menu bar rather than filtered out of
        ``findChildren(QAction)``: that returns widget actions too -- each
        ``QLineEdit`` with a clear button contributes one -- and none of those
        can be relocated by a menu heuristic because none of them is in a menu.
        Asking the menu bar what is in it is both narrower and truer.
        """
        items: list[QAction] = []
        # `QAction.menu()` is typed as returning QObject, so every result is
        # narrowed rather than assumed -- and `isinstance` is also the check
        # that separates a submenu from a plain item.
        pending = [menu for action in self.menuBar().actions() if (menu := _submenu(action))]
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

    # -- state -----------------------------------------------------------

    def _on_filter_changed(self) -> None:
        """Keep the invisible-state banner honest.

        There is no model yet, so this only handles the case the filter bar can
        answer on its own. Once rows exist, "the filter matched nothing" joins
        it -- that is the pairing that stops an over-narrow filter looking like
        a dead device.
        """
        if self.filter_bar.is_empty:
            self.banner.hide()
