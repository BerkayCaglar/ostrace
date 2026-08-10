# ostrace GUI — current state audit

Research only. Nothing in the repository was modified.

**Subject:** `src/ostrace/gui/`, phase 4 / 0.1.0.
**Contract read against:** `docs/design/gui.md` (written before the code; where the
two disagree the document is right and the code is the bug).
**User's verdict being explained:** *the window looks old-fashioned* — reported in those words, and this
document exists to find out what produced the impression.

## Method, and what "measured" means below

Three sources of evidence, kept distinct:

- **Code**, cited as `file:line`.
- **Measured from the committed screenshot.** `docs/images/viewer-light.png` and
  `viewer-dark.png` are 1028×749, rendered by `tools/capture_screens.py` at
  1:1 logical pixels. I decoded the PNG and scanned scanlines for band
  boundaries, so every pixel figure below is a real measurement of the shipped
  UI, not an estimate.
- **Derived from Qt defaults**, marked as such. PySide6 is not installed on this
  machine (`py -3 -c "import PySide6"` → `ModuleNotFoundError`, and
  `site-packages` has no `PySide6`), so nothing was run live. Anywhere that
  mattered I preferred a screenshot measurement over a Qt-default assumption.

### The measured layout of the shipped window (1028×749, light scheme)

| Band | y range | Height | Colour |
| --- | --- | --- | --- |
| Menu bar | 0–19 | 20 px | `#f3f3f3` (Window) |
| separator | 20 | 1 px | `#dadada` |
| Filter bar | 21–50 | 30 px | `#f3f3f3` (Window) |
| separator | 51 | 1 px | `#bbbbbb` |
| Table header | 52–70 | 19 px | `#fefefe`→`#f0f0f0` gradient, `#aeaeae` rule at y=71 |
| Table rows | 72–554 | 20 px pitch | `#ffffff` / `#f7f7f7` alternating |
| Splitter handle | 555–560 | 6 px | `#f3f3f3` between two `#bbbbbb` hairlines |
| Detail pane | 561–726 | 166 px | **`#f3f3f3` (Window), not Base** |
| Status bar | 728–748 | 21 px | `#f3f3f3` (Window) |

Horizontal, at the header (`y=60`), section dividers measured at
x = 78, 150, 282, 438, 546 — i.e. Time 78 px, Level 72 px, Process 132 px,
Subsystem 156 px, Category 108 px, Message the remainder. That is exactly
`characters × horizontalAdvance("0")` from `columns.py:49-56` with a 6 px digit
advance, so column sizing is working as designed.

At the right edge (`y=120`): vertical scrollbar x = 1001–1014 (14 px), a 1 px
border, then the **minimap at x = 1016–1027 (12 px)**, painted `#b3261e` where
an error band lights. The minimap is therefore *outside* the table's own
scrollbar, flush against the window frame, with no border and no viewport
thumb — which is why it reads as two unexplained red blocks glued to the edge.

---

## 1. Window chrome

### 1.1 There is no toolbar. The class docstring says there is.

`src/ostrace/gui/windows/main.py:112`

```python
class MainWindow(QMainWindow):
    """Toolbar, filter bar, table, detail pane, status bar."""
```

`_build_layout` (`main.py:176-214`) builds a filter bar, a banner, a splitter
and a status bar. There is no `addToolBar`, no `QToolBar`, no `QDockWidget`
anywhere in the package — grep over `src/ostrace/gui/` returns zero hits for
all three. The docstring is the only place a toolbar exists.

`docs/design/gui.md:36-40` acknowledges this: *"0.1.0 has no toolbar and no
device selector… Both are gaps rather than choices — a toolbar is the larger of
the two for a program whose main verbs are otherwise two clicks deep."*

**Effort: moderate** (a `QToolBar` with 4–6 actions reusing the existing
`QAction` objects; the actions already carry `setToolTip(binding.description)`
at `main.py:317`). See §Constraints for the menu-count test that a toolbar must
not disturb.

### 1.2 What the menu bar is carrying that a toolbar should

Four menus, built at `main.py:352-380` from `gui/shortcuts.py:58-175`:

| Menu | Items |
| --- | --- |
| **Capture** | Capture, Pause, Disconnect, Open Capture…, Export…, ─, Quit |
| **Edit** | Copy, Find, Mark Row, Clear Marks |
| **View** | Go to Top, Go to Bottom, Next/Previous Error, Next/Previous Gap, Next/Previous Mark, Next Row, Previous Row |
| **Help** | Keyboard Shortcuts, ─, About ostrace |

The five verbs that define the program — **Capture, Pause, Disconnect, Open,
Export** — are all inside `Capture ▸`. Every one of them is two clicks
(menu → item) or a chord. The View menu is eleven navigation items that are
really keyboard commands padded into a menu; nothing in it wants to be clicked.

### 1.3 There is no device selector, and the viewer cannot target a device

`main.py:501-510`:

```python
def _build_source(self) -> LogSource:
    from ostrace.sources.os_trace import OsTraceSource
    return OsTraceSource()
```

`OsTraceSource.__init__` accepts `udid: str | None = None`
(`src/ostrace/sources/os_trace.py:115-125`), and `devices/discovery.py:59`
already exposes `async def list_devices() -> list[DeviceSummary]`. So the
plumbing exists on both sides; the GUI simply never asks. With two phones
plugged in, the viewer captures from whichever `open_lockdown(None)` picks and
the user has no say — where the CLI takes `--udid`.

Acknowledged at `docs/design/gui.md:36-40`.

**Effort: moderate.** `list_devices()` is async, so a selector needs the same
thread treatment `CaptureThread` already gives the stream, or a one-shot
`QThread`/`asyncio.run` off the GUI thread.

### 1.4 How a capture starts today, in clicks

Cold start → `Capture` menu → `Capture` = **2 clicks**, or `Ctrl+R`. Then to
export: Disconnect (2 clicks) → Export… (2 clicks) → dialog. There is no
affordance anywhere in the window itself — the empty window has no button, no
link, no drop target. The only visible hint that the program does anything is
the word "Capture" in the menu bar.

### 1.5 No window icon, no geometry persistence

- No `setWindowIcon` anywhere; grep for `QIcon`/`icon` over `src/` returns one
  hit and it is a comment (`widgets/banner.py:10`). There is no `.ico`, `.png`
  or `.svg` asset in the package. On Windows the taskbar therefore shows the
  generic Python/Qt icon.
- `app.py:26-28` names the org for `QSettings`, but **`QSettings` is never
  constructed**. `run()` (`app.py:68-73`) is `build_application` → `build_window`
  → `show()`. Window size, splitter position, column widths, the last filter and
  the last-opened directory are all forgotten between sessions. Every launch is
  a default-sized window with default columns. That single fact does more for
  the "unfinished/dated" impression than any colour choice.

**Effort: trivial** (icon), **trivial–moderate** (geometry/state via `QSettings`;
note `paths.py` owns file locations, and `QSettings` writes to the platform's
own store rather than a path this project chooses, so it does not collide with
that rule).

---

## 2. Density and spacing

The table itself is **dense and correct**; the chrome around it is loose and
undifferentiated. This is worth stating plainly because the instinct on seeing
"dated" is to add padding, and here that would make it worse.

### 2.1 Row height — good, and load-bearing

`widgets/log_table.py:80` `_ROW_PADDING = 4`, applied at `log_table.py:184`:

```python
vertical.setDefaultSectionSize(self.fontMetrics().height() + _ROW_PADDING)
```

