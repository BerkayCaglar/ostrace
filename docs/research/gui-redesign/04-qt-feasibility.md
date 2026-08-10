# Qt feasibility for the ostrace GUI redesign

What PySide6 can actually deliver, what it costs, and what will break.
Everything below was **run**, not reasoned about. Where I could not run it
(macOS) it is labelled `# UNVERIFIED-MACOS` and attributed to documented Qt
behaviour.

## Environment

| | |
| --- | --- |
| PySide6 / Qt / shiboken6 | **6.11.1** (all three) |
| Python | 3.13.14 |
| Project pin (`pyproject.toml`) | `PySide6-Essentials>=6.8,<7` — so **everything below must also hold at 6.8**; notes flag anything newer |
| Style | `Fusion`, forced by `gui/theme.py::STYLE` |
| Platform plugin | `windows` (real display, **154 font families**) for every measurement unless stated |
| Offscreen cross-check | `QT_QPA_PLATFORM=offscreen` — **0 font families**, as `docs/design/gui.md` §12 already records |
| Display | 2560×1440, `devicePixelRatio = 1.0`, `logicalDpi = 96`. Fractional scaling was simulated with `QT_SCALE_FACTOR` |

Scripts, all in this directory, all runnable with
`<devenv>/Scripts/python.exe -u <script>`:

| script | what it answers |
| --- | --- |
| `probe_qss.py` | first pass over every widget in use |
| `probe_qss2.py` | why header/combobox background-only rules do nothing |
| `probe_qss3.py` | palette ordering, real combobox popup, sort-indicator images |
| `probe_qss4.py` | exact precedence: QSS `::item` vs model roles vs palette |
| `probe_sort.py` | sort-indicator renders (`shots/sort-*.png`) |
| `bench2.py` | interleaved repaint benchmark + cost breakdown + live append |
| `bench3.py` | **isolates the QSS property that destroys scroll blitting** |
| `probe_theme_dpi_icons.py` | `QStyleHints`, HiDPI, icons, toolbar API surface |
| `probe_dpi_icon.py` | run under `QT_SCALE_FACTOR` 1 / 1.5 / 2 |
| `probe_icon2.py` | SVG vs pixmap-backed `QIcon` across densities |
| `probe_offscreen.py` | run twice (native / offscreen) — what CI can assert |
| `probe_toolbar.py`, `probe_ext.py` | `QToolBar` overflow, movability, paint cost |
| `probe_tooltip2/3/4.py` | tooltip styling, and a **live bug in `theme.py`** |

---

## 1. QSS coverage and its limits

### The one rule that explains most of the table

**A `background-color` on its own is silently ignored by every widget whose
style draws its own frame.** QSS only takes over a widget's painting once the
rule contains a *box-model* property — `border`, `padding` or `margin`. Until
then Fusion's primitive paints over your background. Measured, magenta pixels
in a rendered widget:

| rule | result |
| --- | --- |
| `QHeaderView::section { background-color: #f0f }` | **0 px** — no effect at all |
| `QHeaderView::section { background-color: #f0f; border: 0px; padding: 4px }` | **8 804 px** — works |
| `QComboBox { background-color: #f0f }` | **4 px** |
| `QComboBox { background-color: #f0f; border: 1px solid gray }` | **4 190 px** |
| `QPushButton { background-color: #f0f }` | **4 px** |
| `QPushButton { background-color: #f0f; border: 1px solid gray }` | **2 665 px** |

Setting it on the widget, on its parent view, or on `QApplication` made no
difference — it is the missing box-model property, not the scope.
(`probe_qss2.py`.) `QTableView`, `QToolBar`, `QStatusBar`, `QMenuBar`, `QMenu`,
`QLineEdit` and `QScrollBar` do *not* need this; they honour a bare background.

### The table

