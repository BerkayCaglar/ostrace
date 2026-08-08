# GUI design

**Rationale:** [ADR 0004](../adr/0004-pyside6-with-custom-filtered-model.md)
**Implements:** `ostrace.gui`
**Status:** written before the code, like [`docs/formats/`](../formats/). Where
this and the implementation disagree, this is right and the code is the bug.

This is a behaviour contract, not a mockup. It answers the questions that get
decided badly at three in the morning with a half-written widget on screen:
what breaks follow, what a filter is allowed to hide, what "pause" is permitted
to touch, and what the user is told when data goes missing.

Every rule below is either measured on this machine against PySide6 6.11.1, or
attributed to a tool that shipped the mistake. Nothing here is taste.

---

## 1. The window

```
┌─────────────────────────────────────────────────────────────────┐
│  ▶ Capture   ⏸ Pause   ⏏ Disconnect │ device ▾ │ Export ▾  Open │
├─────────────────────────────────────────────────────────────────┤
│ Level ▾  Process [____]  Subsystem [____]  Search [____] □ Regex│
├──────────┬───────┬────────────┬──────────────┬──────────────────┤
│ Time     │ Level │ Process    │ Subsystem    │ Message          │
├──────────┼───────┼────────────┼──────────────┼──────────────────┤
│ 01:10:31 │ ERROR │ dasd[83]   │ com.apple.d… │ Unable to dereg… │
├──────────┴───────┴────────────┴──────────────┴──────────────────┤
│ detail pane — every field of the selected record                │
├─────────────────────────────────────────────────────────────────┤
│ ● 1,204 rec/s │ iPhone · iOS 26.5.2 │ 1.2M records · 61 MB │ 0 gaps│
└─────────────────────────────────────────────────────────────────┘
```

The status bar always shows the gap count, **including when it is zero**.
Wireshark bug 12005: a `Dropped` counter rendered only when non-zero silently
regressed to never rendering, and nobody could tell "no drops" from "counter
broken". A number that is always there is falsifiable; one that appears only on
bad news is not.

---

## 2. Columns, and what the detail pane is for

`Record` has thirteen fields and the table shows six. The split is not about
width. The table carries what you *scan* for; the detail pane carries what you
*confirm* once something has caught your eye.

| Column | Source | Notes |
| --- | --- | --- |
| Time | `timestamp` | The device's clock, with the device's offset. Never the host's |
| Level | `level.title` | Text, always — see §10 |
| Process | `process_label` | `name[pid]`, and the `[pid]` is never the part that gets truncated |
| Subsystem | `subsystem` | `-` when absent |
| Category | `category` | `-` when absent |
| Message | `message` | Elided right, never wrapped |

The detail pane gets everything, including the seven fields the table has no
room for: `process_path`, `image_path`, `thread_id`, `pid` on its own,
`platform`, and both timestamps — the device's and the host's, **with their
delta**, borrowed from lnav's overlay. This project's rule that a timestamp
carries the device's offset is invisible until you can see both clocks side by
side.

Two cheap wins, both from Android Studio Logcat, which ships them as settings:

- **Fixed column widths.** Autosizing columns reflow under the cursor as
  records arrive. Never `ResizeToContents` (§11).
- **Suppress a repeated cell.** Blanking `process`/`subsystem` when it equals
  the row above costs nothing in a delegate and transforms scannability on a
  log where those repeat for hundreds of consecutive rows.

---

## 3. Markers, and the invariant that protects them

A **marker** is a row that is not a device record: a `Gap`, a view eviction, a
connect or a disconnect.

> **Invariant.** A marker is never hidden by a filter. The test is by type, at
> the single choke point where filtering happens, before any predicate runs.

The reasoning, which belongs next to the code: *a filter states which records
the user wants; a marker states the integrity of the answer.* Hiding it makes
the filtered view lie about its own completeness. This is the same principle
the exporters already follow — every one of them declares what it dropped.