Measured: **20 px row pitch**, with roughly 8 px of glyph ink in it. That is
tighter than Fusion's default item height and it is the right call for a log.
Do not change it in a restyle; `docs/design/gui.md:481` and
`tests/test_gui_window.py:145-158` both depend on the fixed-height mechanism.

### 2.2 Header height (19 px) is *shorter* than a row (20 px)

Measured. The header therefore does not read as a header — it reads as one more
row with a gradient. Combined with §3.4 (centred header titles over
left-aligned data) this is the single cheapest visual fix in the whole audit.

### 2.3 The filter bar: uniform 6 px spacing means no visual grouping

`widgets/filter_bar.py:34-35`:

```python
layout = QHBoxLayout(self)
layout.setContentsMargins(6, 3, 6, 3)
```

`setSpacing` is never called, so the layout keeps the style's
`PM_LayoutHorizontalSpacing` (Fusion: 6 px — *derived*). Every widget is
therefore 6 px from its neighbour: `Level`→combo is the same gap as
combo→`Process`, and `Process`→field the same as field→`Subsystem`. Measured
bar height 30 px for a row of eight controls. Nothing tells the eye which label
owns which field; it is a horizontal run of alternating text and boxes.

The labels are bare `QLabel`s created inline (`filter_bar.py:44`, `62`), not
`QFormLayout` buddies, so they are not even click-to-focus.

**Effort: trivial.** `layout.setSpacing(4)` plus a larger gap between groups, or
drop the labels entirely in favour of the placeholder text the fields already
carry (`filter_bar.py:48-49`: `"name or pid"`, `"com.apple.…"`, `"message text"`).

### 2.4 The one layout that *is* tuned

`main.py:204-210` — the central `QVBoxLayout` is explicitly zeroed:

```python
layout.setContentsMargins(0, 0, 0, 0)
layout.setSpacing(0)
```

and so is the table/minimap `QHBoxLayout` at `main.py:186-188`. Good. The
consequence is that the filter bar, the banner and the table are flush against
each other with no separation other than Fusion's 1 px frame lines — measured
`#dadada` at y=20 and `#bbbbbb` at y=51. Two different greys, one per boundary,
neither chosen.

### 2.5 The splitter handle is 6 px of nothing

Measured y 555–560: `#f3f3f3` between two `#bbbbbb` hairlines. `handleWidth` is
left at the Fusion default; there is no grip dots, no hover affordance. The one
draggable divider in the window is invisible until you find it with the cursor.

### 2.6 The detail pane paints Window grey, not Base

Measured: the pane body is `#f3f3f3` where the table is `#ffffff`.
`widgets/detail_pane.py:70` creates a plain `QWidget` as the scroll area's
widget, which paints `QPalette::Window`. So a third of the window is a grey
form panel bolted under a white table. This is the strongest single "Qt 4 era"
signal in the screenshot.

**Effort: trivial** (`setBackgroundRole(QPalette.Base)` / `setAutoFillBackground`,
or a stylesheet on that one widget).

---

## 3. Colour

### 3.1 Where the palette comes from

`gui/theme.py:74-111` — sixteen hex literals per scheme, no reading of the
platform, deliberately (`theme.py:3-27`, and `docs/design/gui.md:411-421`
explicitly reverses its own earlier "seeded from the OS palette" wording in
favour of what the code does). This is a good decision and the redesign should
keep it: it is what lets `tests/test_gui_theme.py` assert WCAG on three
operating systems and lets the screenshot job force a scheme.

| Role | Light | Dark |
| --- | --- | --- |
| Window | `#f3f3f3` | `#1e1e1e` |
| Base | `#ffffff` | `#252526` |
| AlternateBase | `#f7f7f7` | `#2d2d30` |
| Text | `#1a1a1a` | `#f0f0f0` |
| Highlight | `#0067c0` | `#0078d4` |
| PlaceholderText | `#6b6b6b` | `#9a9a9a` |

### 3.2 The app does follow the OS light/dark setting — for the palette only

`app.py:48-49` resolves the scheme once at startup, `app.py:56` re-applies the
palette on `colorSchemeChanged`. `theme.resolve_scheme` (`theme.py:216-224`)
treats `Unknown` as light, which is honest.

**But the widgets never learn.** `RecordModel.set_scheme` (`models.py:701-710`)
and `Minimap.set_scheme` (`minimap.py:84-87`) exist and **are called from
nowhere in `src/`** — the only callers are `tests/test_gui_model.py:373` and
`tests/test_gui_minimap.py:313`. `MainWindow.scheme` is assigned once at
`main.py:145` and never updated. So on a live OS light↔dark switch the Fusion
palette flips while every severity foreground, the mark tint and every minimap
stripe stay in the old scheme. `docs/design/gui.md:434-436` claims *"A live OS
theme switch is the same function called again from `colorSchemeChanged`"* — that
is true of the palette and false of everything else. **Doc-vs-code mismatch, and
by the project's own rule the code is the bug.**

**Effort: trivial** (connect `colorSchemeChanged` through to the window, call the
two existing `set_scheme` methods; both already emit the right `dataChanged`).

### 3.3 What actually gets colour today: the whole row, in two greys

`models.py:487-489`:

```python
def _foreground(self, row: Row) -> object:
    level = row.level if isinstance(row, Record) else MARKER_LEVEL
    return self._severity[level].foreground
```

`ForegroundRole` is answered for **every column**, so severity tints the entire
row's text, not the Level cell. And from `theme.py:142-159`:

- `INFO` and `NOTICE` = `#1a1a1a` — identical to `Text`.
- `DEBUG` = `#6b6b6b` — **identical to `PlaceholderText`**, i.e. the disabled/hint
  grey.
- `USER_ACTION` = `#0067c0` (blue), `ERROR` = `#b3261e`, `FAULT` = `#8c1d18`.

In a real capture that is two colours: black for Info/Notice, grey for Debug,
with a rare red line. The committed screenshot is exactly that — a wall of grey
and black. Every Debug row reads as *disabled*, which is a strong and wrong
signal for the most numerous row type in a log.

`BackgroundRole` (`models.py:491-502`) returns a tint for **`FAULT` only**
(`#fdecea` / `#3a1f1f`); `ERROR` has `tint=None` at `theme.py:148`. So an error
row carries no background at all — only red text and a leading `!` glyph from
`models.py:431-433`.

**Effort: moderate.** Any change here must keep the WCAG AA assertions in
`tests/test_gui_theme.py:44-77` green against `Base`, against each level's own
tint, and against `mark_tint`.

### 3.4 Alternating row colours are effectively invisible

`log_table.py:176` `setAlternatingRowColors(True)`, against
`Base #ffffff` / `AlternateBase #f7f7f7` (measured in the screenshot as
`(255,255,255)` and `(247,247,247)`). Contrast ratio ≈ **1.06:1**. Dark is the
same story: `#252526` vs `#2d2d30`. The feature is switched on and buys nothing;
with `setShowGrid(False)` at `log_table.py:175` there is then **no** row or
column delineation in the table body at all. Column separators exist only in the
header (measured `#d3d3d3` verticals at y=60) and stop at the header's bottom
rule.

### 3.5 Selection is full-saturation Windows blue

`theme.py:83` `Highlight: "#0067c0"`, `theme.py:101` `"#0078d4"`. Measured in
the screenshot at y=303–322: exactly `(0,103,192)`. Full-chroma, edge-to-edge,
no rounding, no inset. Every modern log viewer uses a desaturated or tinted
selection; this is the Windows XP/Vista system highlight.

