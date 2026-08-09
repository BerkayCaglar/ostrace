# GUI toolkit evaluation

**Date:** 2026-08-08
**Feeds:** [ADR 0004](../adr/0004-pyside6-with-custom-filtered-model.md)
**Status of the evidence:** capability claims are from upstream issue trackers
and maintainer statements, cited inline. Performance figures are from published
benchmarks and profiled reports, not from a rig built for this project.

---

## Requirements

The viewer is not a generic table. Five properties are non-negotiable, and each
one eliminated at least one candidate.

1. **A virtualised table.** Around 200,000 retained rows, arriving at up to
   1,200 per second. A toolkit that materialises a widget per row is finished
   before it starts.
2. **Per-row background colour** for severity. This is how a log viewer is read.
3. **Text selection and clipboard access.** Copying a message is the single most
   common thing a user does with a log line.
4. **Identical rendering on Windows and macOS.** The maintainer has no Mac. A
   toolkit that delegates to native widgets is one whose macOS appearance cannot
   be verified before users see it.
5. **A licence compatible with GPL-3.0-or-later.**

## Eliminated on capability

These did not reach the performance discussion.

**Toga / BeeWare.** Per-row colour coding is refused *by design* — maintainers
have declined it twice, most recently December 2024, on the grounds that it
conflicts with native platform styling. There is also no cross-platform
clipboard API; issue #1192 has been open since 2021. Requirements 2 and 3, both
absent.

