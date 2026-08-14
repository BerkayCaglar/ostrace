# ostrace GUI redesign — interaction model and information architecture

Scope: what is on screen, where, and what happens when the user acts. Colour and
typography are somebody else's file. Nothing in this document modifies the repo.

Read against: `docs/design/gui.md` (the behaviour contract), `CLAUDE.md` (the
hard rules), all of `src/ostrace/gui/`, `src/ostrace/cli.py`,
`src/ostrace/exporters/`, `src/ostrace/devices/`, `src/ostrace/paths.py`,
`tests/test_gui_*.py`.

Two conventions used throughout:

- **Every claim about the current code carries a `file:line`.** Where I could
  not verify something on this machine (PySide6 is not installed in the
  interpreter on `PATH` here), it is marked **`[verify]`** with the probe to run.
- Every proposal is tagged **MUST**, **NICE** (if cheap) or **LATER**, and the
  tags are collected in §10.

---

## 0. What is actually wrong today

Not "it looks dated". Three concrete things, in the order they cost a user time:

1. **The main verbs are two clicks deep and the program's central object — the
   device — has no representation at all.** `MainWindow.capture_from_device`
   (`windows/main.py:485`) constructs `OsTraceSource()` with no udid
   (`windows/main.py:508-510`), so the viewer silently captures from whatever
   `require_device` picks first (`devices/discovery.py:163-165`). With two
   phones plugged in, the GUI gives the user no way to know which one it chose,
   let alone to choose. The CLI has `--udid` (`cli.py:49`).
2. **`doctor` does not exist in the GUI.** `devices/doctor.py` produces a
   structured `Report` of `Check(name, status, detail, hint)` covering the exact
   failures this domain actually has — no usbmux, no device, network-only,
   untrusted, clock skew. The GUI's answer to all of them is one banner carrying
   `str(exc)` plus `exc.hint` (`windows/main.py:496-497`). The best diagnostic in
   the project is unreachable from the program most people will run.
3. **Several states are invisible or stale.** §6 of the design doc lists the
   reconnect banner as unbuilt, and it still is. On top of that I found a live
   staleness bug in the filter banner — see §4.5.

Plus two defects worth fixing on their own merits, found while reading:

- **The export dialog does not call `paths.check_export_destination`.** The CLI
  does (`cli.py:295`). See §6.1 — this can still destroy a capture.
- **`Filter.is_empty` (`gui/filters.py:62`) and `FilterBar.is_empty`
  (`widgets/filter_bar.py:88`) are never consulted by the window**, and neither
  is `RecordModel.hidden_by_filter` (`gui/models.py:737`). They were written for
  a "your filter is hiding things" indicator that was never built. §4.4 builds it.

---

## 1. The window, top to bottom