Android Studio Logcat implements exactly this exemption in one line
(`it.header === SYSTEM_HEADER || filter.matches(...)`, reference identity,
short-circuited first) — and then failed to classify logd's own
`chatty … expire N lines` notice as a marker, so a `tag:` filter silently hides
the message explaining why data is missing. Classify **every** discontinuity as
a marker, including any that arrives looking like an ordinary record.

No surveyed product guarantees this for loss markers. It is unclaimed ground,
and it is cheap.

### The four marker kinds are not one kind

| Marker | Means | Recoverable? |
| --- | --- | --- |
| **Gap** | Records the device emitted and nothing received. `Gap(start, end, reason)`, written to the session file | **No.** Gone forever |
| **Evicted** | The view hit its row cap and dropped its own oldest rows | **Yes.** Still in the capture on disk |
| **Connected** / **Disconnected** | The device arrived or left | n/a |

**Gap and Evicted must not render as the same row.** They look alike and mean
opposite things: one says the data is gone, the other says the data is on disk
and merely not on screen. Rendering an eviction as a `Gap` would make the GUI
lie about the session file. The eviction row says so in its own words — *"…
earlier records are in the capture but not in this view"* — and offers to jump
into the session file.

Every tool surveyed gets the eviction case wrong by saying nothing at all:
Logcat's `trimToSize()` is silent, the AWS toolkit silently trims 10,000 lines
while faithfully reporting *server-side* sampling, and Console.app "holds no
more than a few seconds of data before it starts throwing away old lines" —
that last one at exactly this project's throughput. Copy Logcat's one good
habit: cut on a record boundary.

Gap wording follows the plaintext exporter, because `docs/formats/` wins:
`---- gap {start} to {end} ({reason}) ----`.

### Validation from Apple's own model

Unified logging already has a first-class loss record — firehose activity type
`0x07`, payload `{start_time, end_time, count}`, no message body, a peer of
`Log`/`Activity`/`Signpost`. `Gap(start, end, reason)` is the same object,
which is a good sign for a decision made without knowing that.

Two consequences worth recording rather than acting on now:

- Apple's carries a **count**; ours cannot, because ours is synthesised when a
  dropped connection is re-established and nothing counted what was missed. If
  `os_trace_relay` ever surfaces Apple's own loss records, those come with a
  count and a different `reason`.
- `log stream` **shows** dropped-message output by default and `log show`
  hides it. For a live viewer, show.

Whether `reason: str` should become a taxonomy — Windows Event Log separates
dropped (1101), cleared (1102), service stopped (1100) and started (6005),
storage full (1104), rolled over (1105) and per-record failure (1108) as
individually greppable IDs — is a **session-format** question, not a GUI one.
It is deliberately not decided here: `docs/formats/session-file.md` fixes the
answer for every capture already written. The GUI's marker kinds are a view
concept and cost the format nothing.

