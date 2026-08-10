# ostrace GUI — visual system

Target: a first release that reads as a precise instrument, not a consumer app.
Reference points: Android Studio Logcat (2022 rewrite), Datadog / Grafana log
explorers, Zed and VS Code panels, Proxyman, Linear's density.

Everything here is expressible through `src/ostrace/gui/theme.py`. Nothing
bypasses it, because the WCAG assertions in `tests/test_gui_theme.py` are only
worth anything if every colour on screen came from the module they read.

Numbers marked **(measured)** were taken on this machine — Windows 11,
PySide6 6.11.1, 96 DPI, devicePixelRatio 1.0, application default font
Segoe UI 9.0 pt. Contrast ratios are from the WCAG function `theme.py` already
ships, run over the proposed values (`verify_palette.py`, beside this file).

---

## 0. What changes, structurally

| | 0.1.0 | proposed |
| --- | --- | --- |
| Colour source | `_ROLES`, `_SEVERITY`, `MARK_*` in `theme.py` | same module, one `TOKENS` dict per scheme that `_ROLES`/`_SEVERITY` are *derived from* |
| Stylesheet | none | `theme.stylesheet_for(scheme)` — a `string.Template` over the same tokens |
| Toolbar | none (`gui.md` §1 calls this a gap) | `gui/widgets/toolbar.py`, 12 actions from `shortcuts.BINDINGS` |
| Icons | none | `gui/icons/*.svg` + `gui/icons.py`, recoloured per scheme |
| Table painting | `QStyledItemDelegate` + model `Foreground`/`Background` roles | `RowDelegate` adding a severity rail, a mark bar, and a restrained selection |
| Empty state | nothing (the banner is the only signal) | painted in `LogTable.paintEvent` |

The `LogSource` / model / pump architecture is untouched. This is a skin plus a
toolbar.

---

## 1. Colour system

### 1.1 How it maps onto `theme.py`

`theme.py` currently holds three separate colour tables — `_ROLES`,
`_SEVERITY`, `MARK_TINT`/`MARK_ACCENT`/`_DISABLED_TEXT` — with hex literals in
each. The redesign keeps every one of those structures and their public
functions (`palette_for`, `severity_for`, `mark_tint`, `mark_accent`,
`contrast_ratio`, `apply_theme`) and inserts one table *above* them:

```python
#: The single source of every colour in the program. `_ROLES`, `_SEVERITY` and
#: the mark colours are all views onto this, so a token changed here changes
#: every place it is used and the WCAG suite in `test_gui_theme.py` sees it.
TOKENS: dict[Scheme, dict[str, str]] = {Scheme.LIGHT: {...}, Scheme.DARK: {...}}
```

`_ROLES` then reads `TOKENS[scheme]["surface"]` etc. rather than a literal, and
gains four new module-level accessors for the things `QPalette` has no role
for. That is the whole extension:

```python
def token(name: str, scheme: Scheme) -> QColor      # any token, as a QColor
def selection_tint(scheme: Scheme) -> QColor        # the table row selection
def selection_rail(scheme: Scheme) -> QColor
def marker_style(kind: MarkerKind, scheme: Scheme) -> MarkerStyle
def stylesheet_for(scheme: Scheme) -> str
```

Nothing outside `theme.py` writes a hex value. The contrast tests keep working
unchanged, and three new ones (§1.6) extend them to the surfaces the redesign
adds. `Severity` grows two fields — `rail: QColor | None` and
`weight: QFont.Weight` — because a rail and a bold Level cell are severity
information and belong next to the foreground that CI already checks.

### 1.2 The palette

Two families of neutral: a very slightly cool grey (blue-shifted by ~4°) for
surfaces, so the accent blue does not read as a foreign object, and pure hues
only for severity. No warm greys anywhere — warm grey plus red severity is what
makes an app look like a 2011 admin panel.

| token | light | dark | used for |
| --- | --- | --- | --- |
| `surface` | `#f1f2f4` | `#15171c` | window, toolbar, filter bar, status bar (`QPalette.Window`, `Button`) |
| `surface-raised` | `#ffffff` | `#1b1e24` | table body, inputs, detail pane (`Base`) |
| `surface-alt` | `#f7f8fa` | `#1f232a` | alternating table row (`AlternateBase`) |
| `surface-sunken` | `#e7e9ed` | `#101216` | scrollbar trough, pressed toolbutton, minimap ground |
| `hover` | `#eceff4` | `#23282f` | row hover, toolbutton hover |
| `border` | `#d6d9df` | `#2e333c` | hairlines between regions (`Mid`) |
| `border-strong` | `#b3b8c2` | `#0f1116` | splitter handle, header underline (`Dark`) |
| `control-border` | `#7e8590` | `#6b7381` | input / combo / checkbox outline |
| `text-primary` | `#14161a` | `#e7eaf0` | body text (`Text`, `WindowText`, `ButtonText`) |
| `text-secondary` | `#474e59` | `#b4bbc7` | detail-pane labels, column headers |
| `text-muted` | `#5f6773` | `#99a2b0` | placeholders, status bar, Debug (`PlaceholderText`) |
| `text-disabled` | `#a3a9b4` | `#606874` | disabled group of every text role |
| `accent` | `#1f5fd0` | `#5b9bff` | focus ring, links, checked toolbutton (`Accent`, `Link`) |
| `highlight` | `#1f5fd0` | `#2b62bd` | `QPalette.Highlight` — menus, combo popup, text selection |
| `highlight-text` | `#ffffff` | `#ffffff` | `QPalette.HighlightedText` |
| `selection` | `#dbe6fa` | `#22304a` | **table row selection tint** (not a palette role) |
| `selection-rail` | `#1f5fd0` | `#5b9bff` | 2 px bar at the left edge of the selected row |
| `mark` | `#fff3cf` | `#332a12` | marked-row background (`MARK_TINT`) |
| `mark-accent` | `#7a5400` | `#e0a83c` | mark gutter bar, minimap mark stripe (`MARK_ACCENT`) |
| `gap-band` | `#f9e2de` | `#3a2220` | Gap row fill, and the Fault tint (same value, §1.4) |
| `gap-rail` | `#a5291c` | `#ff8a7a` | Gap row left rail, solid |
| `evict-rail` | `#767e8c` | `#7b8391` | Eviction row left rail, dotted |
| `level-debug` | `#5f6773` | `#99a2b0` | `Level.DEBUG` foreground |
| `level-info` | `#474e59` | `#b4bbc7` | `Level.INFO` |
| `level-notice` | `#14161a` | `#e7eaf0` | `Level.NOTICE` |
| `level-user-action` | `#1f5fd0` | `#5b9bff` | `Level.USER_ACTION` |
| `level-error` | `#b02a1f` | `#ff8a7a` | `Level.ERROR` |
| `level-fault` | `#8c1d18` | `#ffab9d` | `Level.FAULT` |