### 1.1 The layout

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ Capture   Edit   View   Help                                       menu bar   │
├───────────────────────────────────────────────────────────────────────────────┤
│ [📱 My iPhone ▾] [● Capture] [⏸ Pause] │ [📂] [⤴] │ [◂!][!▸] [◂⋯][⋯▸]   │
│                                                        …spacer…  [▾ 12,480 new]│
├───────────────────────────────────────────────────────────────────────────────┤
│ Level [Error and above ▾]  Process [ ≠ ]  Subsystem [ ≠ ]  Search [ .* ]       │
│                                       [Saved ▾]  4,912 of 200,000 shown  ✕     │
├───────────────────────────────────────────────────────────────────────────────┤
│ ⚠ Device disconnected — reconnecting (4 of 30).      [Disconnect] [Diagnose…]  │
├──────────┬───────┬──────────┬────────────┬──────────┬─────────────────────┬───┤
│ Time     │ Level │ Process  │ Subsystem  │ Category │ Message             │ ▌ │
├──────────┼───────┼──────────┼────────────┼──────────┼─────────────────────┤ ▌ │
│ 01:10:31 │ ✕ ERR │ dasd[83] │ com.apple… │ default  │ Unable to dere…     │▐█▌│
│ …                                                                          ▌ │
├──────────┴───────┴──────────┴────────────┴──────────┴─────────────────────┴───┤
│ detail pane — every field of the selected record                              │
├───────────────────────────────────────────────────────────────────────────────┤
│ ● 1,204 rec/s │ My iPhone (iPhone18,2, iOS 26.5.2) │ 1.2M rec · 84 MB │ 0 gaps │
└───────────────────────────────────────────────────────────────────────────────┘
```

Structurally this is today's `_build_layout` (`windows/main.py:176-214`) with one
row inserted: `QVBoxLayout` → **toolbar** → filter bar → banner → splitter
(table+minimap / detail) → status bar. The banner stays *below* the filter bar
and *above* the split, which is right: it is a notice about the content, and the
filter bar is a control that can cause the notice.

### 1.2 The toolbar — every control, in order

`QToolBar`, `setMovable(False)`, `setFloatable(False)`, added with
`addToolBar(Qt.ToolBarArea.TopToolBarArea)`. `QToolBar` is not hidden by macOS's
menu-bar relocation, so this row exists identically on all three platforms.

| # | Control | Widget | Icon | Label | Why here |
|---|---|---|---|---|---|
| 1 | **Device selector** | `QToolButton`, `InstantPopup` | phone outline + caret | **yes** — the device's `DeviceInfo.name`, or `No device` | The one piece of state every capture depends on, and today the only place it appears is a status-bar readout that is written *after* the capture has already started (`windows/main.py:648-650`). It goes first because it is the subject, and a subject belongs left of its verbs. |
| 2 | **Capture ⇄ Disconnect** | `QToolButton` whose `defaultAction` swaps | filled dot ● / eject ⏏ | **yes** | The primary verb. One button rather than two because `_set_capturing` (`windows/main.py:640-646`) already makes them mutually exclusive — two buttons of which one is always dead is two buttons of noise. Swapping is what every live tool does. The *word* changes with the state, which is the affordance. |
| 3 | **Pause** | `QToolButton`, checkable | two bars ‖ | **yes** | Kept visually and semantically separate from Disconnect, per §7 of the contract and `windows/main.py:9-22`. Its checked state is the persistent "you are paused" cue the banner cannot be, because the banner is dismissible. |
| — | separator | | | | Divides live-capture verbs from file verbs. |
| 4 | **Open capture…** | `QToolButton` | folder | no (tooltip `Open capture… (Ctrl+O)`) | Frequent, but never urgent, and its name is long. |
| 5 | **Export…** | `QToolButton` | box with out-arrow | no | Same. Disabled with an explanatory tooltip when `self.capture is None`, instead of today's "press it and read a banner" (`windows/main.py:735-759`). The banner path stays for the keyboard. |
| — | separator | | | | |
| 6 | **Previous error / Next error** | two `QToolButton`s | chevron up/down with a severity dot | no | The most-used navigation in a log viewer and currently reachable only by `Ctrl+Shift+E` or the View menu. |
| 7 | **Previous gap / Next gap** | two `QToolButton`s | chevron up/down with a broken line | no | Gaps and evictions are the project's distinguishing feature. One click. |
| — | expanding `QWidget` spacer | | | | Pushes the state readout right, away from the verbs. |
| 8 | **Follow chip** | `QToolButton`, text changes | double chevron ▾▾ | **yes**, dynamic: `Following` / `▾ 12,480 new` / `At end` | This is §4's own listed omission — "whether follow is on, and how many records have arrived unseen… neither is among them". Clicking it runs `go_to_bottom` (`windows/main.py:772`), so the first press jumps and the second resumes, exactly as the key does. |

**Deliberately not on the toolbar:** Mark / Clear marks (Edit menu + `Ctrl+M`;
the minimap already shows marks and the Marks panel of §5.2 lists them), Find
(it is a filter field that is already on screen), Diagnose (Help menu, and
offered *as a banner action at the moment it is needed* — §7.4), Copy, Quit,
About, and every capture option. Eight controls is the budget; a ninth would
make this a ribbon.

**Button style:** `Qt.ToolButtonStyle.ToolButtonTextBesideIcon` for 1–3 and 8,
`ToolButtonIconOnly` for 4–7. Mixed styles per button are set with
`QToolButton.setToolButtonStyle` on the individual widget obtained via
`toolbar.widgetForAction(action)`. The labelled ones are the four a first-time
user must be able to read; the icon-only ones are the ones a daily user reaches
for without looking.

**Icons, and the dependency question.** Qt ships no icon set for Windows or
macOS, and `QIcon.fromTheme` resolves only on Linux. The two dependency-free
options are `QStyle.StandardPixmap` (free, sparse, and stylistically flat) and
painting them ourselves. **Recommendation: a `gui/icons.py` of ~80 lines that
paints each glyph with `QPainter` onto a `QPixmap`, stroke colour taken from
`QPalette.ButtonText`, `setDevicePixelRatio` from the widget.** That keeps the
determinism argument of §10 intact (the icon set is a function of the scheme,
not of the platform), survives the screenshot job on all three OSes, involves no
font metrics so §12's offscreen prohibition does not bite, and adds nothing to
`pyproject.toml`. Do **not** reach for `qtawesome` or an icon font — that is a
new runtime dependency and a new font-loading failure mode.

Fallback if that is judged too much work for this release: `ToolButtonTextOnly`
throughout. A text toolbar is not dated; an inconsistent one is.

### 1.3 What stays in the menu bar

Everything. The menu bar is the complete command surface and the toolbar is a
shortcut to the frequent subset — that relationship is what makes the toolbar
safe to keep small, and it is enforced structurally: **every command comes from
`gui/shortcuts.py:BINDINGS`, the window builds actions from it
(`windows/main.py:298-320`), the menus are filled from it
(`windows/main.py:374-375`), the `F1` sheet renders it
(`shortcuts.py:197-211`), and `test_gui_window.py:128` asserts the menu item
count equals `len(BINDINGS) + len(RELOCATED)`.** The toolbar must be built from
the same `actions_by_name` dict; `menu_items()` walks the menu bar only
(`windows/main.py:382-405`), so reusing actions on a toolbar does not disturb
that count.

Menu changes:

- **Capture**: add `Devices ▸` (submenu, mirrors the toolbar selector),
  `Capture options…` (§2.5). Existing items unchanged.
- **View**: add `Detail Pane` (checkable), `Columns ▸` (checkable per column),
  `Marks` (checkable panel), `Jump to Time…`.
- **Help**: add `Diagnose…`. `Keyboard Shortcuts` and `About` stay.
- **Edit**: add `Copy Message`, `Clear Filter`.

### 1.4 The filter bar

Same shape as `docs/design/gui.md` §1 drew and as `widgets/filter_bar.py` built,
plus three additions and one substitution. Detail in §4.

- `Level` combo — unchanged, `_level` (`filter_bar.py:37`).
- `Process` field — gains a trailing `≠` toggle (negate).
- `Subsystem` field — gains a trailing `≠` toggle.
- `Search` field — the `Regex` checkbox moves *inside* the field as a trailing
  `.*` toggle via `QLineEdit.addAction(action, TrailingPosition)`.
- `Saved ▾` — recent and named filters (§4.3).
- **Hidden chip** — `4,912 of 200,000 shown ✕`, always present when the filter
  is non-empty (§4.4).

The bar wraps to a second line under ~900 px using a `QGridLayout` with a
breakpoint in `resizeEvent`, rather than horizontally scrolling. **NICE.**

### 1.5 The table / detail split

- Keep `QSplitter(Vertical)` with `setChildrenCollapsible(False)`
  (`windows/main.py:202`) and the first-show ratio computed in `showEvent`
  (`windows/main.py:278-294`). Both are right and the reasoning is recorded.
- **Diverge:** allow the detail pane to be hidden — but only from `View ▸ Detail
  Pane` and `Ctrl+I`, never by dragging the handle to zero. The doc's stated
  reason for non-collapsible is "a pane that can vanish behind a one-pixel handle
  is a pane the user cannot get back". A menu toggle *is* the way back, so the
  objection does not apply to it. On a laptop screen the detail pane costs a
  quarter of the rows. **MUST.**
- **Persist** splitter sizes, detail-pane visibility, column widths and column
  visibility in `QSettings`. `gui/app.py:43-46` already sets
  `setOrganizationName`/`setApplicationName` for exactly this and nothing uses
  it. A window that forgets its layout every launch is the single loudest "this
  is a prototype" signal. **MUST.**
- **Column chooser**: `horizontalHeader().setContextMenuPolicy(CustomContextMenu)`
  → a menu of six checkable entries, mirrored in `View ▸ Columns`. `Subsystem`
  and `Category` are the two people turn off. Hiding a column is
  `setColumnHidden`, O(1), no model change. **NICE.**
- **Row context menu** on the table (`Qt.ContextMenuPolicy.DefaultContextMenu`
  + `contextMenuEvent`, which the Menu key and `Shift+F10` also raise, so it is
  keyboard-reachable for free): `Copy` / `Copy Message` / — / `Filter by this
  Process` / `Exclude this Process` / `Filter by this Subsystem` / — / `Mark` /
  `Jump to Time…`. The filter items *write into the existing fielded bar*, which
  is why this release needs no query language (§4.1). **MUST** — this is the
  single highest ratio of felt modernity to code in the whole document.

### 1.6 The status bar

Keep the four permanent readouts (`widgets/status_bar.py:51-52`) and the rule
that a transient `showMessage` can never push one off. Changes:

- **A state dot joins the rate readout**: `● 1,204 rec/s` while streaming,
  `◐ reconnecting` during an outage, `○ idle` otherwise. The dot is
  *reinforcement*; the word beside it carries the information, per §10's rule
  that colour is never the only cue. **MUST** (it gives the reconnect state a
  permanent home so the banner can be dismissed without losing the fact).
- **Pass the bytes on disk.** `StatusBar.set_volume` already takes
  `bytes_on_disk` (`status_bar.py:66`) and no caller supplies it. During a live
  capture the session file's size is one `Path.stat()` per pump tick — O(1), and
  it is how a user judges whether to keep going. **NICE.**
- Gap count: unchanged, including when zero (`status_bar.py:72-74`). That rule
  and its Wireshark-12005 justification are reused twice more in this document.
- The transient left area is used for exactly one class of message: the
  confirmation of a completed instantaneous action (`Copied 12 rows`,
  `Filter saved as "network errors"`). Never for state — state gets a banner.

---

## 2. The device story

### 2.1 What information is actually available

| Source | Gives | Cost |
|---|---|---|
| `devices.discovery.list_devices()` (`discovery.py:59`) | `[DeviceSummary(udid, connection)]`, USB and network | one usbmux round trip, no pairing needed |
| `discovery.open_lockdown(udid)` + `read_device_info(...)` (`discovery.py:82`, `:97`) | `DeviceInfo` — name, product type, iOS version, build, tz name, UTC offset, clock skew | a lockdown session per device; **fails with `DeviceNotPairedError` if Trust was never answered** |
| `discovery.require_device(udid)` (`discovery.py:149`) | the chosen device, or `NoDeviceFoundError` with a written hint | as above |
| `devices.doctor.run(udid)` (`doctor.py:67`) | `Report(checks=[Check(name, status, detail, hint)], device)` — usbmux, devices, transport, selection, pairing, identity, clock | all of the above, in dependency order, stopping at the first upstream failure |

So the menu can show UDIDs immediately and *upgrade each row to a human name*
when identity comes back. That two-phase shape is what the CLI's
`ostrace devices -v` does (`cli.py:192-201`), including closing each lockdown in
a `finally` (`cli.py:198-200`).

### 2.2 The control

A `QToolButton` at the far left of the toolbar, `InstantPopup`, its text the
selected device's `DeviceInfo.name` (short) and its tooltip `DeviceInfo.label`
(`model.py:222-228` — `My iPhone (iPhone18,2, iOS 26.5.2)`). Menu rebuilt
on `aboutToShow`:

```
 ● My iPhone — iPhone18,2, iOS 26.5.2      USB
   iPad — iPad14,1, iOS 26.4                     USB
   ⚠ iPhone (00008120-…) — not trusted           USB
   iPhone (00008110-…) — network (not supported) [disabled]
  ────────────────────────────────────────────────
   Refresh                                       F5
   Capture options…
   Diagnose…                              Ctrl+Shift+D
```

Rows are `QAction`s in a `QActionGroup` (exclusive, checkable). Network devices
are **listed and disabled**, never hidden — `list_devices`' own docstring
(`discovery.py:63-65`) argues that hiding them "would turn 'not supported yet'
into 'your device is invisible and you do not know why'", and the same argument
applies twice as hard in a GUI.

### 2.3 Enumeration must not block the GUI thread

`list_devices` and `read_device_info` are `async` and talk to hardware. Mirror
`gui/live.py`'s shape exactly, because it is already the house pattern and it is
correct: a `QThread` with its own `asyncio` loop, signals for lifecycle only.

```
DeviceScanner(QThread)
    found      = Signal(object)   # list[DeviceSummary], immediately
    identified = Signal(str, object)  # udid, DeviceInfo, one per device
    failed     = Signal(str)