| widget | styleable | caveat |
| --- | --- | --- |
| `QTableView` (widget/viewport) | **yes** | `QTableView { background }` fills the viewport (42 927 px). **But it costs 12× on scroll — see §3. Use the palette instead.** |
| `QTableView::item` (cells) | **yes** | QSS reaches cells and **overrides the model** — see §2. `padding` is the only safe declaration. |
| `QTableView` selection | **yes** | `::item:selected { background }` *or* `selection-background-color`; either replaces palette `Highlight`. |
| `QTableView` alternating rows | **yes** | `alternate-background-color` works (19 406 px) **and is safe for scrolling**. Palette `AlternateBase` also works — until an `::item { background }` rule kills it. |
| `QHeaderView::section` | **yes** | needs a box-model property (above). |
| `QHeaderView` sort indicator | **survives** | Folklore says styling `::section` deletes the arrow. **It does not.** With `background+border+padding` the arrow still draws and *recolours with `color:`* — see `shots/sort-F-fullcustom-shown.png` (light arrow on a dark section). `::up-arrow` / `::down-arrow` are stylable if you want your own (48 px of a custom red arrow rendered). |
| `QScrollBar` | **yes** | Style **all** sub-controls or you inherit Fusion's arrow buttons on the ends. Groove 2 296 px + handle 280 px with the full set. Cannot be made an auto-hiding overlay scrollbar — see §9. |
| `QLineEdit` | **yes** | bg/border/border-radius/padding all work (5 305 px bg, 840 px border). Placeholder text comes from palette `PlaceholderText`, not from QSS `color`. |
| `QComboBox` (closed) | **yes** | needs a border (above). `::drop-down` and `::down-arrow` are separate sub-controls. |
| `QComboBox` popup | **yes** | The popup is a **separate top-level** (`QListView` inside a `QFrame` whose `isWindow()` is `True`). `QComboBox QAbstractItemView { … }` reaches it — **verified only with the popup actually shown** (6 277 px). Rendering an unshown popup view returns 0 px and will fool you. |
| `QToolBar` | **yes** | bar 7 411 px, `QToolButton` 1 924 px. Style `::handle` and `::separator` too. |
| `QToolButton` | **yes** | full `:hover` / `:pressed` / `:checked` pseudo-states work. |
| `QStatusBar` | **yes** | 7 044 px. Add `QStatusBar::item { border: 0 }` or you keep Fusion's sunken frames around each widget. |
| `QMenuBar` | **yes on Windows/Linux** | 7 692 px here. **`# UNVERIFIED-MACOS`: on macOS `QMenuBar::isNativeMenuBar()` is `True` by default and the bar becomes a real `NSMenu` in the system menu bar — QSS is ignored entirely.** `Qt.AA_DontUseNativeMenuBar` exists (confirmed present) and would give a styleable in-window bar at the cost of looking wrong on macOS. Do not design a menu bar that has to look a particular way. |
| `QMenu` (popups) | **yes** | 9 304 px. **`# UNVERIFIED-MACOS`: menus hanging off the *native* menu bar are `NSMenu` and ignore QSS; free-standing context menus are Qt-drawn and accept it.** |
| `QSplitter::handle` | **yes** | 960 px. `setHandleWidth()` still controls the hit area. |
| `QToolTip` | **yes, application-scoped** | `app.setStyleSheet("QToolTip{…}")` → 1 499 of 1 716 px. A stylesheet on the *host widget* also propagates (1 162 px). **Palette does not work — see below.** |

### Bug found on the way: tooltips ignore `theme.py`

`QApplication.setPalette()` does **not** reach tooltips. `gui/theme.py` sets
`ToolTipBase`/`ToolTipText` for both schemes and neither arrives:

```
light: theme wants ToolTipBase=#ffffff  QToolTip.palette() has=#ffffe1  MISMATCH
dark : theme wants ToolTipBase=#2d2d30  QToolTip.palette() has=#ffffe1  MISMATCH
```

`#ffffe1` is the Windows platform theme's tooltip yellow. So **in the dark
scheme today, tooltips are pale yellow with black text.** The Message column's
tooltip (`models.py` `ToolTipRole`) is the most-used tooltip in the program.

Two things fix it, both measured: `QToolTip.setPalette(pal)` (cyan 1 162 px), or
an application-level QSS `QToolTip` rule. The QSS route is preferable because it
also gets you the padding and border radius a redesign will want.
(`probe_tooltip3.py`, `probe_tooltip4.py`.)

---

## 2. QSS ↔ QPalette — the empirical rule

Setup: a model returning `BackgroundRole` (cyan) on some rows and
`ForegroundRole` (lime) on others; a widget palette with `AlternateBase` orange
and `Highlight` navy. Pixel counts, `probe_qss4.py`:

| stylesheet on the view | model `BackgroundRole` | model `ForegroundRole` | palette `AlternateBase` |
| --- | --- | --- | --- |
| *(none)* | 13 404 | 36 | 20 106 |
| `::item { padding: 0px 6px }` | 13 404 | 36 | 20 106 |
| `::item { border: 0px }` | **0** | 36 | 20 106 |
| `::item { border-radius: 6px }` | **0** | 36 | 20 106 |
| `::item { background-color: … }` | **0** | 36 | **0** |
| `::item { color: … }` | 13 404 | **0** | 20 106 |
| `QTableView { background-color: … }` | 13 404 | 36 | 20 106 |

Selection:

| | palette `Highlight` | QSS |
| --- | --- | --- |
| *(none)* | 6 702 | 0 |
| `::item { padding }` | 6 702 | 0 |
| `::item:selected { background }` | **0** | 6 702 |
| `QTableView { selection-background-color }` | **0** | 6 702 |

Disabled text (`QLabel` and `QPushButton`, same answer):

| | palette `Disabled` group | QSS `color` | QSS `:disabled` |
| --- | --- | --- | --- |
| *(none)* | 37 | – | – |
| `Widget { color: X }` | **0** | 37 | – |
| `Widget { color: X } Widget:disabled { color: Y }` | **0** | 0 | 37 |

**Order does not matter.** `setPalette` then `setStyleSheet` and the reverse
give byte-identical results. The mechanism is that `setStyleSheet` **rewrites
the widget's palette** during polish — measured directly:

```
before : Base=#ffffff
after  : Base=#ff00ff  Text=#00ff00     (after setStyleSheet)
cleared: Base=#ffffff                   (after setStyleSheet(""))
```

`app.setStyle("Fusion")` after `setStyleSheet` does **not** clear the
stylesheet (it does clear the palette — which is why `apply_theme` sets style
first).

### The rule the implementation should follow