Six tokens are aliases rather than new colours: `level-debug` = `text-muted`,
`level-info` = `text-secondary`, `level-notice` = `text-primary`,
`level-user-action` = `accent`, and in light `highlight` = `accent`. Keep the
alias explicit in `TOKENS` (repeat the hex) rather than referencing — a level
that later needs to diverge should not have to be untangled first.

### 1.3 Contrast

Every pair WCAG cares about, computed with `theme.contrast_ratio`. AA body is
4.5:1, AA large / UI is 3:1.

**Text on backgrounds — light**

| foreground | on `surface-raised` | on `surface` | on `surface-alt` | on `selection` | on `mark` |
| --- | --- | --- | --- | --- | --- |
| `text-primary` | **18.11** | 16.17 | 17.04 | 14.41 | 16.36 |
| `text-secondary` | **8.39** | 7.49 | 7.90 | 6.68 | 7.58 |
| `text-muted` | **5.72** | 5.10 | 5.38 | 4.55 | 5.16 |
| `level-user-action` | **5.82** | 5.20 | 5.48 | 4.63 | 5.26 |
| `level-error` | **6.57** | — | 6.18 | 5.23 | 5.93 |
| `level-fault` | **9.11** | — | 8.58 | 7.25 | 8.23 |
| `highlight-text` on `highlight` | **5.82** | | | | |

**Text on backgrounds — dark**

| foreground | on `surface-raised` | on `surface` | on `surface-alt` | on `selection` | on `mark` |
| --- | --- | --- | --- | --- | --- |
| `text-primary` | **13.85** | 14.88 | 13.08 | 10.96 | 11.77 |
| `text-secondary` | **8.64** | 9.28 | 8.16 | 6.84 | 7.34 |
| `text-muted` | **6.48** | 6.96 | 6.12 | 5.13 | 5.50 |
| `level-user-action` | **6.02** | 6.47 | 5.69 | 4.77 | 5.12 |
| `level-error` | **7.29** | — | 6.88 | 5.77 | 6.19 |
| `level-fault` | **9.19** | — | 8.68 | 7.27 | 7.81 |
| `highlight-text` on `highlight` | **5.86** | | | | |

The worst cell in the whole matrix is `level-debug` on `selection` in light,
at **4.55:1** — over AA body with 0.05 to spare. `level-notice` on `gap-band`
is 14.63 (light) / 12.19 (dark); `level-fault` on `gap-band` (which is also the
Fault tint) is 7.36 / 8.09.

**Non-text, against the 3:1 floor for control boundaries and meaningful
graphics (WCAG 1.4.11)**

| pair | light | dark |
| --- | --- | --- |
| `control-border` on `surface` | 3.32 | 3.75 |
| `control-border` on `surface-raised` | 3.72 | 3.49 |
| `accent` (focus ring) on `surface-raised` | 5.82 | 6.02 |
| `selection-rail` on `selection` | 4.63 | 4.77 |
| `mark-accent` on `mark` | 6.13 | 6.64 |
| `mark-accent` on `selection` | 5.40 | 6.19 |
| `gap-rail` on `gap-band` | 5.78 | 6.41 |
| `evict-rail` on `surface-raised` | 4.09 | 4.37 |

Below the floor **by design**, because they are decorative separators and not
information: `border` on `surface-raised` 1.41 / 1.32, `surface-alt` on
`surface-raised` 1.06 / 1.06 (the alternating stripe — deliberately near the
perception threshold, as in Logcat), `hover` 1.15 / 1.13, `selection` on
`surface-raised` 1.26 / 1.26, `gap-band` on `surface-raised` 1.24 / 1.14.
`text-disabled` at 2.36 / 2.97 is exempt under WCAG 1.4.3 and only has to be
*dimmer than enabled*, which `test_disabled_text_is_dimmer_than_enabled_text`
already asserts.

### 1.4 Colour blindness

Simulated with the Viénot–Brettel–Mollon 1999 LMS reduction for deuteranopia
(the ~8% case; the code is in `verify_palette.py`).

The finding that matters: **`level-error` and `mark-accent` collapse into each
other.** Light, error `#b02a1f` → `#6a6a0e` and mark `#7a5400` → `#616100`;
linear-RGB distance 14.4 → **2.0**, contrast 1.14:1. Dark is no better
(18.8 → 8.4). Red and amber are the same colour to a deuteranope, and no
choice of red and no choice of amber fixes it. Blue is safe throughout —
`level-user-action` stays 36.5 away from error and 36.5 from the mark.

Rather than abandon amber — chosen because a marked row must not look like a
selected one, which the existing `test_a_mark_cannot_be_mistaken_for_a_selection`
guards — the design puts error and mark on **different channels everywhere they
could be compared**:

1. **In the table.** Severity is a *foreground* colour on text plus a glyph
   (`!` Error, `!!` Fault — already shipped and already tested). A mark is a
   *background tint* plus a 3 px bar in the left gutter. A reader never compares
   two coloured glyphs; they compare "is this text red" with "does this row have
   a bar".
2. **In the minimap** — the one place three severity colours are currently
   painted as three identical stripes and compared purely by hue. Change the
   geometry so position carries the meaning:
   - `Band.MARK` → left 5 px, `mark-accent`
   - `Band.ERROR` → right 5 px, `level-error`
   - `Band.MARKER` → full 12 px, `level-user-action`
   Drawn in that order so a full-width marker overpaints, which is correct: a
   gap outranks an error. This also survives a greyscale print, which the
   current three-colour strip does not.
3. **Level stays text.** `gui.md` §10 is right and nothing here weakens it. The
   Level column reads `Debug` / `Info` / `Notice` / `User Action` / `! Error` /
   `!! Fault`; the six levels are told apart by six different words before any
   colour is involved.

Error vs Fault under deuteranopia are `#6a6a0e` vs `#53530c` — a lightness
difference only. They are separated by the glyph (`!` / `!!`), by the Fault
row's tint, and by Fault's rail; `test_error_and_fault_are_distinguishable_from_each_other`
already asserts the first two.

`gap-rail` vs `evict-rail` under deuteranopia: `#63630c` vs `#7c7c8c`,
distance 16.2, contrast 1.54 — weak, which is exactly why §6.4 gives Gap and
Eviction four non-colour differences.

### 1.5 The selection

The current `Highlight` is `#0067c0` / `#0078d4` painted edge to edge behind the
row, with `HighlightedText` white on top. Two problems: full-saturation fill
across a 1200 px row is the loudest thing on screen and reads as Windows XP; and
because `QCommonStyle` draws item text with `HighlightedText` whenever
`State_Selected` is set, **the selected row loses its severity colour entirely**
— an Error you have clicked on stops looking like an Error.