A second consequence, not documented anywhere: **severity colour is destroyed by
selection.** `QStyledItemDelegate::initStyleOption` maps `ForegroundRole` onto
`QPalette::Text`, but the style paints a selected item with
`QPalette::HighlightedText` (`#ffffff`). So the selected row — the one the user
is looking at — loses its severity hue entirely and keeps only the `!` glyph.
`tests/test_gui_theme.py:57-65` checks `HighlightedText` vs `Highlight` and is
therefore satisfied by exactly this behaviour.

### 3.6 There is no stylesheet anywhere

Grep for `setStyleSheet` over the whole repository: **zero hits**. Everything is
palette + Fusion's own painting. That is a deliberate position
(`docs/design/gui.md:414`: *"it is not a stylesheet"*), and it is the reason the
window has no rounded corners, no focus rings, no hover states, no elevation and
no accent surfaces. A redesign that wants any of those has to either introduce
QSS (and then decide how the WCAG tests, which only know the palette, keep
their meaning) or paint them in delegates (and then answer to §11's performance
rules).

### 3.7 `QPalette::Accent` is named in the design and never set

`docs/design/gui.md:437-440` says to derive from palette roles including
**`Accent`**. `_ROLES` (`theme.py:74-111`) sets sixteen roles and `Accent` is not
among them, so Fusion synthesises it from `Highlight`. Minor, but it is the role
a redesign would reach for first.

---

## 4. Typography

### 4.1 No font is chosen anywhere

Grep for `QFont`/`setFont`/`setFamily` over `src/`: **zero hits**. The
application uses whatever Qt's default is on the platform. Consequences:

- Windows: Segoe UI ~9 pt (measured digit advance 6 px).
- macOS: whatever Qt picks — `tools/capture_screens.py:6-8` says outright that
  the point of the screenshot job is that this *"picks a system font nobody here
  can preview"*.
- Linux/offscreen on Windows: **no fonts at all**. `capture_screens.py:163-172`
  refuses to render rather than emit tofu boxes.

So there is no type *choice*, and no fallback chain to reason about — the
fallback is the platform's, which is the one thing this project otherwise works
hard to avoid (`theme.py:3-9` argues determinism for exactly this reason). Fonts
are the one visual axis left platform-dependent.

### 4.2 There is no type scale

One size everywhere: menu bar, filter bar labels, column headers, table cells,
detail pane labels and values, status bar readouts. Nothing is bold except the
key names in the F1 sheet's HTML (`main.py:862`) and the `<h3>` in the About box
(`main.py:884`). No caption size, no emphasis, no hierarchy. A status bar at the
same size and weight as the table body is why the four readouts at the bottom
right read as a run-on sentence rather than as metadata.

### 4.3 No monospace anywhere, including where it belongs

The Time column (`models.py:429-430`, `%H:%M:%S.%f` truncated to milliseconds),
`PID`, `Thread`, and the message bodies — which are full of hex addresses,
UUIDs and `C9344.1.1.15` style identifiers, visible all over the screenshot —
are rendered in the proportional UI font. The detail pane's values
(`detail_pane.py:82-87`) are the same. The plaintext exporter takes trouble to
align columns; the viewer does not.

Note the correct scoping if this is fixed: monospace belongs on Time, PID,
Thread and Message, **not** on the whole table — `log_table.py:211` derives every
column width from `fontMetrics().horizontalAdvance("0")` of the *view's* font, so
a per-column font would decouple width from content unless the widths are
recomputed against the same face.

**Effort: moderate**, and it collides with `tests/test_gui_window.py:264-279`,
which pins `columnWidth(0) == 13 * horizontalAdvance("0")`.

---

## 5. Iconography

**There are no icons in the program.** Zero hits for `QIcon`, `setIcon`,
`StandardPixmap`, `QPixmap` across `src/`. Specifically:

- **Menus:** text only (`main.py:333-350` builds every `QAction` with text and a
  shortcut, never an icon).
- **Buttons:** the banner's recovery button (`banner.py:55-57`) and the export
  dialog's `Choose…`/`Export`/`Close` (`export_dialog.py:99-113`) are plain text
  `QPushButton`s.
- **Level column:** text plus an ASCII glyph — `!` for ERROR, `!!` for FAULT
  (`theme.py:148-149`, `157-158`), assembled at `models.py:431-433`. This is a
  *deliberate* rule (`docs/design/gui.md:452-455`: colour is never the only cue,
  the Level column is text and stays text) and the glyphs are asserted by
  `tests/test_gui_theme.py:120-138`. A redesign may add an icon **beside** the
  text; it may not replace the text.
- **Window/taskbar:** no icon (§1.5).
- **Status bar:** the design sketch draws a `●` live indicator
  (`docs/design/gui.md:32`); `status_bar.py:42-45` has four bare `QLabel`s.

Two supply options, both viable here:

1. **`QStyle.StandardPixmap`** — free, no new dependency, and it looks precisely
   like 2005 (`SP_MediaPlay`, `SP_DialogOpenButton`, the Windows XP-era warning
   triangle). It would make the window look *more* dated, not less.
2. **A bundled SVG set.** `pyproject.toml:58` pins `PySide6-Essentials`, which
   includes `QtSvg`/`QtSvgWidgets`, so `QIcon` can load SVG with no new
   dependency. `[tool.hatch.build.targets.wheel] packages = ["src/ostrace"]`
   (`pyproject.toml:103`) ships non-Python files inside the package, so an
   `src/ostrace/gui/icons/*.svg` directory would be packaged as-is. Two colour
   variants (or `currentColor` recoloured through `QPainter`) are needed because
   the app has two schemes. This is the right choice.

Note the rules a bundled asset must respect: `paths.py` decides where *user*
files go; package resources inside the wheel are not a `paths.py` decision, and
should be loaded via `importlib.resources` rather than `__file__` arithmetic.

---

## 6. The three widgets that carry the experience

### 6.1 The table — `widgets/log_table.py`

**What it is:** a `QTableView` with `FastHeader` (`log_table.py:83-134`), one
delegate on the Process column (`log_table.py:137-153`), grid off, alternating
rows on, vertical header hidden, fixed row height, six interactive columns with
`setStretchLastSection(True)`.

What is clumsy:

1. **Header titles are centred over left-aligned data.** `FastHeader:111` sets
   `option.textAlignment = self.defaultAlignment()`, and `QHeaderView`'s default
   for a horizontal header is `AlignCenter` (*derived*; visible in the
   screenshot — "Process" sits centred over a column of left-aligned process
   names). The model answers no `TextAlignmentRole` (`models.py:93-100`
   `_ANSWERED_ROLES` omits it), so cells are `AlignLeft|AlignVCenter`. Every
   column heading is misaligned with its own content.
   **Effort: trivial** — one `setDefaultAlignment` call, and it is *not* covered
   by any test.
2. **The header has a gradient; nothing else does.** Measured `#fefefe`→`#f0f0f0`
   over 19 px. It is the only gradient in the window and it is Fusion's, i.e.
   the visual language of Qt 4.
3. **The collapse-repeats rule leaves a large empty gutter.** `columns.py:52-54`
   marks Process, Subsystem and Category `collapse_repeats=True`, implemented at
   `models.py:440-464`. In the committed screenshot the first ~12 rows have all
   three of those columns blank, so the eye jumps from a 78 px Time column
   across ~468 px of white to the Message column. The rule is right (it is in
   `docs/design/gui.md:78-80`) but with no grid, no zebra contrast and no
   left-edge anchor, the result reads as a broken or half-loaded table. A
   redesign should keep the blanking and give the run a visual anchor (a subtle
   left rule, a "same as above" tick, or a group boundary line) rather than
   remove it.
4. **No hover state, no focus ring, no current-row indicator other than
   selection.** Default Fusion item painting.