```

Three rules, each from an existing hard rule:

1. **Every lockdown opened for identity is closed in a `finally`**, service
   first. `CLAUDE.md`'s "a device stream is two sockets" applies to identity too:
   the CLI already does `finally: await _quietly_close(lockdown)`
   (`cli.py:198-200`).
2. **Never open lockdown on the device a capture is currently holding.** The
   relay is in use and the identity is already known — `CaptureThread.identified`
   delivered a `DeviceInfo` at `windows/main.py:648`. Use that one.
3. **Nothing here imports pymobiledevice3.** `devices/discovery.py` is the
   boundary and the GUI calls it, exactly as `windows/main.py:508` lazily imports
   `sources.os_trace`.

Scan on: window show, `Refresh`, menu `aboutToShow` if the last scan is older
than ~5 s, and after a capture ends. **Not on a timer** — polling usbmux every
few seconds to keep a menu fresh is a background cost for a menu nobody has
open. Hot-plug notification is `LATER` (it would need a usbmux listen socket).

### 2.4 The states

| State | Toolbar button | Table area | Capture button | One action offered |
|---|---|---|---|---|
| **No device** | `No device`, dimmed phone | empty pane: *"No device attached, and no capture open."* | disabled, tooltip *"No device attached"* | **Diagnose** (primary), `Open capture…` (secondary) |
| **One device** | its name | first-run pane | enabled | **Capture from My iPhone** |
| **Several devices** | the auto-chosen one's name | first-run pane | enabled | as above; the menu is one click away |
| **Untrusted device** | its name + ⚠ | first-run pane | enabled (attempting is how you get the Trust prompt) | pressing Capture surfaces `DeviceNotPairedError` with its own `hint` (`errors.py:94-95`) plus **Diagnose…** |
| **Network-only** | `No USB device` | pane | disabled | **Diagnose** — `doctor` has a dedicated `transport` FAIL check for this (`doctor.py:161-168`) |
| **Capturing** | its name, **disabled** with tooltip *"Disconnect to change device"* | rows | swapped to Disconnect | — |
| **Disappeared mid-capture** | unchanged | rows keep their place | swapped to Disconnect | banner: **reconnecting** (§2.6) |

**Selection policy**, in order: the udid stored in `QSettings` if it is still
attached; else the first USB device, matching `require_device`
(`discovery.py:163-165`); else nothing. The point of showing the name is not to
make the user choose — it is so that with two phones plugged in they can *see*
which one was chosen, which is the failure the CLI's `--udid` exists to prevent
and the GUI currently cannot even express.

### 2.5 Capture options

`Capture options…` opens a small dialog with the four things the CLI has and the
GUI does not:

| Field | CLI equivalent | Default |
|---|---|---|
| Stop after | `--duration` (`cli.py:56-62`) | off |
| Stop after N records | `--max-records` (`cli.py:62-67`) | off |
| Reconnect on outage | `--no-reconnect` (`cli.py:68-72`) | on (`ReconnectPolicy()`, `os_trace.py:97-102`) |
| Write session to | `--output` (`cli.py:50-54`) | `paths.sessions_dir()` |

`MainWindow.start_capture` already accepts `destination`
(`windows/main.py:512`) and nothing in the UI supplies it. The other three need
threading through `CaptureThread` to `capture()` / `OsTraceSource`, which is
mechanical. **NICE** — it closes the CLI/GUI gap at the cost of one dialog
nobody is forced to open.

### 2.6 Diagnose, and the reconnect banner

**Diagnose** runs `doctor.run(selected_udid)` on the scanner thread and shows the
`Report` in a dialog: one row per `Check`, with `[ ok ] [warn] [FAIL] [skip]`
spelled in words exactly as the CLI does (`cli.py:294-301` — "a tick that
renders as a box on someone's console helps nobody", and a GUI that pasted a tick
into an issue would have the same problem). Hints wrap under their check. A
**Copy report** button puts the whole thing on the clipboard in the CLI's own
text format, because the destination is a bug report. **MUST** — this is the
biggest single capability gap between the two front ends.

**Reconnect** is §6's one unbuilt banner. `sources/os_trace.py` retries for up to
`delay 2.0 × max_retries 30` ≈ a minute (`os_trace.py:97-102`) and the window
says nothing for that whole minute. Design:

> ⚠ **Device disconnected — reconnecting (4 of 30).** Records emitted while it
> is away are lost and will be marked as a gap.  [Disconnect] [Diagnose…]

Status dot goes `◐ reconnecting`. On success the banner clears and a `Gap` row
appears in position — which is the honest record and needs no extra notice. On
exhaustion the existing `_on_capture_failed` path fires (`windows/main.py:666`).

**Cost warning:** this requires the source to *report* the outage, which is a
change in `sources/`, not in `gui/`. It must not be a method that only
`OsTraceSource` has — `CLAUDE.md`'s load-bearing constraint is that a recorded
session is substitutable for a live device in every test. The right shape is an
optional `on_state` callback on `ostrace.capture.capture()`, which already takes
`on_item`, `on_open` and `on_progress`; the GUI passes one, the CLI may later,
and a replay source simply never calls it. **MUST for the banner, but sequence
it after the GUI-only work** — it is the one item here that crosses a layer.

---

## 3. The keyboard map

### 3.1 Everything currently bound

All from `src/ostrace/gui/shortcuts.py` unless noted. `StandardKey` resolutions
are Qt's documented table; the Windows column is what a user here sees.

| Action | Attribute | Primary | Aliases | Menu | Source |
|---|---|---|---|---|---|
| Capture | `capture` | `Ctrl+R` | — | Capture | `shortcuts.py:59-65` |
| Pause (checkable) | `pause` | `Ctrl+P` | — | Capture | `shortcuts.py:66-73` |
| Disconnect | `disconnect` | `Ctrl+D` | — | Capture | `shortcuts.py:74-80` |
| Open Capture… | `open` | `StandardKey.Open` → `Ctrl+O` / `⌘O` | — | Capture | `shortcuts.py:81-87` |
| Export… | `export` | `Ctrl+E` | — | Capture | `shortcuts.py:88-94` |
| Copy | `copy` | `StandardKey.Copy` → `Ctrl+C` / `⌘C` | — | Edit | `shortcuts.py:96-101` |
| Find (focus search box) | `find` | `StandardKey.Find` → `Ctrl+F` / `⌘F` | `/` | Edit | `shortcuts.py:102-109` |
| Mark Row | `mark` | `Ctrl+M` | `M` | Edit | `shortcuts.py:110-117` |
| Clear Marks | `clear_marks` | `Ctrl+Shift+M` | — | Edit | `shortcuts.py:118-120` |
| Go to Top | `top` | `StandardKey.MoveToStartOfDocument` → `Ctrl+Home` / `⌘↑` | `G, G` | View | `shortcuts.py:121-127` |
| Go to Bottom | `bottom` | `StandardKey.MoveToEndOfDocument` → `Ctrl+End` / `⌘↓` | `Shift+G` | View | `shortcuts.py:128-134` |
| Next Error | `next_error` | `Ctrl+Shift+E` | `E` | View | `shortcuts.py:135-141` |
| Previous Error | `previous_error` | `Ctrl+Alt+Shift+E` | `Shift+E` | View | `shortcuts.py:142-148` |
| Next Gap | `next_marker` | `Ctrl+Shift+G` | `]` | View | `shortcuts.py:149-155` |
| Previous Gap | `previous_marker` | `Ctrl+Alt+Shift+G` | `[` | View | `shortcuts.py:156-162` |
| Next Mark | `next_mark` | `Ctrl+Shift+N` | — | View | `shortcuts.py:163` |
| Previous Mark | `previous_mark` | `Ctrl+Shift+P` | — | View | `shortcuts.py:164` |
| Next Row | `step_down` | `F8` | — | View | `shortcuts.py:165-167` |
| Previous Row | `step_up` | `F7` | — | View | `shortcuts.py:168-173` |
| Keyboard Shortcuts | `keys` | `F1` | — | Help | `shortcuts.py:174` |
| Quit | `quit` | `StandardKey.Quit` | — | Capture | `windows/main.py:325-327` |
| About ostrace | `about` | **none** (deliberate) | — | Help | `windows/main.py:328` |

Non-action keyboard behaviour: `Find` focuses the search field *and selects its
contents* (`filter_bar.py:101-109`), so the second press starts a new search
rather than appending — keep.

**Keep all of the above.** Every one has a reason recorded and several have a
named bug behind them.

### 3.2 Findings on the existing set

**F1 — `StandardKey.Quit` is unbound on Windows.** Qt's standard-key table binds
Quit on macOS (`⌘Q`) and KDE/GNOME (`Ctrl+Q`) and leaves it **empty on Windows**,
where the platform convention is `Alt+F4` (a window-manager key, not an
application shortcut). If so, the Quit menu item on Windows shows no key at all.
`shortcuts.py:214-224`'s `unbound()` guard does not catch it, because `quit` is
in `RELOCATED` (`shortcuts.py:185`) rather than in `BINDINGS`, and
`test_gui_shortcuts.py:50` only walks `BINDINGS`. **[verify]** with:

```python
QKeySequence(QKeySequence.StandardKey.Quit).isEmpty()
```

Fix: `action_quit.setShortcuts([QKeySequence(StandardKey.Quit), QKeySequence("Ctrl+Q")])`
— harmlessly duplicative on macOS, correct on Windows. And extend `unbound()` to
cover `RELOCATED` so the class of bug cannot recur. **MUST** (small, and it is
the same category of hole the module exists to prevent).

**F2 — the punctuation aliases are not reachable on several European layouts.**
Qt matches shortcuts on the key *with modifiers*, not on the character produced.
On a **Turkish-Q layout — the maintainer's own — `[` and `]` are `AltGr+8` and
`AltGr+9`**, so `Next Gap`/`Previous Gap`'s aliases (`shortcuts.py:153`, `:160`)
are unreachable or require a modifier combination Qt will not match. `/` has the
same problem on several layouts. The `Ctrl+Shift+G` primaries still work, so
nothing is lost — but the aliases are documented in the `F1` sheet as if they
work, which is worse than not having them. **Fix:** keep the aliases (they are
right for US/UK) and add layout-independent partners, `F2` / `Shift+F2` for
gap stepping. **[verify]** on a Turkish-Q layout, which is testable here.

**F3 — `Ctrl+P` is Print on every platform.** `StandardKey.Print` is `Ctrl+P` /
`⌘P`. ostrace has no print, so nothing is shadowed, but a reflexive `⌘P` will
pause the view. Mitigation is already in place and is a good argument for
keeping the binding: pausing raises a banner that says what happened and offers
Resume (`windows/main.py:631-636`). A mis-press is self-explaining and
self-undoing. **Keep, do not change.**

**F4 — `Ctrl+Shift+P` (Previous Mark) is the near-universal command-palette
chord.** Not a platform binding, so no collision in Qt's sense; noted because a
user arriving from VS Code will press it expecting a palette. No change.

**F5 — the single-letter aliases are safe next to text fields, and the reason
should be written down.** `E`, `Shift+E`, `M`, `/`, `[`, `]`, `Shift+G` are
`QAction` shortcuts with the default `Qt.ShortcutContext.WindowShortcut`. A
focused `QLineEdit` accepts `QEvent.ShortcutOverride` for unmodified and
Shift-modified printable keys, so typing `E` into `Search` types an `E` and does
not jump to the next error. **This is load-bearing and undocumented.** Two
consequences: (a) never promote any of them to `ApplicationShortcut`; (b) a
**read-only** `QLineEdit` does *not* override, so if any field ever becomes
read-only these aliases start firing inside it. Add both as comments in
`shortcuts.py` and a test that types a letter into `_search` and asserts the
selection did not move. **MUST** (a test, not a feature).

**F6 — a non-editable `QComboBox` does not override.** With focus on the Level
combo, `E` triggers Next Error instead of type-ahead selection. Harmless, worth
knowing.

### 3.3 Proposed additions

Every one of these must be added to `BINDINGS` with a key, a menu and a
description, or `test_gui_window.py:128` and `test_gui_shortcuts.py:50` fail.
That constraint is a feature: it is why this project cannot ship an undocumented
or unreachable command.

| Action | Key | Alias | Menu | Rank | Notes / collision check |
|---|---|---|---|---|---|
| **Clear Filter** | `Ctrl+Shift+F` | — | Edit | MUST | Reads as the inverse of `Ctrl+F`. Free on all three platforms in this app. Not an editing chord, so `test_gui_shortcuts.py:57` is satisfied. |
| **Jump to Time…** | `Ctrl+J` | — | View | MUST | Free on Win/macOS/Linux here. Explicitly **not** `Ctrl+G` — `⌘G` is Find Next system-wide on macOS and klogg binds `Ctrl+G` to find-next. |
| **Diagnose…** | `Ctrl+Shift+D` | — | Help | MUST | Adjacent to `Ctrl+D` (Disconnect) and mnemonic. Nothing standard uses it. |
| **Toggle Detail Pane** | `Ctrl+I` | — | View | MUST | `⌘I` is "Get Info" on macOS — semantically exact. `Ctrl+I` is italic in editors; no text editing here. |
| **Copy Message** | `Ctrl+Shift+C` | — | Edit | NICE | Free everywhere. Copies only the Message column, folded by `exporters.base.escape` as `copy_selection` already does (`windows/main.py:840-849`). |
| **Refresh devices** | `F5` | — | Capture | NICE | The universal refresh key; nothing else claims it. |
| **Next / Previous Gap (layout-safe)** | `F2` / `Shift+F2` | — | View | NICE | See F2 above. |
| **Marks panel** | `Ctrl+Shift+B` | — | View | NICE | `B` for bookmark. Free. |
| **Next / Previous highlight hit** | `F3` / `Shift+F3` | `n` / `N` | Edit | LATER | Only meaningful once highlight exists (§4.6). `StandardKey.FindNext` resolves to `F3` on Windows and `⌘G` on macOS and knows the difference — use the standard key, not a literal, per `shortcuts.py:15-17`. This is the alias pair §8 of the contract cites klogg for and the code does not yet have. |
| **Escape** | `Esc` | — | (no menu item) | MUST | Dismisses a visible banner; otherwise returns focus from a filter field to the table. Needs no menu entry — but `BINDINGS` requires one, so either give it `Edit ▸ Dismiss Notice` or implement it as a `QShortcut` outside `BINDINGS` and extend the "every action is bound" test to cover that too. **Prefer the menu item**; an invisible command is exactly what `shortcuts.py:19-22` forbids. |

**Not proposed and why:** a Settings/Preferences item (see §8), `Ctrl+L` (browser
address-bar reflex), `Ctrl+G` (macOS Find Next), any bare digit (klogg trap 2,
`docs/design/gui.md` §8), and any destructive verb on an editing chord (klogg
`Ctrl+X` truncates the file; asserted at `test_gui_shortcuts.py:57`).

### 3.4 The focus ring

**Tab order**, set explicitly with `setTabOrder` (Qt's default is construction
order, which will be wrong once the toolbar is inserted):

```
toolbar: device → capture/disconnect → pause → open → export
       → prev-error → next-error → prev-gap → next-gap → follow chip
filter : level → process (→ its ≠ toggle) → subsystem (→ ≠) → search (→ .*)
       → saved → hidden-chip ✕
banner : action button, then secondary button   [only while visible]
content: table → minimap → detail pane
```

`Shift+Tab` reverses. The banner entering the ring only while visible is correct
and automatic — `Banner.hide()` (`banner.py:60`) removes it from the chain.

**Can the whole app be driven from the keyboard?** Today, *almost* — with two
holes:

1. **The minimap is mouse-only.** `widgets/minimap.py` handles `mousePressEvent`
   and `mouseMoveEvent` (`:135-139`) and sets no focus policy, so Tab skips it
   and it has no keys. Its functions are all otherwise reachable (`Ctrl+Shift+E`
   for errors, `Ctrl+Shift+G` for gaps, `Ctrl+Shift+N` for marks), so nothing is
   *lost* — but a control that cannot be focused also cannot be described to a
   screen reader. **Fix: `setFocusPolicy(StrongFocus)`, handle `Up`/`Down`/
   `PageUp`/`PageDown`/`Home`/`End` as jumps to the previous/next lit band, and
   paint a focus rectangle.** ~25 lines. **NICE.**
2. **The header context menu** (§1.5) needs a keyboard route — `View ▸ Columns`
   is it. Table row context menu is free: `contextMenuEvent` fires for the Menu
   key and `Shift+F10`.

With those two, yes: every command is on a key or in a menu, every menu is on
the menu bar, and `F1` prints the whole list from the same table the bindings
come from.

**Screen readers.** Icon-only toolbar buttons announce as empty unless given
`setAccessibleName`; every one gets a name equal to its menu text and a
description equal to its `Binding.description` (which already exists and is
already used as the tooltip, `windows/main.py:317`). The banner must *announce
itself* when it appears, or a blind user is exactly the person who never learns
the capture stopped:
`QAccessible.updateAccessibility(QAccessibleEvent(self._label, QAccessible.Event.Alert))`
in `Banner.show_message`. `QAccessible` is in `QtGui` — no new dependency.
**MUST**, and it is four lines.

**IME.** No bare digit, space or Enter is bound, so candidate selection is never
shadowed. The single-letter aliases are protected by the `ShortcutOverride`
mechanism of F5 while a text field has focus, which is exactly when an IME is
composing. The one residual risk is the two-key sequence `G, G`
(`shortcuts.py:125`): Qt's partial-match state machine holds after the first `G`,
and a partially-matched sequence can swallow the next keystroke elsewhere in the
window. Low impact, worth a test.

---

## 4. Filtering

### 4.1 Do not ship a query language in this release

Android Studio's Logcat replaced its dialog-built filters with a query language
in 2022–2023. What it got **right**:

- One copy-pasteable string. Google's stated reason for the rewrite was that a
  dialog-built filter cannot be shared — and that is a real, daily cost.
- History, and named favourites.
- Negation (`-tag:foo`) — by a distance the most-cited win.
- Explicit operators for the three match kinds: `:` contains, `=` exact,
  `~` regex, so the user is never guessing which one a field uses.
- It kept a UI *builder* that writes into the text field, so discoverability
  survived the change.

What it got **wrong**:

- It replaced the fielded UI outright and broke existing saved filters.
- Implicit AND with quoting rules that surprise people: `foo bar` is two ANDed
  terms, not a phrase.
- Errors surface late: the log empties as you type an incomplete expression, and
  an empty log is indistinguishable from a dead device — the exact failure
  `gui/filters.py:51-59` already guards against here by raising on an incomplete
  regex and *keeping the previous filter*.
- `package:mine` needs project context a standalone viewer does not have.
- The severity threshold disappeared into a token users then could not find.

**Verdict for 0.1.0-adjacent: keep the fielded bar** (`docs/design/gui.md` §5
already concluded this and the two halves of that document never agreed). Five
terms over a fixed schema do not need a parser, and a parser is a thing to
write, test, error-report and document. Instead, ship *the two things the
language was actually for* — shareability and recall — without the parser (§4.3),
and ship the one operator it was most praised for (§4.2).

### 4.2 Negation, as a toggle rather than a syntax

A leading `-` is the obvious design and it is wrong here: it needs an escape rule
for a literal leading hyphen, and process names and subsystems really do contain
them. Instead, put a small **`≠` toggle inside the Process and Subsystem fields**
(`QLineEdit.addAction(action, TrailingPosition)` — the same mechanism the Regex
toggle moves to). It is discoverable, unambiguous, keyboard-reachable, and adds
one `bool` to `Filter`.

Only those two fields. Excluding a chatty daemon is the real use case; "messages
*not* containing X" is rare and the highlight verb serves it better. `Filter`
gains `process_exclude: bool` and `subsystem_exclude: bool`; `matches()`
(`filters.py:76-88`) gains one `!=` each and keeps its cheapest-first ordering.
**NICE.**

### 4.3 Making a filter shareable and recallable, without a parser

`Filter` is already a frozen, comparable dataclass (`filters.py:30`). Give it a
canonical one-line text form:

```
level:error process:dasd -subsystem:com.apple.network search:~timeout
```

This form is **output only in this release.** It is what `Edit ▸ Copy Filter`
puts on the clipboard and what a saved filter is stored as in `QSettings`
(human-readable, greppable, editable by hand). A colleague can read it in an
issue and reproduce it in four seconds. Fixing the spelling now, before anything
parses it, is the same discipline `docs/formats/` applies to on-disk contracts —
and when a reader is added later it has a spec to read.

**Saved filters**: a `Saved ▾` `QToolButton` at the right of the filter bar:

```
  Recent
    level:error process:dasd
    search:~timeout
    level:fault
  ──────────────────────
  Saved
    ● network errors
    ● watchdog
  ──────────────────────
    Save current filter…
    Manage saved filters…
```

Recent is the last 8 distinct non-empty filters, automatic, no naming required —
that is the half people actually use. Saved is named and explicit. Both live in
`QSettings`. **NICE** for saved, **MUST** for recent — recent is ~30 lines and it
removes the single most common annoyance (retyping the filter you had two
minutes ago).

A strict reader for the text form — split on whitespace, `key:value`, reject
anything unrecognised with a precise message and refuse to guess — is about 40
lines and would make filters pasteable both ways. **LATER**, and only with the
rule that an unparseable string leaves the current filter alone and says why,
exactly as the invalid-regex path already does.

### 4.4 Showing that a filter is active, and how much it hides

Today the *only* signal is the banner that appears when a filter hides
**everything** (`windows/main.py:971-978`). Between "hides nothing" and "hides
all", the user gets no indication at all that they are looking at a subset.

Add a **hidden chip** at the right of the filter bar:

> `4,912 of 200,000 shown` `✕`

Rules:

- Rendered whenever the filter is non-empty — **including when it hides nothing**
  (`200,000 of 200,000 shown`). This is the same falsifiability argument the gap
  counter already won (`widgets/status_bar.py:3-9`, Wireshark bug 12005): an
  indicator that appears only on bad news is indistinguishable from a broken one.
- `✕` clears the filter; it is the mouse equivalent of `Ctrl+Shift+F` and of the
  banner's `Clear filter` button.
- O(1): both numbers are maintained counters —
  `RecordModel.hidden_by_filter` (`models.py:737`) and `retained`
  (`models.py:715`). Neither scans. Update on filter change and on the pump tick.
- `Filter.is_empty` / `FilterBar.is_empty` (`filters.py:62`,
  `filter_bar.py:88`) are the predicates that decide whether the chip renders.
  They were written for this and have never been called by the window.

**MUST.** It is one label, two integers that already exist, and it converts the
most common invisible state in the program into a permanent readout.

### 4.5 A found bug: the "everything is hidden" banner is stale during a live capture

`_update_banner` (`windows/main.py:963`) is called from `_apply_filter`
(`:922`) and `_on_loaded` (`:474`) — and **not from the pump tick**. `_on_rate`
(`windows/main.py:652-656`) updates the rate, volume, gap count and follow, and
never re-evaluates the banner. So during a live capture:

- A filter that hid everything when applied keeps saying *"All N records are
  hidden by the filter"* long after matching records have started arriving.
- A filter applied while the table was empty, which then hides everything as
  records arrive, produces a silently empty table and **no banner at all** — the
  precise state §6 of the contract exists to prevent.

Fix: call `_update_banner()` from `_on_rate`, guarded to act only on a
*transition* (so it does not re-show a banner the user dismissed twenty times a
second, and does not fight the pause / overflow / reconnect banners, which own
the banner while they are up). Both branches it evaluates read maintained
integers, so the per-tick cost is two comparisons. **MUST**, and it ships with
the test that fails without it.

### 4.6 Highlight

`docs/design/gui.md` §5 argues for two verbs — filter removes rows, highlight
marks them in place — and phase 4 built only the first. The full version (a
second field, per-term hit count, gutter indicator, `F3`/`n` stepping) is real
work and a second control on an already-busy bar. **LATER.**

The cheap 80% for this release: **draw the current search term highlighted inside
the Message cell of the rows that survive the filter.** It answers "why did this
row match?" with no new control, and the per-row cost is one `str.find` on a
string the delegate is already about to draw — O(1) per *visible* row, ~40 rows
per repaint, well inside the budget. It is fiddly against eliding and a fixed row
height, which is why it is **NICE** rather than MUST.

> **Measured, 2026-08-14.** This estimate and `widgets/log_table.py`'s
> `SeverityDelegate` docstring — "a Python `paint` on that path is the one thing
> the table cannot afford" — appeared to contradict each other, so the paint was
> timed rather than argued about. 200,000 rows, 60 repaints of a 1400×900
> viewport, three delegates **interleaved** across five rounds, median of the
> round medians:
>
> | | median | over the shipped delegate |
> | --- | ---: | ---: |
> | shipped (`initStyleOption` only) | 29.64 ms | — |
> | a `paint` that only calls `super()` | 30.69 ms | +1.05 ms |
> | that `paint` plus the highlight fill | 30.43 ms | +0.78 ms |
>
> **Both statements are true and they are about different quantities.** Crossing
> into Python costs about 1 ms on a 30 ms repaint *for one column*; the docstring
> is about `SeverityDelegate`, which is set view-wide and would pay that for
> every column at once. The highlight drawing itself costs nothing measurable —
> 27,360 `paint` calls were counted, 288 of which found the term, and the arm
> that drew came out 0.26 ms *under* the arm that did not, inside a round-to-round
> spread of about 2 ms.
>
> Two runs at different points in a sequence are not a comparison: run one arm
> after another, the first pays every one-time cost and the later ones do not,
> and the first attempt at this had a *slower* delegate measuring 4 ms faster
> than no delegate at all. Interleaving is what fixed it.

### 4.7 A filter that hides everything always offers a way back

Already true and already tested (`windows/main.py:971-978`;
`tests/test_gui_wiring.py:130`). §4.5 makes it true *continuously* rather than
only at the moment the filter changes, and §4.4 makes the milder version of the
same state ("hides most") visible too. Three ways back, all present at once:
the banner button, the chip's `✕`, and `Ctrl+Shift+F`.

---

## 5. Navigation and place-keeping

### 5.1 What already works, and is better than the field

- **Selection and viewport anchor to the record across a filter change**
  (`models.nearest_view_row`, `models.py:403`; `windows/main.py:924-949`), with
  the nearest-survivor fallback. Wireshark #16318 open since 3.0.7, lnav clamps
  ordinals, Logcat re-appends its document and jumps to the bottom on every
  keystroke. Tested at `tests/test_gui_wiring.py:148` and `:175`.
- **Marks are held by source index** (`models.py:170-172`), so they move with
  their records across a filter change and are rebased on trim
  (`models.py:636`).
- **Go to bottom is two commands on one key** (`windows/main.py:776-799`).
- **`F7`/`F8` step rows without the table having focus** (`windows/main.py:812`).
- **The minimap exists** and clicking or dragging jumps (`minimap.py:135-149`),
  with the row-anchored bucket design measured at 0.59 ms vs 282 ms for pixel
  bands (`models.py:365-378`).

Build on it; do not disturb it.

### 5.2 Proposals, cheap first

| Proposal | Cost | Rank |
|---|---|---|
| **Minimap viewport marker** — a translucent rectangle showing where the visible window sits in the whole capture | ~8 lines in `paintEvent` from `table.verticalScrollBar().value()/maximum()`, O(1) | **MUST** — without it the strip shows *what* but not *where you are*, which makes it a picture rather than a map |
| **Unseen count + follow state** in the toolbar chip | `rowCount()-1-table.indexAt(viewport bottom-left).row()`, O(1) per tick | **MUST** — §4 of the contract lists both as omissions and calls the unseen count "the more useful half" |
| **Jump to time…** (`Ctrl+J`), accepting `14:22:31`, `14:22:31.500`, `+30s`, `-2m` | linear scan of `_visible` on a human action, ~10 ms at 200k, same precedent as `find()` (`models.py:284`) | **MUST** — it is the only navigation primitive that correlates the log with the outside world, which is why people capture a device log at all. ~60 lines |
| **Marks panel** — a hidden-by-default `QDockWidget` listing marked rows (time, level, process, message head), click to jump | `_marks` is a small set; rebuild on change | NICE |
| **Minimap keyboard focus + band stepping** | §3.4 | NICE |
| **Minimap time axis** — the first and last timestamp drawn at the strip's ends | two `drawText` calls. §12 forbids *asserting* font metrics under offscreen; drawing is fine | NICE |
| **Minimap hover tooltip** — "3 errors, 1 gap at 14:22:31" | needs a per-band detail the model does not keep | LATER |
| **Named marks** ("watchdog fires here") | changes `_marks: set[int]` to a dict; touches trim/rebasing and `test_gui_navigation.py` | LATER |
| **Marks persisted per capture** | QSettings keyed by capture path; meaningless for a live capture | LATER |
| **A time-proportional timeline** distinct from the row-proportional minimap | would be *more* honest about a 40-minute gap holding zero rows — but it discards the row-anchored bucket design whose alternative measured 282 ms per rebuild | LATER, with that measurement attached |
| **Context lines around a match** (`grep -C`) | already deliberately out of scope, `docs/design/gui.md` §13 | LATER |

### 5.3 One thing to verify rather than fix

On trim, the model rebases `_visible` and `_marks` but the *view's* current index
is a row number. Because the removal is contiguous and framed by
`beginRemoveRows`/`endRemoveRows` (`models.py:624`, `:644`), Qt's selection model
should adjust it automatically — so the selection probably survives an eviction
correctly. That is a claim worth a test rather than a rewrite:
`test_gui_navigation.py:273` covers the *mark* case but not the *selection* case.

---

## 6. Export

### 6.1 The defect to fix first

`ExportDialog.run_export` (`widgets/export_dialog.py:154-179`) calls
`exporter.export(...)` directly. It never calls
`paths.check_export_destination`, which the CLI calls at `cli.py:295`.

This is reachable. `export_stem` strips `.jsonl` (`paths.py:157`,
`_CAPTURE_ENDINGS`), and `export_path` then appends the format's own suffix
(`paths.py:173-186`). For a capture opened from a bare `foo.jsonl` — which the
GUI's own file dialog offers, `windows/main.py:415` — choosing format `jsonl`
computes the default destination as `foo.jsonl`: **the input file**. That is
exactly the incident `check_export_destination`'s docstring records
(`paths.py:188-201`): a 2.2 MB capture became zero bytes, the command reported
`0 records`, and it exited successfully.

Fix: call `check_export_destination(destination, self.capture.path)` before
exporting, catch `DestinationInUseError` alongside the existing
`(OstraceError, OSError)` (`export_dialog.py:164`) — it is an `OstraceError`
subclass (`errors.py:159`) so the existing handler already catches it, but the
call has to *happen*. Render its message and hint in the report label. Ships with
the test that fails without it. **MUST, highest priority in this section.**

Also: warn when the destination already exists. Every exporter overwrites, and
`QFileDialog.getSaveFileName` only prompts when the user goes through the
chooser — not when they accept the derived default.

### 6.2 The flow

**Format first, destination second** — and that is not a preference, it is
forced: the destination's default is *derived* from the format
(`export_dialog.py:132`, `:140`), so asking for a destination first would ask the
user for something the program can compute. Keep.

Redesign of the dialog:

```
┌ Export capture ─────────────────────────────────────────────┐
│ My-iPhone-20260808-135325 · 412,301 records · 3 gaps     │
│                                                              │
│  ◉ agent-bundle   A directory of tab-separated text for      │
│                   grep-based investigation                   │
│  ○ ai-report      A summary that shrinks to a token budget   │
│                   and states what it dropped                 │
│  ○ jsonl          JSON Lines, one object per record          │
│  ○ markdown       A document with a summary and the records  │
│  ○ text           Aligned plain text, one record per line    │
│  ○ trace          Verbatim windows around each error         │
│                                                              │
│  Write to  [ …\My-iPhone-20260808-135325-bundle ] [Choose…] │
│                                                              │
│  412,301 records → …\…-bundle                                │
│  What this export cannot tell you:                           │
│    • …                                                       │
│                                       [ Export agent-bundle ] [Close] │
└──────────────────────────────────────────────────────────────┘
```

Changes from `widgets/export_dialog.py`:

- **Six radio rows instead of a combo.** Six is exactly the count where a list
  beats a dropdown: the formats *are* the product, and the descriptions already
  written (`exporters/*.py`, `name`/`description`) are good enough to choose
  from without opening anything. A combo hides five of the six behind a click.
  **NICE** — it is the one item here that breaks tests (§9).
- **The Export button names the format** — `Export agent-bundle` — and the
  resolved destination is visible above it, so `Enter` is a complete answer and
  the default path costs zero decisions. The default stays `agent-bundle`
  (`export_dialog.py:54`) for the reason recorded: it is the only format that
  loses nothing. **MUST.**
- **A header line** naming the capture, its record count and its gap count, so
  the user knows what they are exporting. **NICE.**
- **`Choose…` beside the field, not under it.** Today it is in a `QVBoxLayout`
  inside a form row (`export_dialog.py:94-102`), which reads as an unrelated
  control. **MUST** (trivial).
- **The destination in the report becomes a link that reveals the file**:
  `QDesktopServices.openUrl(QUrl.fromLocalFile(parent_dir))` — `QtGui`, no new
  dependency, opens Explorer/Finder at the folder. It answers the "where did it
  go" question the module docstring worries about. **NICE.**
- **Keep: the dialog does not close on success**, and it lists what the format
  could not say using `exporters.notes.export_notes` — the same sentences the
  CLI prints (`export_dialog.py:173`, `cli.py:299-300`). That is the best thing
  about this dialog and it must survive any restructuring.
- **The token budget stays conditional on `ai-report`** (`export_dialog.py:127`).
  Correct progressive disclosure, already built.

### 6.3 The other real risk: export blocks the GUI thread

`exporter.export(self.capture.items(), ...)` (`export_dialog.py:163`) runs
synchronously over the whole file. For a million-record capture the window
freezes with no cursor change, no progress, no cancel — and the user's model of
what happened is "it crashed".

- **MUST, minimum:** `QApplication.setOverrideCursor(WaitCursor)`, disable the
  Export button, and put `Writing…` in the report label before starting. Honest,
  three lines, still blocking.
- **NICE:** run the export on a `QThread` with a progress signal. The exporter
  API is a plain function over an iterator, so it is thread-safe as long as
  nothing else touches that `Capture`. The reading side already solved this shape
  — `gui/loader.py`'s `CaptureLoader` steps from the event loop rather than
  reading in one pass.

### 6.4 Exporting while a capture runs

Keep the refusal and its `Disconnect` action (`windows/main.py:735-759`) — the
reasoning is sound (a file growing under the exporter produces a report whose end
is arbitrary) and `_adopt_session` (`windows/main.py:571`) is what stops it being
a dead end. Two additions:

- The refusal should say **how much** would be exported once disconnected
  ("412,000 records so far"), so the user can judge the cost of finishing.
  **NICE.**
- **When a capture ends — by Disconnect or by itself — post a banner:**
  *"Capture finished: 412,301 records in My-iPhone-20260808-135325."*
  `[Export…]` `[Dismiss]`. Today the window's only signal is the title change at
  `windows/main.py:597`, which is described in its own comment as "the one place
  the window says where the capture went". That is the exact moment the user
  wants Export, and it is currently silent. **MUST**, and it reuses the banner
  mechanism unchanged.

### 6.5 Export only what the filter shows?

Tempting and wrong for this release. Every exporter declares what it dropped; an
export that silently applied a *view* filter would be the same class of lie §3
of the contract forbids. If it is ever offered it must be an explicit, labelled
choice and the exporters' notes must carry it, which makes it a
`docs/formats/` change. **LATER.**

---

## 7. Empty, first-run and error states

### 7.1 The rule that assigns each state an owner

A **banner** explains a state that *contradicts* what the table shows (paused,
reconnecting, filtered, truncated). An **empty pane** fills a table that has
nothing to show at all. Both can exist at once, but **never for the same fact and
never with the same sentence** — so each state below has exactly one owner, and
exactly one primary action.

Implementation: a `QStackedWidget` in the splitter's first slot, swapping the
table+minimap for an `EmptyState` widget (icon, title, one sentence, one primary
button, at most one secondary link). ~120 lines, no dependency.

### 7.2 Every empty state

| # | State | Owner | On screen | The one action |
|---|---|---|---|---|
| 1 | **Nothing opened yet, device attached** | pane | *"No capture open."* + the last three recent captures as links | **Capture from My iPhone** · secondary `Open capture…` |
| 2 | **Nothing opened yet, no device** | pane | *"No device attached, and no capture open."* | **Diagnose** · secondary `Open capture…` — pressing Capture here would only produce the banner they are already looking at |
| 3 | **Capture running, device silent** | pane | *"Capturing from My iPhone. No records yet."* + *"A quiet device can say nothing for tens of seconds."* (measured, `gui/live.py:5-7`) | **Disconnect**. The status bar's `● 0 rec/s` and green dot are the evidence that this is not a dead capture — that distinction is the whole point |
| 4 | **Reading a large capture** | pane | *"Reading capture… 412,000 records"* | **Cancel** — `CaptureLoader.cancel()` exists (`windows/main.py:434`) and is unreachable from the UI today |
| 5 | **Filter hides everything** | banner (exists, `main.py:971`) | *"All 200,000 records are hidden by the filter."* | **Clear filter**. Pane shows a neutral title only, no duplicate action |
| 6 | **Capture failed / no device** | banner (exists, `main.py:679`) | the error's own message + `hint` | **Retry** · **Diagnose…** as a second button — requires widening `Banner.show_message` to an optional secondary; `act()` keeps its meaning (primary) so `test_gui_wiring.py:141` is unaffected |
| 7 | **File failed to open** | banner (exists, `main.py:439`) | *"Could not open X: …"* | **Open another…** instead of today's `Dismiss` — dismissing leaves an empty window with nothing to do |
| 8 | **Capture opened but empty** | banner (exists, `main.py:986`) | *"This capture contains no records."* | **Open another…** |
| 9 | **Truncated capture opened** | banner (exists, `main.py:469`) | *"…still being written or the writer was killed. Its last records are missing."* | **Dismiss** — correct, because the content behind it is usable |
| 10 | **Paused** | banner (exists, `main.py:631`) + checked toolbar button | add the *N buffered* §6 lists as missing — `Pump` knows `len(self.queue)` (`pump.py:127`) | **Resume** |
| 11 | **Paused queue overflowed** | banner (exists, `main.py:658`) | *"N records did not fit. They are in the session file, not lost."* | **Resume** |
| 12 | **Reconnecting** | banner (**not built**) | §2.6 | **Disconnect** · **Diagnose…** |
| 13 | **Capture would not release the device** | banner (exists, `main.py:617`) | *"…still shutting down, and a new capture may fail until it has."* | **none today — a dead end.** Give it **Diagnose…** |
| 14 | **Capture finished** | banner (**not built**) | §6.4 | **Export…** |

The recurring principle, worth writing into `banner.py`: **`Dismiss` is only an
acceptable action when there is usable content behind the banner. Whenever the
view behind it is empty, the banner must carry the action that fills it.** Rows
7, 8 and 13 all violate that today.

### 7.3 What the pane must never do

Never render a gap and an eviction the same way — that rule lives in the table
and the detail pane (`markers.py:13-22`, `detail_pane.py:162-206`) and is already
right. The empty pane never mentions either: it has no rows.

### 7.4 Diagnose is the recovery action, not a feature

Three of the fourteen states above resolve to `Diagnose…`, and every one of them
is a state where `devices/doctor.py` already knows the answer and the GUI
currently offers a sentence instead. That is the argument for building the doctor
dialog: not "the CLI has it", but "three dead ends in the GUI end there".

---

## 8. Progressive disclosure

**Visible by default** (what a first-time user sees, and the entire surface a
daily user needs): the toolbar's eight controls with four of them labelled; the
filter bar's five controls plus the hidden chip; six table columns; the detail
pane; the minimap; four status readouts. Nothing else.

**One level in** — a menu, a dropdown, a right-click or a checkbox:

| Behind | What |
|---|---|
| device menu | device list, Refresh, **Capture options** (duration, max records, no-reconnect, output directory) |
| header right-click / `View ▸ Columns` | column visibility |
| table right-click | Copy Message, Filter/Exclude by this Process or Subsystem, Mark, Jump to Time |
| filter bar `Saved ▾` | recent filters, named filters, save, manage |
| `Help ▸ Diagnose…` | the full doctor report (and it surfaces itself as a banner action when it is needed) |
| `View ▸ Marks` | the marks panel |
| format = `ai-report` | the token budget — already correct (`export_dialog.py:127`) |
| `F1` | the whole key table, generated from `BINDINGS` — already correct |

**Deliberately absent:** a Settings/Preferences dialog. `shortcuts.py:181-185`
argues there is nothing to configure and that a Preferences item Qt relocates
into the macOS application menu is "the item people press without looking". That
argument is correct **today** — and this redesign weakens it: once `QSettings`
holds splitter sizes, detail-pane visibility, column widths and visibility, the
last device, saved filters and recent filters, "nothing to configure" is no
longer true, it is merely "nothing configured *through a dialog*". Those are
different claims.

**Recommendation:** keep Preferences absent in this release — every one of those
settings is set by *doing the thing* rather than by declaring it, which is the
better design — but record the trigger: **the first setting that has no direct
manipulation (drain interval, row cap, timestamp format, default export format)
is the one that requires the dialog**, and at that moment `RELOCATED`
(`shortcuts.py:185`) and the `PreferencesRole` menu-role trap
(`windows/main.py:7-14`) must both be revisited together.

---

## 9. Test impact, and the order to do the work

`tests/test_gui_wiring.py` and its siblings address widgets by attribute.
Everything below is what my proposals touch.

**Untouched (proposals are additive):**
`window.model`, `window.table`, `window.capture`, `window._loader`,
`loader._step` / `loader.loaded`, `window._apply_filter`,
`window.status.gap_text` (`status_bar.py:76`), `window.status._volume`,
`window.detail.field(...)` (`detail_pane.py:217`), `window.banner.text`,
`window.banner.act()`, `window.filter_bar._level`, `_process`, `_search`,
`window.model.row_at` / `source_index` / `nearest_view_row`.

**Touched, low risk:**

| Proposal | Attribute | Risk |
|---|---|---|
| Regex checkbox → in-field toggle (§1.4) | `filter_bar._regex` — `tests/test_gui_wiring.py:123` calls `.setChecked(True)` | A checkable `QAction` also has `setChecked`, so keep the attribute name `_regex` and the test compiles unchanged. `FilterBar.regex` (`filter_bar.py:84`) changes implementation only. **Keep the name.** |
| State dot in the status bar (§1.6) | `status._rate` | `gap_text` and `_volume` untouched |
| Banner secondary action (§7.2 row 6) | `banner.act()` | `act()` stays the *primary*; the secondary is a new method |
| Detail pane grouping, if any | `detail.field(name)` | `field()` is the contract; any restructure must keep `_rows` keyed by the same names |
| Toolbar | `window.menu_items()` (`test_gui_window.py:128`) | Built from the same `actions_by_name`; `menu_items()` walks the menu bar only (`main.py:395`), so the count is unaffected |

**Touched, will break tests — sequence last:**

| Proposal | Breaks |
|---|---|
| Export format combo → radio list (§6.2) | `tests/test_gui_export.py` uses `dialog.format_box` with `findData` / `currentIndexChanged` (`export_dialog.py:75-80`). `format_name` should stay the public accessor so only the widget-level assertions need rewriting |
| Any new `QAction` | `test_gui_window.py:128` (`len(menu_items()) == len(BINDINGS) + len(RELOCATED)`), `test_gui_window.py:95` (every menu item does something), `test_gui_shortcuts.py:50` (`unbound() == []`), `test_gui_shortcuts.py:57` (no destructive verb on an editing chord). Every addition goes through `BINDINGS` with a key, a menu and a description — which is the system working, not an obstacle |
| `Esc` (§3.3) | Has no natural menu item. Either give it `Edit ▸ Dismiss Notice` or accept a `QShortcut` outside `BINDINGS` and extend the coverage test to it |

**Recommended order:**

1. **Pure fixes, no new UI.** Export destination guard (§6.1); `_update_banner`
   on the pump tick (§4.5); `Quit` key on Windows (§3.2 F1); banner actions for
   the three dead ends (§7.2 rows 7, 8, 13); accessibility names + banner alert
   (§3.4). Each ships with the test that fails without it.
2. **Additive readouts.** Hidden chip (§4.4), minimap viewport marker (§5.2),
   unseen count (§5.2), status-bar dot and bytes (§1.6), capture-finished banner
   (§6.4).
3. **`shortcuts.py` additions**, one per new command (§3.3).
4. **The toolbar**, built from the actions that now exist (§1.2). Plus
   `QSettings` persistence and the empty-state stack (§1.5, §7).
5. **The device selector**, its scanner thread and the doctor dialog (§2). New
   files, no existing test touched.
6. **Filter bar restructure** — negate toggles, in-field regex, saved/recent
   (§4.2, §4.3).
7. **Export dialog restructure** (§6.2), and the export thread (§6.3).
8. **`sources/` change for the reconnect callback** (§2.6) — last, because it
   crosses a layer and needs its own review.

---

## 10. Scope: must-have, nice-to-have, later

### Must-have for the redesign

Fixes:

1. `check_export_destination` in the export dialog — it can still zero a capture.
2. `_update_banner` on the pump tick — the "everything is hidden" banner is
   stale in both directions during a live capture.
3. `Ctrl+Q` alongside `StandardKey.Quit`, and `unbound()` extended to
   `RELOCATED`. **[verify]** the Windows resolution first.
4. Banner actions for the three dead ends: failed open → *Open another…*, empty
   capture → *Open another…*, undead capture thread → *Diagnose…*.
5. Accessible names on icon-only controls; banner announces itself as an alert.
6. A test that a letter typed into the Search field does not fire the
   single-letter aliases (documents the `ShortcutOverride` mechanism that makes
   them safe).

New:

7. **Toolbar** — the eight controls of §1.2.
8. **Device selector**, its scanner thread, and the six states of §2.4.
9. **Doctor dialog**, reachable from Help and offered as a banner action.
10. **Reconnect banner** (needs the `capture(on_state=…)` callback).
11. **Empty-state pane** and the fourteen states of §7.2.
12. **Hidden chip** — `N of M shown`, always when a filter is set.
13. **Row context menu**, including *Filter by this process*.
14. **Recent filters** (no naming required).
15. **Jump to time** (`Ctrl+J`).
16. **Minimap viewport marker.**
17. **Follow state + unseen count** in the toolbar chip.
18. **Capture-finished banner** offering Export.
19. **`QSettings` persistence** of splitter sizes, detail-pane visibility, column
    widths and visibility, last device.
20. **Detail pane hideable** from `View` / `Ctrl+I`.
21. Export: `Choose…` beside its field; button names the format; wait cursor and
    a disabled button while writing.
22. New keys: `Ctrl+Shift+F`, `Ctrl+J`, `Ctrl+Shift+D`, `Ctrl+I`, `Esc`.

> **This tier is closed.** All twenty-two items shipped: 0.1.1 took the ones
> that could be done at once and 0.1.2 finished the rest, and the
> [changelog](../../../CHANGELOG.md) records which release took which. What is
> live in this document is the two tiers below.

### Nice-to-have if cheap

Column chooser · ~~negate toggles on Process and Subsystem~~ · ~~in-field regex
toggle~~ · ~~named saved filters~~ · ~~`Copy filter` text form~~ · search-term
highlighting inside the Message cell · marks panel · minimap keyboard focus and
band stepping · minimap time axis · ~~capture options dialog (duration, max
records, no-reconnect, output)~~ · ~~status-bar bytes-on-disk~~ · ~~`N buffered`
in the paused banner~~ · export radio list · export header line ·
reveal-in-folder link · export on a thread · `F2`/`Shift+F2` layout-safe gap
keys · ~~`F5` refresh~~ · `Ctrl+Shift+C` copy message · `Ctrl+Shift+B` marks
panel · filter bar wrapping at narrow widths · ~~loader progress with Cancel~~.

> **Struck through: shipped.** This tier is being taken in four packages, one
> pull request each, grouped by the sentence they belong to rather than by the
> file they touch. The filter bar was the first and the capture options the
> second. The remaining two are the export dialog, and the View menu — marks,
> the minimap's keyboard, and the columns.
>
> The loader's Cancel is on the capture package rather than on the export one
> because it is the same sentence: what the window says about work it is in the
> middle of. `progress with Cancel` in the list above turned out to be Cancel
> only — the record count was already in the status bar and a second progress
> readout would have been the same number twice.
>
> Two items moved between packages on the way. Search-term highlighting and the
> bar's narrow-width wrapping were drafted with the filter bar and belong with
> the table and the layout, so they went to the View package; the paint
> measurement in §4.6 was taken for them and is recorded there.

### Later

A filter query language or even a strict text-form *reader* · full highlight as a
second verb with hit counts and a gutter indicator · `F3`/`n` hit stepping ·
named marks · marks persisted per capture · minimap hover detail · a
time-proportional timeline · export-what-the-filter-shows · hot-plug device
notification · network capture · per-pane follow · in-row expansion on
`Right`/`Left` · context lines around a match · a Preferences dialog (and with
it, the `RELOCATED` / `PreferencesRole` question).

---

## 11. Dependency and performance ledger

**No new runtime dependency anywhere in this document.** Everything used is
PySide6 (already pinned) or the standard library:

| Need | Mechanism | Module |
|---|---|---|
| Toolbar | `QToolBar` / `QToolButton` | QtWidgets |
| Icons | hand-painted `QPixmap` → `QIcon`, palette-derived | QtGui |
| Persistence | `QSettings` (org/app already set, `app.py:43-46`) | QtCore |
| Reveal in folder | `QDesktopServices.openUrl(QUrl.fromLocalFile(...))` | QtGui |
| Screen-reader alerts | `QAccessible.updateAccessibility(QAccessibleEvent(...))` | QtGui |
| Empty states | `QStackedWidget` | QtWidgets |
| Marks panel | `QDockWidget` + `QListWidget` | QtWidgets |
| Device scanning | `QThread` + `asyncio` loop, the `gui/live.py` pattern | QtCore |

**Explicitly rejected because they would be new dependencies:** `qtawesome` or
any icon font; any Markdown/HTML renderer for the doctor report (a `QLabel` with
`RichText` is enough, as `show_keys` already does, `windows/main.py:854-871`).
**Borderline:** QtSvg ships in `PySide6-Essentials`, so inline-SVG icons would
not be a new *distribution* dependency — but painted icons need no new import at
all, so prefer them.

**Per-row cost.** Everything proposed that runs per row is O(1) per *visible*
row (~40), never per retained row (up to 200,000):

- hidden chip, unseen count, gap count, rate, bytes → maintained integers or one
  `stat()`, read once per pump tick;
- search-term highlighting → one `str.find` on a string the delegate is already
  drawing;
- minimap viewport rectangle → one division and one `fillRect`;
- column hiding → `setColumnHidden`, no model work.

**O(retained), on a human action only** — the same precedent `RecordModel.find`
already sets (`models.py:284`): jump-to-time, next-highlight-hit, a filter
change. None of them runs on arriving data.

**Nothing new runs per retained row per tick.** The one thing that would — a
per-band minimap detail for hover tooltips — is deliberately in **Later**, with
the 282 ms measurement (`models.py:365-378`) as the reason.