The redesign splits the two uses that were sharing one role:

- **`QPalette.Highlight` stays a saturated fill** (`#1f5fd0` / `#2b62bd`), because
  it is also the menu highlight, the combo-box popup highlight, and the text
  selection inside a `QLineEdit`, where a solid fill is correct and native.
  `test_selected_rows_stay_legible` keeps testing exactly that, unchanged and
  still meaningful (5.82 / 5.86).
- **The table row selection is its own token**, `selection` /
  `selection-rail`, painted by `RowDelegate`:
  - background `selection` (a 6–8% wash of the accent),
  - a **2 px `selection-rail`** in slot B of the left gutter (§6.3), which is
    what makes a low-contrast wash unmistakable at a glance,
  - the row's own **severity foreground preserved**, by setting *both*
    `QPalette.Text` and `QPalette.HighlightedText` on `option.palette` before
    calling `super().paint()`,
  - `State_HasFocus` cleared, so Fusion does not draw the dotted focus
    rectangle — a dated tell on its own.
  - no border, no gradient, no rounding. A selected row must not change the
    table's rhythm.

Multi-row selection: the rail is drawn on every selected row, and the wash is
identical on all of them.

An inactive window keeps the same tint (do not fall back to grey); Fusion's
`Inactive` group is already set to the same colours by `palette_for`.

### 1.6 What the tests must gain

Three additions, mirroring assertions that already exist so the suite stays
proportional to the design:

| new test | mirrors | asserts |
| --- | --- | --- |
| `test_every_severity_is_legible_on_a_selected_row` | `..._on_a_marked_row` | `contrast(severity.foreground, selection_tint(scheme)) >= 4.5` for all six levels, both schemes. Worst case 4.55. |
| `test_the_marker_rails_survive_greyscale` | `test_the_urgent_levels_carry_a_glyph` | Gap and Eviction differ in **fill**, **line style** and **weight**, not only in hue: `marker_style(GAP).fill is not None and marker_style(EVICTION).fill is None`, `.dashed` differs, `.weight` differs. |
| `test_every_token_is_used_and_defined` | — | `set(TOKENS[LIGHT]) == set(TOKENS[DARK])`, and every `${name}` in the QSS template exists in `TOKENS`. `string.Template.substitute` already raises on a missing one; this catches the reverse, a token nobody uses. |

Not weakened, not deleted: all eleven existing tests in `test_gui_theme.py`
still pass against these values. `test_a_mark_cannot_be_mistaken_for_a_selection`
(`contrast(mark, highlight) > 2.0`) gives 5.26 light and 2.42 dark — the dark
margin is thin and is the reason `mark` dark was set to `#332a12` rather than a
lighter amber.

---

## 2. Typography

### 2.1 Two faces, one rule each

**Table body, and the values in the detail pane: monospace.** Six columns of
similar-looking text, a Time column that must align digit-under-digit, and a
Message column full of identifiers, paths, UUIDs and hex. It is also what makes
`LogTable.apply_column_widths` honest: it sizes columns as
`characters * horizontalAdvance("0")`, which is exact in a monospace face and an
approximation in a proportional one.

**Everything else: the platform's own UI font**, i.e. `QApplication.font()`
untouched. Segoe UI Variable on Windows 11, SF Pro on macOS, whatever Fontconfig
resolves on Linux. Specifying a UI face by name buys nothing and loses native
feel; more practically, it is the only way to avoid an OS branch, which
`CLAUDE.md` forbids outside `compat.py`.

Where a proportional face meets a number — the status bar's `1,204 rec/s`,
`1.2M records`, the detail pane's PID and thread — set
`QFont.setFeature("tnum", 1)` (Qt 6.7+) so figures stop dancing as the counter
ticks. Fall back silently if the face has no `tnum`.

### 2.2 Fallback stacks

Set with `QFont.setFamilies([...])`, which is a Qt-level ordered fallback list
and therefore **not an OS branch** — the same list ships on all three platforms
and Qt picks the first family that exists.

```python
MONO_FAMILIES = (
    "Cascadia Mono",      # Windows 11 (measured: present), and Windows 10 + Terminal
    "SF Mono",            # macOS 11+                       # UNVERIFIED-MACOS
    "Menlo",              # macOS 10.6+, always resolvable  # UNVERIFIED-MACOS
    "JetBrains Mono",     # common on Linux dev machines, not guaranteed
    "DejaVu Sans Mono",   # near-universal on Linux
    "Noto Sans Mono",     # Fedora / GNOME default
    "Liberation Mono",    # RHEL family
    "Consolas",           # every Windows since Vista (measured: present)
    "Courier New",        # last resort that exists everywhere
    "monospace",          # Fontconfig generic
)
```

Degradation is sane at every step: Cascadia → Consolas on older Windows is a
character-width change from 8 px to 7 px at 9.5 pt **(measured)**, which
`apply_column_widths` absorbs because it asks the font rather than assuming.
The `# UNVERIFIED-MACOS` markers are load-bearing — there is no Mac here, and
"SF Mono" was historically not exposed to the font database by family name.
Menlo behind it is the guarantee.

**Nothing is bundled.** Every platform ships an adequate mono. The one case
where bundling earns its keep is the screenshot job: `gui.md` §12 records that
the offscreen plugin's font database is **empty on Windows** (0 families vs 154,
measured) and that `QFontDatabase.addApplicationFont()` fixes it. If that
fallback is ever needed, bundle **JetBrains Mono Regular only** — SIL OFL 1.1,
GPL-compatible, redistributable inside a GPL-3.0-or-later work — at **≈274 KB**
for the single TTF, registered at startup only when
`QFontDatabase.families()` is empty. Not in 0.1.0.

### 2.3 The scale

Absolute point sizes override the platform's own accessibility settings and look
wrong on macOS, where the default UI size is larger. So the scale is
**multiplicative on `QApplication.font().pointSizeF()`**, which is the
platform's answer and requires no branch. Round to the nearest 0.5 pt.

| name | × base | at base 9.0 pt (Windows, measured) | px @96 dpi | used for |
| --- | --- | --- | --- | --- |
| `micro` | 0.85 | 7.5 pt | 10 px | minimap tooltip, badge counts |
| `small` | 0.92 | 8.5 pt | 11 px | column header, status bar, detail-pane labels |
| `body` | 1.00 | 9.0 pt | 12 px | toolbar, filter bar, buttons, menus |
| `mono` | base + 0.5 | 9.5 pt | 13 px | **table body**, detail-pane values |
| `emphasis` | 1.15 | 10.5 pt | 14 px | banner text, empty-state body |
| `title` | 1.30 | 12.0 pt | 16 px | empty-state heading, About |