5. **No column reorder/hide UI.** `setSectionResizeMode(Interactive)`
   (`log_table.py:187`) allows resizing but nothing persists it (§1.5), and there
   is no header context menu.
6. **No context menu at all** on the table — no right-click Copy, no "filter by
   this process", no "copy message". `copy_selection` exists
   (`main.py:823-852`) and is reachable only via `Ctrl+C` or `Edit ▸ Copy`.

What `docs/design/gui.md` asks for and got: six columns (§2 table), fixed widths
(§2), repeat suppression (§2), no wrap / elide right (§11), fixed row height
(§11), `FastHeader` (§11), the Process middle-elide so the `[pid]` survives (§2,
`log_table.py:137-153`). The table is the best-specified and best-implemented
part of the program; its problem is purely that it is unstyled.

### 6.2 The filter bar — `widgets/filter_bar.py`

**What it is** (`filter_bar.py:31-53`): `QLabel("Level")` + `QComboBox` +
`QLabel("Process")` + `QLineEdit` + `QLabel("Subsystem")` + `QLineEdit` +
`QLabel("Search")` + stretched `QLineEdit` + `QCheckBox("Regex")`, all in one
`QHBoxLayout` at uniform spacing.

What is clumsy:

1. **Four labels that the placeholders already say.** `filter_bar.py:47-49` sets
   `"name or pid"`, `"com.apple.…"`, `"message text"` as placeholder text *and*
   prefixes each field with a `QLabel`. The label row costs horizontal space and
   adds nothing.
2. **The level combo reads `"Debug and above"`** (`filter_bar.py:41`) — correct
   threshold semantics (`docs/design/gui.md:271-274`), but the default state of
   the program shows a control that looks like a filter is applied when none is.
   There is no "All levels" or "no filter" resting label.
3. **`Regex` is a bare checkbox at the far right**, detached from the Search
   field it modifies (`filter_bar.py:51-53`) — it should be inside or adjacent to
   the field, which `QLineEdit.addAction` supports natively.
4. **No indication that a filter is active.** No count, no chip, no highlighted
   field, no "clear all". The only feedback is the banner, and only in the total
   case (`main.py:971-978`). `FilterBar.is_empty` (`filter_bar.py:88-99`) computes
   exactly the fact needed to show an "active" state and is used only to
   distinguish banner cases.
5. **No match count.** `main.py:460` and `main.py:654` both call
   `status.set_volume(...)` with `self.model.retained` / `loaded` — i.e. the
   *unfiltered* total. Filter 5,000 records down to 12 and the status bar still
   reads `5,000 records`. There is nowhere in the window that says how many rows
   the filter kept. `RecordModel.hidden_by_filter` (`models.py:736-738`) exists
   and is never used in `src/`.
6. **No filter history, no shareable filter string.** Acknowledged at
   `docs/design/gui.md:262-268`.

### 6.3 The detail pane — `widgets/detail_pane.py`

**What it is:** a `QScrollArea` (`detail_pane.py:63-76`) containing a
`QFormLayout` of right-aligned `QLabel:` / word-wrapped `QLabel` pairs, rebuilt
from scratch on every selection change (`detail_pane.py:78-89`, `_set` removes
every row and re-adds).

What is clumsy:

1. **It is the classic Qt Designer form.** Right-aligned bold-less labels ending
   in a colon, left-aligned values, `QFormLayout`'s default spacing. Measured
   background `#f3f3f3` (Window) against the table's `#ffffff` (§2.6).
2. **Fourteen scalar fields in a vertical stack**, most of them short
   (`detail_pane.py:139-159`), so the pane is mostly whitespace on the right two
   thirds while the one field that needs room — Message — wraps at the bottom,
   below the fold. Measured pane height 166 px; the screenshot shows only 7 of
   the ~13 rows, so `Message` is never visible without scrolling.
3. **No emphasis anywhere.** Level, Process and Message are the same weight and
   colour as `Platform`. Severity colour, which the table has, is not carried
   into the pane at all.
4. **Values are `QLabel` with `TextSelectableByMouse`** (`detail_pane.py:85`) —
   selectable but not copyable as a unit, no "copy field" affordance, and a long
   `process_path` cannot be selected precisely.
5. **Full teardown/rebuild per selection** (`detail_pane.py:80-82`), plus
   `_fit_body`'s `activate()` + `heightForWidth()` (`detail_pane.py:117-120`).
   This runs on every arrow-key step through the log. It is off the 16 Hz pump
   path so it is not a throughput risk, but it makes `F7`/`F8` stepping feel
   heavy, and `docs/design/gui.md:396-400` explicitly says not to budget
   performance work here — so the fix is structural (reuse widgets) rather than
   micro-optimisation.

What §9 asks for and did not get: the cheap **in-row expansion on `Right`/`Left`**
that Console.app pairs with a bottom panel, and with it the two stream
semantics. Acknowledged at `docs/design/gui.md:388-394`.

---

## 7. Feedback and state

### 7.1 The cold-start window says nothing

On launch: empty table with six headers, banner hidden
(`banner.py:60` `self.hide()`; asserted by `tests/test_gui_window.py:293-294`),
detail pane showing the placeholder from `detail_pane.py:122-123`:

> **Nothing selected:** Select a record to see every field of it.

and a status bar reading `idle  no device  0 records  0 gaps`. `_update_banner`
(`main.py:963-991`) is only ever called from `_on_loaded` and `_apply_filter`, so
the resting state has no message by construction.

**This is the worst empty state in the program.** A first-time user sees an
empty grid, a form telling them to select something that does not exist, and
"no device" — with no button, no instruction and no indication that
`Capture ▸ Capture` is the thing to press. **Effort: trivial to moderate** (an
empty-state panel over the table, or a resting banner with two actions —
`Capture` and `Open capture…` — both of which already exist as slots).

### 7.2 The banner — `widgets/banner.py`

`QFrame` with `Shape.StyledPanel` (`banner.py:40`), a word-wrapped `QLabel`
(`banner.py:50-53`) and one `QPushButton` (`banner.py:55-57`), margins
`(8, 4, 8, 4)` (`banner.py:48`).

- **No severity, no colour, no icon.** A "capture stopped" error, a "view is
  paused" notice and a "truncated capture" warning all render as the same grey
  bar with a button. `docs/design/gui.md:278-296` distinguishes eight states; the
  widget distinguishes none of them visually.
- **It appears and disappears instantly**, pushing the table down ~30 px with no
  transition (`banner.py:81` `self.show()`, `banner.py:86` `self.hide()`).
- **A banner with no action cannot be dismissed.** `main.py:617-620` (`_park`,
  the "capture has not released the device yet" message) calls `show_message`
  with `action=None`, so `banner.py:79` hides the button — and `act()` is the only
  path to `hide()` other than `set_paused(False)` (`main.py:638`) and the filter
  branch at `main.py:979-981`. That message stays on screen indefinitely.
  **Effort: trivial** (a close affordance, or `Esc`, which is unbound — see
  §Constraints).
- The eight banner messages themselves are well written and are the strongest
  UX asset the program has (`main.py:439`, `469-473`, `478-481`, `497`, `590-593`,
  `617-620`, `631-636`, `659-664`, `679-683`, `746-758`, `916`, `972-976`,
  `986-990`). They are all in one visual register — grey.

### 7.3 The status bar — `widgets/status_bar.py`

Four `QLabel`s added with `addPermanentWidget` (`status_bar.py:51-52`), so they
sit right-aligned in a row. Rendered: `idle  no device  5,000 records  0 gaps`.

- **No separators.** `docs/design/gui.md:32` draws
  `● 1,204 rec/s │ iPhone · iOS 26.5.2 │ 1.2M records │ 0 gaps` — the `│`
  separators and the `●` live dot are both absent, and neither absence is
  acknowledged anywhere in the document. The four facts read as one string.
