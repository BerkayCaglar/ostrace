# ostrace — competitive landscape for the GUI

Research-only report. Nothing in the repo was modified.

Scope: what the competing log viewers actually look like today, what their users
document as complaints, and where the opening is for ostrace's PySide6/Qt Widgets
viewer. Every claim that is not a direct observation of the ostrace source carries
a URL.

**Baseline — what ostrace 0.1.0 already ships** (read from
`src/ostrace/gui/` and
`docs/design/gui.md`):

- Menu bar only. **No toolbar, no device selector** (`docs/design/gui.md` §1 says so
  explicitly: "0.1.0 has no toolbar and no device selector").
- Fielded filter bar: `Level ▾  Process  Subsystem  Search □ Regex`
  (`gui/filters.py` — a conjunction of four terms, level is a threshold over
  ostrace's own ordered `Level` enum, invalid regex raises rather than emptying
  the view).
- Six-column virtualised `QTableView`; bottom detail pane with all eleven fields
  plus device-vs-host timestamp delta.
- Minimap strip (errors bucketed, gaps and marks placed exactly).
- Marks (amber, deliberately not the accent colour), gap/eviction markers that a
  filter may never hide, banners for the invisible states, follow derived from the
  viewport rather than stored.
- Status bar: four readouts — rate, device, volume, **gap count always rendered
  including zero**.
- 21 keyboard bindings generated from one table (`gui/shortcuts.py`), aliasing both
  the `Ctrl+End`/`F3` and the `G`/`n` traditions; `F1` renders the same table.
- Theme: deterministic `QPalette` from 16 hex literals per scheme, Fusion style
  forced, severity foregrounds asserted against WCAG AA in CI (`gui/theme.py`).
- **Selection and viewport anchor to record identity across a filter change**, not
  to a row ordinal (`docs/design/gui.md` §5).

Known gaps I will refer back to: no toolbar, no filter persistence/history/sharing,
no highlight verb (only filter), no "showing N of M" readout, no follow indicator,
no unseen-record count, no reconnect banner, no monospace/typographic treatment of
the message column, no icons at all.

---

## 1. Apple Console.app (macOS), including device mode

### What the window looks like today