`mono` is an additive step rather than a multiplier because monospace faces run
small: Cascadia Mono at 9.5 pt has `QFontMetrics.height() == 15 px` against
Segoe UI at 9.0 pt at 16 px **(measured)** — matched optical size, one pixel
tighter line box, which is free density.

Weights: `Normal` (400) everywhere except the column header (`DemiBold`, 600,
paired with `small` and letter-spacing 0.4 px), the Level cell for `ERROR` and
`FAULT` (`DemiBold`), and the Gap row's Level cell (`DemiBold`). Italic is used
in exactly one place — the Eviction row (§6.4) — so it stays a signal.

No letter-spacing anywhere else. No all-caps except the four existing marker
words (`GAP`, `TRIMMED`) and the column headers.

---

## 3. Density and spacing

### 3.1 The scale

Base **4 px**, in *logical* (device-independent) pixels.

`space = 2, 4, 6, 8, 12, 16, 24, 32`

4 px is the right base here rather than 8 because the whole table is built from
one 22 px row: 8 would force either 16 px rows (too tight for a 15 px font box)
or 24 px rows (11% fewer records on screen, which is the metric that matters in
a log viewer). 2 px exists only for rails and hairlines.

### 3.2 Sizes at 100% scaling

All values logical px. Where a value is derived from the font, the derivation is
given, because a hard-coded pixel height is wrong on the first machine with a
different font size.

| element | value | derivation / note |
| --- | --- | --- |
| **table row** | **22** | `max(22, fontMetrics().height() + 7)`. At Cascadia Mono 9.5 pt: 15 + 7 = 22 **(measured)**. `_ROW_PADDING` goes 4 → 7. Set on `verticalHeader().setDefaultSectionSize`, resize mode stays `Fixed`. |
| table cell padding | 8 left / 8 right | first column **12** left, to clear the 6 px gutter |
| **left gutter** | **6** | two slots: **A** at x 0–3 (severity / marker rail), **B** at x 4–6 (state rail: selection or mark). See §6.3. |
| **header** | **26** | `row + 4`. `setFixedHeight` on the horizontal header. |
| header padding | 8 left / 8 right, 0 vertical | 1 px `border` bottom, no side borders, no bevel |
| **toolbar** | **38** | `6 + 26 + 6`. Buttons 26×26, icon 16×16, so 5 px of icon padding. |
| toolbar item spacing | 4 | `QToolBar.setIconSize(QSize(16,16))`, `layout().setSpacing(4)` |
| toolbar separator | 1 px line, 16 tall, 8 px margin each side | |
| **filter bar** | **34** | `5 + 24 + 5` |
| filter field height | 24 | `1 border + 3 pad + 16 text + 3 pad + 1 border` at Segoe UI 9 pt (height 16, measured) |
| filter field min width | 140 (Process, Subsystem), Search stretches | Level combo 168 (fits `User Action and above`) |
| filter label → field gap | 6; group → group gap | 16 |
| **banner** | **34 min**, grows with wrap | `8 + 18 + 8`; 12 px side padding; 3 px left accent bar |
| **detail pane** | row 20, gap 2 → **22 rhythm** | matches the table row, so the eye does not re-tune |
| detail label column | 112 fixed, right-aligned, `small`, `text-secondary` | `QFormLayout.setHorizontalSpacing(12)`, `setVerticalSpacing(2)` |
| detail pane padding | 12 top/bottom, 16 left/right | |
| **status bar** | **24** | `setFixedHeight`; 12 px side padding; items separated by 16 px and a 1 px `border` divider 12 px tall |
| **minimap** | **12 wide** + 1 px `border` on its left | replaces `2.0 * advance("0")` = 16 px at 9.5 pt. Stripe min height stays 2. |
| **scrollbar** | 10 wide, handle 6 with 2 px margins, radius 3, no arrow buttons | `QScrollBar::add-line/sub-line { height: 0 }` |
| **splitter handle** | 4 (hit area 6) | 1 px `border-strong` centre line |
| menu bar | 26, items 8 px side padding | Windows/Linux only; native on macOS |
| window minimum | **1120 × 640** | see §3.3 |
| default window | 1280 × 860 | what the mock renders; Message gets 444 px ≈ 55 characters |

### 3.3 Column widths — the padding has to be added, not absorbed

`LogTable.apply_column_widths` currently sets
`spec.characters * horizontalAdvance("0")`. That is a *text* budget, and it is
being spent on chrome: at 8 px per character the Time column gets 104 px, the
cell padding takes 16 of them, and `09:14:02.118` — exactly the 12 characters
the column was sized for — elides to `09:14:02.1…`. Caught by building the
mock; it is wrong in 0.1.0 too, just less visibly at 4 px of padding.

```python
width = spec.characters * unit + _CELL_PADDING * 2 + (_GUTTER if first else 0)
```

| column | chars | text px | padding | width |
| --- | --- | --- | --- | --- |
| Time | 13 | 104 | 12 + 8 | **124** |
| Level | 12 | 96 | 8 + 8 | **112** |
| Process | 22 | 176 | 8 + 8 | **192** |
| Subsystem | 26 | 208 | 8 + 8 | **224** |
| Category | 18 | 144 | 8 + 8 | **160** |
| | | | fixed total | **812** |

Plus the scrollbar (10) and the minimap (12): 834 px of the window is spoken
for before Message gets anything. Wanting ≥ 280 px (≈ 35 characters) for
Message puts the minimum window at **1120** wide. At the 1280 default, Message
gets 444 px ≈ 55 characters.

### 3.4 HiDPI

Every number above is logical. Qt 6 scales at paint time; on Windows the ratio
is fractional (1.25 / 1.5 / 1.75), on macOS it is an integer and High DPI cannot
be turned off. Consequences, in the order they bite:

1. **Never hard-code a pixel height that a font determines.** Row, header,
   field and banner heights are derived from `QFontMetrics` above; the constants
   are floors, not values.
2. **1 px lines drawn in a delegate use a cosmetic pen** —
   `QPen(colour, 0)` — which is exactly one *device* pixel at any ratio.
   `QPen(colour, 1)` becomes 1.5 device px at 1.5× and antialiases into a blur.
3. **Rails are 2-3 px logical, never 1.** A 1 px rail disappears at 1.0× against a
   1.26:1 wash and shimmers at 1.5×.
4. **QSS `px` values are logical** and Qt rounds them per widget. Keep radii at
   4 and borders at 1; 3 px radii round inconsistently at 1.25×.
5. **Icons ship as SVG**, so there is no `@2x` problem. `QIcon.pixmap()` is
   asked for the logical size and Qt renders at the device ratio (verified:
   `QIcon(svg).pixmap(16, 16)` returns a valid pixmap, and the SVG image plugin
   is present in PySide6-Essentials 6.11.1 — measured).