- **No live indicator.** `set_rate(None)` → `"idle"` (`status_bar.py:56-61`); a
  running capture just changes the text to `1,204 rec/s`. There is no
  colour/animation distinguishing "streaming" from "stopped".
- **`records` is the unfiltered retained count** (see §6.2.5).
- **No capture-file path readout.** The window title carries it
  (`main.py:457`, `597`) and nothing else does.
- The always-present gap count is correct and well-reasoned
  (`status_bar.py:72-74`, `docs/design/gui.md:44-48`, asserted at
  `tests/test_gui_window.py:285-290`).

### 7.4 Filter hides everything

`main.py:971-978` → banner *"All 5,000 records are hidden by the filter."* with
`Clear filter`. This works and is tested (`test_gui_wiring.py:130-145`). The
table behind it is simply blank — no ghost, no "0 of 5,000" readout in the
header, no dimming of the filter fields that caused it.

### 7.5 Progressive load

`CaptureLoader` emits `progressed` per 2,048-record batch (`loader.py:44-46`),
wired to `status.set_volume` at `main.py:459-461`. So a large file shows a
climbing record count in the status bar and nothing else — no progress bar, no
busy indicator, no cancel button (`CaptureLoader.cancel` exists at
`loader.py:71` and is reachable only by opening a different capture,
`main.py:433-434`).

### 7.6 Export dialog — `widgets/export_dialog.py`

Worth noting because it is the only modal the user will meet. A `QFormLayout` of
combo/spinbox/line-edit, with the destination `QLineEdit` and its `Choose…`
button stacked **vertically** (`export_dialog.py:94-102` uses a `QVBoxLayout`),
so the button sits under the path field instead of beside it. The results
`QLabel` (`export_dialog.py:104-107`) renders bullet lists as plain text with
`"  • "` prefixes (`export_dialog.py:178`). `QFileDialog` is forced non-native in
both places (`main.py:420`, `export_dialog.py:147`) for a documented and correct
reason — but it means the file chooser also looks like Qt rather than like the OS.

---

## 8. `docs/design/gui.md` — section-by-section, built vs not built

Legend: **✓** built · **✗** not built · **A** acknowledged as a gap in the
document itself (§13 or inline) · **U** undocumented omission.

### §1 The window

| Item | Status |
| --- | --- |
| Menu bar (Capture / Edit / View / Help) | ✓ `main.py:362-370` |
| **Toolbar** | ✗ **A** — `gui.md:36-40`. Nothing in `src/`; `main.py:112` docstring claims one |
| **Device selector** | ✗ **A** — `gui.md:36-40`. `main.py:510` passes no udid |
| Six columns incl. Category | ✓ `columns.py:49-56` |
| Gap count always shown | ✓ `status_bar.py:72-74` |
| **Status-bar `│` separators and the `●` live dot** (sketch, `gui.md:32`) | ✗ **U** |

### §2 Columns and detail pane

| Item | Status |
| --- | --- |
| Six-column split | ✓ |
| Time = device clock with offset | ✓ `models.py:429-430`, `detail_pane.py:140-141` |
| Level as text, always | ✓ `models.py:431-433` |
| `[pid]` never truncated | ✓ `MiddleElidingDelegate`, `log_table.py:137-153` |
| Subsystem/Category `-` when absent | ✓ `models.py:143-145` |
| Message elided right, never wrapped | ✓ `log_table.py:173-174` |
| Detail pane carries all eleven fields | ✓ `detail_pane.py:139-159` |
| Both clocks **with their delta** | ✓ live only, `detail_pane.py:143-146`; deliberately absent for files (`main.py:955-961`) |
| Fixed column widths | ✓ `log_table.py:202-215` |
| Suppress repeated cell | ✓ — but in `data()` (`models.py:440-464`), where §2 says *"costs nothing in a delegate"*. Minor divergence, and it puts per-cell Python work on the hot path |

### §3 Markers and the minimap

| Item | Status |
| --- | --- |
| Marker never hidden by a filter (type test at one choke point) | ✓ `models.py:549-557`, `markers.py:80-89` |
| Gap vs Eviction rendered differently | ✓ `models.py:466-485`, `markers.py:52-62` |
| Gap wording owned by the exporter | ✓ `models.py:484` calls `plaintext.gap_line` |
| Minimap strip (not a `QScrollBar` subclass) | ✓ `widgets/minimap.py` |
| Errors bucketed, gaps/marks placed exactly | ✓ `models.py:317-363` |
| **Viewport position indicator on the minimap** | ✗ **U** — the strip shows *what* but never *where you are*. `minimap.py:116-133` paints bands only. Measured: 12 px of white gutter outside the scrollbar with two red blocks in it |
| **Minimap legend / tooltip per band** | ✗ **U** — one static tooltip for the whole strip (`minimap.py:67`) |

### §4 Follow

| Item | Status |
| --- | --- |
| Follow derived from the viewport, never stored | ✓ `main.py:698-733` |
| Breaks on selection, scroll-up, jump | ✓ `main.py:715-722` |
| `Ctrl+End` jump then resume, clearing selection | ✓ `main.py:772-799` |
| **"Follow is on" indicator** | ✗ **A** — `gui.md:216-219` |
| **Unseen-record count** | ✗ **A** — `gui.md:216-219`, and called *"the more useful half"* |

### §5 Filtering and highlighting

| Item | Status |
| --- | --- |
| Fielded filter bar (level threshold + 3 fields + regex) | ✓ `filter_bar.py` |
| Incremental filtering, O(batch) | ✓ `models.py:506-532` |
| Hand-written index list, not `QSortFilterProxyModel` | ✓ `models.py:159-160` |
| Selection/viewport anchored to record identity | ✓ `main.py:924-949`, `models.py:403-423` |
| **Highlight as a second verb** (mark rows in place, composes with filter) | ✗ **U** — §5's headline rule. Not built, and **not listed in §13**. The only in-place marking is the manual `Ctrl+M` mark (`models.py:248-264`), which is a different feature |
| **Gutter indicator for a highlight hit** | ✗ **U** |
| **Per-term hit count** | ✗ **U** — and there is no match count of any kind (§6.2.5) |
| Expression language / copy-pasteable filter / history | ✗ **A** — `gui.md:262-268` |

### §6 States that must be visible

| State | Status |
| --- | --- |
| Paused | ✓ `main.py:630-636` (without *N* buffered — **A**) |
| Everything filtered out | ✓ `main.py:971-978` |
| No device | ✓ `main.py:493-498` |
| Empty capture | ✓ `main.py:982-990` |
| **Disconnected mid-capture — reconnecting** | ✗ **A** — `gui.md:290`, `298-302`. `sources/os_trace.py` retries for up to a minute and the viewer says nothing |
| Capture stopped | ✓ `main.py:666-683` |
| Paused queue overflowed | ✓ `main.py:658-664`, `pump.py:126-143` |
| Truncated capture opened | ✓ `main.py:466-473` |

### §7 Pause and Disconnect

All built: pause never touches the source (`pump.py:101-105`), Disconnect named
after its consequence (`main.py:544-569`, asserted `test_gui_window.py:131-139`),
export refused while running with the resolving control named
(`main.py:735-760`), session adopted on thread end (`main.py:571-597`), 100k
paused-queue bound emitting an `Eviction` (`pump.py:50`, `126-143`).

### §8 Keyboard

