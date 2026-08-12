# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Draw the two-relay comparison for the README.

The claim this project rests on is that `com.apple.os_trace_relay` delivers a
log `com.apple.syslog_relay` does not, and the second half of that sentence had
never been measured: `docs/research/log-sources-comparison.md` records "roughly
900-1,200 lines" for the syslog path, which is a line count where a chart wants
records. An earlier draft of this image labelled the second bar *678 records*,
arrived at by adding two rows of the first bar together. That is why the image
did not ship.

The numbers below are one run, stated with the conditions that produced it, and
`--data` redraws from a fresh one. Both relays were read **over the same
wall-clock window from one process**: the same device delivered 5,140 records in
one 20-second window and 36,763 in another, so two sequential runs would compare
the device's mood rather than the two services.

**The bar shows tiers, not a ratio, and that is deliberate.** Across three runs
the ratio moved between 9.1x and 20.1x with how much DEBUG the device happened
to be emitting; what did not move is which tiers arrive. `syslog_relay` returned
NOTICE and above to within 1.5% every time, and exactly it once. A chart built
on the ratio would be picking its best number.

Colours come from `gui/theme.py`'s severity tokens, so the image and the viewer
it advertises agree by construction.

    python tools/build_source_chart.py docs/images/log-sources-light.png
    python tools/build_source_chart.py out.png --scheme dark --data run.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import NamedTuple

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontInfo,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QPainter,
)

#: One run, 2026-08-13, `iPhone18,2` on iOS 26.5.2 over USB: a 60-second window
#: with the first 5 seconds dropped, because `os_trace_relay` replays a backlog
#: at connect and folding that into the total would flatter the first bar.
MEASURED = {
    "window_seconds": 60.0,
    "warmup_dropped_seconds": 5.0,
    "os_trace_warm": 233_956,
    "syslog_warm": 11_642,
    "levels_warm": {"DEBUG": 206_135, "INFO": 16_342, "NOTICE": 11_216, "ERROR": 263},
}

#: Straight out of `TOKENS` in `gui/theme.py`.
SCHEMES = {
    "light": {
        "bg": "#f1f2f4",
        "plate": "#ffffff",
        "fg": "#14161a",
        "muted": "#5f6773",
        "border": "#d6d9df",
        "DEBUG": "#8b94a3",
        "INFO": "#5f6773",
        "NOTICE": "#1f5fd0",
        "ERROR": "#b02a1f",
    },
    "dark": {
        "bg": "#15171c",
        "plate": "#1b1e24",
        "fg": "#e7eaf0",
        "muted": "#99a2b0",
        "border": "#2e333c",
        "DEBUG": "#6b7482",
        "INFO": "#99a2b0",
        "NOTICE": "#5b9bff",
        "ERROR": "#ff8a7a",
    },
}

FACE = "Cascadia Code"
CANVAS = QSize(1200, 500)
SCALE = 2

MARGIN = 72
BAR_WIDTH = CANVAS.width() - MARGIN * 2
BAR_HEIGHT = 64

#: Drawn in this order, so the tier a `syslog_relay` tool never sees comes
#: first and the eye reads the bar as "this much, then the sliver".
TIERS = ("DEBUG", "INFO", "NOTICE", "ERROR")


class Text(NamedTuple):
    body: str
    px: int
    weight: QFont.Weight
    ink: str


def _font(px: int, weight: QFont.Weight) -> QFont:
    font = QFont(FACE)
    font.setPixelSize(px * SCALE)
    font.setWeight(weight)
    return font


def _require_face() -> None:
    """Refuse before a pixel is drawn, rather than during.

    Qt substitutes a missing family silently, so the image would still be
    written -- in whatever face this machine happened to have, and the two
    schemes would differ only when somebody compared them side by side.

    Checked here rather than inside `_font`, and that is not tidiness: raising
    from inside the paint leaves a live `QPainter` on a `QImage` that is then
    collected, and Qt ends the process for it. The first draft did exactly that
    and reported `Fatal Python error: Aborted` with no message -- the same shape
    as the `QThread` hazard in ADR 0007, from the other end of the toolkit.

    **Do not run this under the offscreen platform plugin.** Measured here:
    `QFontDatabase.families()` returns 154 families under the normal Windows
    plugin and **zero** under `offscreen`, so every face fails to resolve and
    the guard below fires on a machine that has the font installed.
    """
    if not QFontDatabase.families():
        message = (
            "Qt sees no font families at all, which is what the offscreen "
            "platform plugin gives on Windows. Run without QT_QPA_PLATFORM."
        )
        raise SystemExit(message)
    probe = QFont(FACE)
    if not QFontInfo(probe).exactMatch():
        message = f"{FACE} is not installed; Qt would substitute {QFontInfo(probe).family()!r}"
        raise SystemExit(message)


def _write(painter: QPainter, text: Text, tokens: dict[str, str], left: int, top: int) -> None:
    painter.setFont(_font(text.px, text.weight))
    painter.setPen(QColor(tokens[text.ink]))
    rect = QRectF(left * SCALE, top * SCALE, (CANVAS.width() - left) * SCALE, text.px * 1.6 * SCALE)
    flags = int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    painter.drawText(rect, flags, text.body)