6. **Do not assert a font metric under the offscreen plugin.** Already a rule in
   `gui.md` §12; every number in §3.2 is off-limits to the offscreen lane.

---

## 4. Iconography

### 4.1 Decision

**Bundle Lucide SVGs (ISC), recoloured at runtime from `TOKENS`.**

| option | verdict |
| --- | --- |
| `QStyle.StandardPixmap` | **Rejected.** Free and dependency-free, but Fusion synthesises its own pixmaps and they look like 2005 — and the fatal one: they arrive as pixmaps, not masks, so they **cannot be recoloured with the theme**. A dark scheme would show light-scheme arrows. There is also no standard pixmap for capture, mark, subsystem or "next error"; roughly five of the fifteen icons needed exist at all. |
| Draw in `QPainter` | **Rejected as the general answer.** Recolours perfectly and costs zero bytes, but fifteen hand-built `QPainterPath`s is a lot of code whose only test is a human looking at it. **Kept for the four things that are genuinely shapes rather than icons**: the severity rail, the mark bar, the minimap stripes, and the marker rules — all already painted in code. |
| Bundled SVG | **Chosen.** Renders at any DPR, is one file per icon, and recolours by substituting one attribute. |

Lucide over Feather (Lucide is the maintained fork, 1.5 px stroke on a 24 grid,
which is the Zed/Linear/Proxyman visual register) and over Material Symbols
(Apache-2.0 and fine legally, but filled 24 dp glyphs read consumer, and the
files are 2–3× larger). ISC is GPL-3.0-or-later compatible; add
`LICENSES/ISC-lucide.txt` and a line in the README's third-party notices.

**Byte cost:** a Lucide-style stroke icon measured at **209 bytes** for `play`
on this machine; the set averages 350–600 B. **Fifteen icons ≈ 7 KB**
uncompressed, ≈ 3 KB in the wheel. Negligible next to PySide6-Essentials.
Hatchling already ships everything under `src/ostrace/`, so no packaging change
is needed.

### 4.2 How they recolour

This is the part that rules approaches out, and it splits in two.

**Icons used from Python** (every `QAction`, every `QPushButton`) —
`gui/icons.py`:

```python
def icon(name: str, scheme: Scheme, *, role: str = "text-secondary") -> QIcon
```

Reads the master SVG once with
`importlib.resources.files("ostrace.gui.icons").joinpath(f"{name}.svg").read_text()`,
replaces the single literal `currentColor` with `TOKENS[scheme][role]`, renders
through `QSvgRenderer` into a `QPixmap`, and caches on `(name, scheme, role,
devicePixelRatio)`. Three modes are registered per `QIcon`:
`Normal` = `text-secondary`, `Active`/`Selected` = `text-primary`,
`Disabled` = `text-disabled`. A `On` state in `accent` is added for the two
checkable actions (Pause, and the theme toggle if it ships).

Reading a file out of the installed package is **not** a `paths.py` decision —
`paths.py` owns where *the user's* files go; this is package-internal resource
lookup and must use `importlib.resources`, never a path built from `__file__`.

**Icons referenced from QSS** cannot use any of that: `image: url(...)` takes a
*file path*, and there is no way to hand it a runtime-tinted `QIcon`. Only three
are needed — `chevron-down` (combo arrow), `check` (checkbox tick), `minus`
(tristate) — so ship those **pre-tinted, one copy per scheme**, in
`icons/light/` and `icons/dark/`, and substitute the absolute path into the
stylesheet template as `${icon_chevron_down}`. Six extra files, ≈ 3 KB. On
Windows the path must be written with forward slashes and no drive-letter
escaping problems: `str(path).replace("\\", "/")`.

A `tools/build_icons.py` regenerates those six from `TOKENS`, and a test asserts
the shipped file's `stroke=` matches the token — otherwise the two colour
systems drift and only a screenshot would ever notice.

### 4.3 The icons

Toolbar, left to right, in three groups plus a right-aligned pair. Every one is
an existing `shortcuts.BINDINGS` entry, so the toolbar is generated from the
same table as the menus and the `F1` sheet — `gui.md` §8's anti-drift rule
applies to a third consumer for free.

| # | Lucide name | action | notes |
| --- | --- | --- | --- |
| 1 | `play` | Capture | disabled while capturing |
| 2 | `pause` | Pause | checkable; `On` state in `accent` |
| 3 | `unplug` | Disconnect | the destructive verb, named after its consequence |
| — | separator | | |
| 4 | `folder-open` | Open capture… | |
| 5 | `download` | Export… | |
| — | separator | | |
| 6 | `search` | Find | focuses the search field |
| 7 | `bookmark` | Toggle mark | |
| 8 | `bookmark-x` | Clear marks | |
| — | separator | | |
| 9 | `triangle-alert` + `chevron-up` | Previous error | two 16 px glyphs in one 34 px button, alert left, chevron right |
| 10 | `triangle-alert` + `chevron-down` | Next error | |
| 11 | `chevrons-up` | Top | |
| 12 | `chevrons-down` | Bottom / resume following | |
| — | stretch | | |
| 13 | `keyboard` | Keyboard shortcuts (F1) | right-aligned |
| 14 | `contrast` | Theme override | **aspirational** — 0.1.0 follows the OS only; ship the icon when the override does |

Elsewhere:

| icon | where |
| --- | --- |
| `chevron-down` | `QComboBox::down-arrow` (QSS, pre-tinted) |
| `check`, `minus` | `QCheckBox::indicator:checked` / `:indeterminate` (QSS, pre-tinted) |
| `x` | banner dismiss; `QLineEdit` clear button — note Qt takes that one from `QStyle.StandardPixmap.SP_LineEditClearButton` and QSS cannot reach it. Either accept Fusion's, or replace it by turning off `setClearButtonEnabled` and adding a `QAction` with our own icon at `TrailingPosition`. The second is three lines and worth it, because Fusion's clear button is the single most visibly dated widget in the filter bar. |
| `file-search` | empty state, 32 px, `text-disabled` |
| `circle-off` | "no device" empty state, 32 px |

`QToolButton` labels: `ToolButtonIconOnly` with the binding's `description` as
the tooltip, except Capture / Pause / Disconnect, which get
`ToolButtonTextBesideIcon` — the three verbs a first-time user must not have to
hover to find. That also means the toolbar is not a row of anonymous glyphs,
which is the usual failure of this pattern.

---

## 5. QSS and `QPalette`

### 5.1 The split

The rule: **`QPalette` owns anything a style or a delegate draws; QSS owns
chrome that neither of them draws well.** They interact badly because
`QStyleSheetStyle` wraps the real style and, for any widget with a matching
rule, takes over drawing — including the parts you did not style.

