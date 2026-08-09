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

It renders a window with a **real capture loaded**, not an empty one. An empty
table says nothing about column widths, elision, severity colouring or the
detail pane -- which is most of what there is to get wrong on a platform nobody
here can look at. It is also what the README needs, and two tools rendering two
different windows would eventually disagree about which one was current.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtGui import QFontDatabase, QImage

from ostrace.gui.app import build_application
from ostrace.gui.models import Find
from ostrace.gui.theme import Scheme, apply_theme, palette_for
from ostrace.gui.windows.main import MainWindow

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

#: Big enough that nothing is elided into meaninglessness, small enough to read
#: in a pull request without scrolling.
WIDTH = 1280
HEIGHT = 800

#: A committed capture from the physical device, already filtered to system
#: processes. Under `tests/` rather than in the package: this is a repository
#: tool run from a checkout, and a fixture shipped in the wheel would be a
#: megabyte every user pays for so that a maintainer can take a picture.
FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "ios26-mixed.jsonl.gz"

#: How many event-loop turns to allow the capture loader. It reads 2,048
#: records per zero-delay tick, so a 5,000-record fixture needs three -- the
#: bound is here so that a loader which never finishes fails the job instead of
#: hanging it.
_MAX_TURNS = 5_000


def _register_font(path: Path) -> str | None:
    """Make one font file available, for platforms whose plugin ships none."""
    handle = QFontDatabase.addApplicationFont(str(path))
    if handle == -1:
        return None
    families = QFontDatabase.applicationFontFamilies(handle)
    return families[0] if families else None


def _fill(app: QApplication, window: MainWindow, capture_path: Path) -> None:
    """Load a capture and turn the event loop until it is all in.

    ``open_capture`` reads in batches from a zero-delay timer so that a large
    file cannot freeze the window, which means the rows are not there when it
    returns. There is no ``exec()`` here to deliver those ticks, so they are
    pumped by hand.
    """
    loaded = False

    def done() -> None:
        nonlocal loaded
        loaded = True

    window.open_capture(capture_path)
    if window._loader is None:  # noqa: SLF001 - a tool, and the alternative is a signal for one caller
        msg = f"{capture_path} did not open"
        raise RuntimeError(msg)
    window._loader.finished.connect(done)  # noqa: SLF001

    for _ in range(_MAX_TURNS):
        app.processEvents()
        if loaded:
            break
    else:
        msg = f"the loader did not finish {capture_path} in {_MAX_TURNS} turns"
        raise RuntimeError(msg)

    # Land on an error: it puts a coloured row under the cursor, fills the
    # detail pane with a record worth reading, and is the same jump the E key
    # performs. A screenshot of row zero would show whatever the device
    # happened to say first.
    window.find_next(Find.ERROR)
    app.processEvents()

    # Snap to a row boundary. The table scrolls by pixel -- which is what makes
    # a live tail smooth -- so `scrollTo` lands wherever the arithmetic falls,
    # and the top of the picture was a row sliced through the middle. Nobody
    # notices while scrolling; everybody notices in a still.
    bar = window.table.verticalScrollBar()
    row_height = window.table.verticalHeader().defaultSectionSize()
    bar.setValue(bar.value() // row_height * row_height)
    app.processEvents()


def capture(app: QApplication, scheme: Scheme, destination: Path, source: Path) -> Path:
    """Render the main window under ``scheme``, showing ``source``."""
    apply_theme(app, scheme)
    window = MainWindow(scheme=scheme)
    window.resize(WIDTH, HEIGHT)
    window.show()
    app.processEvents()
    _fill(app, window, source)

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
        "--capture",
        type=Path,
        default=FIXTURE,
        help="the capture to show in the window (default: the committed fixture)",
    )
    parser.add_argument(
        "--font",
        type=Path,
        help="a .ttf to register before rendering, for a platform plugin that has none",
    )
    args = parser.parse_args(argv)

    if not args.capture.exists():
        print(f"no capture at {args.capture}", file=sys.stderr)
        return 1

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
        written = capture(app, scheme, args.out / f"main-{scheme.value}.png", args.capture)
        print(f"{written} ({app.platformName()}, {app.font().family()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
