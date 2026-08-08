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

    hints = app.styleHints()
    apply_theme(app, resolve_scheme(hints))

    # A theme switch while the program is open. Verified to fire on Windows;
    # the cocoa plugin has the same wiring but there is no Mac here to see it,
    # and it is a no-op under the offscreen plugin, which is why the scheme is
    # a parameter everywhere below rather than something read at the point of
    # use.
    hints.colorSchemeChanged.connect(lambda _scheme: apply_theme(app, resolve_scheme(hints)))
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