**`QPalette` (built by `palette_for`, all three colour groups, every role
explicit — as today):**

| role | token |
| --- | --- |
| `Window`, `Button` | `surface` |
| `WindowText`, `ButtonText`, `Text` | `text-primary` |
| `Base` | `surface-raised` |
| `AlternateBase` | `surface-alt` |
| `PlaceholderText` | `text-muted` |
| `Highlight` / `HighlightedText` | `highlight` / `highlight-text` |
| `Accent` (Qt 6.6+) | `accent` |
| `Link`, `LinkVisited` | `accent` |
| `ToolTipBase` / `ToolTipText` | `surface-raised` / `text-primary` |
| `Mid` | `border` |
| `Dark` | `border-strong` |
| `Light`, `Midlight` | `hover`, `surface-alt` |
| `Shadow` | `border-strong` |
| `BrightText` | `#ffffff` / `#ffffff` |
| `Disabled` group of `Text`/`WindowText`/`ButtonText`/`HighlightedText` | `text-disabled` |

Why the palette and not QSS: `QTableView`'s alternating rows come from
`AlternateBase` through `QCommonStyle`, and `QStyledItemDelegate` reads
`option.palette` — so **every colour the table body shows must be reachable from
the palette or from an explicit token handed to the delegate**. Native things
Qt draws itself (menus, tooltips, the file dialog, `QMessageBox`) also read only
the palette; QSS would leave them looking unthemed.

**QSS (`theme.stylesheet_for(scheme)`, applied with `app.setStyleSheet`):**

Styled: `QToolBar`, `QToolButton`, `QLineEdit`, `QComboBox` (+ `::drop-down`,
`::down-arrow`), `QCheckBox::indicator`, `QPushButton`,
`QHeaderView::section`, `QScrollBar:vertical/horizontal` and its sub-controls,
`QSplitter::handle`, `QStatusBar` and `QStatusBar::item`, `QMenuBar` /
`QMenu` / `QMenu::item` / `QMenu::separator`, `QToolTip`, `Banner` (via
`setObjectName("banner")` and a `#banner` selector, plus a `severity` dynamic
property so one rule set covers info/warning/error banners), `QFrame#detailPane`,
`QTableView` — **frame only**: `border`, `border-top`, `background`.

**Never styled, and this is the load-bearing prohibition:**

```
QTableView::item                 /* any state */
QTableView { selection-background-color: ...; alternate-background-color: ... }
```

Setting any of those switches the item view onto the stylesheet drawing path.
`QStyleSheetStyle` then resolves item colours from the rule instead of from
`option.palette`, which silently discards the delegate's per-row
`Text`/`HighlightedText` brushes — the severity colours vanish on selection and
nothing in the code looks wrong. Same reason `QHeaderView::section` is safe
(the header has no delegate) and `QTableView::item` is not.

Two smaller traps worth writing down:

- `QStatusBar::item { border: 0 }` is required, or Qt draws a sunken frame
  around every permanent widget — the single most obviously old thing in the
  current window.
- `QToolButton { border: none }` is required, or Fusion keeps the bevel and the
  hover state fights the QSS background.
- On macOS the menu bar is native and `QMenuBar` rules do nothing.
  `# UNVERIFIED-MACOS`.

### 5.2 Building the stylesheet

One template, one substitution pass, per scheme, at theme-apply time:

```python
_QSS = Template("""
QToolBar { background: ${surface}; border: 0; border-bottom: 1px solid ${border};
           padding: ${space_6}px ${space_8}px; spacing: ${space_4}px; }
QToolButton { border: none; border-radius: 4px; padding: 5px;
              color: ${text_secondary}; }
QToolButton:hover   { background: ${hover}; }
QToolButton:pressed { background: ${surface_sunken}; }
QToolButton:checked { background: ${selection}; color: ${accent}; }
QToolButton:disabled{ color: ${text_disabled}; }
...
""")

def stylesheet_for(scheme: Scheme) -> str:
    return _QSS.substitute(_qss_values(scheme))
```

`string.Template`, **not** an f-string and **not** `str.format`: QSS is made of
`{ }` and both of those would need every brace doubled, which is how a
stylesheet ends up with one unescaped brace and silently stops applying from
that point on (Qt logs nothing). `Template.substitute` also raises `KeyError` on
a token that does not exist, so a typo fails at import in the test suite rather
than rendering a colourless window.

Token names are `str`-safe: `_qss_values` maps `surface-raised` →
`surface_raised` and adds the spacing scale as `space_4` … `space_32` and the
three icon paths. Keep hyphenated names in `TOKENS` (they read better in the
design table) and mangle once, at the boundary.

### 5.3 How the table body actually gets its colours

Not from QSS, and only partly from the palette:

1. **`RecordModel.data()`** answers `ForegroundRole` and `BackgroundRole` from
   the cached `Severity` objects (unchanged mechanism, new colours). The
   `_ANSWERED_ROLES` fast path stays.
2. **`RowDelegate.initStyleOption`** — runs per cell — sets, on
   `option.palette`:
   - `Text` ← severity foreground (Qt already does this from `ForegroundRole`),
   - `HighlightedText` ← **the same severity foreground**, which is the fix for
     "a selected Error stops looking like an Error",
   - `Highlight` ← `selection_tint(scheme)`.
   Then clears `State_HasFocus`.
3. **`RowDelegate.paint`** draws, before `super().paint()`: the row fill for
   marker rows, and after it: the left rail (severity / selection / mark) with a
   cosmetic pen. Column 0 only — the rail is one draw per row, not six.
4. **Alternating rows** come from `AlternateBase` in the palette. Note the
   ordering already in the code: a `BackgroundRole` returned by the model
   overrides alternation, which is why only Fault, marks and markers return one.
5. **Prebuild every brush.** `_rebuild_severity` already does it; the rails and
   marker styles join it. `paint()` must never construct a `QColor`.

### 5.4 Runtime switching

```python
def apply_theme(app: QApplication, scheme: Scheme) -> None:
    app.setStyle(STYLE)                       # first — a style change resets the palette
    app.setPalette(palette_for(scheme))
    app.setStyleSheet(stylesheet_for(scheme))  # last — re-polishes every widget
```

`setStyleSheet` re-polishes automatically. What it does **not** do is reach the
objects that cached `QColor`s, so the window needs one fan-out:

```python
class MainWindow:
    def set_scheme(self, scheme: Scheme) -> None:
        self.scheme = scheme
        self.model.set_scheme(scheme)
        self.minimap.set_scheme(scheme)
        self.table.set_scheme(scheme)      # -> RowDelegate
        self.toolbar.set_scheme(scheme)    # -> rebuilds every QIcon
        self.detail.set_scheme(scheme)
```

**Existing bug worth fixing in the same change.** `gui/app.py` line 56 wires
`colorSchemeChanged` to `apply_theme` alone:

```python
hints.colorSchemeChanged.connect(lambda _scheme: apply_theme(app, resolve_scheme(hints)))
```

`RecordModel.set_scheme` and `Minimap.set_scheme` exist and are never called
from there — grep finds callers only in tests. So on a live OS theme switch
today the palette flips and **every severity colour and every minimap stripe
stays in the old scheme**: light-scheme reds on a dark table. The redesign makes
this much more visible (more colours come from `TOKENS`), so the connection must
become `lambda: window.set_scheme(resolve_scheme(hints))` with `apply_theme`
called inside it.

This is also the one behaviour CI cannot verify — `setColorScheme()` is a no-op
under the offscreen plugin (`gui.md` §10) — so it needs a test that calls
`window.set_scheme` directly and asserts the model's and minimap's schemes
followed, which *is* verifiable offscreen.

---

## 6. Component specs

Colours are token names. States are `default / hover / pressed / checked /
focused / disabled`.

### 6.1 Toolbar

Height 38. `background: surface`, `border-bottom: 1px solid border`, no
gradient, no bevel, not floatable, not movable
(`setFloatable(False)`, `setMovable(False)` — a toolbar the user can accidentally
tear off is a support question).

| state | appearance |
| --- | --- |
| default | icon `text-secondary`, no background, no border, radius 4 |
| hover | background `hover`, icon `text-primary` |
| pressed | background `surface-sunken` |
| checked (Pause) | background `selection`, icon `accent`, and a 2 px `accent` bar along the button's bottom edge |
| focused (keyboard) | 1 px `accent` outline inset 1 px — never the platform focus rect |
| disabled | icon `text-disabled`, no hover response |

The three text-beside-icon buttons get 8 px right padding and `body` size.
Separator: 1 px `border`, 16 px tall, centred, 8 px margins.

### 6.2 Filter bar

Height 34, `background: surface`, `border-bottom: 1px solid border`. Contents:
`Level ▾ | Process [ ] | Subsystem [ ] | Search [ ] | ☐ Regex`.

Labels `small` / `text-muted`, 6 px before their field, 16 px between groups.

`QLineEdit` / `QComboBox`: height 24, `background: surface-raised`,
`1px solid control-border`, radius 4, padding `0 8px`, `body` size, placeholder
`text-muted`.

| state | appearance |
| --- | --- |
| hover | border `text-muted` |
| focused | border `accent` **and** a second inset 1 px `accent` ring at 40% — Qt has no `box-shadow`, so a focus ring is drawn as two borders (outer on the widget, inner via `padding` reduction) or accepted as a single 2 px border. Prefer the single 2 px `accent` border with `padding` reduced by 1 px so the field does not resize on focus. |
| invalid regex | border `level-error`, and the banner carries the message (already implemented) — the field never shows a tooltip alone |
| disabled | background `surface`, text `text-disabled` |

`QCheckBox::indicator`: 14×14, radius 3, `1px solid control-border`;
checked = fill `accent`, tick `check` icon in white; focused = 2 px `accent`.

The Search field stretches; Process and Subsystem are 140 min. The Level combo
is 168 wide so `User Action and above` does not elide.

### 6.3 Table

**Header.** Height 26, `background: surface`, `border-bottom: 1px solid border`,
no side borders, no bevel, no sort indicator (nothing is sortable — a log is in
arrival order and always will be). Text `small` / `DemiBold` /
`text-secondary`, letter-spacing 0.4 px, left-aligned, 8 px padding. Section
resize handles keep Qt's default cursor; hovering a divider shows a 1 px
`accent` line. `FastHeader` is unchanged — it suppresses `State_Sunken` and
`State_On`, which the QSS above also never styles, so the two agree.

**Row.** Height 22. Text `mono`. Cells 8 px padded, no grid
(`setShowGrid(False)`, already). Alternating rows `surface-raised` /
`surface-alt` (1.06:1 — visible as texture, invisible as stripes).

**The left gutter has two slots.** This came out of building the mock: a single
rail cannot carry both "this row is an Error" and "this row is selected", and
the version where selection overwrote the severity rail lost exactly the
information the user was looking at — the same failure as `HighlightedText`
overwriting the severity foreground.

```
 x:  0   3 4   6              12
     │AAA│ │BB│               │  Time   │  Level  │ …
     slot A  slot B           cell text starts here
```

- **Slot A**, 3 px at x = 0: *what this row is.* `level-error`, `level-fault`,
  `gap-rail` (solid) or `evict-rail` (dotted). Absent for
  Debug / Info / Notice / User Action, so a screen of Notice rows has a clean
  left edge and an error is findable by peripheral vision.
- **Slot B**, 2 px at x = 4: *what the user has done to this row.*
  `selection-rail` when selected, `mark-accent` when marked.

| state | appearance |
| --- | --- |
| default | background per alternation, foreground `level-*`, both slots empty |
| hover | background `hover`; **the whole row**, so set `QTableView` mouse tracking on and repaint the row in the delegate — Qt's `State_MouseOver` is per cell |
| selected | `selection` fill, slot B = `selection-rail`, severity foreground preserved, slot A untouched, no focus rect |
| marked | `mark` fill, slot B = `mark-accent` |
| marked **and** selected | fill is `selection`, slot B stays `mark-accent`. The caret must always be findable, and the mark survives because `mark-accent` on `selection` is 5.40:1 light / 6.19:1 dark. This does **not** contradict the model's "marks outrank every colour rule" — that rule is about the *severity* tint, which the model resolves in `_background`; selection is the delegate's and is resolved afterwards. |
| Fault | `gap-band` fill (the same tint as a Gap row, which is right: a Fault *is* the severe case), foreground `level-fault`, slot A = `level-fault`, Level cell `!! Fault` in `DemiBold` |
| Error | no fill; foreground `level-error`; slot A = `level-error`; Level cell `! Error` in `DemiBold` |

**The level indicator.** Text, always, in the Level column — `gui.md` §10 and
not up for renegotiation. Slot A is *reinforcement* of the same fact, never a
substitute for it.

**Repeat collapsing** (already implemented) is a reading aid, and it now needs a
visual so it does not read as missing data: a blanked repeat cell draws a 1 px
`border` dash, 8 px wide, vertically centred, at the cell's left padding.
Optional, and cheap in the delegate.

### 6.4 Gap and Eviction — the two that must not look alike

A **Gap** means records are gone forever. An **Eviction** means records are on
disk and merely not on screen. They are opposite facts, and `gui.md` §3 makes
that an invariant. Four independent differences, **none of which is hue**, so
the distinction survives a greyscale print and deuteranopia (§1.4 shows the two
rails are only 1.54:1 apart once simulated):