Built: one generated table (`shortcuts.py:58-175`), actions built from it
(`main.py:298-331`), F1 sheet rendered from the same list (`main.py:854-871`),
both traditions aliased, `StandardKey` used where one exists, no destructive verb
on an editing chord (asserted `test_gui_shortcuts.py:56-78`), every action bound
(`shortcuts.py:214-224`), pause bound, `F7`/`F8` work without table focus
(`main.py:812-821`).

Nothing unbuilt here.

### §9 Detail pane

| Item | Status |
| --- | --- |
| Bottom panel with every field | ✓ |
| **In-row expansion on `Right`/`Left`** and its stream semantics | ✗ **A** — `gui.md:388-394` |
| **"Interval between updates" preference** | ✗ **A** — `gui.md:402-406`; exists as `pump.TICK_MS` and `main._FOLLOW_MIN_MS` |

### §10 Theme

| Item | Status |
| --- | --- |
| Palette as a pure function of a scheme, sixteen literals | ✓ `theme.py:74-111`, `162-187` |
| Mark colour distinct from the accent, amber | ✓ `theme.py:120`, asserted `test_gui_theme.py:80-86` |
| Severity checked against Base *and* the mark tint | ✓ `test_gui_theme.py:44-77` |
| Colour never the only cue; Level stays text; `!`/`!!` glyphs | ✓ `theme.py:148-149`, `157-158` |
| Fusion forced, style before palette | ✓ `theme.py:227-235`, asserted `test_gui_theme.py:153-166` |
| **Live OS theme switch re-runs the same function** | **partial ✗ U** — the palette flips (`app.py:56`) but `RecordModel.set_scheme` and `Minimap.set_scheme` are never called from `src/`; `MainWindow.scheme` is fixed at `main.py:145`. Severity colours, mark tint and minimap stripes keep the old scheme |
| **Derive from `Accent`** | ✗ **U** — `Accent` is not in `_ROLES` |

### §11 Performance rules

All eight rules implemented as stated: `FastHeader` (`log_table.py:83-134`),
`QTableView` only, prebuilt `flags()` (`models.py:182`, `204-206`), `multiData()`
deliberately not overridden (`models.py:36-40`), no `ResizeToContents`, fixed row
height via the vertical header (`log_table.py:181-184`), prebuilt brushes
(`models.py:186-194`), `setWordWrap(False)` + elide right, no `Qt.X.Y` chains in
hot paths. Producer thread → `deque` → 50 ms `QTimer` → one `beginInsertRows`
(`live.py:68`, `pump.py:107-124`), 200k cap trimmed at +10% in one
`beginRemoveRows` (`models.py:75-79`, `559-646`).

One contradiction of its own rule, in a widget: `Minimap.paintEvent` calls
`palette_for(self.scheme)` on **every repaint** (`minimap.py:119`), constructing a
fresh `QPalette` and 48 `setColor` calls, four times a second during a capture —
directly against `minimap.py:77`'s own *"Never allocate inside `paintEvent`"*.
Cheap to fix, and worth fixing before a redesign adds anything else to that
paint.

### §12 What CI can verify

Screenshot job built (`.github/workflows/screenshots.yml`, `tools/capture_screens.py`),
`workflow_dispatch`-only, `if-no-files-found: error`, native plugin on Windows /
offscreen on macOS, refusal to render with an empty font database
(`capture_screens.py:163-172`). Menu-role test built
(`tests/test_gui_window.py:61-93`).

Note: the committed screenshots are **1028×749**, not the 1280×800 the tool asks
for (`capture_screens.py:57-58`) — the window was clamped by the capturing
machine's available screen area. Cosmetic, but it means the committed README
images are not the documented size.

### §13 Deliberately out of scope

Substring selection inside a message, context lines (`grep -C`), per-pane
follow, and a `Gap` reason taxonomy — all correctly absent.

### Summary of §8's headline: what is missing and *not* acknowledged

The document is unusually honest about its own gaps, so the undocumented
omissions are the short list and the interesting one:

1. **Highlight as a second verb** (§5) — the section's own headline rule.
2. **Gutter indicator** and **per-term hit counts** (§5); more basically, any
   filtered-match count anywhere.
3. **Live theme switch does not reach the widgets** (§10) — a functional bug, not
   a scope decision.
4. **`Accent` role never set** (§10).
5. **Minimap has no viewport indicator** (§3) — the strip tells you a gap exists
   but not whether you are above or below it.
6. **Status-bar separators and live dot** (§1 sketch).

---

## 9. Constraints the redesign inherits

### 9.1 Every keyboard shortcut currently bound

All from `src/ostrace/gui/shortcuts.py:58-175` unless noted. Primary first,
aliases after. A redesign must not collide with any of these.

| Action | Primary | Aliases | Line |
| --- | --- | --- | --- |
| `capture` | `Ctrl+R` | — | `shortcuts.py:59-65` |
| `pause` (checkable) | `Ctrl+P` | — | `shortcuts.py:66-73` |
| `disconnect` | `Ctrl+D` | — | `shortcuts.py:74-80` |
| `open` | `StandardKey.Open` (`Ctrl+O`) | — | `shortcuts.py:81-87` |
| `export` | `Ctrl+E` | — | `shortcuts.py:88-94` |
| `copy` | `StandardKey.Copy` (`Ctrl+C`) | — | `shortcuts.py:95-101` |
| `find` | `StandardKey.Find` (`Ctrl+F`) | **`/`** | `shortcuts.py:102-109` |
| `mark` | `Ctrl+M` | **`M`** | `shortcuts.py:110-117` |
| `clear_marks` | `Ctrl+Shift+M` | — | `shortcuts.py:118-120` |
| `top` | `StandardKey.MoveToStartOfDocument` (`Ctrl+Home`) | **`G, G`** | `shortcuts.py:121-127` |
| `bottom` | `StandardKey.MoveToEndOfDocument` (`Ctrl+End`) | **`Shift+G`** | `shortcuts.py:128-134` |
| `next_error` | `Ctrl+Shift+E` | **`E`** | `shortcuts.py:135-141` |
| `previous_error` | `Ctrl+Alt+Shift+E` | **`Shift+E`** | `shortcuts.py:142-148` |
| `next_marker` | `Ctrl+Shift+G` | **`]`** | `shortcuts.py:149-155` |
| `previous_marker` | `Ctrl+Alt+Shift+G` | **`[`** | `shortcuts.py:156-162` |
| `next_mark` | `Ctrl+Shift+N` | — | `shortcuts.py:163` |
| `previous_mark` | `Ctrl+Shift+P` | — | `shortcuts.py:164` |
| `step_down` | `F8` | — | `shortcuts.py:165-167` |
| `step_up` | `F7` | — | `shortcuts.py:168-173` |
| `keys` | `F1` | — | `shortcuts.py:174` |
| `quit` | `StandardKey.Quit` | — | `main.py:325-327` |
| `about` | *(none — deliberately, `AboutRole`)* | — | `main.py:328` |

Notes for a redesign:

- All actions are added to the window (`main.py:349` `self.addAction(action)`),
  so they are **window-context** shortcuts. The bare-letter aliases (`M`, `E`,
  `Shift+E`, `/`, `[`, `]`, `G G`, `Shift+G`) coexist with typing in the filter
  bar only because `QLineEdit` accepts `ShortcutOverride` for text input. **Any
  new text-entry widget that is not a `QLineEdit`/`QTextEdit` subclass must
  handle `ShortcutOverride` or those letters will be swallowed.**
- **`Esc` is unbound** and is the obvious key for "dismiss banner" / "clear
  filter" / "leave the search field".
- Also free and conventional: `Ctrl+L`, `Ctrl+K`, `Ctrl+T`, `Ctrl+W`, `Ctrl+B`,
  `Ctrl+,`, `Ctrl+Shift+F`, `F2`, `F5`, `F11`.