> **A colour belongs to exactly one of the two systems, and for anything the
> model or the view computes per row it must be the palette.**
>
> 1. **Row/cell colour is palette-only.** Never write a `QTableView::item` rule
>    containing `background`, `border`, `border-radius` or `color`. Any of
>    those silently deletes the model's `BackgroundRole` (severity tint, mark
>    tint) or `ForegroundRole` (per-level severity colour). `::item { padding }`
>    is the sole safe declaration, and even it costs 22 % on a full repaint (§3).
> 2. **Table background and alternating rows are palette-only** (`Base`,
>    `AlternateBase`). Not because of precedence — `QTableView { background }`
>    is harmless to the model — but because it destroys scroll blitting (§3).
> 3. **Selection colour: pick one and write it down.** Palette `Highlight` is
>    the cheaper and more consistent choice and is what the model already
>    reasons about; if the design wants a rounded selection it has to move to a
>    delegate anyway, which suppresses the fill.
> 4. **Chrome is QSS-only**: scrollbar, header sections, toolbar, tool buttons,
>    line edits, status bar, splitter handles, menus, tooltips. None of these is
>    per-row and none is consulted by the model.
> 5. **Every QSS `color` needs an explicit `:disabled` twin,** because QSS
>    `color` applies to the disabled state too and shadows the palette's
>    `Disabled` group, which `theme.py::palette_for` carefully fills in.
> 6. **A theme switch must regenerate the stylesheet string**, not only the
>    palette. Colours living in QSS are static text. This argues for keeping the
>    QSS colour surface as small as possible and deriving it from the same
>    `_ROLES` table.

---

## 3. Cost

### Methodology (and why the previous benchmark was wrong)

The previous benchmark in this repo timed a selection change without forcing
the repaint that costs the time. Everything below:

- runs against the real `LogTable` over the real `RecordModel` with **200 000
  rows** built from `tests/fixtures/ios26-mixed.jsonl.gz` (5 000 real records
  repeated; message length mean 101, median 78, max 1 079 characters), viewport
  **1400×900**, row height 20 px → **~45 rows × 6 columns ≈ 270 cells per
  repaint**;
- gives the widget the real paint machinery with
  `setAttribute(WA_DontShowOnScreen, True); show()` — a real backing store, real
  paint events, nothing on screen;
- **ends every timed operation in a forced synchronous repaint.** Two modes:
  `viewport().repaint()`, which blocks until `paintEvent` returns and repaints
  the whole viewport (worst case: resize, filter change, theme change, model
  reset); and the **incremental path a wheel notch really takes**
  (`scrollBar.setValue(+rowHeight)` then `processEvents()`, which lets Qt blit
  and repaint only the exposed strip);
- installs a `paintEvent` counter **and an area counter** on the viewport, both
  printed. A run that painted nothing shows as zero and the harness aborts;
- **interleaves** all configurations round-robin, 40 rounds × 6 samples, so
  machine drift hits every configuration equally. This mattered: in the
  non-interleaved v1 the *same* baseline measured 28.6 ms and 31.7 ms in two
  sections — a spread larger than most of the effects being measured;
- moves the scroll position by a prime stride (977 rows) between samples so no
  repaint can be served from the backing store.

### 3.0 Where the 30 ms actually goes

Full viewport repaint, median of 25 (`bench2.py`):

| configuration | ms |
| --- | --- |
| same widget, **no model** (background fill only) | **0.07** |
| trivial model, 1 column, 5-char cells | 2.81 |
| trivial model, 6 columns, 5-char cells | 11.49 |
| **real `RecordModel`, 6 columns, `LogTable` as shipped** | **26.71** |
| trivial model, 6 columns, **400-char** cells | **121.00** |

**Text layout and the per-cell Python↔C++ crossings are the entire cost** —
roughly 100 µs per cell, and it scales with *message length*, not with row
count. Painting the widget itself is 0.07 ms, i.e. free. Everything in §3.1–3.4
is a percentage on top of a number that styling did not create and cannot fix.

### 3.1 Global stylesheet — the finding that matters

Full-viewport repaint, 40 interleaved rounds (`bench2.py`):

| case | median ms | vs baseline |
| --- | --- | --- |
| A baseline, no stylesheet | 28.282 | 1.00× |
| B chrome-only QSS (nothing matches `::item`) | 30.194 | 1.07× |
| C chrome + `::item { padding }` | 34.598 | 1.22× |
| D chrome + `::item` + `::item:selected` | 33.264 | 1.18× |
| E chrome + `::item` + `::item:hover` | 33.406 | 1.18× |

So a stylesheet costs **7 % if it never matches a cell, ~20 % if it does.**
Acceptable. Then the same cases on the **wheel-scroll** path:

| case | median ms/notch | vs baseline |
| --- | --- | --- |
| A baseline | 2.299 | 1.00× |
| B chrome-only | 1.780 | 0.77× |
| C chrome + `::item { padding }` | 1.947 | 0.85× |
| **D chrome + `::item` + `::item:selected`** | **34.153** | **14.86×** |
| **E chrome + `::item` + `::item:hover`** | **33.841** | **14.72×** |
| L everything together | 36.099 | 15.70× |

`bench3.py` isolates it to a single declaration. Painted area is reported
because it proves the mechanism:

| stylesheet | ms/scroll | vs none | painted px per scroll | % of viewport |
| --- | --- | --- | --- | --- |
| 00 no stylesheet at all | 2.487 | 1.00× | 27 680 | 2 % |
| 01 chrome only | 1.632 | 0.66× | 27 720 | 2 % |
| 02 chrome + `QTableView::item{padding}` | 1.773 | 0.71× | 27 720 | 2 % |
| 03 chrome + `QTableView::item{border:0}` | 1.745 | 0.70× | 27 720 | 2 % |
| 04 chrome + `QTableView::item:selected{bg}` | 1.652 | 0.66× | 27 720 | 2 % |
| 05 chrome + `QTableView::item:hover{bg}` | 1.639 | 0.66× | 27 720 | 2 % |
| **06 chrome + `QTableView{border:0px}`** | **30.768** | **12.37×** | **1 210 336** | **96 %** |
| **07 chrome + `QTableView{background:#1b1b1b}`** | **30.780** | **12.38×** | **1 205 820** | **96 %** |
| 08 chrome + `QTableView{alternate-background-color}` | 1.651 | 0.66× | 27 720 | 2 % |
| 09 chrome + `QTableView{color:#ddd}` | 1.614 | 0.65× | 27 720 | 2 % |
| 10 chrome + `QTableView{selection-background-color}` | 1.642 | 0.66× | 27 720 | 2 % |
| 11 chrome + `QTableView{gridline-color:#333}` | 1.614 | 0.65× | 27 720 | 2 % |
| **12 `QTableView{background}` alone, no chrome** | **32.232** | **12.96×** | **1 215 152** | **96 %** |
| **13 chrome + `QAbstractScrollArea{background}`** | **30.495** | **12.26×** | **1 205 820** | **96 %** |
| 14 chrome QSS + **palette** `Base`/`AlternateBase` | **1.613** | **0.65×** | 27 720 | 2 % |

> **Any QSS declaration that gives `QTableView` (or `QAbstractScrollArea`) a
> box model — `background` or `border` on the *widget* — makes the viewport
> non-blittable. Every scroll notch then repaints 96 % of the viewport instead
> of 2 %: 30 ms instead of 1.6 ms, a hard ~32 fps ceiling on scrolling a log.**

The *pseudo*-properties (`alternate-background-color`, `color`,
`selection-background-color`, `gridline-color`) are consumed by the item view
rather than the box model and are all free. Every `::item` rule is free on this
path too.

Attempted workarounds:

| | ms/scroll | painted |
| --- | --- | --- |
| QSS bg + `viewport().setAutoFillBackground(True)` | 31.237 | 96 % |
| QSS bg + `WA_OpaquePaintEvent` on the viewport | **1.581** | 2 % |
| QSS bg set on the viewport widget instead | 30.465 | 96 % |
| **palette `Base` only, no QSS bg** | **1.571** | **2 %** |

`WA_OpaquePaintEvent` does restore the fast path, but it is a promise to Qt
that the widget paints every pixel of its rect; combined with a translucent or
rounded QSS background it produces garbage. **Take the palette route.** It is
also what `theme.py` already does, so this is a constraint on the redesign, not
a change to the code.

Note the free lunch: chrome-only QSS is measurably **faster** than no
stylesheet (1.63 vs 2.49 ms/notch) — the hand-written scrollbar is cheaper to
draw than Fusion's.

### 3.2 A second custom delegate

| case | full repaint ms | vs A | wheel ms | vs A |
| --- | --- | --- | --- | --- |
| A plain text Level column | 28.282 | 1.00× | 2.299 | 1.00× |
| F pass-through `QStyledItemDelegate` on Level | 28.699 | 1.01× | 2.334 | 1.02× |
| G **pill delegate** (antialiased rounded rect + centred text) | 28.632 | 1.01× | 2.253 | 0.98× |

**A second delegate is free** — within noise on both paths. A per-row coloured
level pill costs nothing measurable. The Python call per cell is ~45 cells for
one column; against 100 µs/cell of text layout it disappears. This directly
contradicts the intuition that "another Python delegate on a 200k-row table
will be slow"; at 200 k rows the table is virtualised and only ~45 rows exist.

### 3.3 `setAlternatingRowColors`

| | full repaint ms | wheel ms |
| --- | --- | --- |
| I alternating ON | 28.320 | 2.267 |
| H alternating OFF | 28.014 | 2.279 |

**Free** — 1 % on the full repaint, nothing on scroll, both inside noise.
Keep it.

### 3.4 Rounded corners / borders on the selected row via a delegate

Implemented by clearing `State_Selected` from the style option and painting an
antialiased capsule, on **every** column's delegate:

| | full repaint ms | vs A | wheel ms |
| --- | --- | --- | --- |
| J stock rectangular selection, 1 row selected | 28.965 | 1.02× | 2.283 |
| K rounded capsule delegate, 1 row selected | 31.140 | 1.10× | 2.380 |
| K′ rounded capsule delegate, nothing selected | 31.002 | 1.10× | — |

**Affordable: ~10 % on a full repaint, ~4 % on scroll.** The cost is the
`QStyledItemDelegate` subclass being installed on all six columns (it is paid
even with nothing selected), not the rounding. Caveat that is design work
rather than performance: a delegate paints *per cell*, so a capsule spanning
the whole row needs the first and last visible column to draw the two ends and
the middle columns to draw a plain rect — otherwise you get six capsules.

### 3.5 Everything together, and the live-capture budget

| | full repaint | wheel |
| --- | --- | --- |
| L full QSS + pill delegate + rounded selection | 35.505 ms (1.26×) | 36.099 ms (15.70×) |

The 15.7× is entirely the `QTableView { background }` in that sheet. Remove it
and the same visual result costs ~1.15× on both paths.

Live capture, appending 100 records and repainting, 16 Hz (`bench2.py`):

| | median | p95 | budget |
| --- | --- | --- | --- |
| no stylesheet, no extra delegate | 30.952 ms | 39.519 ms | 62.5 ms |
| full QSS + pill delegate | 32.196 ms | 37.937 ms | 62.5 ms |