| | Gap | Eviction |
| --- | --- | --- |
| **fill** | `gap-band` across the full row — the row is visibly *heavier* than its neighbours | none; `surface-raised`, same as any row |
| **rail** (slot A) | 3 px **solid**, `gap-rail`, full row height | 3 px **dotted** (2 on / 2 off), `evict-rail` |
| **borders** | 1 px solid `gap-rail` at 30% along the top *and* bottom edge — the row is a closed band | 1 px **dotted** `border` along the top edge only — the row is an open annotation |
| **Level cell** | `GAP`, `DemiBold`, upright | `TRIMMED`, regular, **italic** |
| **Message** | `gap_line(...)` from `exporters.plaintext` — unchanged, the exporter owns the spelling | `Eviction.text` — *"… earlier records are in the capture but not in this view"* |
| **foreground** | `level-notice` (`MARKER_LEVEL` is `NOTICE`, unchanged) | `text-muted` |
| **row height** | 22, same as any row | 22 |

Weight, line style, slant and fill are four channels that a black-and-white
printer and a monochromat both keep. In greyscale a Gap is a filled band with a
solid bar; an Eviction is an unfilled row with a dotted bar in italic. Nobody
confuses them.

Do **not** use `QTableView.setSpan` to merge the marker row's cells. It is
O(spans) on every layout and has to be re-applied after every `beginResetModel`
— a filter change would silently unmerge every marker. The Message column
already carries the full text and the Time column beside it is wanted.

Both kinds expose themselves to the delegate through one new role,
`MarkerRole = Qt.ItemDataRole.UserRole + 1`, returning a `MarkerKind` or
`None`. `isinstance` checks belong in the model, which already has them; the
delegate stays model-agnostic. Add `MarkerRole` to `_ANSWERED_ROLES`.

### 6.5 Detail pane

`background: surface-raised`, `border-top: 1px solid border`. 12 px vertical /
16 px horizontal padding. Two columns: label 112 px, right-aligned, `small`,
`text-secondary`, no trailing colon in the widget (add it in the layout as
today); value `mono`, `text-primary`, selectable, wrapping.

Row rhythm 22 (20 + 2), matching the table so the two panes share a grid.

Values that are absent read `-` in `text-disabled` (the `ABSENT` constant is the
exporters' spelling and does not change). `Message` gets the remaining height
and its own 1 px `border` top rule 8 px above it, because it is the field people
actually read.

For a Gap the pane is unchanged in structure and gains a 3 px `gap-rail` bar
down its left edge; for an Eviction, a 3 px dotted `evict-rail` — the same two
signatures as the row, so the pane confirms rather than re-explains.

Empty state (`clear()`): the existing two-field form is replaced by a centred
`file-search` icon at 32 px in `text-disabled`, `Nothing selected` in `title` /
`text-secondary`, and one `emphasis` / `text-muted` line.

### 6.6 Status bar

Height 24, `background: surface`, `border-top: 1px solid border`,
`QStatusBar::item { border: 0 }`. `small`, `text-muted`, with the *numbers* in
`text-primary` — a two-tone readout is what makes a status bar scannable and
costs one rich-text label each.

Four permanent readouts, right-aligned, 16 px apart with a 1 px `border` divider
12 px tall between them, and 12 px from the window edge (the existing 8 px right
margin exists because "0 gaps" lost its last character; 12 keeps that fix):

`● 1,204 rec/s` · `iPhone · iOS 26.5.2` · `1.2M records · 84.1 MB` · `0 gaps`

- The `●` is 6 px, `accent` while streaming, `text-disabled` when idle. It is
  the only place in the window with a coloured dot, so it means exactly one
  thing. No pulsing — Qt would need a `QTimer` repaint and it would be the only
  animation in the program.
- The gap count is rendered always, including zero (Wireshark 12005 — unchanged
  rule), and turns `level-error` when non-zero. Colour is reinforcement; the
  number is the information.

### 6.7 Banner

Full width, between the filter bar and the splitter (unchanged position). Min
height 34, 8 px vertical / 12 px horizontal padding, `emphasis` text, word wrap
on, no icon (the accent bar carries the severity), 3 px accent bar down the left
edge, `border-bottom: 1px solid border`, radius 0 — a full-bleed strip, not a
floating card.

A `severity` dynamic property drives one QSS rule set:

| severity | fill | bar | used by |
| --- | --- | --- | --- |
| `info` | `selection` | `accent` | paused, filter hides everything, empty capture |
| `warning` | `mark` | `mark-accent` | paused queue overflowed, truncated capture, thread would not release the device |
| `error` | `gap-band` | `gap-rail` | capture stopped, no device, capture could not be opened |

The action button is a `QPushButton` styled flat: `body`, `accent` text, no
border, 6 px padding, radius 4; hover `hover`; pressed `surface-sunken`. It sits
right, 12 px from the edge, with an `x` icon-only dismiss button after it when
the banner has no recovery action (today those show a `Dismiss` text button —
either is fine, but not both).

### 6.8 Empty state

`QTableView` has no placeholder, so `LogTable.paintEvent` calls
`super().paintEvent(event)` and then, when `model().rowCount() == 0`, paints
into `self.viewport()` a centred block: 32 px icon in `text-disabled`, 12 px
gap, `title` / `text-secondary` heading, 6 px gap, one `emphasis` /
`text-muted` line, max width 420 px, wrapped.

| situation | heading | line |
| --- | --- | --- |
| nothing opened yet | `No capture open` | `Press Capture to record from a connected device, or open a saved capture.` |
| filter hides everything | `No rows match the filter` | `All N records are hidden. Clear the filter to see them.` — the banner keeps the button |
| capture is empty | `This capture contains no records` | `The session file is valid and holds nothing.` |
| device attached, nothing yet | `Waiting for the device` | `The capture is running. A quiet device can stay silent for tens of seconds.` |

The last one matters and is not in `gui.md`'s banner table: `stream()` can block
indefinitely without yielding, so "connected and silent" and "broken" produce
the same empty table.

---

## 7. Order of work

1. `TOKENS` + `stylesheet_for` in `theme.py`; `palette_for` reads tokens. New
   contrast tests. Nothing on screen changes shape yet.
2. `gui/icons.py` + the SVG set + the licence file.
3. `gui/widgets/toolbar.py`, generated from `shortcuts.BINDINGS`.
4. `RowDelegate` — selection, rails, marks, marker rows. `MarkerRole` in the
   model.
5. Density constants: `_ROW_PADDING`, header/toolbar/filter/status heights,
   minimap width and stripe geometry.
6. `MainWindow.set_scheme` fan-out and the `app.py` `colorSchemeChanged` fix.
7. Empty state.
8. Re-run the screenshot job in both schemes on all three platforms; that is the
   only look at macOS this design will get.