Gaps and errors also belong in a **scrollbar minimap** (Wireshark's Intelligent
Scrollbar, klogg's overview strip). It is the only mechanism found that reveals
a discontinuity outside the viewport, and the alternative is a user who never
learns the hole exists.

---

## 4. Follow

**Follow is derived from the viewport on every repaint. It is never a stored
bit.** Logcat computes its toggle from caret plus scrollbar; Console.app stored
a flag and shipped an eleven-month tail-breaks-on-selection bug. A stored bit
can disagree with the view, and then the button is lying.

**Breaks follow:** selecting a row, scrolling up by any amount, an explicit
jump. **Does not break follow:** horizontal scrolling.

The set must be *complete and symmetric*. klogg's is neither — a plain click
does not break follow but moving the selection down does — and a user cannot
build a mental model from that. With a detail pane, selection is the primary
interaction, so breaking follow on selection is not optional.

**One wheel-tick up exits follow.** klogg gates exit behind an elastic
accumulator (threshold 300, resistance `pos/8`, decay 4 per 10 ms) so slow
scrolling never exits at all; that is its issue #125.

**"Jump to bottom" and "resume following" are two commands, not one.** `Ctrl+End`
jumps; pressing it again at the bottom resumes following. Wireshark's
unresolved *"Ctrl End is close, but doesn't resume auto scroll"* is the cost of
conflating them.

Two indicators, because they are two different facts: whether follow is on, and
how many records have arrived unseen. Prefer text — klogg's issue #100 is an
icon nobody could decode.

---

## 5. Filtering and highlighting

**Two verbs over one expression language.** Filter removes rows; highlight
marks them in place. Wireshark, Procmon, DebugView and lnav all converge here,
and they compose: filter to `Error`, then highlight `404` within it.

Two refinements worth taking: a **gutter indicator**, so a highlight hit is
visible when the message column is truncated, and a **per-term hit count**,
which turns highlight into a free live aggregate.

**Filtering is incremental.** Each arriving batch tests only the new records
and appends matching indices — O(batch). Only a filter *change* rescans. This
is the hand-written index list from ADR 0004, not `QSortFilterProxyModel`,
which was measured at roughly 66× slower on a filter change (about 6 s against
about 0.09 s at 100k rows) — and 6 s is a frozen window, not a slow one.

> Note for anyone reading the prior-art research: it recommends implementing
> the marker exemption inside `QSortFilterProxyModel.filterAcceptsRow()`. The
> insight is right and the location is not available to us. The exemption goes
> at the head of our own predicate, which is the same choke point.

**Selection and viewport anchor to record identity across a filter change, not
to a row number.** After a rescan, resolve the focused record to its new row;
if it did not survive, fall back to the nearest survivor.

Nobody has solved this: Wireshark #16318 has been open since 3.0.7 (*"requires
some Qt interface wizardry"*), lnav clamps row ordinals and teleports, and
Logcat clears its document and re-appends, so **every keystroke in the filter
field throws the user to the bottom**. This is the clearest opportunity in the
whole phase to be better than the established tools, and it is worth real time.

The filter expression is **one text field whose contents are copy-pasteable**.
Google's stated reason for rewriting Logcat's filters in 2023 was that a
dialog-built filter cannot be shared and there was no history. Ship history,
with a match count on each entry so an over-narrow filter is visible before it
is applied. `level:` is a **threshold**, with a separate exact form — and note
that Apple's level values are not severity-ordered, so the threshold is over
our own enum.

---

## 6. States that must be visible

A paused stream looks exactly like a quiet device. An over-narrow filter looks
exactly like a dead one. Every invisible state gets a **persistent in-view
banner with a recovery action**, not a toolbar icon:

| State | Banner | Action |
| --- | --- | --- |
| Paused | Capture is paused. *N* records buffered | Resume |
| Everything filtered out | All records are hidden by the filter | Clear filter |
| No device | No device connected | Retry |
| Disconnected mid-capture | Device disconnected — reconnecting | Disconnect |
| Empty capture | This capture contains no records | — |

Logcat ships the first two with a one-click **Clear filter**; they are the two
that generate support questions everywhere else.

---

## 7. Pause and Disconnect

**Pause freezes the view. It never touches the source.**

This matters more here than in most viewers because of a rule this project
learned the expensive way: releasing a device releases the lockdown session
*and* the `os_trace_relay` service connection together. A pause that reached
the source would be a disconnect wearing a friendlier label, and the records
that arrived during it would be gone.

So: pause freezes `logRowsToRender` and nothing else — Grafana's model, which
promises *"without creating a gap in the log results"*. The stream keeps
running and keeps spooling to disk. DebugView's `Ctrl+E`, which conflates "stop
showing me" with "stop listening" and loses everything in between with no
marker, is the anti-pattern.

**The destructive control is called "Disconnect", not "Stop".** Grafana renamed
theirs to "Exit live mode" precisely because "Stop" was ambiguous against
"Pause". Ours releases the device, and the name should say so.

ostrace spools to disk, so pause can keep its promise honestly and needs no
ring buffer. Grafana promises "no gap" while backing it with a 1,000-line ring
that silently overwrites; CloudWatch buffers about ten seconds and then drops
the *oldest*, tearing a hole in the middle of the timeline rather than
truncating the tail. **If a bound is ever introduced here, it emits a `Gap`.**

---

## 8. Keyboard

**Alias both traditions rather than choosing between them.** klogg binds
find-next to `F3` *and* `n` *and* `Ctrl+G`, and jump-to-bottom to `Ctrl+End`
*and* `Shift+G`, shipping on Windows and macOS — this project's exact target
pair.

| Action | Bindings |
| --- | --- |
| Search | `Ctrl+F`, `/` |
| Next / previous match | `F3` / `Shift+F3`, `n` / `N` |
| Top / bottom | `Ctrl+Home` / `Ctrl+End`, `g` / `Shift+G` |
| Resume following | `Ctrl+End` again, at the bottom |
| Mark a row | `Ctrl+M`, `m` |
| Next / previous mark | `Ctrl+Shift+N` / `Ctrl+Shift+P`, `]` / `[` |
| Next / previous gap | `Ctrl+Shift+G` / `Ctrl+Alt+Shift+G` |
| Next / previous error | `e` / `Shift+E` |
| Step row while the detail pane has focus | `F7` / `F8` |
| Pause | `Ctrl+P` |
| Copy | `Ctrl+C` |

Use `QKeySequence.StandardKey` wherever one exists: `Ctrl` maps to `⌘`
automatically, but *bindings* differ per platform and the standard keys know
that.

Four traps, all from klogg:

- **Never bind a destructive verb to a standard editing chord.** klogg's
  `Ctrl+X` truncates the file on disk (#714).
- Do not let widget-level digit shortcuts eat a numeric prefix.
- Generate the documented key table from the same source as the bindings.
- Do not register an action with no default binding.

Bind pause. Neither Logcat nor Console.app does, and both are asked for it.

`F7`/`F8` row stepping while the detail pane holds focus is necessary rather
than a nicety, exactly as Wireshark documents: *"even if the packet list isn't
focused"*.

Marks outrank every colour rule. A `Gap` does **not** discard them: klogg
discards all marks on truncation with an unresolved `TODO` (#179, a regression
against glogg); the better answer, proposed by its own users, is to keep the
mark and flag it unverified.

---

## 9. Detail pane

A **bottom panel**, plus a separate cheap **in-row expansion** on
`Right`/`Left`. Console.app does both for exactly this record type.

Their stream semantics are borrowed from CloudWatch and are worth stating
because they are not obvious: **row expansion keeps the stream running; opening
the detail panel pauses it.** Expansion is a glance, the panel is a study.

Do not budget performance work for the detail pane. Wireshark's own guidance
names real-time list update, **colouring rules** and name resolution as the
cost centres. The delegate is what to optimise. Also from Wireshark: expose an
*interval between updates* preference, and never recompute the whole list on a
selection change — that is what made its auto-scroll jump (bug 12130).

---

## 10. Theme

**The theme is a function from a colour scheme to a `QPalette`, seeded from the
OS palette at run time.** It is not a set of colours read out of the palette,
and it is not a stylesheet.

That shape is forced by measurement, and it happens to solve three problems at
once — which is how you know it is the right one:

- `QStyleHints.setColorScheme()` is a **no-op under the `offscreen` platform
  plugin** *(measured: `colorScheme()` stays `Unknown`, the palette never
  changes, `colorSchemeChanged` never fires, and the Fusion style does not
  rescue it)*. `QApplication.setPalette()` works under every plugin
  *(measured)*. So the CI screenshot job can force either scheme, on macOS
  included — which the naive approach cannot.
- The colour maths becomes assertable in the offscreen test lane, where no
  platform theme exists.
- A live OS theme switch is the same function called again from
  `colorSchemeChanged`, which is verified to fire on Windows *(measured:
  `ThemeChange`, `StyleChange`, `PaletteChange` per switch)*.

Derive from the palette roles rather than inventing colours: `Base` /
`AlternateBase` for row backgrounds, `Text`, `Highlight` / `HighlightedText`,
`PlaceholderText` for dimming — the theme's own grey is better than ours — and
`Accent`.

**Colour is never the only cue for severity.** The Level column is text and
stays text. A background tint at 14% sits at roughly 1.12–1.22:1 against `Base`
— nowhere near a legibility threshold, which is an argument for tinting as
*reinforcement* and never as *information*. `ERROR` and `FAULT` additionally
carry a leading glyph, so a screenshot survives being printed, and a
colour-blind reader loses nothing.

**Force the Fusion style.** It is the only style besides `windows`/`windows11`
that supports dark at all, the Qt blog calls it the preferred style for
Windows 11, and QTBUG-130480 — where the windows11 style repaints partly in the
old theme after a switch — explicitly does not reproduce under it. For a
project with no Mac there is a second benefit that matters more: **Windows
becomes a faithful preview of macOS.** Apply it *after* constructing the
`QApplication` (QTBUG-126870), and re-apply the palette afterwards, because
`QApplication` resets the palette on a style change.

---

## 11. Performance rules

**This table supersedes the one in ADR 0004.** Those figures came from
published reports; these were re-measured on PySide6 6.11.1, and half of them
did not survive.

| Rule | Status |
| --- | --- |
| **Override `QHeaderView.initStyleOptionForIndex`** | **The single biggest lever**, and it does not cost the column titles. The header asks the selection model, per section, whether the whole column is selected; QTBUG-59478 has been open since 2017 and its fix was *abandoned* the same year. Measured at 200k rows × 6, `selectAll()`, best of three: **3.896 s → 0.007 s, 584×**, `flags()` calls 1,200,689 → 683, header still visible. Implemented as `gui.widgets.log_table.FastHeader`. Hiding the header entirely is the cruder version of the same fix |
| `QTableView` only, never `QTreeView`/`QListView` | **Keep the rule.** The evidence is stale: the "20M `rowCount()` calls" figure was fixed by Qt change 601341, merged 2024-11-01 and backported to 6.8, which this project already pins. `QTableView` is still fastest |
| Cache the `flags()` return value | **Keep, restated.** Measured ~1.3× (3.47 s → 2.55 s at 200k), not 20×. The ADR's "7.760 s → 0.396 s" conflated time-inside-`flags()` with an operation total. It is one line and still worth it — but the calls it optimises are *caused* by the header, and `FastHeader` removes 1,199,000 of the 1,200,689 outright. Fix the cause first |
| Override `multiData()` | **Deleted.** Measured **0.96–0.99× — marginally slower.** Qt does query exactly 7 roles per cell and a Python override *is* called, but the span must be iterated from Python, so 7 inbound crossings become 1 inbound plus ~14 outbound. True in C++, false in PySide6 |
| Never `ResizeToContents` | **Keep, tightened to the *vertical* header.** QTBUG-57848 is about the vertical header specifically; for the horizontal one, `resizeContentsPrecision` (default 1000) already bounds the scan. Still open, P5, dormant since 2019 |
| Fixed row height via `verticalHeader().setSectionResizeMode(Fixed)` | **Keep.** `QTableView` genuinely has no `setUniformRowHeights()` *(measured: absent on `QTableView`, present on `QTreeView`)* |
| Prebuild every `QBrush`/`QColor`; `setWordWrap(False)`, elide right | **Keep.** Untested, but `data()` runs per cell per role, and wrapping forces per-row height computation — the probe table wrapped by default, so this is load-bearing rather than cosmetic |
| Avoid `Qt.X.Y` attribute chains in hot paths | **Added.** This is the real Python-model lesson that the `flags()` result was pointing at: at 800k calls, `Qt.ItemFlag.A \| Qt.ItemFlag.B` costs 0.754 s against 0.051 s for a prebuilt attribute |

Unchanged from ADR 0004 because they were architecture, not measurement:
producer thread → `deque.append` → `QTimer` drain every 50 ms → one
`beginInsertRows` per batch, never one signal per record; and a plain list with
a hard cap around 200k, trimmed only once it overflows by 10% and then in a
single `beginRemoveRows`, never `deque(maxlen=)`, which evicts silently and
desynchronises the view.

---

## 12. What CI can and cannot verify

`QWidget.grab()` and `QWidget.render()` produce **real pixels under the
offscreen plugin**, on a widget that was never shown *(measured)*. So a
screenshot needs no display, no window manager and no xvfb — including on
macOS, which is the only way this project will ever see its own macOS UI.

One trap, and it is invisible until you look at the image: **the offscreen
plugin's font database is empty on Windows** *(measured: 0 families against 154
under the native plugin)*. Text renders as tofu boxes while `QFontMetrics`
keeps returning plausible numbers. Two consequences:

- Screenshots use the **native plugin on Windows and offscreen on macOS**.
  Registering a font with `QFontDatabase.addApplicationFont()` also fixes it
  *(measured)* and is the fallback.
- **No test may assert a font metric under offscreen.** The same string
  measured 60 px there and 36 px natively. Column widths, elide positions and
  row heights are all off-limits; model behaviour is unaffected, since it never
  touches a font.

| Verified in the offscreen lane, every OS | Not verifiable there |
| --- | --- |
| Model: filtering, the row cap, marker exemption, batch insertion | Colour-scheme switching (`setColorScheme` is a no-op) |
| The theme function's colour maths | Anything font-metric dependent |
| Signal and state machinery | Native menu placement — see below |

The screenshot job is `workflow_dispatch`-only: a documentation tool, not a
gate. It renders each screen in both schemes and uploads with
`if-no-files-found: error`, so a silent capture failure fails the run rather
than producing an empty artifact nobody notices.

### The screenshot job cannot show the macOS menu bar, and that is structural

The first run made this plain. On macOS under the offscreen plugin the window
renders correctly — real fonts, correct palette, layout matching Windows almost
pixel for pixel — and it draws the menu bar **inside the window**, because the
offscreen plugin has no native menu integration.

Switching to the `cocoa` plugin would not fix it. On macOS the menu bar belongs
to the *screen*, not to the window, so `QWidget.render()` cannot contain it by
construction, whatever the plugin. Capturing it would need a real window-server
session and a full-screen grab.

So the picture proves layout, fonts, palette, elision and clipping on macOS. It
does **not** prove that a menu item stayed where it was put. **The menu-role
test is the only guard for that**, which is why it asserts the property rather
than an appearance: every clickable item in the menu bar declares a `MenuRole`,
so no item is left on the text heuristic that would relocate it.

Do not read the presence of a macOS screenshot as coverage of the menu trap.

---

## 13. Deliberately out of scope for phase 4

- **Substring selection inside a message.** `QTableView` selects whole cells.
  Cell and row copy ship; a read-only `QLineEdit` delegate does not. The detail
  pane covers the common case, as ADR 0004 already records.
- **Context lines around a match** (`grep -C`). LogExpert's Back Spread / Fore
  Spread is the only GUI implementation found and the demand is real, but with
  process, subsystem and PID on every row a *relational* filter — everything
  else from this process around this moment — probably serves the need better.
  Decide after the filter language exists.
- **Per-pane follow.** Only relevant with two list panes, which phase 4 does
  not have. Noted because klogg's single shared flag has been issue #211 since
  2020 and retrofitting it is the expensive order.
- **A `Gap` reason taxonomy.** A session-format decision, not a GUI one (§3).