- `shortcuts.py:185` `RELOCATED = ("quit", "about")` and there is deliberately
  **no Settings action** — `tests/test_gui_window.py:78-93` asserts
  `not hasattr(window, "action_settings")`. A redesign that wants a preferences
  dialog must change that test and give the action an explicit `MenuRole`.
- New keys go in `BINDINGS`, never as ad-hoc `QShortcut`: `key_table()`
  (`shortcuts.py:197-211`) is the F1 sheet, and
  `tests/test_gui_shortcuts.py:95-105` asserts one row per binding.

### 9.2 Test attachment points — renaming or restructuring these breaks tests

**Public-ish window attributes** (all of `MainWindow`):

| Attribute | Used by |
| --- | --- |
| `window.model` | `test_gui_wiring.py:45`, `test_gui_navigation.py` throughout, `test_gui_live.py:223-225` |
| `window.table` | `test_gui_wiring.py:46,80`, `test_gui_navigation.py:55,85,107,140,155,162,168-175,183,300,309-313,335,352`, `test_gui_window.py:146-161,275-279` |
| `window.detail` | `test_gui_wiring.py:84,99-100`, `test_gui_navigation.py:183` |
| `window.banner` | `test_gui_wiring.py:75,127,139,141,145`, `test_gui_window.py:294,300,314-315`, `test_gui_live.py:294-296,459`, `test_gui_export.py:177` |
| `window.status` | `test_gui_wiring.py:52-53`, `test_gui_window.py:288-290` |
| `window.filter_bar` | `test_gui_wiring.py:109,122-123,135,167,196`, `test_gui_window.py:299,309,315,325-326` |
| `window.capture` | `test_gui_wiring.py:61-62` |
| `window.menus` | `test_gui_window.py:125` |
| `window.action_*` (all 22) | `test_gui_shortcuts.py:107-131`, `test_gui_window.py:90-91,137-139`, `test_gui_live.py:348-415` |
| `window.menu_items()` | `test_gui_window.py:61-128`, `test_gui_shortcuts.py:107-119` |
| `window._loader` | `test_gui_wiring.py:29-35`, `tools/capture_screens.py:97-100` |
| `window._apply_filter()` | `test_gui_wiring.py:110,124,136,143,168,197` |

**Private members reached into by tests** — these are effectively API:

| Member | Used by | Breaks if… |
| --- | --- | --- |
| `filter_bar._level` | `test_gui_wiring.py:109,167,196` — `setCurrentIndex(4)` and expects `Level.ERROR` | the combo gains an "All levels" row, or `Level` is reordered, or the combo is replaced by a segmented control |
| `filter_bar._process` / `._subsystem` / `._search` / `._regex` | `test_gui_wiring.py:122-123,135`, `test_gui_window.py:299,325-326` | any of the four fields is renamed or replaced by a token/chip widget |
| `status._volume` | `test_gui_wiring.py:53` (`"3,000" in ...text()`) | the volume readout stops being a `QLabel` named `_volume` |
| `status.gap_text` | `test_gui_window.py:288-290`, `test_gui_wiring.py:52` | the gap readout changes shape |
| `banner.text` / `banner.act()` | many, above | the banner gains multiple actions, or `act()` stops being "the way out" |
| `detail.field(name)` | `test_gui_wiring.py:84,99-100`, `test_gui_detail.py` throughout | **any detail-pane label is renamed.** The label strings are the test API: `"Message"`, `"Device time"`, `"Device UTC offset"`, `"Host time"`, `"Difference"`, `"Level"`, `"Process"`, `"PID"`, `"Process path"`, `"Subsystem"`, `"Category"`, `"Thread"`, `"Image"`, `"Platform"`, `"Nothing selected"`, `"Gap start"`, `"Gap end"`, `"Duration"`, `"Reason"`, `"Recoverable"`, `"Records not shown"`, `"Visible log starts after"` |
| `detail._form` | `test_gui_detail.py:31-45,128-159` — walks `QFormLayout` rows by `FieldRole` and expects the field widget to be a `QLabel` | the pane stops using `QFormLayout`, or values stop being `QLabel`s |
| `minimap._bands` | `test_gui_minimap.py:197-213` | the band cache is renamed |

**Structural assertions:**

- `test_gui_window.py:128`: `len(window.menu_items()) == len(BINDINGS) + len(RELOCATED)`.
  **Any new menu item that is not a `Binding` or in `RELOCATED` fails this test.**
  Toolbar-only buttons reusing existing actions are safe.
- `test_gui_window.py:61-75`: every menu item must declare a non-default
  `MenuRole`; `main.py:333-350` `_action` is the only constructor and enforces it.
- `test_gui_window.py:95-110`: every menu item must have a receiver on
  `triggered`.
- `test_gui_window.py:160-161`: the table's horizontal header must be a
  `FastHeader`.
- `test_gui_window.py:334-356`: the Process column's delegate must be a
  `MiddleElidingDelegate` and the view's own elide mode must stay `ElideRight`.
- `test_gui_window.py:264-279`: `columnWidth(0) == 13 * fontMetrics().horizontalAdvance("0")`
  — pins the character-unit sizing scheme and the Time column's 13.
- `test_gui_minimap.py:189-193`: `strip.width() == int(horizontalAdvance("0") * 2.0)`
  — pins the minimap to 2 character widths.
- `tests/test_gui_theme.py` pins the colour system: every severity ≥ 4.5:1 on its
  own background (`:44-53`), on `mark_tint` (`:68-77`); `HighlightedText` ≥ 4.5:1
  on `Highlight` (`:56-65`); mark ≠ highlight and > 2.0:1 apart (`:80-86`); the
  two schemes differ (`:89-101`); disabled dimmer than enabled (`:104-116`);
  ERROR and FAULT carry glyphs and INFO does not (`:119-129`); ERROR and FAULT
  differ in **both** glyph and tint-presence (`:132-138`). **A restyle that gives
  ERROR a background tint must keep `(error.tint is None) != (fault.tint is None)`
  true — i.e. it would have to remove FAULT's tint or change that test.**

### 9.3 Performance-sensitive paths a restyle must not disturb