Both fit, with about half the tick to spare. The redesign costs **1.2 ms** of a
62.5 ms budget. (This forces a *full* repaint each tick, which is pessimistic —
appending at the bottom while following normally invalidates only the last
rows.)

### Honest summary of §3

Nothing a designer is likely to ask for costs more than ~10–25 %, **except one
declaration that costs 12×**. The dominant cost in this table is text layout of
long log messages and it is unaffected by any styling decision. If the redesign
needs the table to be faster, the lever is the Message column (shorter elide
target, narrower default width, or a cheaper elide), not the stylesheet.

---

## 4. Light/dark following the OS

### API, and what 6.11.1 exposes

All present and introspected (`probe_theme_dpi_icons.py`):

| | |
| --- | --- |
| `Qt.ColorScheme` | `Unknown`, `Light`, `Dark` — **Qt 6.5+** |
| `QStyleHints.colorScheme()` | present — **Qt 6.5+** |
| `QStyleHints.colorSchemeChanged(Qt::ColorScheme)` | present — **Qt 6.5+** |
| `QStyleHints.setColorScheme()` | present — **Qt 6.8+** |
| `QStyleHints.unsetColorScheme()` | present — **Qt 6.8+** |
| `QPalette.ColorRole.Accent` | present — Qt 6.6+ |

The project pin is `>=6.8`, so **all of the above are available at the floor of
the supported range.** `setColorScheme`/`unsetColorScheme` are exactly at 6.8;
if the pin is ever lowered they go first.

Behaviour on Windows, native plugin:

```
hints.colorScheme()          -> ColorScheme.Light        (read from the OS)
setColorScheme(Dark)         -> Dark     signal fired 1x  palette Window #1e1e1e
setColorScheme(Light)        -> Light    signal fired 2x  palette Window #f0f0f0
setColorScheme(Unknown)      -> Light    signal fired 2x  (Unknown == "follow the OS")
unsetColorScheme()           -> Light
```

`colorSchemeChanged` **is** a real change signal and `gui/app.py` is already
connected to it. Setting `Unknown` (or `unsetColorScheme()`) means "go back to
following the system", not "report Unknown".

Offscreen, unchanged from what `docs/design/gui.md` §12 records and re-verified
at 6.11.1:

```
styleHints.colorScheme()  -> Unknown
setColorScheme(Dark)      -> Unknown    signals=0
```

### Per platform

- **Windows** — verified here. `QStyleHints.colorScheme()` reads the OS
  preference and `colorSchemeChanged` fires on a live switch.
- **macOS** — `# UNVERIFIED-MACOS`. The cocoa plugin implements the same
  `QPlatformTheme::colorScheme()` hook against `NSApp.effectiveAppearance`; the
  documented behaviour is identical, and `gui/app.py` already carries a comment
  saying the wiring is there but unseen.
- **Linux** — the value comes from the XDG desktop portal
  (`org.freedesktop.appearance color-scheme`). Where no portal is running,
  `Unknown` is the honest answer and `resolve_scheme()` already falls back to
  light. This is a real gap on minimal window managers, not a bug.

### Where the platform code has to live

**Nowhere new.** This is the good news for the hard rule. `QStyleHints` is
Qt's own platform abstraction: `hints.colorScheme()` returns the right answer
on all three systems from identical Python, so **no `sys.platform` branch is
required and none should be added.** `gui/theme.py::resolve_scheme(hints)` is
already the single seam and it is correct.

The rule (`only compat.py may branch on the OS`, written as the literal
`sys.platform == "win32"`) only comes into play if the redesign wants something
Qt does not abstract — Windows Mica/acrylic backdrop, macOS
`NSVisualEffectView` vibrancy, a frameless window with a native drop shadow.
Every one of those is a native call and **every one of them must go in
`compat.py`**, behind a function whose non-Windows branches are written blind
and marked `# UNVERIFIED-MACOS`. My recommendation is to ask for none of them.

---

## 5. HiDPI

Qt 6 needs **no opt-in**. `AA_EnableHighDpiScaling` and `AA_UseHighDpiPixmaps`
still exist as enum members (so old code does not fail to import) but are
no-ops; high-DPI scaling is always on. The default rounding policy is
`PassThrough` — confirmed at runtime — meaning Qt uses the exact fractional
scale factor rather than rounding to an integer, which is what Windows wants
and what macOS reports as an integer anyway.

Measured under `QT_SCALE_FACTOR` 1 / 1.5 / 2 (`probe_dpi_icon.py`):

| | dpr 1.0 | dpr 1.5 | dpr 2.0 |
| --- | --- | --- | --- |
| `QSS border: 10px` → `contentsMargins()` | 15 | 15 | 15 |
| …red **device** pixels rendered | 2 000 | 4 500 | 8 000 |
| `QFontMetrics.height()` | 16 | 16 | 16 |
| `QFontMetrics.horizontalAdvance("0")` | 6 | 6 | 6 |

**Sizes in a stylesheet are device-independent pixels and nothing breaks.**
`10px` stays 10 logical px at every scale and Qt renders 1.5²/2² as many device
pixels. Font metrics are likewise logical, so `LogTable.apply_column_widths()`
(character units × `horizontalAdvance("0")`) and the font-derived row height
are already dpr-independent. A designer may specify the whole sheet in px.

Two real caveats:

- **Do not use `px` for anything meant to be one physical hairline.** A
  `1px` border is 1 logical px, i.e. 2 device px at dpr 2. That is usually what
  you want, but a "hairline" separator will look heavier on a Retina display
  than the designer's mock.