A three-part NSWindow: a **left sidebar** listing Devices (the Mac itself, plus any
tethered iPhone/iPad/Watch) and Reports; a **toolbar** with Start/Pause streaming,
Clear, Reload, Now, Activities, Action; a **search field** on the right that builds
tokenised filters; a flat, low-density table with **rigid fixed columns**; and an
optional info pane. Dark mode is inherited from AppKit and is fine. Typography is
the system UI font at a comfortable but space-hungry size — Howard Oakley,
introducing his own replacement browser, specifically praises getting readability
"without sacrificing too much space as in Console's rigid columns"
(<https://eclecticlight.co/2025/02/26/introducing-logui-an-experimental-log-browser/>).

Device mode: select the iPhone in the sidebar and Console streams `os_log` from it.
Apple's own canonical guide ("Your Friend the System Log", Quinn) documents it as
"On the left, select either your local Mac or an attached iOS device"
(<https://developer.apple.com/forums/thread/705868>).

### Killer features

- **Genuinely sophisticated search tokens.** `subsystem:com.foo.bar` etc., and the
  search field "supports copy and paste" — so a filter *is* shareable text
  (<https://developer.apple.com/forums/thread/705868>). ostrace's fielded bar is
  not.
- **Saved searches (Favorites).** Quinn: "Console supports saved searches"
  (same URL). Persisted filters are table stakes and ostrace has none.
- **Time-window scoping.** "By default it shows the last 5 minutes" (same URL).
- **Zero install, already on every Mac, and it speaks to the device.** That is the
  real moat and ostrace cannot beat it on macOS — it beats it by existing on
  Windows and Linux at all.

### Documented complaints

This is the richest complaint corpus of any tool surveyed.

- **The firehose.** Michael Tsai's roundup, "Console, the Vital Tool That Apple
  Abandoned", collects: "It's such a firehose, I don't know how anyone can make
  sense of it"; Console "has become virtually useless if you don't know what to
  filter for"; processes like healthd/hidd "make you spend the next ten minutes
  filtering out noise"; "vast quantities of worthless spew generated every second"
  (<https://mjtsai.com/blog/2020/06/26/console-the-vital-tool-that-apple-abandoned/>).
  Two commenters in that thread say they stopped using Console entirely.
- **Search is a filter, not a find — and it destroys your place.** Apple Discussions
  thread 254884707: the user expects Find to locate text in context, and instead
  "If I enter text in the Search field the log is filtered"; worse, the selected
  text does not remain selected after clearing the search field. The accepted
  workaround was to leave Console and open the file in VS Code
  (<https://discussions.apple.com/thread/254884707>). A reply from etresoft says
  Console "has virtually no value at all" and "only displays the log messages while
  you have it enabled".
- **Nothing before you pressed Start.** Console streams live only; the entry you
  wanted "happened before you launched it"
  (<https://mjtsai.com/blog/2020/06/26/console-the-vital-tool-that-apple-abandoned/>).
- **No aid at volume.** Oakley: Console "struggles to cope with logarchives of any
  size", offers "little aid for the high volume of entries", "no access at all to
  recent entries in the live log", "displays just a small selection of entry fields"
  and makes "only limited use of log entry structure" — against a unified log with
  25+ fields
  (<https://eclecticlight.co/2024/12/21/a-brief-history-of-logs-and-console/>).
- **Retention has collapsed.** Same article: what used to be ~20 days is now
  "little longer than a few hours" as tracev3 files roll.
- **`<private>` redaction.** Strings are redacted by default on a device that is not
  being run from Xcode, so the message you wanted reads `<private>`
  (<https://developer.apple.com/forums/thread/738648>,
  <https://github.com/EthanArbuckle/unredact-private-os_logs>). Apple documents the
  opt-outs (`privacy: .public`, `OSLogPreferences` / `Enable-Private-Data` in
  Info.plist) but nothing in Console *tells you* that is why the line is empty.
- **The strongest signal of all: three independent replacement browsers.** Howard
  Oakley wrote Consolation (2017), Ulbow (2019) and LogUI (2025) because "what used
  to be a primary tool in diagnosing problems has been abducted without replacement"
  (<https://eclecticlight.co/2024/12/21/a-brief-history-of-logs-and-console/>,
  <https://eclecticlight.co/2025/02/26/introducing-logui-an-experimental-log-browser/>).
  People do not write three replacements for a tool that is fine.

**Do not copy:** search-as-filter with no separate find/highlight verb; hiding Info
and Debug by default without saying so on screen; a fixed rigid column layout with
no density control.

---

## 2. Xcode console / Devices & Simulators

### What it looks like

Two different surfaces, both weak:

1. The **debug console** in the Xcode workspace — a text pane at the bottom.
   Xcode 15 rewrote it with per-level colouring, a filter box with a **Recent
   Filters** section, and a scope selector (All Output / Debugger Output / Target
   Output) (<https://www.avanderlee.com/xcode/xcode-debug-console/>,
   <https://nilcoalescing.com/blog/FilteringLogsInXcode15/>).
2. **Window ▸ Devices and Simulators ▸ Open Console** — which just launches
   Console.app's device view, so it inherits everything in §1
   (<https://intercom.help/deploygate/en/articles/4682692-getting-the-device-log-in-xcode>).

### Killer feature

Structured logging in Xcode 15: colour per level, metadata shown inline,
click-through to source, and **the filter persists from run to run**
(<https://www.avanderlee.com/xcode/xcode-debug-console/>). Filter persistence is
exactly what ostrace lacks.

### Documented complaints

- **Framework spew drowns your own logs.** "Console flooded with CFNetwork and
  DataDetectorsUI Logs" (<https://developer.apple.com/forums/thread/748493>);
  "RealityKit generates an excessive amount of logging" that is "not actionable by
  third-party developers", with the reporter saying they re-apply filters dozens of
  times a day (<https://developer.apple.com/forums/thread/794813>); the older
  "Xcode 8 - System log noise in Console"
  (<https://developer.apple.com/forums/thread/51196>) and "Debug console now has too
  much info" (<https://developer.apple.com/forums/thread/51260>) show this is a
  decade-old, unfixed complaint.
- **`OSLogPreferences` is ignored under Xcode.** Developers who correctly configure
  suppression find Xcode's console hooks bypass it
  (<https://developer.apple.com/forums/thread/745425>).
- **Xcode silently drops log records at high rate.** An Apple Developer Tools
  engineer confirms, in an accepted answer: when streaming, "data rate becomes too
  large and we have to drop logs", with no back pressure, versus the default
  synchronous collection that applies "back pressure on your process"
  (<https://developer.apple.com/forums/thread/771147>). The user-visible artefact is
  a warning about "log/signpost messages lost due to high rates".
  **This is the single most important finding in the whole report for ostrace's
  positioning** — see §9's Gap/Eviction argument.

**Do not copy:** a console that is a text buffer rather than a table; a console
whose only "column" is a formatted line.

---

## 3. Android Studio Logcat (the 2022 rewrite) — the closest analogue

### What it looks like today

A tool window with a real **toolbar** (Clear, Pause, Restart, Scroll to the End,
Soft-Wrap, Configure Logcat Formatting Options, New Tab, Show history), a
**single query field** at the top, and the log view below. It supports **tabs** and
**split panels** (Split Right / Split Down), each split with its own device, query
and view options. Two view modes — **Standard** and **Compact** — plus per-field
toggles for timestamp, tags, process IDs and package names. Colours are themable via
Settings ▸ Editor ▸ Color Scheme ▸ **Android Logcat** and **Logcat Filter**
(<https://developer.android.com/studio/debug/logcat>).

### Killer features (this is the feature set ostrace should measure itself against)

- **A real query language with autocomplete.** `tag:`, `package:`, `process:`,
  `message:`, `level:`, `age:` (`5m`, `3h`, `1d`); negation with a leading `-`
  (`-tag:MyTag`); regex per field with a trailing `~` (`tag~:My.*Tag`); combinable
  (`-tag~:...`); `&`, `|` and parentheses; implicit OR within a key and AND across
  keys. `Ctrl+Space` completes. (Same URL.)
- **Semantic shortcuts:** `package:mine`, `is:crash`, `is:stacktrace`,
  `level:INFO` meaning INFO-and-above.
- **Filter history and starred favourites**, persisted across projects, with
  `name:<identifier>` to label a saved query. Autocomplete draws from history.
- **Session persistence across app crashes** — tabs, filters and view options
  survive; `PROCESS ENDED` / `PROCESS STARTED` markers are inserted inline.
- **Configurable cycle buffer size** and a default filter for new windows.

Google's **stated reason** for the rewrite is directly applicable to ostrace's
current fielded bar: the old UI let you either do a regex string search or build a
filter by populating fields, and "the second option made sharing and setting up
queries more difficult"
(<https://developer.android.com/studio/releases/past-releases/as-dolphin-release-notes>,
<https://alexzh.com/new-logcat-5-features-for-effective-android-app-debugging/>).
ostrace ships exactly the option Google abandoned.

### Documented complaints

- **Autoscroll fights the user.** Google issue 225987089, "Logcat autoscrolls to the
  end", filed 2022-03-21 (<https://issuetracker.google.com/issues/225987089>);
  the older "prevent to auto scroll to bottom", issue 70149059
  (<https://issuetracker.google.com/issues/70149059>). Note the issue bodies require
  sign-in; the titles and filing dates are public and are the citable part.
- **Pause was requested for eight years.** "Android Studio: Add pause option to
  logcat view", issue 36996561, filed 2014-06-06
  (<https://issuetracker.google.com/issues/36996561>) — shipped only in the rewrite.
  ostrace binds Pause to `Ctrl+P` already.
- **The filtered-empty banner is a real, ticketed problem** — Google issue 247786909
  concerns the "All logs entries are hidden by the filter" banner
  (<https://issuetracker.google.com/issues/247786909>). ostrace ships that banner
  with a one-click Clear filter.
- **Someone wrote a replacement in disgust.** `LessShittyLogcat` exists, and its
  selling points read as a list of Logcat's failures: "Jerk-free scrolling without
  scroll lock constantly re-enabling itself"; "View filtered and unfiltered logs at
  the same time. Separate buffers"; a pause that leaves "the logcat connection open,
  but queue[s] up messages"; message grouping when a thread emits several messages
  at the same timestamp; and wrapping so a message is "not split over a bunch of
  different lines" (<https://github.com/JonathanDotCel/LessShittyLogcat>).
  The pause behaviour it advertises is *exactly* ostrace's §7 model.
- **Clear-on-crash / clear semantics** have long been complained about
  (<https://issuetracker.google.com/issues/37012950>,
  <https://dev.to/hameteman/how-to-not-clear-the-logcat-on-a-crash-1phi>).
- **The document-rebuild problem.** As `docs/design/gui.md` §5 records, Logcat
  clears its document and re-appends on a filter change, so a keystroke in the query
  field throws you to the bottom. The autoscroll issues above are the user-visible
  face of that.

**Copy:** query language with autocomplete; history + starred favourites; compact vs
standard density toggle; the filtered-empty banner with a one-click escape; cutting
the buffer on a record boundary.
**Do not copy:** rebuilding the document on every filter change; auto-scroll that
re-enables itself; hiding the pause verb for eight years.

---

## 4. Wireshark — the reference virtualised table

### What it looks like

Menu bar, an icon toolbar, a **display filter bar** with live green/red/yellow
validity tinting and a bookmark button for saved filters, then three stacked panes:
packet list (dense, coloured by rule), packet detail tree, packet bytes. An
**Intelligent Scrollbar** paints a minimap of the colouring rules down the right
edge — the direct ancestor of ostrace's minimap strip. Status bar shows
`Packets: N · Displayed: M (x%)`, which is the "showing N of M" readout ostrace does
not have.

### Killer features

- **The display filter language**, with autocomplete, validity colouring, and
  **saved/bookmarked filters** in the filter bar itself.
- **Colouring rules** — user-defined, ordered, editable, and reflected in the
  Intelligent Scrollbar.
- **Filter vs find as separate verbs** (display filter removes; Find Packet
  locates), which is the split `docs/design/gui.md` §5 argues for and ostrace has
  not yet shipped.
- **Column customisation** driven by protocol fields.

### Documented complaints

- **The selected packet is lost when the display filter changes.** The canonical
  thread: a user asks for "the selected line not move" when a filter is applied and
  removed; Jaap answers that no such option exists, that it is "not a trivial
  matter" and "requires some Qt interface wizardry"
  (<https://ask.wireshark.org/question/14032/selected-packet-position-when-display-filter-is-removed/>).
  The corresponding enhancement, issue 16318 (Qt UI moves the selected packet on
  filter change, filed against 3.0.7 by John McCabe), is **still not resolved** —
  the tracker page renders it as `UNCONFIRMED`
  (<https://gitlab.com/wireshark/wireshark/-/issues/16318>).
  **This is a Qt application, with a full-time paid dev team, that has not fixed
  this in six years. ostrace ships it.**
- Related loss-of-place bugs: "Moving a column deselects selected packet and moves
  to beginning of packet list" (<https://gitlab.com/wireshark/wireshark/-/issues/16251>);
  "Vertical Scroll Bar Disappeared after using Display Filter"
  (<https://gitlab.com/wireshark/wireshark/-/issues/220>); autoscroll jumping
  (<https://osqa-ask.wireshark.org/questions/56089/autoscroll-jumping/>);
  scroll rate not configurable (<https://gitlab.com/wireshark/wireshark/-/issues/18213>).
- **Ctrl+End does not resume auto-scroll** — quoted in `docs/design/gui.md` §4 as
  the cost of conflating "jump to bottom" with "resume following". ostrace already
  separates them.
- **The UI reads as dated.** Review aggregators are blunt: "the design dated, the
  navigation confusing"; the interface "can feel dated" and "doesn't feel the most
  intuitive"; "overwhelming and dated for new users"
  (<https://thectoclub.com/tools/wireshark-review/>,
  <https://www.capterra.com/p/209737/Wireshark/reviews/>,
  <https://www.g2.com/products/wireshark/reviews?qs=pros-and-cons>). Two terminal
  reimplementations exist partly in response
  (<https://news.ycombinator.com/item?id=38531181>,
  <https://news.ycombinator.com/item?id=47128535>).
- **Filter autocomplete gaps**, e.g. Find Packet does not autocomplete filters
  (<https://gitlab.com/wireshark/wireshark/-/issues/16638>).

**Copy:** the displayed-vs-total status readout; saved filters bookmarked in the
filter bar; live validity tinting of the filter field; the scrollbar minimap.
**Do not copy:** three fixed panes with no density control; an icon toolbar of
16px monochrome glyphs nobody can read; conflating jump-to-bottom with resume.

---

## 5. The modern web log explorers — Sentry, Datadog, Grafana

These are not competitors. They are the reference for what a 2026 log UI is expected
to feel like, and the source of several ideas that are cheaper in Qt than they are on
the web because ostrace has the whole capture in process.

### 5a. Sentry (Explore ▸ Logs)

Single-column page: global filter row (project/environment/time) → query bar →
optional **Visualize** chart → table with **rows that expand in place** into a
properties panel. No permanent facet sidebar. An **Aggregates** tab switches the same
table to one-row-per-group with `Group By` + count/sum/avg
(<https://docs.sentry.io/product/logs/>).

Killer features:
- **Promote a property to a column** from an expanded row — "individual properties can
  be added as columns to the results view" (same URL). Directly portable.
- **Auto-refresh (live tail) as a mode with stated invariants**: only when sorted
  descending by time and on a relative range; auto-disables above ~100 logs/sec or
  after 10 minutes (<https://sentry.io/changelog/auto-refresh-your-logs/>). The lesson
  is not the limits, it is that the app *states* them instead of misbehaving quietly.
- **Log pinning** — pinned rows stick to the top as a sticky header while you scroll
  and re-query (<https://sentry.io/changelog/log-pinning/>). This is a competitor's
  answer to "keep my place", and it is weaker than ostrace's: it needs an explicit
  user act, where ostrace's anchoring is automatic.
- The 2024–26 issue-UI rewrite is explicitly built on **progressive disclosure** —
  drawers rather than always-on panels
  (<https://sentry.io/changelog/new-issue-details-ui-now-available/>).

Complaints: timestamps without milliseconds breaking ordering
(<https://github.com/getsentry/sentry/discussions/86804>); over-eager PII scrubbing
mangling legitimate log text (same thread — a warning against "smart" transforms on
displayed text); and a long run of table-column ergonomics bugs
(<https://github.com/getsentry/sentry/issues/78305>,
<https://github.com/getsentry/sentry/issues/86290>,
<https://github.com/getsentry/sentry/issues/88648>).

### 5b. Datadog Log Explorer — the canonical four-zone layout

Query bar (autocomplete + syntax highlighting + recent searches) / time picker;
**left facet panel**; **histogram** over the current query; **list view**; **right
side panel** on row click.

- **Facets with counts.** Qualitative facets show "a top list of unique values, and a
  count of logs matching each of them"; numeric facets show "a slider indicating
  minimum and maximum values"; a facet-search box matches both display name and field
  name (<https://docs.datadoghq.com/logs/explorer/facets/>). Checkboxes rewrite the
  query — sidebar and query bar are two views of one state.
- **Query bar as an editor.** "The Log Explorer query bar autocompletes your queries";
  syntax highlighting "clearly differentiates input types, such as keys, values, free
  text, and control characters"; and power users can turn both **off**
  (<https://www.datadoghq.com/blog/search-logs-datadog-log-management/>).
- **Saved Views** = query + time range + visualisation + column config, addressable
  and shareable (<https://docs.datadoghq.com/logs/explorer/saved_views/>).
- **"View in Context"** — the surrounding-logs feature; it *rewrites the current
  search* to show lines around the selected one, deriving the context key from
  hostname/service/filename/container
  (<https://docs.datadoghq.com/logs/explorer/side_panel/>).
- **Content Height / Content Display** options: single-line vs wrapped multi-line rows
  (<https://docs.datadoghq.com/logs/explorer/visualize/>).
- **Patterns view** clusters similar messages and highlights the *variable* parts
  inline in yellow, with a hover preview of each token's value distribution
  (<https://docs.datadoghq.com/logs/explorer/analytics/patterns/>). iOS system logs are
  heavily templated; this is the single most under-exploited idea in the survey, and
  ostrace already has `analysis/templates.py`.
- **Live Tail samples uniformly at random** under load and says so, rather than
  dropping silently (<https://docs.datadoghq.com/logs/explorer/live_tail/>).
- **Dark mode has its own data-colour ramps** (Viridis/Plasma), not an inverted
  stylesheet (<https://www.datadoghq.com/blog/introducing-datadog-darkmode/>).

Complaints: the UI "can be heavy", large views "lag or fail to load", search
occasionally refusing to work
(<https://medium.com/@joachim_43659/bitten-by-the-datadog-when-monitoring-bites-back-335398adb0a8>);
cluttered for newcomers (<https://www.capterra.com/p/135453/Datadog-Cloud-Monitoring/reviews/>);
Live Tail fails often enough to need a dedicated troubleshooting page
(<https://docs.datadoghq.com/logs/troubleshooting/live_tail/>).

### 5c. Grafana Explore / Loki / Logs Drilldown

Query editor → **log volume histogram** → logs list → per-row **Log details**
(<https://grafana.com/docs/grafana/latest/explore/logs-integration/>).

- **Positive/negative filter buttons** on every field in Log details — include this
  value / exclude this value, rewriting the query.
- **"Show context"** is literally `grep -C`: N lines around the match, **adjustable
  window**, label filters editable *inside* the context view, "open in split view".
  `docs/design/gui.md` §13 declared context lines out of scope for phase 4 on the
  grounds that LogExpert was the only GUI implementation found — that is now wrong:
  Grafana and Datadog both ship it.
- **Live tailing with four separate controls: Pause / Resume / Clear logs / Stop.**
  Four, not one. This is exactly ostrace's §7 argument, shipped.
- Display options: **deduplication at four levels (None / Exact / Numbers /
  Signature)**, wrap lines, prettify JSON, font size, timestamp format, text
  highlighting, download as TXT/JSON/CSV.
- **"Copy shortlink"** — a URL to a *specific log line* which, when opened, scrolls to
  and highlights it. The best "share your place" primitive found anywhere.
- **Logs Drilldown** (queryless): service list by volume, then Logs / Labels / Fields /
  Patterns tabs, with small-multiple volume sparklines per label so you choose by
  *shape* rather than by typing; every panel has an escape hatch back to raw LogQL
  (<https://grafana.com/docs/grafana/latest/explore/simplified-exploration/logs/>).

Complaints, and they are the important ones:
- **"your scroll position will be forgotten once a new line gets added. You'll be
  automatically scrolled to the bottom again"** —
  <https://github.com/grafana/grafana/issues/90732>.
- Scroll/pagination churn: <https://github.com/grafana/grafana/issues/71728>,
  <https://github.com/grafana/grafana/issues/67625>,
  <https://github.com/grafana/grafana/issues/79196>,
  <https://github.com/grafana/explore-logs/issues/396>.
- **Vanishing logs when pausing Loki in Explore mode** —
  <https://github.com/grafana/grafana/issues/90531>. A pause that loses data is
  precisely the anti-pattern `docs/design/gui.md` §7 was written against, and Grafana
  — the tool that document cites approvingly — has the bug.
- Hacker News on the queryless UI (<https://news.ycombinator.com/item?id=39979750>):
  "The explore ui for setting labels is atrocious and painful"; another commenter
  compares it to "looking through a straw with oven mitts on" against plain text
  tools.
- Pushing every UI state change into browser history broke their own tabs
  (<https://github.com/grafana/logs-drilldown/issues/1015>) — a failure mode a Qt app
  simply does not have.

---

## 6. Proxyman vs Charles — the "looks current" reference, and Instruments

### 6a. The finding that matters most

**Proxyman is native Swift on macOS and Electron on Windows and Linux**
(<https://github.com/ProxymanApp/proxyman-windows-linux>,
<https://proxyman.com/changelog-windows>). Charles is native-widget Java/Swing
(<https://en.wikipedia.org/wiki/Charles_Proxy>). The tool people call modern is the
*less* native one. Modernity is spacing, icon discipline, flat surfaces, restrained
colour and a real dark theme — not the toolkit. Qt Widgets can hit all five.

Proxyman's own layout: left sidebar (grouped/pinned domains, sessions), centre request
table, right/bottom tabbed detail pane, top toolbar; "Customize toolbar, panels,
columns, and tabs"; **saved filter presets**; "Pin working domains and hide noisy
traffic"; light and dark themes throughout (<https://proxyman.com/>).

Charles' visual reputation, in users' own words:
- Scott Gruby's review is titled "Useful development tool; ugly interface" —
  "The interface doesn't look like a Mac app"
  (<https://blog.gruby.com/2010/08/29/review-charles-proxy-useful-development-tool-ugly-interface.html>).
- Hacker News, Dec 2025 (<https://news.ycombinator.com/item?id=46333983>): one
  commenter "couldn't recognize all its unlabeled icons without hovering for
  tooltip"; another, "Turning on/off features always a journey through menus";
  others prefer Proxyman for being "better, easier, and more macOS friendly" and for
  performance.
- Users patch a modern look-and-feel in themselves — a 2022 write-up shims FlatLAF
  into Charles (<https://jixun.uk/en/posts/2022/restyle-charles-using-flatlaf/>).

**The single most actionable finding in this whole report: what people name as
"dated" is the unlabelled icon toolbar, not the colours or the fonts.**

### 6b. Dated-vs-current checklist, translated to Qt Widgets

| Axis | Dated (Charles) | Current (Proxyman) | Qt action |
| --- | --- | --- | --- |
| Toolbar | many small **unlabelled** coloured bitmap icons | few large monochrome line icons, several with text labels, rest in menus | `QToolButton` with `ToolButtonTextBesideIcon` for 4–6 primary verbs only |
| Icons | raster, coloured, ~16px, inconsistent metaphors | one monochrome line set on a consistent grid | one SVG set, HiDPI, recoloured from `QPalette` |
| Typography | one Java default size, no hierarchy | system UI font, 2–3 sizes, secondary text dimmed | keep the platform UI font for chrome; **monospace for message and timestamp only** |
| Spacing | tight, widgets touching the frame | consistent 4/8 px rhythm, generous row padding | one spacing constant; row height ~26–30 px at 100% DPI |
| Relief | bevels, sunken frames, etched separators | flat surfaces separated by background-tone deltas | `QFrame::NoFrame`; 1 px hairline at ~8% contrast |
| Colour | grey chrome + saturated everything | neutral chrome; colour only for semantics | colour carries level only — already ostrace's §10 rule |
| Table | +/- expanders, dotted lines, harsh zebra | chevrons, no lines, ≤4% zebra or none | alternating base at a very small delta |
| Scrollbars | full-width with arrow buttons | thin, no arrow buttons | QSS with `::add-line`/`::sub-line` height 0 — *see the caveat in §9* |
| Dark mode | absent or accidental | designed, at parity | ostrace already has this |
| Discoverability | features buried in nested menus | row-hover inline actions, rich context menus | hover-revealed filter-in/filter-out/copy on a row |

### 6c. Instruments

Toolbar (Record/Pause/Stop, device and process pickers) → **track pane** with a track
filter and **track pinning** → navigation bar → **detail pane** with its own filter
bar → right-hand inspector showing stack traces with your frames white and system
frames grey. The **inspection head** is a scrubber; **dragging across the track pane
selects a time window and the detail table filters to it**; flags can be dropped in
the timeline to mark places
(<https://developer.apple.com/videos/play/wwdc2019/411/>,
<https://developer.apple.com/library/archive/documentation/AnalysisTools/Conceptual/instruments_help-collection/Chapter/Chapter.html>).

Borrow three things, leave the rest:
1. **Drag-select on a timeline to filter the table below.** This is the right
   generalisation of the Datadog/Grafana histogram: the brush *is* a filter, not just
   a zoom.
2. **Flags anchored to time.** A time-anchored marker survives a filter change by
   construction — the same insight as ostrace's record-identity anchoring, arrived at
   from the other direction.
3. **Pinning a lane for comparison.**

Do **not** borrow the multi-lane track stack: Instruments has genuinely parallel
continuous signals (CPU per core, per thread); a log stream is one discrete event
series and N lanes would be mostly empty. One density histogram, optionally stacked by
level, plus a marker gutter.

Complaints are diffuse rather than quotable, which is itself the finding: every
tutorial opens by apologising for the UI — a picker "which shows 17 different
instruments can be quite overwhelming"
(<https://www.avanderlee.com/debugging/xcode-instruments-time-profiler/>); "some
developers find Instruments overwhelming"
(<https://www.kodeco.com/16126261-instruments-tutorial-with-swift-getting-started>).
Apple itself concedes "navigating the layers of the software stack can be confusing"
(<https://developer.apple.com/videos/play/wwdc2026/268/>). Symbolication failures
leaving raw addresses in the detail pane are a recurring forum theme
(<https://developer.apple.com/forums/tags/instruments>).

---

## 7. Keeping your place across a filter change — how rare is it, exactly

This was the specific question asked. The answer: **no surveyed tool does what ostrace
does, and the ones that address it at all do so by making the user do the work.**

Verified in ostrace's own source: `gui/models.py` exposes `source_index(view_row)`
returning "A handle on a row that survives a filter change", and
`nearest_view_row(source)` resolving it after a rescan with a nearest-survivor
fallback; `gui/windows/main.py` calls both around `model.set_filter()`, behind a
`QTimer` debounce.

| Tool | Selected row survives a filter/query change? | What it offers instead |
| --- | --- | --- |
| **Wireshark** | **No.** Open since 3.0.7; maintainer says it "requires some Qt interface wizardry" (<https://ask.wireshark.org/question/14032/selected-packet-position-when-display-filter-is-removed/>, <https://gitlab.com/wireshark/wireshark/-/issues/16318>) | nothing |
| **Console.app** | **No** — and the selected text does not even survive *clearing* the search field (<https://discussions.apple.com/thread/254884707>) | nothing |
| **Logcat** | **No** — clears the document and re-appends; the autoscroll tickets are the visible face of it (<https://issuetracker.google.com/issues/225987089>) | Scroll to the End button |
| **Grafana** | **No** — and worse, arriving data steals your scroll position (<https://github.com/grafana/grafana/issues/90732>) | Copy shortlink to a line; Show context |
| **Datadog** | **No** | Saved Views, URL state, "View in Context" |
| **Sentry** | **No guarantee** | manual **pinning** of rows (<https://sentry.io/changelog/log-pinning/>) |
| **klogg** | Not documented; sidesteps it with a separate filtered pane (<https://github.com/variar/klogg/blob/master/DOCUMENTATION.md>) | marks always shown in the filtered view |
| **lnav** | **Yes — in the LOG view only** (see correction below) | timestamp anchoring; session restore |
| **ostrace** | **Yes, automatically, everywhere** | — |

### Correction to `docs/design/gui.md` §5

That section says "lnav clamps row ordinals and teleports". **Research does not support
this and the maintainer says the opposite.** In lnav discussion #1238 a user reported
exactly this workflow — filter, find a line, remove the filter, expect to stay put —
and Tim Stack replied: **"The intention is to preserve the location, so if it's not
working, that's definitely a bug"**, then explained that location preservation works
**in the LOG view by using timestamps as anchors**, and that he has not made it work in
the TEXT view "since it can be inefficient/inaccurate"
(<https://github.com/tstack/lnav/discussions/1238>). Corroborating release notes: "The
location of views should be restored from the session when filters are active" (v0.13.0)
and "Marks in the TEXT view are now stable after filtering is applied" (v0.12.0)
(<https://github.com/tstack/lnav/blob/master/NEWS.md>).

This matters three ways and none of them weaken ostrace's position:

1. **It is still rare** — one tool out of nine, and that tool is a terminal file viewer
   with no device support.
2. **lnav's anchor is a timestamp; ostrace's is record identity.** A timestamp is not
   unique in a log where hundreds of records share a millisecond, which is why lnav's
   approach degrades in exactly the view that lacks parsed timestamps. ostrace's handle
   is a source index, so it is exact and works regardless of clock resolution or of
   whether two records collide.
3. **The claim in §5 should be re-worded before it appears in any user-facing copy.**
   "Nobody has solved this" is false as written; "only lnav solves this, only in one of
   its views, and only for tools that read files rather than devices" is true, more
   defensible, and still a strong claim.

Beyond that, the finding stands, and one further problem is unchanged: the behaviour is
currently **invisible**. A user cannot notice the thing that did not happen. That is a
micro-interaction and positioning problem, not an engineering one — see §9.



## 8. lnav, and the iOS utility tier

### 8a. lnav — the design benchmark, not a competitor

BSD-2-Clause, C++, ~10.5k stars, docs at v0.14.1
(<https://lnav.org/features>, <https://github.com/tstack/lnav>,
<https://docs.lnav.org/en/latest/ui.html>).

Five-band terminal stack: top status bar → **interactive breadcrumb bar** showing "the
semantic location of the focused line" (focused with `` ` ``) → main view with a
**proportional scrollbar that doubles as a minimap** (errors red, warnings yellow,
search hits and bookmarks painted into the gutter) → dockable Files/Filters panels
below the view on `TAB` → bottom status bar → prompt. The bottom bar carries line
number, position as a percentage, current hit / total hits, and — when filters are on —
**the number of lines hidden by filtering**. Colour is semantic and heavy; themes are
configurable; `CTRL+s` pins a **sticky header** line to the top.

Views are modes, not panes: LOG, TEXT, DB, **HIST** ("stacked bar chart of messages over
time classified by their log level"), **TIMELINE** (Gantt of operations with error
sparklines), PRETTY, SCHEMA, SPECTRO.

**Killer feature: log files are SQLite virtual tables.** "Log files are directly used as
the backing for SQLite virtual tables" (<https://lnav.org/features>) — press `;` and run
SQL against what you are looking at, no ingest, no index build. Plus 70+ built-in
formats and timestamp-merge of multiple files into one view.

Two interactions worth stealing outright:
- **The scrollbar-as-minimap** with errors, marks and hits all in one gutter. ostrace
  has the strip; lnav shows how much can live in it.
- **`Shift+i` — jump to the histogram *time-synced to the current line*, and back.**
  Overview and detail without losing your place. `z`/`Shift+z` change the bucket size.

Also: time is a first-class navigation axis (`d`/`D` = ±24 h, `1`–`6` jump to
10-minute boundaries, `0`/`Shift+0` by day), and marks are rich — `m` mark, `Shift+m`
mark a range, `u`/`Shift+u` jump between them, `c` copy marked lines, and per v0.14.0
"Sticky headers and user bookmarks are saved and restored across sessions"
(<https://docs.lnav.org/en/latest/hotkeys.html>).

Complaints:
- **Fragmented filtering** — five mechanisms (`:filter-in`/`:filter-out`,
  `:filter-expr`, `:hide-lines-before/after`, `:set-min-log-level`, the Filters panel).
  A user asked for "one panel where you can view, add, toggle, delete"; the maintainer
  agreed and tracked it (<https://news.ycombinator.com/item?id=40737829>,
  <https://github.com/tstack/lnav/issues/1275>).
- "got overwhelmed by its interface"; docs "confusing and incomplete"; histogram
  top-aligns rather than centring on the focused line
  (<https://news.ycombinator.com/item?id=40703892>).
- Performance: 40 minutes to open a large plain-text log
  (<https://github.com/tstack/lnav/issues/304>); non-linear SQL slowdown with more than
  one file (<https://github.com/tstack/lnav/issues/699>); minutes to quit
  (<https://github.com/tstack/lnav/issues/645>).
- **Windows support arrived only in v0.13.1**, msys2-based, needs `msys-2.0.dll`
  beside the binary, and backslash paths and glob recursion are broken; the maintainer
  diagnoses "`std::filesystem` code in msys does not recognize Windows paths correctly"
  (<https://github.com/tstack/lnav/discussions/1492>,
  <https://github.com/tstack/lnav/issues/1335>).

**Verdict:** the best tool in this report, and not a competitor — it reads files, has no
concept of a device, a device clock, or a reconnect, and its Windows port is a year old
and rough.

### 8b. iMazing — consumer device manager, console is a footnote

Device screen → **Tools** → Advanced → **"Show Device Console"**, which opens a separate
window with exactly three controls: a **search field**, **Pause** ("without losing the
preceding log history"), and **Save/Export to `.txt`**
(<https://imazing.com/guides/how-to-access-iphone-ipad-console-log>). No columns, no
level model, no colour coding documented. The guide's own advice is to rename the export
to `.log` and open it in Apple's Console app to get "structured columns (timestamp,
process, message)" — iMazing telling you to leave iMazing for structure. Their docs also
warn in bold that you must keep the window open or capture stops.

The feature shipped in **iMazing 2.1, November 2016**
(<https://imazing.com/blog/imazing-2-1-device-console>) and is essentially unchanged
nine years later. The app around it got a full redesign with **dark mode on Windows and
macOS** in iMazing 3, April 2024
(<https://9to5mac.com/2024/04/24/imazing-3-launches-for-mac-and-pc-with-all-new-design-fresh-features-dark-mode-more/>)
— low density, big icon tiles, consumer-grade.

Real product: backup extraction and forensics. Complaints are commercial — $39.99 to
$129.99 tiers, an upgrade treadmill, opaque free-tier limits
(<https://www.alternativeto.net/software/imazing/about/>).

**Verdict: not a credible developer log tool.** Its competitive weight is distribution —
a QA lead on Windows may already have it.

### 8c. 3uTools — the accidental incumbent

Toolbox → **Realtime Log**, with **Export** and **Empty**; third-party QA docs mention a
Pause (<https://www.3u.com/news/articles/146/how-to-view-the-realtime-log-of-your-idevice-using-3utools>,
<https://help.testlio.com/en/articles/130095-get-ios-logs-on-windows>,
<https://academy.test.io/en/articles/6800698-console-logs-on-ios-device>). No documented
search field, filter expression, level model, colour coding or dark mode. Marketing
frames it as recording "all the operations and behaviors on the iPhone" — written for
repair shops, not developers. The actual product is Flash & JB.

Concerns: ad-monetised (<https://softwarevs.com/3utools-review/>); recurring unresolved
questions about data upload and PRC data handling, and third-party download sites as a
malware vector (<https://techtechnik.com/is-3utools-safe/>); the macOS build lags badly.

**Verdict: not a competitor on merit, but it is the incumbent by documentation.**
Testlio and test.io both instruct testers to install 3uTools to get iOS logs on Windows.
That is the adoption barrier — not quality, but that 3uTools is the answer currently
written into QA onboarding. And it is exactly the kind of tool many corporate
environments will not permit, which is a clean wedge for a pip-installable,
source-available, no-network tool.

### 8d. `idevicesyslog` — the CLI everyone actually uses

No TUI; a raw line-oriented stdout stream. It *does* colour by default on a TTY,
auto-disabled when redirected, with `--colors`/`--no-colors`
(<https://manpages.debian.org/testing/libimobiledevice-utils/idevicesyslog.1.en.html>).
Filters are launch-time flags: `-m/--match`, `-M/--unmatch`, `-t/--trigger`,
`-T/--untrigger`, `-p/--process`, `-e/--exclude` (pid or name, OR-combined with `|`),
`-q/--quiet` with a curated noisy-process denylist, `-k/-K` for kernel messages.

Killer features: it runs everywhere in a pipe, and **`--trigger`/`--untrigger`** —
start capturing when a marker string appears and stop at another — is a genuinely clever
CI-shaped feature nobody else offers.

Documented complaints:
- **`idevicesyslog` does not show subsystem or category** —
  <https://github.com/libimobiledevice/libimobiledevice/issues/1588>, open since July
  2024 with no maintainer reply. The reporter logs from Swift with an explicit
  subsystem and category and sees only a process name. **This is the single most
  important issue in the report for ostrace's positioning**: Apple's unified log is
  subsystem/category-structured, and the tool the whole non-Mac world uses throws that
  structure away. ostrace has both as first-class columns *and* as filter terms.
- Output truncated on iOS 18.5
  (<https://github.com/libimobiledevice/libimobiledevice/issues/1667>, open).
- A memory leak proportional to log volume
  (<https://github.com/libimobiledevice/libimobiledevice/issues/1677>) — fix status
  uncertain, bug documented.
- "doesn't show info or debug messages"
  (<https://github.com/libimobiledevice/libimobiledevice/issues/1587>) — the "where did
  my logs go" confusion class that ostrace's banners exist to prevent.
- Relay fragility with no reconnect: "Connection to syslog relay interrupted"
  (<https://github.com/libimobiledevice/libimobiledevice/issues/802>). There is
  `-x/--exit` and nothing that resumes.
- **A structural limitation ostrace inherits and should document:** `idevicesyslog` sees
  system log entries, not `stdout`/`stderr`, which point at `/dev/null` when an app is
  launched from the Home screen; Xcode's debugger "hooks stdout and stderr via its
  debugging infrastructure, but there's no way to do that otherwise"
  (<https://developer.apple.com/forums/thread/736555>). Anything on `os_trace_relay`
  has the same limit. Say so in the docs or inherit the bug report.
- **Windows distribution is the state of the art's low point.** No official Windows
  binaries; the documented enterprise workaround is a third-party port and
  `idevicesyslog.exe -d > c:\ios_log.log`, then open the file in something else
  (<https://www.hexnode.com/mobile-device-management/help/obtain-ios-device-logs-using-mac-and-windows/>).

### 8e. Others found, and the size of the hole

| Tool | Platform | What it is | Relevance |
| --- | --- | --- | --- |
| **Phosphor** (<https://github.com/momenbasel/Phosphor>) | **macOS only**, SwiftUI, MIT | iOS device manager backed by **pymobiledevice3** with libimobiledevice fallback; advertises real-time syslog streaming with filter, search, **colour-coded levels** and export | **The closest thing to ostrace that exists.** Same backend choice. macOS-only, and logging is one tab of a device manager. Watch it. |
| **go-ios** (<https://github.com/danielpaulus/go-ios>) | Win/Linux/macOS, single static binary | `ios syslog` and **`ios ostrace`** ("Stream os_trace_relay logs"); handles the iOS 17+ tunnel | Strongest CLI competitor. No GUI. Note it splits syslog from ostrace the same way ostrace's sources do. |
| **pymobiledevice3** (<https://github.com/doronz88/pymobiledevice3>) | Win/Linux/macOS, Python | ostrace's own backend | **No official GUI ships with it.** That gap is the product. |
| **tidevice** (<https://github.com/alibaba/tidevice>) | cross-platform, Python | Alibaba's iOS device CLI incl. syslog | CLI only. |
| **iOSLogger** (<https://github.com/TwizzyIndy/iOSLogger>) | macOS | 2-star hobby project using private `MobileDevice.framework` | Exists because Lemonjar's iOS Console died. Cautionary tale. |
| **iOS Console** (Lemonjar) | macOS | Free minimalist GUI console with a text filter (<https://www.podfeet.com/blog/2016/07/ios-console/>) | **Dead.** Does not work on modern iOS. |
| **klogg** (<https://github.com/variar/klogg>) | Win/Linux/macOS, **Qt** | Multi-GB general-purpose GUI log searcher | Not iOS-aware, but it is the Qt desktop log-viewer UX ostrace will be compared against. |

**Searched for and not found: any cross-platform GUI for live iOS logs, open-source or
commercial, built on pymobiledevice3, libimobiledevice or go-ios.** GitHub topic pages,
AlternativeTo's macOS-Console alternatives list
(<https://alternativeto.net/software/mac-os-x-console/>) and general search return
nothing. Phosphor is macOS-only; iMazing and 3uTools are consumer shells; everything
else is a CLI.

**The market position, stated plainly:** ostrace is not entering a crowded field. On
Windows and Linux the current state of the art is "run a CLI, redirect to a file, open
the file in something else" — and the CLI does not even carry subsystem or category.

---

## 9. Where ostrace can win

Ranked by (user pain × cheapness to build in PySide6/Qt Widgets). Each entry names the
competitor that lacks it and why users noticed. Every item is checked against the
project's rules: no new runtime dependency unless flagged, `paths.py` owns locations,
`compat.py` owns OS branches, `docs/formats/` wins over code.

### Tier 1 — high pain, cheap in Qt

**1. Say "showing N of M" in the status bar.** *(informational)*
The status bar has four readouts and none of them is the filtered count
(`gui/widgets/status_bar.py`). Wireshark has had `Packets: X · Displayed: Y (Z%)` for
twenty years and it is the one thing its status bar unambiguously gets right
(<https://www.linuxtopia.org/online_books/network_security/wireshark_user_guide/wireshark_ChUseStatusbarSection.html>).
lnav shows "the number of lines hidden by filtering" in the same place. Console.app,
Xcode and Logcat show nothing — which is precisely why "where did my logs go" is a
recurring support class (<https://github.com/libimobiledevice/libimobiledevice/issues/1587>,
<https://issuetracker.google.com/issues/247786909>).
Cost: one `QLabel` and one signal.

**2. Filter history and named saved filters.** *(interaction)*
Console.app has saved searches (<https://developer.apple.com/forums/thread/705868>);
Xcode 15 has Recent Filters and persists the filter across runs
(<https://www.avanderlee.com/xcode/xcode-debug-console/>); Logcat has history plus
**starred favourites persisted across projects** with `name:` labels
(<https://developer.android.com/studio/debug/logcat>); Wireshark bookmarks filters in
the filter bar; Proxyman ships "saved filter presets" (<https://proxyman.com/>).
**ostrace has none of it.** This is the largest single feature gap against every
competitor simultaneously, and it is a `QComboBox` with a completer plus a JSON file
whose location comes from `paths.py`.

**3. A toolbar with 4–6 labelled buttons.** *(visual + interaction)*
`docs/design/gui.md` §1 already calls its absence "the larger of the two [gaps] for a
program whose main verbs are otherwise two clicks deep", and no `QToolBar` exists
anywhere in `gui/windows/main.py`. Every competitor has one. Critically, the research
says **what reads as dated is the unlabelled icon toolbar**, not the presence of one —
Charles' toolbar is the thing HN commenters name, "couldn't recognize all its unlabeled
icons without hovering for tooltip"
(<https://news.ycombinator.com/item?id=46333983>). So: `QToolButton` with
`ToolButtonStyle.ToolButtonTextBesideIcon`, Capture / Pause / Disconnect / Open /
Export, and nothing else. Icons from Lucide (ISC, <https://lucide.dev/license>) or
Tabler (MIT) — both permissive and therefore GPL-3.0-compatible for inclusion, both
redistributable, both plain SVG that `QIcon` renders and `QPalette` can tint. No new
runtime dependency: ship the handful of SVGs in the package.

**4. Make the anchoring visible.** *(interaction, and it is the flagship)*
ostrace's one clear advantage is currently unobservable — the user cannot notice that
they did not get thrown to the bottom. Three cheap fixes: (a) a brief highlight pulse on
the anchored row after a rescan, the way Grafana's shortlink highlights the line it
scrolled to; (b) when the anchored record does *not* survive, say so in the status
bar — "your row was filtered out; nearest kept" — rather than silently landing on a
neighbour; (c) put it in the README and the `F1` sheet. Wireshark has not fixed this in
six years and calls it "Qt interface wizardry"
(<https://ask.wireshark.org/question/14032/selected-packet-position-when-display-filter-is-removed/>).
Also: re-word the "Nobody has solved this" claim per §7 before it ships in user-facing
copy — lnav does solve it in LOG view.

**5. Highlight as a second verb, separate from filter.** *(interaction)*
`docs/design/gui.md` §5 argues for it and 0.1.0 does not ship it. Wireshark, Procmon,
DebugView and lnav all have the split. Console.app's *lack* of it is a live, documented
complaint: a user expects Find to locate text in context and instead "the log is
filtered", and the selected text does not survive clearing the field — they left for
VS Code (<https://discussions.apple.com/thread/254884707>). Add the gutter indicator and
per-term hit count §5 already specifies; the hit count turns highlight into a free live
aggregate.

**6. A follow indicator and an unseen-record count.** *(interaction)*
`docs/design/gui.md` §4 asked for both and neither shipped. Every single web tool has an
open auto-scroll complaint — Grafana's is verbatim "your scroll position will be
forgotten once a new line gets added"
(<https://github.com/grafana/grafana/issues/90732>) — and Logcat has two tickets
(<https://issuetracker.google.com/issues/225987089>,
<https://issuetracker.google.com/issues/70149059>). ostrace's follow semantics are
already right; what is missing is the "N new records — jump to latest" pill that tells
you follow is off and how far behind you are. One overlay `QPushButton`.

**7. The reconnect banner.** *(informational)*
The one row of §6's table marked "not built". `sources/os_trace.py` retries for up to a
minute and the viewer says nothing. `idevicesyslog` has no reconnect at all and its
users hit "Connection to syslog relay interrupted" with no recourse
(<https://github.com/libimobiledevice/libimobiledevice/issues/802>). Showing "Device
disconnected — reconnecting (23s)" turns ostrace's existing retry logic from invisible
into a selling point. The banner widget already exists.

**8. Density toggle: Comfortable / Compact.** *(visual)*
Logcat ships exactly this as Standard vs Compact, in the toolbar
(<https://developer.android.com/studio/debug/logcat>); Datadog ships Content Height and
Content Display (<https://docs.datadoghq.com/logs/explorer/visualize/>). Console.app's
"rigid columns" are what Howard Oakley names when introducing his replacement
(<https://eclecticlight.co/2025/02/26/introducing-logui-an-experimental-log-browser/>).
In Qt this is `verticalHeader().setDefaultSectionSize()` plus a font-size delta — and
note §11's rule that the row height must stay `Fixed`, so a toggle is two constants,
not a layout change.

### Tier 2 — high value, moderate cost

**9. A query expression with autocomplete, replacing (or beside) the fielded bar.**
*(interaction)*
Google's stated reason for the 2022 Logcat rewrite is that the field-populating UI "made
sharing and setting up queries more difficult"
(<https://developer.android.com/studio/releases/past-releases/as-dolphin-release-notes>).
ostrace ships exactly the design Google abandoned. Console.app's search field "supports
copy and paste" so a filter is shareable text
(<https://developer.apple.com/forums/thread/705868>); Datadog highlights syntax and
autocompletes (<https://www.datadoghq.com/blog/search-logs-datadog-log-management/>).
Target syntax, borrowing Logcat's grammar because it is proven: `process:`, `subsystem:`,
`category:`, `message:`, `level:`, negation with `-`, per-field regex with `~`, `&`/`|`
and parentheses. `QCompleter` and a `QSyntaxHighlighter` are both in QtWidgets/QtGui —
no new dependency. Keep Datadog's escape hatch: let power users turn highlighting off.

**10. Facet sidebar with live counts.** *(informational + interaction)*
Datadog's facet panel is the feature its layout is organised around — unique values with
counts, a facet-search box matching display *and* field name, checkboxes that rewrite
the query (<https://docs.datadoghq.com/logs/explorer/facets/>). Michael Tsai's Console
roundup names the *absence* of exactly this: no "auto-populated dropdown for subsystems
and processes", no easy drill-down
(<https://mjtsai.com/blog/2020/06/26/console-the-vital-tool-that-apple-abandoned/>).
**This is cheaper for ostrace than for Datadog** — the whole capture is in process, so
counting distinct processes and subsystems is a `Counter` over a list, not a server
query. A `QTreeView` over "Process (243) / Subsystem (89) / Category (31)" with counts
would answer the single most-cited Console.app complaint directly.

**11. Timeline histogram with brush-to-filter.** *(interaction + informational)*
Datadog, Grafana and lnav all have a volume histogram; Instruments has the interaction
that makes it worth having — **drag across the timeline and the table below filters to
that window** (<https://developer.apple.com/videos/play/wwdc2019/411/>). lnav's
`Shift+i` — jump to the histogram time-synced to your current line and back — is the
navigation trick that makes density tractable
(<https://docs.lnav.org/en/latest/hotkeys.html>). One custom `QWidget` painting buckets
by level, plus a rubber band. Do **not** copy Instruments' multi-lane track stack: a log
stream is one discrete event series and N lanes would be mostly empty.

**12. "Show context" — surrounding records.** *(interaction)*
`docs/design/gui.md` §13 rules this out for phase 4 on the grounds that LogExpert was
"the only GUI implementation found". That is now out of date: Grafana ships it with an
**adjustable window**, editable label filters inside the context view, and open-in-split
(<https://grafana.com/docs/grafana/latest/explore/logs-integration/>), and Datadog ships
"View in Context" which rewrites the query around the selected log
(<https://docs.datadoghq.com/logs/explorer/side_panel/>). §13's own alternative — a
relational filter, "everything else from this process around this moment" — is better
suited to iOS logs and is now cheap, because process, subsystem and pid are already on
every row. Worth reopening.

**13. Message templating / pattern clustering.** *(informational)*
Datadog's Patterns view clusters similar messages and highlights the **variable** parts
inline, with a hover preview of each token's value distribution
(<https://docs.datadoghq.com/logs/explorer/analytics/patterns/>). iOS system logs are
extremely templated, and **ostrace already has `analysis/templates.py`** — the work is
surfacing existing analysis in the GUI, not writing it. This would be a genuinely
distinctive feature; nothing in the iOS tooling tier has anything like it.

**14. Copy location / shareable position token.** *(interaction)*
Grafana's "copy shortlink" — a link that reopens scrolled to and highlighting a specific
line — is the best "share your place" primitive found anywhere. A desktop app has no URL
bar, so the honest port is a compact text token plus a matching CLI flag: copy a record's
identity, paste it into an issue, `ostrace open <capture> --at <token>` jumps there.
**This is arguably better than a URL**, because ostrace's export bundle means the
recipient can get the data too. Flag: this touches the CLI and the session format, so it
is a cross-phase decision, not a GUI-only one.

**15. Command palette.** *(interaction)*
21 bindings exist and are discoverable only via `F1`. The pattern's documented benefit is
exactly this problem: "you can build and your users can discover features that could
never warrant a button or a dropdown"
(<https://blog.superhuman.com/how-to-build-a-remarkable-command-palette/>). Because
`gui/shortcuts.py` is already one generated table, the palette is a `QDialog` with a
`QLineEdit` and a `QListView` filtered over `BINDINGS` — perhaps 80 lines, zero new
concepts, zero new dependencies. Bind `Ctrl+Shift+P`, the convention VS Code and Sublime
established (<https://digitalseams.com/blog/why-do-sublime-text-and-vs-code-use-ctrl-shift-p-for-the-command-bar>).

### Tier 3 — visual polish, cheap, high perceived value

**16. Monospace for the message and timestamp columns only.** *(visual)*
Chrome keeps the platform UI font; the data gets a monospace face so columns align and
hex/UUIDs are readable. JetBrains Mono is SIL OFL 1.1
(<https://github.com/JetBrains/JetBrainsMono/blob/master/OFL.txt>), as are IBM Plex Mono
and Fira Code — all redistributable inside a GPL-3.0 application provided the licence
text travels with them. **Cheaper option with no bundling at all:**
`QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)`, which gets Consolas /
SF Mono / DejaVu Sans Mono per platform for free. Note the §12 trap: no test may assert
a font metric under the offscreen plugin.

**17. Suppress repeated cells; blank a process/subsystem equal to the row above.**
*(visual)* §2 already specifies this, borrowed from Logcat, as a delegate one-liner that
"transforms scannability". Worth confirming it actually shipped.

**18. Flatten the chrome.** *(visual)* `QFrame::NoFrame` on the panes, hairline
separators at ~8% contrast rather than etched bevels, zebra striping at ≤4% delta,
consistent 4/8 px spacing, row height ~26–30 px at 100% DPI. This is the concrete
content of "modern" per the Proxyman/Charles comparison — and the decisive evidence
there is that **Proxyman is Electron on Windows and Linux**
(<https://github.com/ProxymanApp/proxyman-windows-linux>) while Charles is native
widgets. The toolkit is not the constraint; spacing and icon discipline are.

**19. Row-hover inline actions.** *(interaction)* Filter-in / filter-out / copy
appearing on hover, the way Grafana puts positive/negative filter buttons on every field
in Log details. Cheap in a delegate, and it makes the facet idea usable without a
sidebar.

**20. Label `<private>`.** *(informational — a genuinely novel one)*
On a device not launched from Xcode, `os_log` string interpolations are redacted and the
message reads `<private>`
(<https://developer.apple.com/forums/thread/738648>). Every tool shows the redaction;
none explains it. ostrace could detect the token, style it distinctly, and offer a
one-line explanation with the two remedies (`privacy: .public`, or `OSLogPreferences` /
`Enable-Private-Data` in Info.plist). This is a pure documentation-in-the-UI win, costs a
delegate branch and a tooltip, and directly serves the confused-developer case that
generates forum threads.

### Things ostrace already does that competitors do not — say so louder

- **Gap vs Eviction as distinct, filter-exempt markers.** No surveyed tool makes the
  distinction. The validating evidence is strong: an **Apple Developer Tools engineer
  confirms Xcode silently drops records when "data rate becomes too large and we have to
  drop logs"** (<https://developer.apple.com/forums/thread/771147>); Datadog's Live Tail
  *samples* under load and at least says so
  (<https://docs.datadoghq.com/logs/explorer/live_tail/>); Grafana has an open bug where
  pausing makes logs **vanish** (<https://github.com/grafana/grafana/issues/90531>);
  Logcat's `trimToSize()` is silent. ostrace is the only tool that tells you the
  difference between "gone forever" and "still on disk, not on screen".
- **Pause never touches the source.** Grafana's own users lose data on pause
  (<https://github.com/grafana/grafana/issues/90531>); `LessShittyLogcat` exists partly
  to provide a pause that leaves "the logcat connection open, but queue[s] up messages"
  (<https://github.com/JonathanDotCel/LessShittyLogcat>). ostrace spools to disk, so the
  promise is honest rather than ring-buffered.
- **Subsystem and category as first-class columns and filter terms.** The single
  outstanding, unanswered complaint against the tool the whole non-Mac world uses
  (<https://github.com/libimobiledevice/libimobiledevice/issues/1588>).
- **Gap count always rendered, including zero.** Falsifiable by construction.

### Do NOT copy — known to annoy

- **Search that silently means filter.** Console.app's single worst-reviewed behaviour
  (<https://discussions.apple.com/thread/254884707>).
- **Rebuilding the view on every filter keystroke**, which is what makes Logcat jump to
  the bottom. ostrace already debounces and rescans incrementally; do not regress it.
- **Auto-scroll that re-enables itself** — `LessShittyLogcat`'s headline grievance
  ("scroll lock constantly re-enabling itself") and the subject of open tickets in
  Grafana and Logcat.
- **Unlabelled icon toolbars.** The specific thing HN names about Charles.
- **Hiding Info/Debug by default without saying so on screen.** Console.app does it and
  it produces a steady stream of "my logs are missing" threads
  (<https://github.com/libimobiledevice/libimobiledevice/issues/1587>).
- **Five different filtering mechanisms.** lnav's own most-upvoted complaint
  (<https://news.ycombinator.com/item?id=40737829>). One filter surface, one place to see
  what is active.
- **A multi-lane Instruments-style track stack.** Wrong data shape for a log.
- **Deep QSS restyling of scrollbars and native controls.** Tempting for "modern", but
  `gui/theme.py`'s core rule is that the theme is a function to a `QPalette`, *not* a
  stylesheet, and that determinism is what lets CI assert WCAG AA on three platforms.
  A stylesheet layer would put that at risk and would need per-platform testing that
  does not exist. Get "modern" from spacing, icons, typography and flat frames instead.
- **Heavy animation and hover-tooltip-dependent affordances.** Expensive in Qt Widgets,
  and Datadog's "the web UI, while pretty, can be heavy" is the failure mode
  (<https://medium.com/@joachim_43659/bitten-by-the-datadog-when-monitoring-bites-back-335398adb0a8>).

### Dependency and licence flags

- Icons (Lucide ISC / Tabler MIT / Feather MIT): **no runtime dependency** if the SVGs
  are vendored; both licences are permissive and one-way compatible with GPL-3.0-or-later.
  Keep the licence text and add the files to the SPDX headers convention.
- Fonts: prefer `QFontDatabase.systemFont(...FixedFont)` — **zero bundling, zero licence
  question**. If a specific face is wanted, JetBrains Mono / IBM Plex Mono / Fira Code
  are OFL 1.1 and redistributable.
- Command palette, query completion, syntax highlighting, histogram, facet tree, sticky
  pinned row: **all pure QtWidgets/QtGui**. No new runtime dependency for anything in
  Tiers 1–3.
- The only items that would reach outside the GUI are #14 (copy-location token — touches
  the CLI and possibly the session format, and `docs/formats/` wins) and any change to
  what a `Gap` carries.