The model holds up to 200,000 rows (`models.py:75`) and is fed by a 50 ms drain
(`pump.py:44`, i.e. 20 Hz; the prompt's 16 Hz is the same order) with the tail
scroll throttled separately to 100 ms (`main.py:97`).

- **`RecordModel.data()` (`models.py:218-238`) runs per cell per role.** Qt asks
  about seven roles per visible cell; the role test at `models.py:223` short-
  circuits three of them before any work. **Do not add a role to
  `_ANSWERED_ROLES` (`models.py:93-100`) casually** — each one added is
  `visible_cells × repaints` extra Python calls. `TextAlignmentRole`,
  `DecorationRole`, `FontRole` and `SizeHintRole` are all currently unanswered
  and each would be a per-cell cost. Prefer view-level settings (alignment on the
  header/view, one font on the view) over per-cell roles.
- **`_display` → `_repeats_previous` (`models.py:440-464`)** already does an
  extra `row_at()` + `_field()` per cell for three of the six columns. That is
  the existing per-cell budget; a restyle should not add to it.
- **`_foreground` / `_background` (`models.py:487-502`)** return prebuilt
  `QColor`s from `_rebuild_severity` (`models.py:186-194`). **Never construct a
  `QColor`/`QBrush` inside `data()`** — that is why the cache exists.
- **The one existing custom delegate:** `MiddleElidingDelegate`
  (`log_table.py:137-153`), installed on `Column.PROCESS` only
  (`log_table.py:163`). It exists because `textElideMode` is a whole-view
  property and the Process column needs `ElideMiddle` so the `[pid]` survives
  (`docs/design/gui.md:62`, `145`), while Message needs `ElideRight`. It
  overrides `initStyleOption` only — it does **not** override `paint`, so the
  per-cell cost is one Python call, not a full custom paint.
  **A redesign that adds a `paint()` override to the Message column — the widest
  column, always visible — puts a Python paint call on every visible row of every
  repaint at 20 Hz.** `docs/design/gui.md:396-400` names colouring rules as one of
  Wireshark's three cost centres and says *"the delegate is what to optimise"*.
- **`FastHeader` (`log_table.py:83-134`)** exists because
  `QHeaderView::initStyleOptionForIndex` asks the selection model per section
  whether the whole column is selected (QTBUG-59478). Measured 5.98 s → 2.92 s
  on `selectAll()` at 200k×6, `flags()` calls 1,200,689 → 683. **Do not reinstate
  a stock `QHeaderView`**, and if the header is restyled, keep filling
  `option.text` — the first version skipped `super()` entirely and painted a
  header with no titles; nothing failed, only a screenshot showed it
  (`test_gui_window.py:164-187` is the regression guard).
- **`Minimap.paintEvent` (`minimap.py:116-133`)** runs up to 4 Hz during a
  capture (`REFRESH_MS = 250`, `minimap.py:44`) and currently rebuilds a whole
  `QPalette` per paint (`minimap.py:119`). Fix that before adding to it.
- **`_follow` (`main.py:698-733`)** is throttled to 100 ms because each tail
  scroll is a full viewport repaint measured at ~20 ms. Anything that makes a row
  more expensive to paint multiplies directly into that number.
- **Row height must stay fixed** (`log_table.py:181-184`); wrapping or
  `ResizeToContents` reintroduces per-row height computation
  (`test_gui_window.py:145-158` guards it).

### 9.4 The offscreen test environment

`QT_QPA_PLATFORM=offscreen` in CI (`.github/workflows/ci.yml:141`) and in the
documented local command (`CONTRIBUTING.md:37`). **Its font database is empty on
Windows** — measured 0 families vs 154 under the native plugin
(`docs/design/gui.md:503-512`) — while `QFontMetrics` keeps returning plausible
numbers for a face nobody sees.

Where this bites a restyle:

- **No new test may assert a pixel measurement of rendered text.** Column widths,
  elide positions, row heights, wrapped-label heights are all off-limits as
  absolute numbers.
- The two existing tests that *look* like they violate this survive because both
  sides of the comparison use the same (fictional) metric:
  `test_gui_window.py:275-279` (`columnWidth(0) == 13 * horizontalAdvance("0")`)
  and `test_gui_minimap.py:189-193` (strip width). Copy that pattern, not a
  literal.
- `test_gui_detail.py:128-159` is the model to imitate for anything geometric:
  it asserts a **relation** (`label.height() >= label.heightForWidth(width)`),
  never a number, and says so in its docstring.
- **Colour is safe offscreen.** `test_gui_minimap.py:287-323` renders to a
  `QImage` and asserts pixel colours; `QWidget.render()` produces real pixels
  under the offscreen plugin on a widget that was never shown. So a restyle *can*
  be regression-tested by rendering and sampling colours — just not by measuring
  text.
- `tools/capture_screens.py:163-172` refuses to render when the font database is
  empty, and `screenshots.yml` therefore uses the **native** plugin on Windows
  and **offscreen** on macOS. A redesign that bundles a font would change that
  calculus (`--font` already exists at `capture_screens.py:140-150`).
- **Colour-scheme switching cannot be tested at all** offscreen —
  `setColorScheme()` is a no-op there (`theme.py:11-16`). The §10 bug in §3.2 is
  therefore structurally invisible to CI, which is presumably why it survived.

### 9.5 Project rules that constrain the implementation

- **Only `compat.py` may branch on the operating system**, using the literal
  `sys.platform == "win32"` form (`CLAUDE.md`, `src/ostrace/compat.py:11-18`). So
  a per-platform font family, a per-platform icon set or per-platform chrome
  cannot be selected in `gui/`; it must go through `compat.py` — and the
  three-platform `mypy` run depends on the literal form.
- **Only `paths.py` decides where files go.** Package resources (SVGs, a bundled
  font) are not a `paths.py` decision, but any user-visible file a redesign
  writes — a saved layout, a filter history — is.
- **`docs/formats/` wins over the code**, and `docs/design/gui.md` is a behaviour
  contract of the same kind: a redesign that diverges from it should update the
  document in the same change, and prefer the document where they disagree.
- **Two SPDX lines at the top of every new source file.**
- `CHANGELOG.md` under `## [Unreleased]` for anything user-visible; branch, PR,
  never commit to `main`.

---

## 10. The ten highest-impact defects, ordered

1. **No toolbar** — the five primary verbs are all two clicks deep in
   `Capture ▸`. `main.py:176-214` builds no toolbar; `main.py:112` claims one.
   *Moderate.*
2. **Cold-start window is inert** — empty grid, "Nothing selected", "no device",
   zero affordances. `main.py:963-991` never runs at rest; `detail_pane.py:122-123`.
   *Trivial–moderate.*
3. **Detail pane is a grey Qt-Designer form** on Window colour under a white
   table, right-aligned `label:` pairs, no emphasis, Message below the fold.
   `detail_pane.py:63-89`, measured `#f3f3f3`. *Moderate.*
4. **Full-saturation `#0067c0` selection** that also destroys severity colour on
   the selected row. `theme.py:83`, `theme.py:101`. *Trivial (colour) / moderate
   (keeping severity legible while selected).*
5. **Two-tone table**: severity paints the whole row and resolves to black,
   grey (= `PlaceholderText`, so Debug reads *disabled*) or a rare red; only
   FAULT has a background. `models.py:487-502`, `theme.py:142-159`. *Moderate.*
6. **No delineation in the table body**: grid off, alternating rows at 1.06:1,
   column separators only in the header, and repeat-blanking leaves a ~468 px
   empty gutter between Time and Message. `log_table.py:175-176`, `theme.py:78-79`,
   `models.py:440-464`. *Trivial–moderate.*
7. **Headers centred over left-aligned data, and shorter (19 px) than a row
   (20 px)**, with the window's only gradient. `log_table.py:111` +
   `QHeaderView` default alignment. *Trivial.*
8. **No icons anywhere** and no window icon — menus, buttons and status bar are
   all bare text. Zero `QIcon` hits in `src/`. *Moderate* (bundled SVG set;
   `PySide6-Essentials` already provides QtSvg).
9. **Banner has one visual register for eight different states**, no icon, no
   colour, instant layout jump, and a no-action banner cannot be dismissed.
   `banner.py:38-60`, `main.py:617-620`. *Trivial–moderate.*
10. **Nothing persists between sessions** — no geometry, no splitter position, no
    column widths, no last filter, no last directory. `QSettings` is named at
    `app.py:26-28` and never constructed. *Trivial–moderate.*

Runners-up worth carrying into the redesign brief: the minimap has no viewport
indicator and sits outside the scrollbar as a 12 px white gutter
(`minimap.py`, measured x 1016–1027); the status bar has no separators, no live
dot and reports the **unfiltered** count (`status_bar.py:51-52`, `main.py:460`);
the filter bar spends horizontal space on four labels the placeholders already
say (`filter_bar.py:44,62`); and the live theme switch never reaches the widgets
(`app.py:56` vs the uncalled `set_scheme` at `models.py:701` and `minimap.py:84`).
