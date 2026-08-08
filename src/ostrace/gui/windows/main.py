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

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QModelIndex, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ostrace.errors import OstraceError
from ostrace.exporters.base import escape
from ostrace.gui.filters import Filter
from ostrace.gui.live import CaptureThread
from ostrace.gui.loader import CaptureLoader
from ostrace.gui.models import Find, RecordModel
from ostrace.gui.pump import Pump
from ostrace.gui.shortcuts import BINDINGS, key_table, sequences
from ostrace.gui.theme import Scheme
from ostrace.gui.widgets.banner import Banner
from ostrace.gui.widgets.detail_pane import DetailPane
from ostrace.gui.widgets.export_dialog import ExportDialog
from ostrace.gui.widgets.filter_bar import FilterBar
from ostrace.gui.widgets.log_table import LogTable
from ostrace.gui.widgets.status_bar import StatusBar
from ostrace.model import DeviceInfo
from ostrace.paths import sessions_dir
from ostrace.storage.capture import Capture, open_capture

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget as QWidgetType

    from ostrace.sources.base import LogSource

__all__ = ["MainWindow"]

_TITLE = "ostrace"

#: Proportions of the vertical split at first show, as stretch factors rather
#: than pixels: no fixed pixel sizes anywhere, because High DPI cannot be
#: switched off on macOS and its device pixel ratio is an integer where
#: Windows' is fractional.
_TABLE_STRETCH = 3
_DETAIL_STRETCH = 1

#: How long to wait for the capture thread to release the device. Its teardown
#: is a socket close rather than a network round trip, so this is generous.
_STOP_TIMEOUT_MS = 5_000

#: How near the bottom still counts as "at the bottom" for auto-follow. A few
#: pixels of slack, because a scrollbar rarely lands exactly on its maximum.
_FOLLOW_SLACK = 4

#: How long the filter waits for the typing to stop. Long enough that a word is
#: one rescan rather than five, short enough that the table does not feel
#: detached from the keyboard.
_FILTER_DEBOUNCE_MS = 200


def _submenu(action: QAction) -> QMenu | None:
    """The submenu an action opens, or ``None`` if it is a plain item."""
    menu = action.menu()
    return menu if isinstance(menu, QMenu) else None