- **Fractional dpr rounds sub-pixel geometry.** With `PassThrough` at dpr 1.25
  a 5-logical-px padding is 6.25 device px and gets rounded; borders on adjacent
  widgets can end up 1 device px apart. Nothing to do about it; just do not
  build a design that depends on two borders aligning exactly.

**SVG icons are rendered at the right density automatically**, provided the
`QIcon` is backed by the SVG and not by a pixmap:

```
QIcon(svg).pixmap(20, dpr=1.0 ) -> 20x20 device px
QIcon(svg).pixmap(20, dpr=1.25) -> 25x25
QIcon(svg).pixmap(20, dpr=1.5 ) -> 30x30
QIcon(svg).pixmap(20, dpr=2.0 ) -> 40x40   (dpr 3.0 -> 60x60)
```

`QIcon.availableSizes()` returns `[]` for an SVG-backed icon. That is normal —
it renders at any requested size — and is **not** evidence the icon failed to
load; check `isNull()` instead.

`QIcon` needs to be told **nothing** for density, as long as you never hand it
a fixed `QPixmap`. That failure mode is measurable:

```
SVG-backed QIcon,                       asked for dpr 3 -> 60x60  (crisp)
pixmap-backed QIcon built at dpr 1,     asked for dpr 3 -> 20x20  (UPSCALED/BLURRY)
pixmap-backed QIcon with 5 dprs added,  asked for dpr 3 -> 60x60
```

---

## 6. Icons

### Mechanism: plain files + `importlib.resources`. Not `pyside6-rcc`.

I built a wheel to settle the packaging question. With
the project's existing config — `[tool.hatch.build.targets.wheel] packages =
["src/ostrace"]`, unchanged — a `.svg` and a `.qss` dropped into the source tree
land in the wheel:

```
ostrace/py.typed
ostrace/gui/theme.qss
ostrace/gui/icons/play.svg
```

**No `pyproject.toml` change is needed.** Hatchling ships everything under the
package directory; the sdist target already lists `src`, so they are in the
sdist too.

Against that, `pyside6-rcc` costs: a build step nobody's `pip install -e .`
runs, a generated `_rc.py` that must be committed and kept in sync with the
assets, a diff that is a base64 blob, and a `PySide6-Essentials` build-time
dependency for a package whose GUI is an *optional* extra. It buys nothing
here — the wheel is unpacked on install, so `importlib.resources.files()`
returns a real filesystem path.

Recommended shape:

```python
from importlib.resources import files
data = (files("ostrace.gui.icons") / "play.svg").read_bytes()
```

Read **bytes**, not a path. `read_bytes()` works under every loader including
zipimport, and you need the bytes anyway to recolour (below). If you do want a
path for `QIcon(str(path))`, use `importlib.resources.as_file()`.

`PySide6.QtSvg` is importable in **PySide6-Essentials** (verified — it is not
an Addons module), and `svg`/`svgz` are in `QImageReader.supportedImageFormats()`.
No new dependency.

### Recolouring for the theme

A plain `QIcon(svg)` will not recolour. Four options, measured:

| option | cost | verdict |
| --- | --- | --- |
| **A. Ship two SVG sets (light/dark)** | 0 | Doubles the asset count and every future icon must be exported twice. Fine for 5 icons, bad for 20. |
| **B. `QPainter` `CompositionMode_SourceIn` tint of a rendered pixmap** | **0.019 ms** per 24 px icon at dpr 2 | Works (verified: rendered `#333333` → `#ff0000`). **But it yields a *pixmap*-backed `QIcon`, which is blurry at any dpr you did not pre-render** (§5). You must `addPixmap()` one per dpr, and you cannot know the dpr of a monitor the window has not been dragged to yet. |
| **C. Rewrite the SVG text (`currentColor` → hex) and re-render** | **0.075 ms** per icon | Simple, no `QIconEngine`. Same pixmap-backed dpr problem as B. |
| **D. `QIconEngine` subclass that re-renders the SVG in `scaledPixmap()`** | ~0.075 ms **per paint**, and paints are rare | **Recommended.** |

Option D is the only one that is correct at every size and density, because Qt
tells the engine what it needs. Verified: a `QToolBar` painting a 20 px icon
asks the engine for exactly `(20, 20, dpr)` with the right dpr at each scale
factor:

```
QT_SCALE_FACTOR unset -> engine calls [(20, 20, 1.0)]
QT_SCALE_FACTOR=1.5   -> engine calls [(20, 20, 1.5)]
QT_SCALE_FACTOR=2     -> engine calls [(20, 20, 2.0)]
```

Author the SVGs with `stroke="currentColor"` / `fill="currentColor"`, have the
engine substitute the theme colour at render time, and a theme switch is
`update()` — no icon rebuilding at all. Rebuilding a **20-icon set** from
scratch costs **~2 ms** if you ever want to (`probe_dpi_icon.py`), so even the
naive approach is imperceptible.

One macOS-specific extra worth knowing: `QIcon.setIsMask(True)` exists and is
accepted everywhere. `# UNVERIFIED-MACOS`: on macOS it marks the image as an
NSImage *template*, which the system recolours for light/dark and for menu
highlight. It is a no-op on Windows and Linux, so it is safe to set
unconditionally and costs nothing — but do not *rely* on it for the theme,
because it does nothing on two of three platforms.

`QIcon.fromTheme()` also works (a freedesktop icon theme was found even on
Windows), but themed icon availability differs per platform and per desktop.
Bundle the icons.

