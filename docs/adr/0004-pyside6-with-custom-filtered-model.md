---
status: accepted
date: 2026-08-08
decision-makers: Berkay ÇAĞLAR
---

# PySide6 with a hand-written filtered table model

## Context and Problem Statement

The viewer must display a live log stream at roughly 1,200 records per second,
retain on the order of 200,000 rows, colour rows by severity, filter
interactively without a visible stall, and allow copying. It has to look and
behave the same on Windows and macOS — and the author has no Mac, so anything
that renders through a platform-native widget set is being written blind.

Two questions: which toolkit, and how to filter.

## Decision Drivers

- Virtualised table: 200k rows must not mean 200k widgets.
- Per-row background colour, which several toolkits refuse outright.
- Text selection and clipboard access.
- Identical rendering across platforms, because only one can be tested.
- Licence compatible with GPL-3.0-**or-later** (see [ADR 0003](0003-license-gpl-3-0-or-later.md)).

## Considered Options

1. **PySide6** with `QTableView` + a custom `QAbstractTableModel`.
2. **PyQt6** — architecturally identical.
3. **Toga / BeeWare.**
4. **Flet.**
5. **Tkinter + ttkbootstrap** — what the predecessor used.
6. **Dear PyGui.**
7. **A local web UI** in a browser tab.

## Decision Outcome

Chosen option: **PySide6**, `QTableView` with a hand-written
`QAbstractTableModel` that maintains **its own filtered index list**.

Explicitly **not** `QSortFilterProxyModel`. Measured on 100,000 rows, a filter
change through the proxy takes about 6 seconds against about 0.09 seconds for a
direct predicate over an index list — roughly a 66× gap, and 6 seconds is a
frozen window, not a slow one.

> **Re-measured, and the number was wrong.** On PySide6 6.11.1 with the model
> as built, 100,000 records, best of three with a view attached: our index list
> 0.130 s, the proxy's built-in regex over a role 0.607 s, a Python
> `filterAcceptsRow` 0.642 s. About **4.7×**, and no configuration froze
> anything. The choice is unchanged — 4.7× is still worth having, and the row
> cap, the eviction notice and the marker exemption all need a model we own —
> but it does not rest on the figure above.

Our filtering is incremental: each arriving batch tests only the new records and
appends the matching indices, which is O(batch). Only a change to the filter
itself rescans.

### Consequences

- Good: Qt draws its own widgets identically on every platform, which is exactly
  what the no-Mac constraint calls for.
- Good: PySide6's LGPLv3 option leaves "or-later" intact.
- Good: `QTableView` is properly virtualised; only visible cells are queried.
- Bad: Qt is a large dependency. Mitigated by depending on
  **`PySide6-Essentials`, never bare `PySide6`** — the meta-package additionally
  pulls `PySide6-Addons` (QtWebEngine, Qt3D, QtCharts, QtMultimedia), none of
  which a log viewer touches:

  | Wheel (6.11.1) | Windows x64 | macOS universal2 |
  | --- | ---: | ---: |
  | `PySide6-Essentials` | 77.5 MB | 110.4 MB |
  | `PySide6-Addons` | 168.8 MB | 331.7 MB |
  | bare `PySide6` | ~246 MB | ~442 MB |

  One dependency line saves 170–330 MB.
- Bad: `QTableView` selects whole cells, not substrings. Cell and row copy are
  straightforward; substring selection inside a message needs a custom
  `QStyledItemDelegate` exposing a read-only `QLineEdit`. The detail pane covers
  the common case until then.
- Bad: Qt's open-source Community Edition rides the roughly six-monthly minor
  train, and LTS patch releases past the first are commercial-only. Budget a
  PySide6 bump about twice a year; pin a range, never an exact version.

### Performance rules that follow, and are mandatory rather than stylistic

> **Superseded.** The table below is kept as the record of what was decided and
> why. Before phase 4 the claims were re-measured on PySide6 6.11.1 and half did
> not survive: `multiData()` is *marginally slower* in PySide6, the `flags()`
> figure was overstated by about 15×, and hiding the horizontal header — a
> footnote here — is worth about 1000×. Use
> [`docs/design/gui.md` §11](../design/gui.md) instead. The choice of PySide6
> and of a hand-written filtered model is unaffected.

Each comes from a measurement or an open Qt bug, and each has stalled a real
table view at these row counts.