**Tkinter + ttkbootstrap** — what the predecessor tool used, so its limits are
known from use rather than from reading. `ttk.Treeview` is not virtualised (Tk
feature request #231, open since 2010); it selects whole rows only; and **the
macOS aqua theme ignores background colours**, so severity colouring would
silently do nothing on the one platform that cannot be tested. Requirements 1,
2 and 3.

**Dear PyGui.** No text selection — the upstream ImGui issue (#950) has been
open since 2016. It also redraws continuously, which is wrong for an application
left open all day watching a device. Requirement 3.

## Considered seriously and rejected

**Flet** was the most attractive of the rejected options and would produce the
best-looking result. Three things stopped it: `DataTable` is not virtualised, so
windowing would have to be hand-rolled over `ListView`; it is pre-1.0 with about
a three-month deprecation window and seven breaking changes in one recent
release; and `flet build macos` requires a Mac, which is precisely the
constraint being worked around.

**PyQt6** is architecturally identical to PySide6 and equally capable. It is
GPLv3-**only**. Adopting it would pin this project to exactly GPL version 3 and
permanently foreclose the "or-later" option, in exchange for nothing. Its
documentation is also markedly thinner — no class-by-class API reference.

**A local web UI** has the strongest table story of anything considered, and is
recorded in ADR 0004 as the designated escape hatch if Qt is ever ruled out. It
was not chosen because it means building and maintaining a real frontend plus a
transport layer in a second language, and because AG Grid's rectangular range
copy is Enterprise-only with an EULA that cannot be combined with GPL-3.

If it is ever taken, it must be **a browser tab, not an embedded webview**. A
webview inherits three different, OS-frozen, individually buggy engines —
WKWebView on macOS, WebKitGTK on Linux, WebView2 on Windows — and only one of
them can be tested here. Qt draws its own widgets identically on all three,
which is the same constraint pointing the other way.

## Prior art

Every cross-platform desktop log viewer with real adoption is native Qt: klogg
(GPL-3.0) and its predecessor glogg. Every web-UI log viewer — Logdy, Dozzle —
is a server you point a browser at, not a packaged desktop application. No
successful project was found that ships a bundled Python server inside an
embedded webview, which is the shape this project would have been inventing.

## The performance findings that shaped the model design

> **Superseded, 0.1.0.** This section is the pre-phase-4 survey and is kept as
> the record of what the design was reasoned from. Every figure in it was
> re-measured on PySide6 6.11.1 while phase 4 was built, and about half did not
> survive: `multiData()` is *marginally slower* rather than the biggest lever,
> the `flags()` figure was overstated by roughly 15×, the proxy is 4.7× rather
> than 66× and never froze, and the horizontal header — mentioned here only as
> a workaround — is worth about 2× against the model that ships.
> **[`docs/design/gui.md` §11](../design/gui.md) is the current
> version.** The conclusion this section was drawing — Qt with a hand-written
> filtered model — is unaffected, which is why it is corrected rather than
> deleted.

Choosing Qt settles the toolkit. It does not settle the design, and a naive Qt
model at these row counts is slow in ways that are not obvious from the
documentation.

### `QSortFilterProxyModel` is unusable at this scale

Filtering 100,000 rows through the proxy measures around **6 seconds** per
filter change, against about **0.09 seconds** for a direct predicate over a
plain index list — roughly 66×. Six seconds is not a slow filter; it is a frozen
window.

The design consequence is that the model keeps its own filtered index list. On
each arriving batch it tests only the new records and appends matching indices,
which is O(batch). Only a change to the filter itself triggers a rescan. This is
the decision most likely to look like a mistake to someone reading the Qt
documentation, which is why it is written down twice.

### View class matters more than expected

Benchmarked at 10 million items, the three view classes are not
interchangeable:

| View | `data()` calls | `rowCount()` calls |
| --- | ---: | ---: |
| `QTableView` | 84 | — |
| `QListView` | 379 | 20,000,000 |

Initialisation time at 70 million items: `QTableView` 0.499 s, `QListView`
152.8 s, `QTreeView` 236.7 s.

### `multiData()` is the biggest single lever in a Python model

Qt queries roughly seven roles per visible cell. The default `multiData()`
implementation simply calls `data()` seven times — seven C++↔Python boundary
crossings per cell, per repaint. Overriding it collapses that to one. In C++
this is a minor optimisation; in Python it is the dominant cost.

### `flags()` is called far more often than it looks

A profiled PySide6 case at 200,000 rows spent **12.2 s** across 2.4 million
`flags()` calls, plus a further **1.4 s** in enum `__or__` from rebuilding the
flag combination each time. Caching a single prebuilt value took the case from
7.760 s to 0.396 s.

### Two open Qt bugs to design around

- **QTBUG-57848** (open since 2016): `ResizeToContents` on a header queries
  *every* row, not just visible ones. So: never `resizeRowsToContents()`, never
  `ResizeToContents` headers. `resizeContentsPrecision(0)` limits it to the
  visible area if it is needed at all.
- **QTBUG-59478** (open since 2017): selection is O(N²) beyond about 10,000 rows
  because the horizontal header repaint calls `isColumnSelected`. Hiding the
  horizontal header is the workaround if selection lags.

Also worth knowing: `QTableView` has no `setUniformRowHeights()` — that is
`QTreeView`-only. The equivalent is
`verticalHeader().setSectionResizeMode(Fixed)` plus `setDefaultSectionSize()`.

### One capability gap that has to be worked around

`QTableView` selects whole cells, not substrings. Cell and row copy are simple
(`Ctrl+C` → `selectedIndexes()` → tab-separated to the clipboard), but selecting
part of a message needs a custom `QStyledItemDelegate` exposing a read-only
`QLineEdit`. The detail pane covers the common case in the meantime.

## macOS traps that are invisible from Windows

Each of these would ship broken and would not be noticed by a Windows-only
developer.

**Menu items silently relocate.** Qt applies text heuristics on macOS: any
action whose text matches `settings`, `options`, `preferences`, `config` or
`setup` is moved into the application menu; `about…` goes to About; `quit` and
`exit` go to Quit. Every action defaults to `TextHeuristicRole`. A "Settings…"
item would vanish from the menu it was placed in. The fix is
`setMenuRole(QAction.MenuRole.NoRole)` explicitly on every action that must stay
put.

**`QFileDialog` ignores the `filter` argument** with the macOS native dialog.
The export dialogs rely on filters. Either accept the loss or pass
`DontUseNativeDialog`. Separately, subclassing `QFileDialog` with `Q_OBJECT`
silently forces the non-native dialog.

**High DPI cannot be disabled** on macOS — `QT_ENABLE_HIGHDPI_SCALING=0` has no
effect — and macOS reports an integer `devicePixelRatio` while Windows allows
fractional values. So: no fixed pixel widths, no `setFixedHeight`, no hardcoded
point sizes anywhere in a dense monospaced table.

**Dark mode.** Severity colours must derive from `QPalette` or branch on
`QStyleHints.colorScheme()`. Hardcoded yellow-on-white or dark-red-on-dark fails
on one theme or the other.

**Qt 6.11 requires macOS 13 or newer.** That belongs in `LSMinimumSystemVersion`
and in the README.

**Shortcuts.** `QKeySequence.StandardKey` throughout: `Ctrl` maps to `⌘`
automatically, but the *bindings* differ — Back is `Alt+Left` on Windows and
`⌘[` on macOS.

### The mitigation that makes blind macOS work tractable

GitHub-hosted runners are free and unlimited on public repositories. Beyond
running the test suite on macOS, CI can **take a screenshot of the GUI offscreen
and upload it as a build artifact**. That is the only practical way to see a
relocated menu item or a clipped layout without owning a Mac.