def draw(scheme: str, data: dict) -> QImage:
    _require_face()
    tokens = SCHEMES[scheme]
    levels: dict[str, int] = data["levels_warm"]
    total: int = data["os_trace_warm"]
    syslog: int = data["syslog_warm"]

    size = QSize(CANVAS.width() * SCALE, CANVAS.height() * SCALE)
    image = QImage(size, QImage.Format.Format_ARGB32)
    image.fill(QColor(tokens["bg"]))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    def write(text: Text, left: int, top: int) -> None:
        _write(painter, text, tokens, left, top)

    write(Text("What one iPhone emits in a minute", 34, QFont.Weight.DemiBold, "fg"), MARGIN, 40)
    write(
        Text("and what each lockdown service hands back", 22, QFont.Weight.Normal, "muted"),
        MARGIN,
        84,
    )

    # os_trace_relay, segmented by tier.
    write(Text("os_trace_relay", 22, QFont.Weight.DemiBold, "fg"), MARGIN, 148)
    write(Text(f"{total:,} records", 22, QFont.Weight.Normal, "muted"), MARGIN + 200, 148)
    left = float(MARGIN)
    top = 186
    for tier in TIERS:
        count = levels.get(tier, 0)
        if not count:
            continue
        width = BAR_WIDTH * count / total
        painter.fillRect(
            QRectF(left * SCALE, top * SCALE, width * SCALE, BAR_HEIGHT * SCALE),
            QColor(tokens[tier]),
        )
        share = count / total
        label = f"{tier}  {share:.0%}"
        painter.setFont(_font(20, QFont.Weight.DemiBold))
        # Fits, or it goes in the legend instead. A centred label on a 7%
        # segment does not get truncated by Qt, it gets drawn over its
        # neighbours: the first draft rendered `NFO 7` across the boundary.
        if QFontMetricsF(painter.font()).horizontalAdvance(label) < width * SCALE * 0.85:
            painter.setPen(QColor(tokens["bg"]))
            painter.drawText(
                QRectF(left * SCALE, top * SCALE, width * SCALE, BAR_HEIGHT * SCALE),
                int(Qt.AlignmentFlag.AlignCenter),
                label,
            )
        left += width

    # Every tier named with its count, because the narrow ones are exactly the
    # ones a reader wants the number for -- ERROR is 0.1% and two pixels wide.
    swatch = 16
    at = float(MARGIN)
    for tier in TIERS:
        count = levels.get(tier, 0)
        if not count:
            continue
        painter.fillRect(
            QRectF(at * SCALE, (top + BAR_HEIGHT + 24) * SCALE, swatch * SCALE, swatch * SCALE),
            QColor(tokens[tier]),
        )
        entry = f"{tier} {count:,} ({count / total:.1%})"
        write(
            Text(entry, 18, QFont.Weight.Normal, "muted"),
            int(at) + swatch + 10,
            top + BAR_HEIGHT + 16,
        )
        painter.setFont(_font(18, QFont.Weight.Normal))
        at += swatch + 10 + QFontMetricsF(painter.font()).horizontalAdvance(entry) / SCALE + 32

    # syslog_relay, on the same scale, drawn from its own measured count.
    write(Text("syslog_relay", 22, QFont.Weight.DemiBold, "fg"), MARGIN, 316)
    write(Text(f"{syslog:,} entries", 22, QFont.Weight.Normal, "muted"), MARGIN + 200, 316)
    width = BAR_WIDTH * syslog / total
    top = 354
    painter.fillRect(
        QRectF(MARGIN * SCALE, top * SCALE, width * SCALE, BAR_HEIGHT * SCALE),
        QColor(tokens["NOTICE"]),
    )
    write(
        Text(
            f"NOTICE and above, and nothing below it — {syslog / total:.0%} of the log",
            20,
            QFont.Weight.Normal,
            "muted",
        ),
        MARGIN + int(width) + 20,
        top + BAR_HEIGHT // 2 - 16,
    )

    write(
        Text(
            f"iPhone18,2 · iOS 26.5.2 · both relays read over the same "
            f"{data['window_seconds']:.0f} s window",
            19,
            QFont.Weight.Normal,
            "muted",
        ),
        MARGIN,
        448,
    )
    # `end()` explicitly: a QPainter still active when its device is destroyed
    # warns on every platform and leaves the image half drawn on some.
    painter.end()
    return image


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--scheme", choices=sorted(SCHEMES), default="light")
    parser.add_argument("--data", type=Path, help="a run written by the comparison script")
    args = parser.parse_args(argv)

    data = json.loads(args.data.read_text(encoding="utf-8")) if args.data else MEASURED
    QGuiApplication(sys.argv[:1])
    image = draw(args.scheme, data)
    if not image.save(str(args.output)):
        message = f"could not write {args.output}"
        raise SystemExit(message)
    print(f"{args.output}  {image.width()}x{image.height()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
