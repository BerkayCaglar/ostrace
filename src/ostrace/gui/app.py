# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Application construction, kept separate from the event loop.

``build_application()`` returns a fully themed ``QApplication`` without
starting anything. The tests and the screenshot tool both need exactly that:
an application configured the way a user's would be, that never blocks. Only
``run()`` calls ``exec()``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QApplication

from ostrace import __version__
from ostrace.gui import icons
from ostrace.gui.theme import Scheme, apply_theme, resolve_scheme
from ostrace.gui.windows.main import MainWindow

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["build_application", "build_window", "run"]

#: Used by ``QSettings`` and shown by the window manager. ``setOrganizationName``
#: is what stops Qt writing settings under a vendor called "Unknown".
APP_NAME = "ostrace"
ORG_NAME = "ostrace"


def build_application(argv: Sequence[str] | None = None) -> QApplication:
    """A themed application, not yet running.

    Any existing instance is reused. Qt permits exactly one ``QApplication``
    per process and constructing a second is a hard failure, which matters here
    because a test session builds one per test file otherwise.
    """
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication(list(argv) if argv is not None else [])

    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setApplicationVersion(__version__)
    # On the application rather than on the window: every window, dialog and
    # message box inherits it, and the taskbar entry comes from here too. There
    # was no icon at all, so the title bar, Alt-Tab and the taskbar all showed
    # Qt's default -- which on Windows is a blank sheet.
    app.setWindowIcon(icons.app_icon())

    # Once, at startup. A theme switch *while* the program is open is the
    # window's to handle and deliberately not connected here: this function
    # cannot see whether the user has chosen a scheme, so a connection made at
    # this level overrides that choice from outside the object that holds it.
    # It did. Two listeners answered the same signal under different rules --
    # this one unconditionally, `MainWindow._on_color_scheme_changed` only
    # while the user had expressed no preference -- so an operating-system
    # switch moved the palette and the stylesheet while the table, the model,
    # the minimap and the icons stayed where the user had put them. What that
    # looks like is a dark window with a white log in the middle of it.
    apply_theme(app, resolve_scheme(app.styleHints()))
    return app


def build_window(scheme: Scheme | None = None) -> MainWindow:
    """The main window, built but not shown."""
    if scheme is None:
        app = QApplication.instance()
        scheme = resolve_scheme(app.styleHints()) if isinstance(app, QApplication) else Scheme.LIGHT
    return MainWindow(scheme=scheme)


def run(argv: Sequence[str] | None = None) -> int:
    """Launch the viewer and block until the user closes it."""
    app = build_application(argv)
    window = build_window()
    window.show()
    return app.exec()