| Rule | Why |
| --- | --- |
| `QTableView` only — never `QTreeView`/`QListView` | At 10M items: `QTableView` made 84 `data()` calls, `QListView` 379 and *20 million* `rowCount()` calls. Initialisation at 70M items: 0.499 s vs 152.8 s vs 236.7 s |
| Override `multiData()` | Qt queries about seven roles per visible cell, and the default `multiData()` just calls `data()` seven times — seven C++↔Python crossings per cell. Overriding collapses it to one. The single biggest lever in a *Python* model |
| Cache the `flags()` return value | A profiled PySide6 case at 200k rows spent 12.2 s across 2.4M `flags()` calls plus 1.4 s in enum `__or__`. Caching one prebuilt value: 7.760 s → 0.396 s |
| Prebuild every `QBrush`/`QColor` | `data()` runs per cell per role; never allocate inside it |
| Fixed row height via `verticalHeader().setSectionResizeMode(Fixed)` | `QTableView` has no `setUniformRowHeights()` — that is `QTreeView`-only |
| Never `resizeRowsToContents()` or `ResizeToContents` headers | QTBUG-57848, open since 2016: `ResizeToContents` queries *all* rows regardless of visibility. Use `resizeContentsPrecision(0)` if needed |
| `setWordWrap(False)`, elide right | Wrapping forces per-row height computation |
| Consider hiding the horizontal header if selection lags | QTBUG-59478, open since 2017: selection is O(N²) beyond ~10k rows because the horizontal header repaint calls `isColumnSelected` |

Row retention is a plain list with a hard cap around 200k, trimmed only once it
overflows by 10% and then in a single `beginRemoveRows` — not per tick, and not
`deque(maxlen=)`, which evicts silently and desynchronises the view.

Records cross from the capture thread to the GUI through a `collections.deque`
(`append` is atomic under the GIL, so no lock), drained by a `QTimer` every
50 ms with one `beginInsertRows` per batch. At 1,200 rec/s that is about 60 rows
per batch and 20 model updates per second. Never one signal per record.

### Confirmation

`tests/test_gui_model.py` runs the model offscreen (`QT_QPA_PLATFORM=offscreen`)
in CI on all three operating systems, with no display. Filtering behaviour and
row-cap trimming are asserted there rather than by hand.

## Pros and Cons of the Options

### PyQt6

- Good, because it is architecturally identical and equally capable.
- Bad, because it is GPLv3-**only**. It would pin this project to exactly
  version 3 and permanently foreclose "or-later".
- Bad, because it ships no class-by-class API reference; the documentation gap
  against PySide6 is substantial.

### Toga / BeeWare

- **Eliminated on capability, not performance.** Per-row colour coding is
  refused by design — maintainers have confirmed this twice, most recently in
  December 2024 — and there is no cross-platform clipboard API (issue #1192,
  open since 2021). Two hard requirements simply unavailable.

### Flet

- Good, because it is the best-looking option and pleasant to write.
- Bad, because `DataTable` is not virtualised; windowing would have to be
  hand-rolled over `ListView`.
- Bad, because it is pre-1.0 with a roughly three-month deprecation window and
  seven breaking changes in one recent release.
- Bad, because `flet build macos` requires a Mac — the exact thing not available.

### Tkinter + ttkbootstrap

- Good, because it is what the predecessor used and it works today.
- Bad, because `ttk.Treeview` is not virtualised (Tk FR #231, open since 2010).
- Bad, because it selects whole rows only.
- Bad, because **the macOS aqua theme ignores background colours** — severity
  colouring would silently do nothing on the one platform that cannot be tested.

### Dear PyGui

- Bad, because there is no text selection; upstream ImGui #950 has been open
  since 2016.
- Bad, because continuous redraw is wrong for an application left open all day.

### Local web UI

- Good, because it has the strongest table story of any option, and it is the
  designated escape hatch if Qt is ever ruled out.
- Bad, because it means building and maintaining a real frontend plus a
  transport layer, in a second language.
- Bad, because AG Grid's rectangular range copy is Enterprise-only and its EULA
  cannot be combined with GPL-3, leaving Community plus a hand-rolled copy
  handler.
- If ever taken, it must be **a browser tab, not an embedded webview**. A
  webview inherits three different, OS-frozen, individually buggy engines —
  WKWebView, WebKitGTK, WebView2 — of which only one can be tested here. Qt
  draws its own widgets identically on all three, which is precisely why the
  no-Mac constraint argues for it.

## More Information

- [docs/research/gui-toolkit-evaluation.md](../research/gui-toolkit-evaluation.md)
- Prior art: every cross-platform desktop log viewer with real adoption is
  native Qt — klogg (GPL-3.0) and its predecessor glogg. Every web-UI log
  viewer — Logdy, Dozzle — is a server you point a browser at, not a packaged
  desktop app. No successful project was found shipping a bundled Python server
  inside an embedded webview.