---

## 7. A toolbar

Measured paint cost of an eight-action bar, 300 renders each:

| | ms/paint |
| --- | --- |
| real `QToolBar` with `QToolButton`s | **0.102** |
| `QWidget` + `QHBoxLayout` + `QPushButton`s | **0.261** |

Both are free (compare 28 ms for one table repaint), and the real `QToolBar` is
the *cheaper* of the two. **Performance is not an input to this decision.**

A real `QToolBar` is fully styleable — `QToolBar`, `QToolBar::handle`,
`QToolBar::separator`, `QToolButton` with `:hover` / `:pressed` / `:checked`
(rendered, `shots/toolbar-real.png`: dark bar, light text, rounded hover
targets). So "custom widget for full control of appearance" buys nothing that
QSS does not already give.

What the real `QToolBar` gives you, verified:

- **Overflow.** As the window narrows, actions that do not fit are hidden and
  reached through the extension chevron: at 900 px 10/10 action widgets visible,
  at 420 px 6/10, at 240 px 2/10.
- **`setMovable(False)` / `setFloatable(False)`** — both confirmed effective.
  Do this. The drag handle and tear-off float are a 2003 affordance and will
  wreck any modern layout.
- **The `QMainWindow` context menu** listing toolbars and docks
  (`createPopupMenu()` is non-`None`). Suppress it if the design does not want
  it.
- Default `iconSize` is 24×24 and default `toolButtonStyle` is `IconOnly` —
  both almost certainly wrong for a log viewer whose verbs are Capture, Pause,
  Disconnect. `ToolButtonTextBesideIcon` at 16–20 px is the usual choice.

`unifiedTitleAndToolBarOnMac`: the property and setter both exist, but
`setUnifiedTitleAndToolBarOnMac(True)` followed by a read returns **`False`** on
Windows — Qt silently ignores it off macOS. So it is safe to call
unconditionally and needs no `compat.py` branch. `# UNVERIFIED-MACOS`: on macOS
it merges the toolbar into the title bar. Note that Qt's own documentation has
described this as having "no effect" / being problematic with certain toolbar
contents on recent macOS; since there is no Mac here, **do not make the design
depend on it**. Treat it as a bonus if it works.

**Recommendation: a real `QToolBar`**, movable and floatable off, styled by
QSS, `ToolButtonTextBesideIcon`. The overflow behaviour alone is worth it — a
custom widget would silently clip its right-hand actions on a narrow window,
and Capture/Pause/Disconnect are exactly the actions that must never become
unreachable.

---

## 8. Testability

Same script run under both plugins (`probe_offscreen.py`):

| assertion | native `windows` | `offscreen` | safe in CI? |
| --- | --- | --- | --- |
| QSS reaches `QLineEdit` background | 5 894 px | 5 894 px | **yes** |
| QSS reaches `QHeaderView::section` | 6 884 px | 6 561 px | **yes**, if the tolerance allows for text |
| QSS reaches `QToolBar` | 9 379 px | 9 404 px | **yes** |
| QSS reaches `QMenuBar` | 7 692 px | 7 688 px | **yes on Win/Linux; meaningless for macOS** |
| `QIcon(svg).pixmap(24, dpr 2)` | 48×48 | 48×48 | **yes** |
| font families | 154 | **0** | — |
| default font | Segoe UI 9pt | Sans Serif 9pt | — |
| `QFontMetrics.height()` | **16** | **12** | **NO** |
| `horizontalAdvance("0")` | **6** | **12** | **NO** |
| `horizontalAdvance(<40 chars>)` | **189** | **420** | **NO** |
| `LogTable` row height | **20** | **16** | **NO** |
| `styleHints.colorScheme()` | Light | **Unknown** | **NO** |
| `setColorScheme(Dark)` | Dark, 1 signal | **Unknown, 0 signals** | **NO** |

**The good news is bigger than expected: QSS coverage is assertable offscreen.**
Every stylesheet rule reached its widget with essentially the same painted area
under both plugins. A CI test can render a widget with a sentinel colour and
assert the pixel count, on all three operating systems, with no display — which
means the §2 precedence rules (does an `::item` rule eat `BackgroundRole`?) can
be locked down by tests rather than by comments.

### The traps, enumerated

1. **Any font metric.** `horizontalAdvance("0")` is 6 natively and 12
   offscreen — a **2× error**, and `QFontMetrics` returns plausible numbers the
   whole time while text renders as tofu. Column widths, elide positions, row
   heights, toolbar `sizeHint()`, "does this label fit" — all off-limits.
   Already in `docs/design/gui.md` §12; a redesign that introduces padding and
   larger row heights will be tempted to assert on them.
2. **Colour-scheme switching.** `setColorScheme()` is a no-op offscreen, the
   signal never fires, `colorScheme()` stays `Unknown`. Any test of "the app
   follows the OS" must inject a `Scheme` rather than drive `QStyleHints` —
   which is exactly why `theme.py` takes the scheme as a parameter. Do not let
   the redesign move colour decisions to a point where they read
   `QStyleHints` directly.
3. **The macOS menu bar.** `isNativeMenuBar()` is `False` under offscreen even
   *on macOS*, so the offscreen lane renders the menu bar inside the window and
   proves nothing about the real one. `docs/design/gui.md` §12 already calls
   this structural. Anything the redesign wants from the menu bar — styling,
   icons, a custom item — is unverifiable, forever, on this machine and in CI.
