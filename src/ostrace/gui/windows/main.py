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
    QFileDialog,
    QMainWindow,
    QMenu,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ostrace.errors import OstraceError
from ostrace.gui.filters import Filter
from ostrace.gui.live import CaptureThread
from ostrace.gui.loader import CaptureLoader
from ostrace.gui.models import RecordModel
from ostrace.gui.pump import Pump
from ostrace.gui.theme import Scheme
from ostrace.gui.widgets.banner import Banner
from ostrace.gui.widgets.detail_pane import DetailPane
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

        self.filter_bar.changed.connect(self._on_filter_changed)
        self.action_open.triggered.connect(self.choose_capture)
        self.action_capture.triggered.connect(self.capture_from_device)
        self.action_disconnect.triggered.connect(self.stop_capture)
        self.action_pause.toggled.connect(self.set_paused)
        self._set_capturing(capturing=False)

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