class MainWindow(QMainWindow):
    """Toolbar, filter bar, table, detail pane, status bar."""

    # Declared, then filled from `gui.shortcuts.BINDINGS` in `_build_actions`.
    # Assigning them through `setattr` alone would leave a type checker blind
    # to twenty attributes -- and static checking is one of the few things
    # standing in for the macOS testing this project cannot do. The list is
    # asserted against the table in `test_gui_shortcuts.py`, so the two cannot
    # drift.
    action_capture: QAction
    action_pause: QAction
    action_disconnect: QAction
    action_open: QAction
    action_export: QAction
    action_copy: QAction
    action_find: QAction
    action_mark: QAction
    action_clear_marks: QAction
    action_top: QAction
    action_bottom: QAction
    action_next_error: QAction
    action_previous_error: QAction
    action_next_marker: QAction
    action_previous_marker: QAction
    action_next_mark: QAction
    action_previous_mark: QAction
    action_step_down: QAction
    action_step_up: QAction
    action_keys: QAction
    action_quit: QAction
    action_about: QAction
    action_settings: QAction

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

        self.capture: Capture | None = None
        self._loader: CaptureLoader | None = None
        self._showing_filter_notice = False
        #: Auto-follow. Set when the user asks to resume it, cleared as soon as
        #: they scroll away -- see `_follow`, which derives the rest.
        self._following = True
        self._capture_thread: CaptureThread | None = None
        self._pump: Pump | None = None
        self.model = RecordModel(scheme, parent=self)
        self.table.setModel(self.model)
        self._connect_selection()

        self._filter_debounce = QTimer(self)
        self._filter_debounce.setSingleShot(True)
        self._filter_debounce.setInterval(_FILTER_DEBOUNCE_MS)
        self._filter_debounce.timeout.connect(self._apply_filter)

        self._build_actions()
        self._build_menus()

        self._connect_actions()
        self._set_capturing(capturing=False)

    def _connect_actions(self) -> None:
        """Wire every action to what it does.

        Separate from ``__init__`` because there are twenty of them and a
        constructor that also happens to be the wiring diagram is one nobody
        reads.
        """
        self.filter_bar.changed.connect(self._on_filter_changed)
        self.action_open.triggered.connect(self.choose_capture)
        self.action_capture.triggered.connect(self.capture_from_device)
        self.action_disconnect.triggered.connect(self.stop_capture)
        self.action_pause.toggled.connect(self.set_paused)

        self.action_copy.triggered.connect(self.copy_selection)
        self.action_find.triggered.connect(self.filter_bar.focus_search)
        self.action_mark.triggered.connect(self.toggle_mark)
        self.action_clear_marks.triggered.connect(self.clear_marks)
        self.action_top.triggered.connect(self.go_to_top)
        self.action_bottom.triggered.connect(self.go_to_bottom)
        self.action_next_error.triggered.connect(lambda: self.find_next(Find.ERROR))
        self.action_previous_error.triggered.connect(
            lambda: self.find_next(Find.ERROR, backwards=True)
        )
        self.action_next_marker.triggered.connect(lambda: self.find_next(Find.MARKER))
        self.action_previous_marker.triggered.connect(
            lambda: self.find_next(Find.MARKER, backwards=True)
        )
        self.action_next_mark.triggered.connect(lambda: self.find_next(Find.MARK))
        self.action_previous_mark.triggered.connect(
            lambda: self.find_next(Find.MARK, backwards=True)
        )
        self.action_step_down.triggered.connect(lambda: self.step_row(1))
        self.action_step_up.triggered.connect(lambda: self.step_row(-1))
        self.action_export.triggered.connect(self.export_capture)
        self.action_keys.triggered.connect(self.show_keys)

    def clear_marks(self) -> None:
        """Drop every mark.

        A method rather than connecting ``self.model.clear_marks`` directly:
        the model is *replaced* whenever a capture is opened or started, and a
        direct connection would go on clearing the marks of a model nobody can
        see any more.
        """
        self.model.clear_marks()

    def _connect_selection(self) -> None:
        """Re-attach to the selection model, which is replaced with the model."""
        selection = self.table.selectionModel()
        if selection is not None:
            selection.currentRowChanged.connect(self._on_current_row_changed)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """Release the device before the window goes.

        Without this the capture thread outlives the window it was reporting
        to, and the device is left streaming into a queue nobody drains -- the
        exact failure this project already paid for once at the source level.
        """
        self.stop_capture()
        super().closeEvent(event)

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
        """Build every action from `gui.shortcuts.BINDINGS`.

        The bindings table is also the help sheet, so a key that changes here
        changes the documentation in the same commit or not at all. klogg's
        fourth trap is a key table in a manual that drifted from the code.

        ``_action`` refuses to create one without a menu role, which is the
        point: a rule enforced by the only constructor survives someone adding
        a menu item in a hurry.
        """
        self.actions_by_name: dict[str, QAction] = {}
        for binding in BINDINGS:
            keys = sequences(binding)
            action = self._action(binding.text, keys[0], checkable=binding.checkable)
            if len(keys) > 1:
                # Aliases are real bindings, not documentation. A menu shows
                # one; `setShortcuts` registers all of them.
                action.setShortcuts(keys)
            action.setToolTip(binding.description)
            setattr(self, f"action_{binding.name}", action)
            self.actions_by_name[binding.name] = action

        # Qt relocates these three on macOS by matching their text, and should:
        # that is the native behaviour a Mac user expects. They get the real
        # role rather than NoRole, and they are built here rather than in the
        # table because their roles, not their keys, are the point.
        self.action_quit = self._action(
            "&Quit", QKeySequence.StandardKey.Quit, role=QAction.MenuRole.QuitRole
        )
        self.action_about = self._action("&About ostrace", role=QAction.MenuRole.AboutRole)
        self.action_settings = self._action(
            "&Settings…",
            QKeySequence.StandardKey.Preferences,
            role=QAction.MenuRole.PreferencesRole,
        )

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
        self.menus = {
            name: QMenu(title, self)
            for name, title in (
                ("capture", "&Capture"),
                ("edit", "&Edit"),
                ("view", "&View"),
                ("help", "&Help"),
            )
        }
        for menu in self.menus.values():
            bar.addMenu(menu)

        for binding in BINDINGS:
            self.menus[binding.menu].addAction(self.actions_by_name[binding.name])

        self.menus["capture"].addSeparator()
        self.menus["capture"].addAction(self.action_quit)
        self.menus["edit"].addSeparator()
        self.menus["edit"].addAction(self.action_settings)
        self.menus["help"].addSeparator()
        self.menus["help"].addAction(self.action_about)

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

    # -- opening a capture -----------------------------------------------

    def choose_capture(self) -> None:
        """Ask for a capture and open it."""
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Open capture",
            str(sessions_dir()),
            "Captures (*.jsonl.gz *.jsonl);;All files (*)",
            # The native macOS dialog ignores the filter argument outright, so
            # the filters above would silently do nothing there. Qt's own
            # dialog honours them and looks the same on every platform, which
            # is the same reason this project chose Qt in the first place.
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if chosen:
            self.open_capture(Path(chosen))

    def open_capture(self, path: Path) -> None:
        """Load a capture into the table.

        Read in batches from the event loop rather than in one pass -- see
        `gui.loader`. Replacing the contents rather than appending to them: two
        captures interleaved by arrival order would be a timeline that never
        happened.
        """
        if self._loader is not None:
            self._loader.cancel()

        try:
            capture = open_capture(path)
        except OstraceError as exc:
            self.banner.show_message(f"Could not open {path.name}: {exc}", "Dismiss")
            return

        self.stop_capture()
        self.capture = capture
        self.model = RecordModel(self.scheme, parent=self)
        self.table.setModel(self.model)
        self._connect_selection()
        self.detail.clear()
        self.status.set_device(capture.device)

        self._loader = CaptureLoader(capture, self.model, parent=self)
        self._loader.progressed.connect(self._on_progress)
        self._loader.finished.connect(self._on_loaded)
        self._loader.failed.connect(self._on_load_failed)
        self._loader.start()

        self.setWindowTitle(f"{path.name} — {_TITLE}")

    def _on_progress(self, loaded: int) -> None:
        self.status.set_volume(loaded)
        self.status.set_gap_count(self.model.gaps)

    def _on_loaded(self) -> None:
        self._on_progress(self._loader.loaded if self._loader else 0)
        if self.capture is not None and self.capture.truncated:
            # Worth saying out loud: the end of a truncated capture is missing,
            # and its absence says nothing about the device.
            self.banner.show_message(
                "This capture has no gzip trailer, so it was still being written "
                "or the writer was killed. Its last records are missing.",
                "Dismiss",
            )
        self._update_banner()

    def _on_load_failed(self, message: str) -> None:
        self._on_progress(self._loader.loaded if self._loader else 0)
        self.banner.show_message(
            f"Stopped reading: {message}. Everything read before that point is shown.",
            "Dismiss",
        )

    # -- live capture ----------------------------------------------------

    def capture_from_device(self) -> None:
        """Start capturing from whatever device is attached.

        No device is not an error worth a dialog: it is the ordinary state of a
        program whose subject is a phone that spends most of its time in a
        pocket. It gets the same banner every other invisible state gets, with
        the same way out.
        """
        try:
            source = self._build_source()
        except OstraceError as exc:
            hint = f" {exc.hint}" if getattr(exc, "hint", None) else ""
            self.banner.show_message(f"{exc}{hint}", "Retry", on_action=self.capture_from_device)
            return
        self.start_capture(source)

    def _build_source(self) -> LogSource:
        """The live source. Imported here, not at module scope.

        `ostrace.sources.os_trace` refuses to be imported under ``-O``, and it
        pulls in pymobiledevice3 -- about forty packages. Neither belongs in the
        path that merely opens a saved capture.
        """
        from ostrace.sources.os_trace import OsTraceSource  # noqa: PLC0415

        return OsTraceSource()

    def start_capture(self, source: LogSource, *, destination: Path | None = None) -> None:
        """Begin a live capture into a fresh model.

        The records go to a session file as well as to the table -- the same
        `ostrace.capture.capture` the CLI runs. A live view that keeps nothing
        would make "pause" a promise it cannot honour and would lose everything
        the moment the window closed. ``destination`` overrides where that file
        goes; by default `paths` decides, as it does for the CLI.
        """
        self.stop_capture()

        self.model = RecordModel(self.scheme, parent=self)
        self.table.setModel(self.model)
        self._connect_selection()
        self.detail.clear()
        self.capture = None
        self.setWindowTitle(f"{source.name} — {_TITLE}")

        self._capture_thread = CaptureThread(source, destination=destination)
        self._pump = Pump(self._capture_thread.queue, self.model, parent=self)
        self._pump.rate_changed.connect(self._on_rate)
        self._pump.overflowed.connect(self._on_pause_overflow)
        self._capture_thread.identified.connect(self._on_identified)
        self._capture_thread.failed.connect(self._on_capture_failed)
        self._capture_thread.completed.connect(self._on_capture_finished)

        self._capture_thread.start()
        self._pump.start()
        self._set_capturing(capturing=True)

    def stop_capture(self) -> None:
        """Release the device.

        Named after its consequence rather than "stop": releasing a device
        releases the lockdown session *and* the ``os_trace_relay`` service, and
        a control that reads as the opposite of "pause" invites the user to
        press it expecting to be able to press it back.
        """
        if self._capture_thread is None:
            return
        self._capture_thread.stop()
        # Bounded: the capture's own teardown is a socket close, not a network
        # round trip. Waiting at all is what stops a second capture starting
        # while the first still holds the device.
        self._capture_thread.wait(_STOP_TIMEOUT_MS)
        if self._pump is not None:
            self._pump.stop()
        self._capture_thread = None
        self._set_capturing(capturing=False)

    def set_paused(self, paused: bool) -> None:
        """Freeze the view. The device is not consulted."""
        if self._pump is not None:
            self._pump.set_paused(paused)
        if paused:
            self.banner.show_message(
                "The view is paused. The capture is still running and still "
                "writing every record to the session file.",
                "Resume",
                on_action=lambda: self.action_pause.setChecked(False),
            )
        else:
            self.banner.hide()

    def _set_capturing(self, *, capturing: bool) -> None:
        self.action_capture.setEnabled(not capturing)
        self.action_disconnect.setEnabled(capturing)
        self.action_pause.setEnabled(capturing)
        if not capturing:
            self.action_pause.setChecked(False)
            self.status.set_rate(None)

    def _on_identified(self, device: object) -> None:
        if isinstance(device, DeviceInfo):
            self.status.set_device(device)

    def _on_rate(self, rate: float) -> None:
        self.status.set_rate(rate)
        self.status.set_volume(self.model.retained)
        self.status.set_gap_count(self.model.gaps)
        self._follow()

    def _on_pause_overflow(self, dropped: int) -> None:
        self.banner.show_message(
            f"The view is paused and {dropped:,} records did not fit. They are "
            f"in the session file, not lost.",
            "Resume",
            on_action=lambda: self.action_pause.setChecked(False),
        )

    def _on_capture_failed(self, message: str) -> None:
        self.banner.show_message(f"Capture stopped: {message}", "Dismiss")
        self._set_capturing(capturing=False)

    def _on_capture_finished(self, result: object) -> None:
        del result
        self._set_capturing(capturing=False)

    def _follow(self) -> None:
        """Stay at the bottom, but only if that is where the user already is.

        Derived from the scrollbar on every tick rather than stored as a mode.
        A stored flag can disagree with the view -- Console.app kept one and
        shipped an eleven-month bug where selecting a row silently stopped the
        tail.
        """
        bar = self.table.verticalScrollBar()
        if bar.value() >= bar.maximum() - _FOLLOW_SLACK:
            self.table.scrollToBottom()

    def export_capture(self) -> None:
        """Offer to write the open capture out.

        Only a capture read from disk can be exported: a live one is still
        being written, and exporting a file that is growing under the exporter
        produces a report whose end is arbitrary. Disconnect first -- which is
        also when the sidecar is finalised.
        """
        if self.capture is None:
            self.banner.show_message(
                "There is nothing to export yet. Open a capture, or disconnect "
                "to finish the one being recorded.",
                "Open capture…",
                on_action=self.choose_capture,
            )
            return
        ExportDialog(self.capture, self).exec()

    # -- navigation, marks, copy -----------------------------------------

    def go_to(self, row: int | None) -> None:
        """Select and scroll to a row, if there is one."""
        if row is None or not 0 <= row < self.model.rowCount():
            return
        index = self.model.index(row, 0)
        self.table.setCurrentIndex(index)
        self.table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)

    def go_to_top(self) -> None:
        self.go_to(0)

    def go_to_bottom(self) -> None:
        """Jump to the last row, and resume following if already there.

        Two commands on one key, in the order klogg settled on: the first press
        takes you to the bottom, the second says *stay* there. Conflating them
        into one is what leaves Wireshark's users with "Ctrl End is close, but
        doesn't resume auto scroll".
        """
        last = self.model.rowCount() - 1
        if last < 0:
            return
        if self.table.currentIndex().row() == last:
            self._following = True
        self.go_to(last)

    def find_next(self, kind: Find, *, backwards: bool = False) -> None:
        current = self.table.currentIndex()
        start = current.row() if current.isValid() else -1 if not backwards else 0
        self.go_to(self.model.find(kind, start, backwards=backwards))

    def toggle_mark(self) -> None:
        current = self.table.currentIndex()
        if current.isValid():
            self.model.toggle_mark(current.row())

    def step_row(self, delta: int) -> None:
        """Move the selection without needing the table to have focus.

        Wireshark documents exactly this and it is necessary rather than a
        nicety once there is a detail pane: reading a record puts focus in the
        pane, and the next thing anyone wants is the next record.
        """
        current = self.table.currentIndex()
        row = current.row() + delta if current.isValid() else 0
        self.go_to(max(0, min(row, self.model.rowCount() - 1)))

    def copy_selection(self) -> None:
        """Copy the selected rows as tab-separated text.

        Rows rather than cells, and TSV rather than anything cleverer, because
        the destination is a bug report or a spreadsheet. Two things the table
        does for readability are undone on the way out:

        - **a blanked repeat cell is filled back in.** What was elided to make
          a long run scannable would be a hole in a pasted record, in exactly
          the fields that identify it.
        - **the message is folded onto one line**, by the exporters' own
          `escape`. Device messages really do contain newlines and tabs, and a
          record spilling across several lines breaks every consumer of a
          tab-separated paste -- which is the whole audience for this. Reused
          rather than reinvented: the folding rule is part of the bundle
          contract, and two spellings of it would eventually disagree.
        """
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        if not rows:
            return
        lines = [
            "\t".join(
                escape(self.model.cell_text(row, column))
                for column in range(self.model.columnCount())
            )
            for row in rows
        ]
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText("\n".join(lines))

    def show_keys(self) -> None:
        """The key sheet, rendered from the same table the bindings come from."""
        rows = "\n".join(f"{keys:<28} {label} — {why}" for label, keys, why in key_table())
        QMessageBox.information(self, "Keyboard shortcuts", rows)

    # -- filtering, selection, state -------------------------------------

    def _on_filter_changed(self) -> None:
        """Coalesce keystrokes into one rescan.

        Rescanning per character is what makes Android Studio's Logcat throw
        the user to the bottom of the buffer on every key they press.
        """
        self._filter_debounce.start()

    def _apply_filter(self) -> None:
        try:
            wanted = Filter(
                minimum_level=self.filter_bar.minimum_level,
                process=self.filter_bar.process,
                subsystem=self.filter_bar.subsystem,
                search=self.filter_bar.search,
                regex=self.filter_bar.regex,
            )
        except ValueError as exc:
            # Half a pattern is not an empty log. The previous filter stays
            # applied and the user is told why, rather than watching the view
            # empty itself as they type.
            self.banner.show_message(str(exc), "Dismiss")
            return

        anchor = self._anchor()
        self.model.set_filter(wanted)
        self._restore(anchor)
        self._update_banner()

    def _anchor(self) -> int | None:
        """Which retained item the user is currently reading.

        A position in the retained list, not a view row: view rows are
        renumbered by the rescan that is about to happen.
        """
        current = self.table.currentIndex()
        if not current.isValid() or self.model.rowCount() == 0:
            return None
        return self.model.source_index(current.row())

    def _restore(self, anchor: int | None) -> None:
        """Put the user back where they were reading.

        The record they had selected may not have survived the new filter, in
        which case the nearest survivor after it is where they were. Nobody
        surveyed does this -- see `RecordModel.nearest_view_row`.
        """
        if anchor is None:
            return
        row = self.model.nearest_view_row(anchor)
        if row is None:
            return
        index = self.model.index(row, 0)
        self.table.setCurrentIndex(index)
        self.table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)

    def _on_current_row_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        del previous
        if not current.isValid():
            self.detail.clear()
            return
        # No host clock: these records came out of a file. Comparing one
        # against the present moment measures how long ago it was captured, not
        # how far apart the two clocks are, and labelling that "difference"
        # would invent a problem the device does not have. The live path, which
        # does have two readings of one moment, will pass it.
        self.detail.show_item(self.model.row_at(current.row()))

    def _update_banner(self) -> None:
        """The two states that look exactly like a quiet device.

        A filter that matches nothing and a device that is saying nothing
        produce the same empty table. Only one of them is the user's own doing,
        and only one has a way out.
        """
        if self.model.rowCount() == 0 and self.model.retained > 0:
            self.banner.show_message(
                f"All {self.model.retained:,} records are hidden by the filter.",
                "Clear filter",
                on_action=self.filter_bar.clear,
            )
            self._showing_filter_notice = True
        elif self._showing_filter_notice:
            self.banner.hide()
            self._showing_filter_notice = False
        #: Auto-follow. Set when the user asks to resume it, cleared as soon as
        #: they scroll away -- see `_follow`, which derives the rest.
        self._following = True