4. **Anything asserting exact pixels of *text*.** Backgrounds and fills are
   stable across plugins; glyphs are not. Assert `count(colour) > threshold` on
   a fill, never an exact total on a region containing text.
5. **`WA_DontShowOnScreen` is what makes paint benchmarks honest**, and it needs
   a plugin with a backing store. Under `offscreen` it works too, but the
   numbers are not comparable to a real display — do not put a timing threshold
   in CI.
6. **The combobox popup must be really shown to be inspected.** Rendering
   `combo.view()` without `showPopup()` reports 0 styled pixels and looks like a
   failure. A CI test for popup styling needs a plugin that can map a top-level
   window; offscreen can, but this is the fragile kind of test.
7. **Fractional DPI.** `QT_SCALE_FACTOR` simulates it, but the only machine
   available reports dpr 1.0 for all three monitors. Nothing about
   1.25×/1.5× layout can be *observed*, only computed.

---

## 9. What a designer may ask for that Qt cannot do

Blunt list. Each of these has come up in a Qt redesign before.

- **`box-shadow`.** QSS has no shadow property at all. Cards, elevated
  toolbars, floating panels — none of it. `QGraphicsDropShadowEffect` exists but
  forces the widget through a software-rendered offscreen surface, which would
  be catastrophic on the table and merely ugly elsewhere. **Fake it with a
  1 px border and a background step, or drop it.**
- **Transitions and animations in CSS.** No `transition`, no `animation`, no
  `transform`. A hover that fades in over 120 ms needs a `QPropertyAnimation`
  per widget per property, written by hand. Hover states are instant.
- **`opacity`.** Not a QSS property. Only `windowOpacity` (whole top-level) or
  `QGraphicsOpacityEffect` (same cost problem as shadows). Colours with an
  alpha channel in `rgba()` do work and cover most real needs.
- **`letter-spacing`, `text-transform`, `text-shadow`, `word-spacing`.** None
  exist in QSS. Letter-spacing is reachable only via `QFont.setLetterSpacing()`
  in code; the other two are not reachable at all.
- **Flexbox/grid, `gap`, `calc()`, CSS variables, `@media`, `:has()`,
  `::before`/`::after`.** QSS is a small subset of CSS 2.1 with Qt extensions.
  Layout is `QLayout`, in Python. A designer handing over CSS will hand over
  something that mostly does not apply.
- **Rounded corners on the log table itself.** `QTableView { border-radius }`
  implies a border, which is the 12× scroll penalty above. The radius has to be
  drawn by a container frame with the table inset — and Qt does not clip a child
  to its parent's rounded corners, so the table's square corners will poke out
  unless the container carries padding equal to the radius (or you use
  `setMask`, which is aliased and ugly). **Say no to a rounded table.**
- **Overlay / auto-hiding scrollbars** (macOS-style, floating over content,
  fading in on scroll). `QScrollBar` occupies layout space; making it float
  requires a custom widget positioned over the viewport, its own fade timers,
  and it will fight the existing minimap widget. Real work, not styling.
- **Window chrome: custom title bar, rounded window corners, unified
  toolbar/title bar.** Requires a frameless window plus per-platform native
  work (hit-testing for resize on Windows, `NSWindow` styling on macOS, and
  whatever the compositor allows on Linux). All of it would have to live in
  `compat.py` and two thirds of it would be written blind. **Recommend
  against.**
- **Acrylic / Mica / vibrancy / any blurred backdrop.** No Qt API.
  `DwmSetWindowAttribute` on Windows, `NSVisualEffectView` on macOS, nothing
  portable on Linux. Same objection as above, doubled.
- **The macOS menu bar, styled.** It is a real `NSMenu`. No colour, no font, no
  icon rules, no custom items. `# UNVERIFIED-MACOS` but not in doubt.
- **A native macOS toolbar (`NSToolbar`) with its search field and
  customisation sheet.** `QToolBar` is Qt-drawn everywhere;
  `unifiedTitleAndToolBarOnMac` is the only concession and it is unverifiable
  here.
- **Per-cell rich text, inline badges inside the message, or variable row
  heights.** All technically possible with `QTextDocument` in a delegate, and
  all of them delete the fixed-row-height rule that `docs/design/gui.md` §11
  and `log_table.py` exist to enforce. Given that text layout is already ~100 µs
  per cell and 90 % of the repaint, a `QTextDocument` per cell would be an
  order of magnitude worse. **Hard no on the Message column.**
- **A bundled custom font.** Mechanically fine
  (`QFontDatabase.addApplicationFont`), but it adds a licence file, ~100–400 KB
  to a wheel whose GUI is an optional extra, and it interacts with the offscreen
  font-database trap in a way that will confuse the screenshot job. If the
  design wants a specific typeface, ask whether the system UI font plus a
  monospace fallback for the Message column will do.
- **Exact visual parity with the mock on macOS.** Not because of Qt, but
  because nobody here can look at it. Anything whose correctness is "it looks
  right" is unverifiable on one of three shipped platforms.

Things a designer might expect to be impossible that **are** fine: gradients
(`qlineargradient`, `qradialgradient`, `qconicalgradient` are all supported),
`border-radius` on every widget except the scroll-area cases above, `rgba()`
colours, per-state styling (`:hover`, `:pressed`, `:checked`, `:focus`,
`:disabled`, `!`-negation), 9-slice `border-image`, per-sub-control styling of
scrollbars/comboboxes/headers, styled tooltips, coloured pill delegates, and a
rounded selection.
