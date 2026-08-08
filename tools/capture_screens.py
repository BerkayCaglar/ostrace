# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Render the GUI to PNG files, so a maintainer with no Mac can see the macOS UI.

Qt clips layouts differently on macOS under a device pixel ratio that is always
an integer there, and picks a system font nobody here can preview. Neither is
visible from Windows, and neither is visible from a passing test suite. A
picture is.

What a picture cannot show is the macOS menu bar: it belongs to the *screen*
rather than to the window, so ``render()`` cannot contain it whatever the
platform plugin, and under ``offscreen`` Qt draws an in-window menu bar
instead. Menu relocation is guarded by the menu-role test, not by this.

It is run from a ``workflow_dispatch`` job, not on every push: a documentation
tool rather than a gate. Nothing here asserts anything.

**Choosing the platform plugin is the workflow's job, not this script's.** The
offscreen plugin renders correctly and needs no display, no window manager and
no extra packages -- but its font database is empty on Windows, where text
comes out as tofu boxes while ``QFontMetrics`` keeps returning plausible
numbers. So the workflow sets ``QT_QPA_PLATFORM`` per operating system and this
file stays free of platform branching. It does refuse to write a picture it
knows is unreadable.

``render()`` into a pre-filled image rather than ``grab()``: both produce
identical output in every case measured here, but ``grab()`` has been reported
not to paint a top-level's background under the offscreen plugin. Pre-filling
costs nothing and is correct under either account.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtGui import QFontDatabase, QImage

from ostrace.gui.app import build_application
from ostrace.gui.theme import Scheme, apply_theme, palette_for
from ostrace.gui.windows.main import MainWindow

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

#: Big enough that nothing is elided into meaninglessness, small enough to read
#: in a pull request without scrolling.
WIDTH = 1280
HEIGHT = 800


def _register_font(path: Path) -> str | None:
    """Make one font file available, for platforms whose plugin ships none."""
    handle = QFontDatabase.addApplicationFont(str(path))
    if handle == -1:
        return None
    families = QFontDatabase.applicationFontFamilies(handle)
    return families[0] if families else None


def capture(app: QApplication, scheme: Scheme, destination: Path) -> Path:
    """Render the main window under ``scheme``."""
    apply_theme(app, scheme)
    window = MainWindow(scheme=scheme)
    window.resize(WIDTH, HEIGHT)
    window.show()
    app.processEvents()

    image = QImage(window.size(), QImage.Format.Format_ARGB32)
    image.fill(palette_for(scheme).window().color())
    window.render(image)

    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(destination))
    window.hide()
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("screenshots"))
    parser.add_argument(
        "--font",
        type=Path,
        help="a .ttf to register before rendering, for a platform plugin that has none",
    )
    args = parser.parse_args(argv)

    app = build_application([])

    if args.font is not None and _register_font(args.font) is None:
        print(f"could not load the font at {args.font}", file=sys.stderr)
        return 1

    if not QFontDatabase.families():
        # Refuse rather than upload a picture of empty rectangles. A screenshot
        # nobody can read is worse than none: it looks like evidence.
        print(
            f"the {app.platformName()!r} platform plugin has no fonts, so every "
            "glyph would render as a tofu box. Pass --font, or use a platform "
            "plugin that has a font database.",
            file=sys.stderr,
        )
        return 1

    for scheme in Scheme:
        written = capture(app, scheme, args.out / f"main-{scheme.value}.png")
        print(f"{written} ({app.platformName()}, {app.font().family()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
