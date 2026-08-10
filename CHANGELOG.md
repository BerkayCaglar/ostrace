# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While the version is below 1.0.0, the minor version may carry breaking changes.
Two things are treated as public API from the start and will be versioned as
such: the `Record` model and the on-disk export formats documented in
[docs/formats/](docs/formats/).

## [Unreleased]

### Added

- **The status bar says how far behind you are.** The follow indicator shipped
  in 0.1.1 and answered half the question: it says the tail has stopped, and
  says nothing about whether five records or fifty thousand have gone past
  since. `docs/design/gui.md` §4 listed the count as missing and called it the
  more useful half. It reads `1,204 behind`, beside the indicator.

  Derived from the row at the bottom edge of the viewport rather than by
  counting arrivals — O(1), and right after a filter change, a trim or a jump,
  each of which moves the reader relative to the end without a record arriving
  at all. Follow itself is derived and not stored for the same reason, and a
  counter kept alongside it would be a second thing able to disagree with the
  view.

  Silent while following, and silent in a file. Both are rules: a followed view
  is at the end by definition, and a capture that is not running has no
  arrivals, so calling the rows below the viewport "behind" would invent one.
  The second silence is asked of the control's own enabled state, so the number
  goes quiet exactly when the button beside it does.

### Changed

- **The README shows the window as it is, and shows it on both platforms.** The
  committed screenshots were taken before 0.1.1 and had gone quietly stale: no
  jump-target control in the toolbar, no follow indicator in the status bar, and
  a detail pane that is a single narrow column of twelve rows. A reader
  comparing them against the program they had just installed would have found
  three differences on the first screen.

  There are now two pairs. The Windows one comes from the screenshot job, as
  before. The macOS one could not: that job runs the offscreen plugin, which
  resolves the interface font to Qt's generic `Sans Serif` rather than to
  `.AppleSystemUIFont` — right about layout and palette, wrong about the one
  thing anybody looks at a macOS screenshot for. It was rendered under `cocoa`
  on a real Mac, which is the first picture of this program on macOS that shows
  the face a Mac user actually sees.

- **macOS has been run by hand for the first time**, on macOS 26.3.1 with
  PySide6 6.11.1 — every documented assumption checked, including the eleven
  tests that need a physical iPhone, which had never executed anywhere but
  Windows. The four `# UNVERIFIED-MACOS` markers are gone: three were right and
  are now recorded as confirmed rather than assumed, and the fourth was wrong.

  **`SF Mono` is not the face a Mac renders the log in.** It was listed as the
  macOS first choice on the grounds that it ships with the system. The file
  does ship, as `/System/Library/Fonts/SFNSMono.ttf`, but Apple registers the
  SF faces under a restricted family name and keeps them out of the font list —
  so `QFontDatabase` offers 181 families there and `SF Mono` is not among them,
  and neither is it in `system_profiler`'s. Every Mac has been reading its logs
  in `Menlo`, which is the next entry. The entry stays, because it resolves for
  anyone who installed Apple's separately distributed copy; the claim about it
  is what was wrong, and is corrected where it stood.

  Also confirmed rather than assumed: the native menu bar leaves the window on
  macOS and the offscreen one does not, `setColorScheme` is genuinely inert
  under the offscreen plugin, the offscreen font database is empty only on
  Windows, `usbmux` needs nothing installed, `/var/db/lockdown` is unreadable,
  and the config and data directories really are one path. Colour-scheme
  switching, which the design notes list as unverifiable in the offscreen lane,
  was watched working natively — until now it had only been seen on Windows.

  **One gap is left, and it is stated rather than closed:** the machine drives a
  single non-Retina display, so nothing has yet been rendered at a 2× device
  pixel ratio, which is what most Macs run at. `docs/design/gui.md` §12 records
  the whole pass, including that.

### Fixed

- **The detail pane drew the previous record's rows over the new one.**
  Replacing the contents took each old row out of the grid and handed it to
  `deleteLater`, which destroys it whenever the event loop next drains — and
  `takeAt` only unhooks a widget from its *layout*. In between, every old row
  was still a visible child sitting at its last geometry, painting straight
  over the rows that replaced it: the `Nothing selected` placeholder printed
  across `Device time`.

  Interactive use never showed it, because the loop drains before the next
  paint. What sees it is anything that rebuilds and renders in one pass —
  every `grab()` in the suite, and `tools/capture_screens.py`, whose entire job
  is to show what this window looks like on macOS. The screenshot job had been
  rendering the bug faithfully since the pane was redesigned and nobody had
  opened the image. **This is the second bug in this pane that only a picture
  could reveal**, and as with the first one every existing assertion — all of
  which read text — passed throughout.

- **The window printed a Qt warning every time it closed.** `saveState` names
  each toolbar by object name and warns when one has none, and `closeEvent`
  calls it, so `QMainWindow::saveState(): 'objectName' not set for QToolBar`
  went to stderr on every quit. The layout did still come back — with a single
  toolbar Qt falls back to position — which is exactly the fallback that stops
  working the first time a second toolbar or a dock exists.

### Planned

**Nothing in this section is built.** It is the rest of the must-have list from
the GUI redesign — [docs/research/gui-redesign/05-interaction.md](docs/research/gui-redesign/05-interaction.md)
§10 — of which 0.1.1 took the affordable half. It is here rather than only in
that document so the backlog sits where the next release gets written, and it
is labelled so nobody reads it as a list of things that shipped.

- **A Doctor window**, reachable from Help and offered as a banner action. The
  checks exist and only the command line can run them, so a graphical user
  meets a dead end at exactly the moment something is wrong.
- **A row context menu**, including *Filter by this process* — narrowing without
  retyping what is already on screen.
- **A viewport marker on the minimap.** The strip shows where the errors are
  and not where you are.
- **Jump to time** (`Ctrl+J`), and a **hideable detail pane** (`Ctrl+I`).
- **Recent filters**, without naming them.
- **A reconnect banner**, which needs the `capture(on_state=…)` callback, and a
  **capture-finished banner** offering Export.
- **Accessible names on the icon-only controls**, and a banner that announces
  itself as an alert.
- `Ctrl+Q` beside `StandardKey.Quit`, and a test that a letter typed into the
  search field does not fire the single-letter aliases.

The nice-to-have and later tiers stay in that document rather than being copied
here. A backlog long enough to skim is one nobody reads.

## 0.1.1 - 2026-08-10

The first release that exists. 0.1.0 was published and withdrawn the day
before — see its entry below — so this is the same program with the reason for
that withdrawal fixed, plus everything three rounds of using it against a phone
turned up.

Almost all of this came from somebody actually running the program. The
security entry came from auditing what this repository had already published.

Worth stating plainly, because it is the pattern: **every one of these bugs was
reachable in a minute of real use, and the test suite covered the code they
were in.** The follow tests scrolled to the bottom by hand before appending —
the one thing a real capture never does. The trim tests never showed the
window, so nothing could scroll. The export tests ran on the interface thread
and never noticed the freeze. The theme tests read a palette where the bug was
in the paint. A green suite is evidence about the states it set up, and every
one of these was found in a state it did not.

### Added

- **The jump arrows can be pointed at something other than errors.** The two
  toolbar chevrons were wired to `Find.ERROR` and nothing else, which is the
  right default and a poor answer to reading a capture for gaps. The target is
  a control beside them now — errors and faults, faults, notices and above,
  gaps, marked rows — remembered between sessions, and `F3` / `Shift+F3`
  follow it. Every kind keeps its own explicit key, so choosing one in the
  toolbar takes nothing away from somebody who already knows `Ctrl+Shift+G`.

- **Close Capture**, on the standard close chord. There was no way back to an
  empty window: a loaded capture, a narrowed filter, a selected row, a device
  in the status bar and a file name in the title were all reachable and none of
  it was reversible without quitting. The filter goes with the capture, since
  this is the one moment the window knows for certain it is not the filter for
  whatever comes next. A running capture is not closed out from under itself.

- **A snapshot export while a capture is still recording.** It used to be
  refused until Disconnect, on the grounds that a file growing under the
  exporter produces a report whose end is arbitrary. The end is only arbitrary
  while it goes unstated: the export now declares that it is a snapshot and
  that it ends where the file had got to rather than where the device stopped,
  in the same `exporters.notes` sentences the CLI prints. `storage.spool` has
  emitted a `Z_SYNC_FLUSH` boundary for exactly this since phase 1 — its
  docstring says live export depends on it — so the capability was there and
  the window was declining to use it. The capture keeps running.

- **An application icon.** There was none, so the title bar, Alt-Tab and the
  taskbar all showed Qt's default, which on Windows is a blank sheet. Drawn
  here, set on the application so every window and dialog inherits it, and
  supplied at seven sizes rather than left to Qt to rescale one bitmap into the
  soft edges that read as an unfinished program.

- **A follow indicator in the status bar, which is also the way back.** It says
  `Following` or `Not following` and pressing it does the other one; `Ctrl+
  Shift+F` and a View menu item reach the same thing. `docs/design/gui.md` §4
  asked for this indicator and phase 4 did not build it, so the state was
  derived correctly and shown nowhere — and since clicking a row stops the tail
  on purpose, the only routes back were a key nobody had been told about and a
  menu item two levels down. Reported as "getting back to auto scroll is very
  hard".

  It is derived from the same `following` the tail itself acts on, so the
  indicator cannot disagree with the behaviour. Putting the state on screen
  immediately exposed a promise `Go to Bottom` had not been keeping: its second
  press resumed nothing for a reader who had *scrolled* away rather than
  clicked away.

- **A close control on the detail pane.** `Esc` was the only way to let go of a
  record, which is a key you have to be told about. The control asks rather
  than acts — it emits, and the window turns that into a deselect — because a
  pane that can hide itself is one the reader has to work out how to bring
  back.

- **A dark-mode switch**, in View, remembered between sessions. The viewer
  followed the operating system and offered no way to disagree with it — which
  is fine until you are the person reading a log at night on a machine set to
  light. Reported as "there is no dark mode": there was one, and no way to ask
  for it. Choosing stops the following; the system remains the default, not the
  authority.

- **`Esc` lets go of the selected row.** Selecting one stops the tail
  deliberately, and there was no way to say you had finished reading it — the
  only route back was `Go to Bottom` pressed twice, which is a thing you have
  to be told. So a live capture stopped following the first time anybody
  clicked anything and stayed stopped.

### Changed

- **The detail pane is two columns of fields and a message block.** It was a
  single-column form of twelve short rows, which against a real window is
  mostly empty space with a stack of labels down the left edge — and the
  message, the one field with anything to say, got the same narrow strip as
  `PID`. The message now has a block of its own in the table's monospaced face,
  and the fields fill the width in pairs, top to bottom in each column so the
  clock fields stay together.

- **`Esc` lets go of the selected row and moves nothing else.** It also forced
  the at-bottom state and scrolled there, on the reasoning that letting go of a
  row is asking for the tail back. Against a real capture that reads as `Esc`
  throwing the reader to the end of the log from wherever they were, which is
  precisely where they had chosen not to be. It was unnecessary as well: follow
  is derived from the viewport, so deselecting at the bottom resumes the tail
  on its own and deselecting half way up does not. `Ctrl+End` remains the way
  to ask for the end.

### Fixed

- **Dark mode came apart when the operating system switched.** Two objects
  answered `colorSchemeChanged` under different rules — `gui.app`
  unconditionally, the window only while the user had expressed no preference —
  and two listeners under different rules is one rule that does not hold.
  Choosing a theme and then letting the system change its own moved the palette
  and the chrome stylesheet while the table, the model, the minimap and the
  icons stayed put: a dark window with a white log in the middle of it. The
  window owns the switch now and `gui.app` connects nothing.

- **The dark theme rendered as white stripes through a dark table, and an empty
  table as a white sheet.** A scroll area paints its background from the
  *viewport's* palette, and the viewport ends up holding one of its own with
  every role explicitly resolved — after which nothing set on the view reaches
  it again. Measured with the table's `Base` correctly at `#1b1e24` and the
  viewport still painting `#ffffff`: rows carrying `AlternateBase` came out
  dark and the ones showing the background stayed white.

  This is the second bug with that picture. The first was the split-brain
  switch above, which was real and is fixed; every assertion that read
  `table.palette()` passed throughout both. The tests read a pixel now.

- **Opening the device menu chose a device.** The first one found was selected
  outright, so pressing the button to *see* what was attached changed the label
  to a device — which reads as the control having connected to it rather than
  having answered a question. Opening a menu is not picking from it. The button
  says `Choose device` until something is clicked, and what a capture is
  actually using is named in the status bar by the device that answered, which
  is where a fact about the capture belongs.

  A capture with nothing chosen still uses whichever device is attached,
  exactly as the command line does with no `--udid`. That is also why the udid
  a scan must leave alone now comes from the device that answered rather than
  from the selector: the selector is empty in that case, and a second lockdown
  against the device a capture is blocked on does not raise, it stalls.

- **The window called itself `os_trace_relay` while recording.** That is the
  Apple service the stream arrives on — an implementation detail of the
  transport, identical for every device, and an answer to no question anybody
  has while looking at a title bar. It now says `Capturing from Berkay's
  iPhone`, or `Capturing` until the device answers, because identifying one is
  a round trip. An opened capture is named by its stem rather than its file
  name: `ios26-errors`, not `ios26-errors.jsonl.gz`. The title was assembled in
  six places with six spellings, two of which cleared it while something was
  still open; it is derived from state in one place now.

- **The columns did not fit the window, so an empty table scrolled sideways.**
  `stretchLastSection` only *grows* the last section into space left over, and
  the columns before it had used the window: measured on the shipped budgets at
  1,280 pixels, five fixed columns of 91 characters came to 1,183 of a 1,254
  pixel viewport, leaving the message 71 — about five characters — and
  overflowing the window by 59 besides. The budgets are what a column wants;
  the message now has a floor of 30 characters that wins, and the shortfall
  comes out of the three identifier columns in proportion, never out of Time or
  Level, whose contents have a known length. Measured after: 1,254 of 1,254,
  no scrollbar, and the message went from 100 pixels to 372.

- **Applying a theme that is already applied re-polished every widget in the
  process.** `setStyle` and `setStyleSheet` do that by definition, and nothing
  checked first. One window is the whole of production so it never showed, but
  it is work done for no reason on every switch — and it is quadratic in a test
  session, where `colorSchemeChanged` reaches hundreds of live windows and each
  one restyles the shared application. `apply_theme` returns early when the
  application is already wearing the scheme, with the stylesheet as the
  witness: it carries the scheme's colours as literals and nothing else ever
  sets it. The suite went from about three and a half minutes to 49 seconds.

- **The scrollbar was invisible in the dark scheme.** Its handle was painted in
  `border-strong`, which is also `QPalette.Dark` and `Shadow`: for a shadow
  "darker than the surface" is the whole job, and for a handle it is the bug.
  Measured, that is `#0f1116` on a `#101216` track — a contrast of **1.01:1**,
  drawn correctly and impossible to see. The handle has its own token now and
  both schemes clear 3:1 against their own track, WCAG 2.1's non-text
  threshold, asserted beside the severity contrasts. The light one was never
  invisible and was under the line too, at 1.64:1.

- **The device button chose a device instead of opening its menu.** It is an
  instant-popup button over a menu that was empty until an asynchronous scan
  returned, and Qt pops up nothing for a menu with no actions — so the press
  appeared to do nothing, and then the scan landed, took the first device and
  changed the label. Both halves of that were one empty popup. The menu is
  never empty now: it says `Scanning…` while a scan is in flight, and its
  contents are replaced by building the new rows before removing the old ones,
  because a `QMenu` emptied under a user who is looking at it closes itself.

- **The `rec/s` readout spent most of its time reading zero.** It was computed
  from a single 50 ms drain, and a device does not deliver evenly — it hands
  over a batch and then says nothing for several ticks, so the commonest value
  for one tick is none at all. A readout that reads 0 while a capture is
  plainly streaming is worse than no readout, because it looks like the device
  stopped rather than like a bug. It is now a count over the last second, which
  is also the unit it is spelled in: a number the user could have counted
  themselves rather than a projection from a twentieth of a second.

- **The View menu drew icons where checkmarks go.** The toolbar and the menus
  share their action objects, so the chevrons put on the two jump actions for
  the toolbar's sake were rendered by the menu in the check column: `Next
  Error` and `Previous Error` appeared with what reads as a tick and an
  indicator beside them, two rows above a `Dark Mode` whose tick is real. No
  action shows an icon in a menu now. The menu was also eleven items in one
  undivided column; grouping is declared in the bindings table and the
  separators are drawn from it, so a reordered item cannot leave a divider
  behind.

- **The detail pane measured itself against rows it had not shown yet.** A
  widget added to the layout of an already-visible parent is not made visible
  until the event loop next runs, and a layout skips hidden items — so
  `QGridLayout.hasHeightForWidth` was false, `heightForWidth` returned -1, and
  the height computed for the pane a line later left the entire field grid out
  of it. Measured: 189 pixels for contents needing 433, which is every row
  rendered as its own top half.

- **The tail never followed a live capture at all.** Appending rows does not
  move a scrollbar: Qt raises the maximum and leaves the value where it was. So
  the check for "is the reader at the bottom", made after the insert, saw 0 out
  of 3,919 and concluded they had scrolled up. Follow died on the first batch
  and could not restart, because the only thing that could have returned the
  bar to the bottom was the follow it was refusing to do.

  It is derived from a person scrolling now — `actionTriggered`, which fires
  for a drag, a wheel, an arrow and a page, and not for `setValue`, which is
  how everything in the window moves the view. Leaving the bottom is something
  a user does, and nothing else can now be mistaken for it. The first attempt
  at this fix read the position immediately *before* each insert instead, which
  works until the 100 ms scroll throttle skips one — and then reads the skipped
  scroll as a reader walking away. That version passed a synthetic test that
  slept between batches and failed against a device on the first try.

- **A trim moved the log out from under whoever was reading it.** The view
  keeps a pixel offset from the top of its content, so dropping twenty thousand
  rows above the viewport slides everything under it. On a device emitting
  three thousand records a second that is every seven seconds, forever, and
  always while somebody is reading. Measured at a cap of 2,000: a reader on
  record 989 was looking at record 1,588 afterwards, having pressed nothing.

- **Export gave no sign it was doing anything.** Measured on a 61,190 record
  capture off a device, every format takes between 1.5 and 2.3 seconds, and the
  cap is 200,000 — all of it on the interface thread, so the window simply
  froze. It runs on its own thread now, with a progress bar, the destination
  named while it works, and a second press refused until the first lands. The
  bar is indeterminate because an exporter reports no progress, and inventing
  one would be worse than none.

- **The test suite wrote to the user's own settings.** `closeEvent` saves the
  layout and one test closes a window, so running the tests put an *offscreen*
  window's geometry into `HKEY_CURRENT_USER` — which the next real launch
  restored faithfully, opening where no display could show it. Redirected to a
  temporary directory now, per test rather than per session: shared, one test
  toggling the theme left it set for every window built afterwards.

### Security

- **The committed fixtures carried the capture device's own identifiers.**
  `tests/fixtures/README.md` claimed a privacy filter, and there was one — but
  it selected on the process a record came *from*. It dropped records emitted
  by installed third-party applications and never read the contents of what
  system daemons logged, which is exactly where a device's identifiers travel.
  A system daemon logging your Wi-Fi BSSID is still logging your Wi-Fi BSSID.

  Auditing all 8,000 records turned up the home Wi-Fi SSID and BSSID, which
  resolves to a street address through public wardriving databases; the device
  UDID and `X-CloudKit-DeviceID`, neither of which can be reset; the iCloud
  DSID and CloudKit account identifiers; `x-apple-mmcs-auth` capability tokens
  scoped to the owner's iCloud backup chunks; ETags, `protectionInfoTag` values
  and digests derived from backup content; paired Bluetooth addresses; and a
  list of installed applications. No password, session key or account
  credential was among it — a capture contains none — but all of it identifies
  a person, a device or a place.

  1,123 of the 8,000 records carry a redaction — a figure anyone holding the
  fixtures can count, rather than a historical tally of how many were edited,
  which is not recoverable now that the originals are gone. Record counts,
  levels and subsystem distributions are unchanged, because a dozen assertions
  rest on them; each value became `<redacted>`, or a same-shaped synthetic
  where the shape is what the parser sees. The rewrite ran through this project's own `SpoolReader` and
  `SpoolWriter`, verified byte-identical on a no-op pass before any
  substitution was made. `tests/fixtures/README.md` now records what was
  removed and the rule that would have prevented it: **filter on what a record
  says, not on who said it.**

  Because the `sdist` ships `tests/`, 0.1.0 carried the unredacted fixtures to
  PyPI. That release has been deleted and 0.1.0 will not be reused; the git
  history was rewritten and the repository recreated, so no commit here has
  ever contained the data.

- **The real device UDID had also been pasted into two unrelated tests** as a
  sample `DeviceInfo` value. Both now use a synthetic one.

- **`tools/audit_capture.py`, and a CI gate on the committed fixtures**, so the
  next capture cannot repeat this. It has two halves because the incident had
  two causes. The *rules* catch what is already known — a globally unique MAC,
  a UDID-shaped token, a DSID in an iCloud content URL, a third-party bundle
  identifier — and one that generalises: a high-entropy value sitting under a
  field name that admits it is a secret. Nobody had `x-apple-mmcs-auth` on a
  list; what gives it away is the word `auth` in front of thirty random
  characters.

  The *census* (`--census`) lists every high-entropy token grouped by the text
  preceding it, for a human to classify. That half is not a gate, because a
  real capture is full of legitimate opaque identifiers — and it is also the
  half that works. Written after the rules were passing, it immediately found
  two more fields the rules had missed: `sig:` and `ref:`, MMCS's abbreviations
  for `signature:` and `reference:`, carrying 42-hex digests of backup chunks.
  Both are redacted and both spellings are now in the vocabulary.

- **A second, independent audit then found three more**, after all of the above
  was written and passing clean. MMCS chunk signatures written positionally as
  `chunk ==> <hex>`; container capability handles written as
  `mmcs put container 1:\t<handle>`; and the backup snapshot UUID — 947
  occurrences, inside a `recordName=` whose neighbouring digest had already
  been replaced with `<redacted>`. The first two had been in the census output
  all along, below the point somebody stopped scrolling. The third was
  invisible because the census discarded UUIDs wholesale.

  So the tool changed too. `_searchable` never included `subsystem` or
  `category`, which means no rule and no census had ever read either field. The
  census now covers every field; its floor drops to 16 characters so that
  nothing falls between it and the key/value rule's own floor; and a new pass
  reports UUIDs recurring more than 25 times, on the principle that a UUID seen
  once is per-operation noise while one seen hundreds of times identifies
  something a human should name. A DSID gets its own rule, being too short and
  too low-entropy for the generic one to ever fire on it. Apple's own sentinel
  UUIDs are documented as such, so the next auditor need not re-derive that
  they are not somebody's redaction. And the module docstring now states
  plainly what the tool still cannot catch: a name, a value pasted into a `.py`
  or a `.md`, and a digest written with no key in front of it.

## 0.1.0 - 2026-08-09 — withdrawn

**This release no longer exists.** Its `sdist` shipped `tests/`, and the
fixtures inside it carried the capture device's own identifiers — see the
`Security` entry above. It was deleted from PyPI, and the version number will
not be reused: PyPI does not allow a deleted version to be re-uploaded, and a
tag pointing at a release that cannot exist would be worse than no tag. There
is deliberately no `v0.1.0` tag in this repository. The next release is 0.1.1.

The entry is kept in full because the work in it is real and the reasoning is
worth having. Only the artifact is gone.

The first release, and the first entry: everything here is new, so the sections
below are grouped by the phase that built them rather than as a diff against a
version that does not exist. Where a measurement contradicted a decision, the
entry says so rather than quietly adopting the new number.

What you get is a command line (`devices`, `capture`, `doctor`, `export` with
six formats) and a graphical viewer (`ostrace-gui`), on Windows, macOS and
Linux, reading Apple's unified log over `os_trace_relay` — subsystem, category,
thread and emitting library included, at DEBUG level and above.

**Every `Fixed` entry below fixes something that never shipped.** There is no
earlier version to have shipped it: the last phase was an audit that read the
whole thing back against its own documentation and ran it against a real
iPhone, and what that turned up is recorded here because the reasoning is worth
keeping — not because any of it is a live risk to a reader of 0.1.0.

### Added (phase 5, the pre-release audit and the redesign)

- **`gaps.tsv` in the agent bundle.** Every other export states a gap inside
  the thing a reader reads; the bundle said it only in `CLAUDE.md`, which is
  explicitly outside the format contract. So `session.log`, `errors.log`,
  `timeline.tsv` and `patterns.tsv` all read straight across the hole, and
  every search an agent ran was answered as though the device had been quiet —
  the one conclusion this format exists to prevent. Its own file rather than a
  marker line, because `session.log`'s contract is one record per line and
  every recipe in the bundle depends on it. Written on every export, header
  only when there are none: a file that appears solely on bad news cannot be
  told from a file nobody wrote.

- **A toolbar**, which `docs/design/gui.md` §1 has specified since before there
  was any code and phase 4 did not build. Every primary verb — capture, pause,
  disconnect, open, export, and the jump to the previous or next error — was
  two clicks deep in a menu. Each button drives an action that already exists
  with its own shortcut and menu item, so this is a second way to reach a verb
  rather than a second implementation of one.

  Capture, Pause and Disconnect keep their labels; the rest are icons. A row of
  unlabelled glyphs is the specific thing people name when they call a tool
  dated, and those three are the ones whose consequences are not guessable —
  one starts a device stream, one freezes a view, one releases the hardware.

- **A device selector.** `OsTraceSource` has always accepted a udid and nothing
  ever passed one, so the viewer captured from whichever device answered first
  and never said which that was. With a phone and an iPad attached that is a
  coin toss the user cannot see, let alone lose.

  Devices are enumerated off the interface thread and in two passes: the list
  appears as soon as usbmux answers, and each row upgrades from a udid to a
  name when the round trip to that device finishes, because identifying a
  sleeping phone takes long enough to freeze a toolbar. The scan never opens a
  lockdown session against a device a capture is holding — that is not an error
  the library reports, it is a stall in the stream the capture thread is
  blocked on reading.

- **Icons**, drawn for this project and tinted from the theme tokens rather
  than baked, so they follow a light/dark switch like everything else. Eight
  files, 1.8 kB: an icon library would be a runtime dependency and a licence
  obligation for less than two kilobytes of geometry. Qt's built-in
  `QStyle.StandardPixmap` set was the free option and is the wrong one — Fusion
  synthesises those as pixmaps rather than masks, so they cannot be recoloured,
  and the dark scheme would draw light-scheme glyphs.

- **`N of M shown` in the status bar**, whenever a filter is hiding anything.
  `RecordModel.hidden_by_filter` has existed since the model was written and
  nothing in the application ever read it, so a filter one character too narrow
  looked exactly like a device that had stopped talking. Wireshark has said
  `Displayed: N` for twenty years; Console, Xcode and Logcat say nothing, and
  the recurring "where did my logs go" is the result. Silent when nothing is
  hidden — unlike the gap count there is no ambiguity to guard against, since
  "hiding nothing" and "not filtering" are the same state.

- **The empty table explains itself.** Nothing opened yet, a device that has
  not spoken, a capture that recorded nothing and a filter that matches nothing
  all produced the same blank grid — the state in which a working program and a
  broken one look identical. The two with an action stay with the banner, which
  can offer it; the two without are painted in the table itself.

- **The window opens at a size worth reading at.** Left to Qt it opened at
  751×362 — the sum of what an empty table and a two-line form ask for, and
  about a third of what six columns of log need.

- **The window remembers its geometry, its split and its column widths.**
  `gui.app` has set the organisation and application names since it was written
  — which is what stops Qt filing settings under a vendor called "Unknown" —
  and nothing ever constructed a `QSettings` to use them. Not the filter and
  not the open capture: a viewer that reopened yesterday's file would be
  guessing, and a filter that survived a restart is one the user has to
  remember they set.

- **Help ▸ About**, which is now the only place the viewer says which version
  it is. The application has always known — nothing displayed it.

### Removed (phase 5, the pre-release audit)

- **Edit ▸ Settings…**, which opened nothing. Nothing in this release is
  configurable, and an inert Preferences item is worst on the platform its
  menu-role machinery exists for: macOS moves it into the application menu,
  where it is the item people press without looking.

### Fixed (phase 5, the pre-release audit)

- **A device name the terminal could not spell killed the command printing
  it.** Redirected output does not get UTF-8; it gets the locale's encoding —
  a code page on Windows, ASCII under `LANG=C` anywhere. Apple names a phone
  after whoever set it up, so the stock name already carries a curly
  apostrophe and a great many carry a script no code page covers. The
  `UnicodeEncodeError` came from inside `print`, past every handler, so
  `ostrace doctor > report.txt` stopped after four checks and left a traceback
  where the diagnostics belonged — in the one situation the redirect is for.
  Characters the encoding cannot carry are now escaped, as Python already does
  on stderr: an escaped name still identifies the device, and a traceback
  identifies nothing.

- **Export was a dead end after a live capture.** Capture from the device,
  press Export, and the viewer said to disconnect to finish the recording.
  Disconnect, press Export again, and it said exactly the same thing: nothing
  ever told the window where the session file had gone, and nothing ever would.
  The records were on disk throughout — `ostrace.capture.capture` finalises the
  session on every exit path including cancellation — so the only thing missing
  was the path.

  `capture()` now reports it through an `on_open` callback as soon as there is
  one, because a cancelled capture never returns a result and the result was
  the only thing carrying it. The window adopts the session when the capture
  thread ends, however it ended, and its title finally says where the capture
  went — which the CLI has always printed and the viewer never said at all.

  Export offers **Disconnect** as the way out while a capture is running, which
  is only worth offering now that it leads somewhere.

- **The viewer's Export destroyed the capture it was reading**, in the case it
  offered by default. `.jsonl` is both an ending `paths` strips from a capture
  name and the jsonl exporter's suffix, so opening a `.jsonl` capture and
  pressing Export put *the capture itself* in the destination field. Accepting
  it truncated the file while the exporter was still iterating over it, and the
  dialog then reported `0 records` where a success goes. Measured against a
  capture recorded off a device: 10,718,395 bytes to 0.

  The command line has refused this since the day it did the same thing —
  `paths.check_export_destination` was written for it, and the dialog reaches
  the same default through the same `export_path` without ever calling the
  guard. It calls it now, and the CLI's `TestItNeverEatsTheCapture` has a
  counterpart on the viewer's side. `DestinationInUseError`'s hint no longer
  says "pass `--output`", which was not advice a dialog could act on.

- **Disconnect did nothing if the capture had not started yet.** Stopping works
  by cancelling the capture task, and until the device has been identified —
  a round trip to it — there is no task to cancel, so it returned quietly and
  the capture went on running against a device the user had already released.

- **A capture that ended by itself left the viewer running against nothing.**
  Unplug the device, or let a limit stop it, and the pump and the overview
  timer kept ticking: the status bar switched to `idle` and then back to
  `0 rec/s` fifty milliseconds later, and stayed there for the rest of the
  session. Export then took the wrong branch and offered a Disconnect that was
  greyed out.

- **Pressing Capture with no device gave three seconds of nothing**, then a
  banner offering **Dismiss**. `OsTraceSource` does not touch the device when
  it is constructed, so the "no device" path the window was catching never
  fired. It offers **Retry** now, and the window title stops naming a source
  that produced nothing.

- **The tail dragged a selected row off the screen.** Follow is derived from
  the view rather than stored — but only from the scrollbar, and clicking a row
  does not move the scrollbar, so a reader who selected a record mid-capture
  had it yanked away by the next batch. `docs/design/gui.md` §4 calls breaking
  follow on selection "not optional", and with a detail pane selection is the
  primary interaction. This is the Console.app bug the rule was written to
  avoid, arriving from the other direction.

- **An empty capture said nothing at all.** A filter matching nothing, a
  capture with nothing in it and a quiet device all produce the same empty
  table; only two of the three explained themselves.

- **The Process column dropped the `[pid]`** when the value did not fit,
  eliding right like every other column. The pid is what tells eight instances
  of one process apart, the plaintext exporter already takes trouble to keep
  it, and `docs/design/gui.md` §2 says it is never what gets truncated.

- **The keyboard sheet assumed a monospaced font.** Padded columns in a
  `QMessageBox` label, which is proportional on every platform.

- **Switching the operating system's theme made the log unreadable.**
  `apply_theme` moves the palette, which is everything Qt draws — but the
  severity foregrounds and the minimap's bands are resolved from the scheme
  once and held, and both `set_scheme` methods were called only from tests. So
  a switch repainted the window in the new scheme and left every record's
  colour in the old one. Measured on the shipped palette: **all twelve**
  level-and-scheme pairs fall below 3:1, and `Info` and `Notice` — most of any
  capture — land at **1.14:1**, near-black on near-black.

  Invisible to the contrast tests, which compare a scheme against itself and so
  could never see a window holding two at once. `docs/design/gui.md` §10 already
  said the switch is "the same function called again"; the fan-out that would
  have made that true was missing. The signal's own argument is what the window
  reads now, rather than re-reading the hints — which also makes the path
  testable, since the offscreen plugin's `setColorScheme` is a no-op and the
  hints never move.

- **Tooltips ignored the theme entirely.** `QToolTip` keeps a palette of its
  own that the application's does not reach, so the `ToolTipBase` and
  `ToolTipText` roles `theme.py` has always set arrived nowhere — tooltips
  stayed on Windows' `#ffffe1` under the dark theme as well as the light one,
  a bright yellow card on a dark window. Qt 6 removed the class-specific
  `setPalette` overload that used to cover this and nothing replaced the call.

- **`ai-report` named the wrong section as verbatim**, and at a small budget
  claimed "the most frequent are shown" above an empty code fence — or "the 0
  most frequent are shown", which is not a sentence. The subsystem placeholder
  rendered as literal underscores inside a code span.

- **The bundle's match-count warning was 11–22% optimistic.** It estimated a
  record's length as the raw message plus a flat sixty characters, where the
  five fixed columns are nearer eighty and the written message is escaped. It
  is measured while `session.log` is written now; erring high is the unsafe
  direction for a number whose whole job is preventing a silent truncation.

- **`trace` said nothing when a window was cut short by the end of the
  capture.** The size-limit case gets a paragraph; running out of capture got
  silence, in the last window — the one a reader studies, where an absent
  aftermath reads as "the device went quiet after the error".

### Changed (phase 5, the pre-release audit)

- **The viewer has a colour system rather than a palette.** Every colour is now
  a named token in `theme.TOKENS` — `surface`, `text-muted`, `level-error` —
  and the palette, the severity colours, the mark and the stylesheet all read
  from there and nowhere else. A colour that bypassed the table would be a
  colour the contrast tests do not check, which is the only reason they are
  worth running.

  What changed on screen: a warmer, less default set of neutrals; a table body
  in a monospaced face, which is what makes a column budget of *characters*
  honest; taller rows and a taller header, with the header text left-aligned
  over the left-aligned data it labels; and chrome — toolbars, fields, menus,
  scrollbars, the status bar — styled from the same tokens. Fusion draws a
  sunken frame around every permanent status-bar widget, which was the most
  dated thing in the window and is now gone.

  **Selecting a row no longer deletes its severity.** `ForegroundRole` becomes
  the palette's `Text`, and the style draws a selected row with
  `HighlightedText` instead — so clicking an Error to read it was the moment it
  stopped looking like an Error, and only the `!` glyph survived. The table's
  selection is its own token, a wash rather than the saturated highlight that
  suits a menu, and every level clears WCAG AA on it.

  The stylesheet deliberately never names `QTableView`. Giving an item view a
  box model in QSS makes its viewport non-blittable — every scroll notch then
  repaints the whole viewport instead of the sliver that moved, measured
  elsewhere at 12.4×. Verified against this sheet on a 60,000-record capture:
  0.3% of the viewport per notch either way.

- **The Time column could lose the end of a timestamp.** A column is a budget
  of characters and the style then insets the text, so spending the budget on
  the column and the margins on the text elides the last character of anything
  sized to fit exactly. It was latent while the body font was proportional —
  `09:14:02.118` is mostly colons and full stops, narrower than the `0` the
  budget counts in — and the monospaced body is what would have exposed it, so
  the formula is fixed in the same change that could have shipped the bug.

- Several published measurements were re-measured and did not survive. The
  largest: the horizontal header optimisation shipped as *"the single biggest
  lever, 541×"*, taken against a stand-in model whose `flags()` returns a
  constant. Against the model that ships it is **about 2×** — 5.98 s to 2.92 s
  on `selectAll()` at 200,000 rows — because the rest of the time is the
  selection model and the repaint, and the prebuilt-`flags` rule has already
  made each of those million calls cheap. The two optimisations were treating
  the same wound and their savings do not add up. Corrected in `gui.md` §11,
  ADR 0004, the research note and the source.

- **A claim about another project was wrong.** `docs/design/gui.md` §5 said
  that nobody had solved keeping the user's place across a filter change, and
  that *"lnav clamps row ordinals and teleports"*. lnav does solve it, by
  anchoring on the log message's timestamp — its maintainer: *"The intention is
  to preserve the location"* — in the view where a timestamp is parsed, and it
  deliberately does not attempt it in the view where one is not. The claim was
  repeated in `gui/models.py` and in a test docstring; all three are corrected.
  Wireshark #16318 really is still open.

  Anchoring on record identity instead of on a timestamp turns out not to be
  the accuracy win the section implied: across two captures off an `iPhone18,2`
  — 39,786 records at roughly 1,000/s — **every timestamp was unique**. The
  narrower reason stands, and is what the section says now.

- Documentation that had drifted from the code: three documents promised a
  `syslog_relay` fallback source that was never built, the research note had
  the `HISTORICAL` stream flag's default backwards, `CONTRIBUTING.md` listed
  the wrong CI commands and a retracted proxy figure, `docs/formats/session-file.md`
  documented a sidecar key nothing writes and called itself a draft, ADR 0005
  counted six files in a seven-file bundle, and `CLAUDE.md` described a project
  two phases behind. `docs/design/gui.md` now records where phase 4 diverged
  from it and why, rather than reading as though it had all been built.

- ADR 0001 and the ADR README now say that a *measurement* inside an accepted
  record is corrected in place with a dated note, while a *decision* is still
  only reversed by a superseding ADR. ADR 0004 had already been edited twice
  under a rule that forbade it; the rule was the thing that was wrong.

### Added

- Repository skeleton: `pyproject.toml` (hatchling + hatch-vcs, src-layout),
  GPL-3.0-or-later licensing, `ruff` + `mypy --strict` + `pytest` configuration.
- CI across Linux, Windows and macOS; the full Python 3.11–3.14 sweep on Linux.
- Release workflow publishing to PyPI via Trusted Publishing (OIDC), so no
  long-lived API token exists.
- Architecture decision records 0001–0006 and the research they rest on, under
  [docs/](docs/).
- A `ostrace` console script and `python -m ostrace`, and — once the GUI extra
  is installed — an `ostrace-gui` entry point.

- The core: `model.py` (`Record`, `Level`, `DeviceInfo`, `Gap`), `errors.py`,
  `paths.py`, `compat.py`, `devices/discovery.py`, `storage/` (gzip JSON-Lines
  spool plus a metadata sidecar) and `sources/` with the live `os_trace_relay`
  source and an offline replay source.
- Two captures from a physical `iPhone18,2` on iOS 26.5.2, committed as test
  fixtures, so the whole pipeline is exercised in CI on three operating systems
  with no device attached.

### Notes

Three things were measured on hardware during this phase and are worth knowing
because the obvious assumption is wrong in each case.

- **Apple's log levels are not severity-ordered.** `SyslogLogLevel` on iOS 26 is
  `NOTICE=0, INFO=1, DEBUG=2, USER_ACTION=3, ERROR=16, FAULT=17`, so a filter
  written against those numbers matches everything. `Level` is our own ordered
  enum for that reason before any portability one.
- **Turning off the `HISTORICAL` stream flag starves the stream rather than
  trimming it.** The same device delivered roughly 1,600 records a second with
  it and 65 a second without, in bursts separated by up to forty seconds of
  silence. It stays on by default.
- **A quiet device can produce nothing for tens of seconds.** Any timeout has to
  come from a separate task; waiting for the next record in order to notice that
  time has passed is a hang, not a timeout.

### Added (phase 3a)

- `ostrace doctor` — diagnoses why a device cannot be reached, in dependency
  order, and stops reporting downstream failures once an upstream one is found.
  Almost every problem in this domain is environmental rather than logical, and
  that deserves a command rather than a paragraph in a README.
- `ostrace devices` — lists what is attached, `--verbose` to read identity.
- `ostrace capture` — streams a device log to a session file. `--duration`,
  `--max-records` and Ctrl-C all stop it cleanly, and the sidecar is finalised
  on every exit path including an exception.
- `ostrace.capture.capture()`, separate from the CLI because a GUI stop button
  has the same obligations as Ctrl-C.

The capture loop takes a `LogSource`, so a recorded session stands in for a
device: the end-to-end tests run a real iPhone capture through the CLI and
assert on the session file that comes out, with no hardware.

`--duration` is enforced with `asyncio.timeout`, which fires from a timer
rather than from record arrival. On a device that can go silent for tens of
seconds, a limit checked only when the next record shows up is not a limit.

### Fixed

A correctness review of phases 0 and 1 found twelve defects, all fixed before
anything depends on them:

- `aclose()` could not close the streaming session. Reading device identity
  opened a second lockdown and, on releasing it, deregistered the first — so
  every start/stop cycle leaked a socket, which is the one thing `aclose()`
  exists to prevent. It also doubled the most expensive operation at capture
  start.
- Every session closed through its context manager recorded `ended_at: null`,
  making a finished capture indistinguishable from a killed one.
- A record with no process path was named after the *first* such pid seen,
  because the pid-dependent fallback was cached against the path. The kernel
  arrives this way.
- Mid-stream outages were matched by exception type while connect-time outages
  asked `recoverable`, so a recoverable outage arriving as a different class
  ended the capture instead of reconnecting.
- Gap start came from the device clock and gap end from the host's, making the
  duration wrong by the clock skew and negative when the device ran ahead.
- `truncated` answered `False` until a full pass completed — including for the
  natural case of asking before reading.
- A non-numeric clock value from lockdown escaped as a bare `ValueError`.
- The device timezone was read once and reused across reconnects.

Plus a dead attribute, a redundant dictionary copy, a counter that
double-counted across passes, and a mixin whose default teardown silently did
nothing.

Test coverage of the live source went from 22% to 80%: the reconnect loop, gap
bookkeeping and session lifecycle are now driven in CI against stubbed device
seams, with no hardware.

### Added (phase 2)

- `analysis/` — message normalisation and a single-pass fold of a capture into
  the numbers worth reporting: counts per level, process, subsystem and minute,
  and distinct message templates with the line each first appears on.
- `exporters/` — the exporter protocol, a registry, and four formats:
  - **agent bundle** — seven files of tab-separated text designed to be
    investigated with `grep` and bounded line reads rather than loaded into a
    context window. Implements
    [docs/formats/agent-bundle.md](docs/formats/agent-bundle.md).
  - **jsonl** — the session file's own per-line shape, uncompressed, written by
    the same encoder. There is one record encoding, not two. No metadata line:
    a JSON Lines file whose first line differs from every other breaks `jq`,
    `pandas.read_json(lines=True)` and every short script, which is the entire
    audience for the format.
  - **text** — aligned columns for reading in a terminal, records and nothing
    else. Where a value overflows its column the pid is kept:
    `duetexpertd(AppPredictionI…[27291]` rather than a truncation that discards
    the field most needed to tell eight instances of a process apart.
  - **markdown** — a document to paste into an issue: which device, what span,
    how much, what the columns mean, then the records verbatim.
  - **ai-report** — a summary that shrinks to a token budget and **states what
    it dropped**. Every section counts what it could not fit and the last
    section lists it, because a report that quietly stops at the budget reads
    as complete: a reader then draws conclusions from an absence that is an
    artefact of truncation rather than a fact about the device. Asked for
    30,000 tokens it produces about 29,700; asked for 3,000, about 2,970, and
    says it omitted 720 of 744 error patterns to get there.
  - **trace** — verbatim, chronological windows around each error, for
    following causality rather than counting. The exact counterpart to
    templating: nothing is normalised or reordered, so the identifiers that let
    one object be followed across a sequence survive. Overlapping windows merge
    rather than duplicate, and the report declares both the anchors it could
    not reach and any window that ends mid-sequence.

`session.log` gained the two columns this rewrite existed for. A query like
"every record from `com.apple.network`, across every process" is not
expressible in the predecessor's four columns; on the committed fixture it
returns 473 records spanning six processes.

Normalisation was extended past the predecessor's rules after measuring what
survived them. The dominant leak was hex with no `0x` prefix — operation
identifiers, content references, protection tags, which iOS emits constantly
and which are pure identity. Recognising them folds the fixture's 1,677
templates to 1,431. A second candidate, loosening the word boundary so that
`1.25s` normalises, was measured and rejected: worth 4 templates out of 1,677.

The generated `CLAUDE.md` is bounded by construction — a bundle of two million
records must not produce a longer one than a bundle of six thousand — and it
declares what it cannot show: gaps in the capture, and any records whose
template was dropped at the cap.

The markdown and AI-report exports state the level set iOS actually emits. The
predecessor documented `Warning` and `Critical`, which it had inherited from the
legacy text stream; a reader who trusted that would filter for a level that
never appears.

Bounding a trace by the *number* of windows turns out not to bound it at all.
An anchor arriving inside an open window extends that window, so where anchors
are dense the extensions never stop: on the error-heavy fixture — 2,250 errors
in 3,000 records — the window-count limit alone produced exactly one window
containing the entire capture, which is not a trace of anything. Windows are
capped by size as well, and one closed that way says it ends mid-sequence
rather than where the interesting records stopped.

A scan now also keeps a bounded verbatim window around the *first* error — the
first, not the most frequent, since what follows it may be consequence rather
than cause. Templating is what makes a large capture describable and also what
hides the one value that mattered; the window is the antidote, and it costs a
fixed 200 records however large the capture is.

### Added (phase 3b)

- `ostrace export` — turns a capture into any of the six formats. It needs no
  device, reads either a session directory or a bare capture file, and writes
  beside it named after it. `--format` choices come from the exporter registry,
  so registering an exporter is all it takes to expose it.

  ```bash
  ostrace export capture.ostrace                  # a bundle beside it
  ostrace export capture.ostrace -f trace         # what led to each error
  ostrace export capture.ostrace -f ai-report --budget-tokens 20000
  ```

  Anything that would make an absence in the output mean something other than
  "the device did not do that" is reported to stderr: gaps in the capture,
  records dropped at the pattern limit, a capture with no gzip trailer because
  it was still being written, and an empty capture. `--quiet` prints only the
  destination, so the command composes with a shell.

  The default is the agent bundle, because it is the only format that loses
  nothing. Everything else is a summary, and a default that quietly discards
  data is the wrong default.

### Changed (phase 5, the README)

- **The README describes what ships rather than what is planned**, with
  screenshots of the viewer in both colour schemes. The images are absolute
  URLs because this file is also the PyPI description, where a relative path
  resolves to nothing.

- It now says what 0.1.0 is *not*: no binaries, nothing signed, macOS verified
  by CI rather than by hand. Every one of those is something a reader would
  otherwise have to discover, and the macOS one in particular is a fact about
  how much this project's macOS support has actually been exercised.

### Fixed (phase 5, found by looking at a picture)

- **The detail pane sized every row to half the height of its text.** It sizes
  itself from what its wrapped text actually needs — a word-wrapped `QLabel`
  reports a minimum of about one line, and a scroll area reads that as
  permission to compress — but it asked the layout that question immediately
  after replacing the rows, when the layout still answers for the *previous*
  contents. Coming from the placeholder, twelve fields were given 8 pixels each
  where they needed 16.

  Every existing test of that pane reads text, and the text was correct
  throughout. The new one compares each row against its own requirement rather
  than against a pixel count, so it means the same thing offscreen.

- **A capture that would not stop took the whole viewer down with it.** The
  wait in Disconnect is bounded — five seconds, so that a device refusing to
  let go cannot freeze the window — and the line after it cleared the last
  reference to the capture thread whether or not that wait had succeeded.
  Dropping a running `QThread` is not a leak: Qt's destructor aborts the
  process. Measured here at exit code `0xC0000409`, with no message on either
  stream, so the symptom a user would report is "it disappeared".

  A thread that outlives the wait is now kept until it really finishes, and the
  user is told — the device is still held, so the next capture would find the
  relay busy.

### Changed (phase 5 groundwork)

- **The screenshot job renders a window with a real capture loaded.** An empty
  table says nothing about column widths, elision, severity colouring or the
  detail pane, which is most of what there is to get wrong on the one platform
  that cannot be looked at here — and it is what the README needs.

- The GUI job runs `python -X faulthandler -m pytest` rather than the console
  script. pytest turns faulthandler off when the session ends, and the one CI
  failure this job has had was the process exiting 1 *after* reporting 159
  passed, with nothing on either stream and no reproduction. The cause is still
  unknown; this is what makes the next occurrence legible.

### Added (phase 4, the overview strip)

- **A minimap beside the table**, marking every error, gap and mark across the
  whole capture. Clicking jumps there. It is the only mechanism in the program
  that reveals a discontinuity *outside* the viewport — a gap forty thousand
  rows above where somebody is reading is otherwise something they never learn
  about, which would undo the reason a gap is a first-class row at all.

  Deliberately not a `QScrollBar` subclass. A scrollbar is drawn by the
  platform style, and painting into its groove means fighting different metrics
  on each platform — on the one platform that cannot be tested here, blind.

- **Row-anchored buckets in the model.** Summarising into pixel bands has to be
  recomputed from scratch whenever a row arrives, because the bands move:
  measured at **282 ms** over 200,000 rows, a third of a second of frozen
  window, twenty times a second. Buckets anchored to row numbers make an append
  touch only the last bucket, and the summary itself now costs **0.59 ms** —
  about 480× faster.

  Errors go through the buckets, because they are dense enough that a bucket of
  smear is invisible. Gaps and marks are placed exactly, because they are rare
  and they are the whole point.

### Fixed (phase 4, the overview strip)

- **A single gap smeared across two fifths of the strip.** Summarised by
  bucket, two gaps in a short capture lit 79 bands out of 180 — a picture
  saying that most of the log was missing.

- **A short capture collapsed to five stripes.** Lighting only the band a
  bucket *starts* in is right when there are more buckets than bands and wrong
  in the other direction; every band a bucket spans gets its flags now.

### Added (phase 4, export)

- **An export dialog that says what it left out.** Any of the six formats,
  written beside the capture and named after it, with the token budget offered
  only for the one format that has one.

  It does not close on success. An export button that reports "done" and
  nothing else is easy to write and quietly wrong: a summary that stopped at a
  budget reads as complete, and the reader then draws conclusions from an
  absence that is an artefact of truncation rather than a fact about the
  device. The dialog stays open and lists the omissions — and says nothing when
  there is nothing to say, because a warning that always appears is one nobody
  reads.

- `exporters.notes.export_notes()`, shared with the CLI. Those sentences were
  private to `ostrace export`; two spellings of "this capture has a gap in it"
  would eventually disagree about which one mattered, and the reader should be
  told the same truth whichever way they asked.

### Fixed (phase 4, export)

- **Exporting to an impossible path escaped the button handler.** Only
  `OstraceError` was caught, and writing into something that is not a directory
  raises `OSError` — an ordinary mistake, and an exception out of a slot takes
  the window with it.

### Added (phase 4, navigation)

- **Keyboard navigation, marks and copy.** Jump to the next or previous error,
  gap or mark; mark a row and come back to it; step rows while the detail pane
  has focus; copy the selection.

- **One binding table that is also the documentation.** `gui/shortcuts.py`
  holds the list; the window builds its actions from it and `F1` renders it, so
  a key that changes changes the help in the same commit or not at all. klogg's
  fourth trap is a key table in a manual that drifted from the code.

  Both traditions are aliased rather than chosen between — `Ctrl+End` *and*
  `Shift+G`, `Ctrl+Shift+E` *and* `E` — because this ships on Windows and macOS
  desktops and is also a log viewer, and picking one would be right for half
  the users at no saving. Tests assert that every action has a key, that no
  destructive verb sits on an editing chord (klogg's `Ctrl+X` truncates the
  file on disk), and that aliases are really registered rather than merely
  documented.

- **Marks are held by source index**, the same handle selection anchors on, so
  a filter change moves them with their records instead of leaving them
  pointing at whatever now occupies that row. A mark on an evicted record goes
  with it: a bookmark pointing at nothing is worse than none.

- `Ctrl+End` twice resumes following, in klogg's order. Conflating "go to the
  bottom" with "stay there" is what leaves Wireshark's users with *"Ctrl End is
  close, but doesn't resume auto scroll"*.

### Fixed (phase 4, navigation)

- **Copying a record could produce several lines.** Device messages contain
  newlines and tabs, and a record spilling across lines breaks every consumer
  of a tab-separated paste — which is the whole audience for the feature. The
  clipboard now uses the exporters' own folding rule rather than a second
  spelling of it, and fills back in the repeated cells the table blanks for
  readability.

- **A marked row looked exactly like a selected one.** The mark borrowed an
  accent colour that turned out to be the selection colour. Marks have their
  own amber tint now, checked against every severity foreground for legibility.

- **`gui/shortcuts` segfaulted the interpreter if imported without a
  `QApplication`.** Constructing a `QKeySequence` without one is not an
  exception, it is a crash — so a check that ran at import time turned a
  mistake in the table into a dead test run with no traceback. The module holds
  data at import and touches Qt only inside functions.

### Added (phase 4, live capture)

- **The viewer captures from a device.** `Capture` streams from an attached
  iPhone into the table and into a session file at the same time, using the
  same `ostrace.capture.capture` the CLI runs. Verified on an `iPhone18,2`:
  1,191 records in eight seconds, device identified in the status bar,
  disconnect clean.

  One capture loop, not two. It is the only place that knows a device stream is
  two sockets and that both must be released, in order, on every exit path
  including cancellation — a lesson this project has already paid for once.

- **The device stream never touches the GUI thread.** It runs on a thread with
  an event loop of its own and reaches the window through a `deque`: the
  producer appends, a 50 ms timer drains, one `beginInsertRows` per batch. At
  1,600 records a second that is about eighty rows per batch and twenty model
  updates a second, against sixteen hundred if each record arrived on its own
  signal. **No Qt signal carries a record**; signals are for lifecycle only.

- **Pause freezes the view and nothing else.** The capture keeps running and
  keeps writing every record to disk, so the promise is real rather than
  rhetorical. What a long pause cannot do is hold everything in memory, so the
  queue is bounded — and when the bound bites, the dropped records are
  announced as an **eviction**, not a gap, because they are in the session file.
  The two look alike on screen and mean opposite things.

- Auto-follow derived from the scrollbar on every tick rather than stored as a
  mode. A stored flag can disagree with the view; Console.app kept one and
  shipped an eleven-month bug where selecting a row silently stopped the tail.

- Closing the window releases the device.

### Fixed (phase 4, live capture)

- **Disconnecting a capture that had already ended crashed.** The capture ends
  by itself when the device is unplugged, and the obvious next thing anyone
  does is press Disconnect — which reached across to an event loop that had
  already closed and raised `RuntimeError: Event loop is closed`.

- The row cap now trims with `beginRemoveRows` rather than a full model reset.
  Resetting is easier and throws away the user's selection and scroll position
  every time the cap is reached — which, on a live capture, is every couple of
  minutes forever, and always while they are reading something.

### Changed (phase 4, live capture)

- `capture()` takes an `on_item` callback, so a live view can show what is
  being captured without a second loop over the device.
- The banner's button carries *what it does* rather than the caller inferring
  it from the wording. There are several of these messages now, and matching on
  the text to decide what the button meant is a bug waiting for a reword.

### Added (phase 4, the viewer opens a capture)

- **`ostrace-gui` now shows a log.** `Open Capture…` reads a session directory
  or a bare `.jsonl.gz` into the table, with severity colouring, repeated cells
  blanked, a filter row, and every field of the selected record in the detail
  pane below.

- **Selection and viewport anchor to a *record* across a filter change**, not
  to a row number. If the anchored record does not survive the new filter, the
  nearest survivor after it is where the user lands, because that is still the
  point in the log they were reading.

  Nobody surveyed does this: Wireshark #16318 has been open since 3.0.7, lnav
  clamps row ordinals and teleports, and Android Studio's Logcat clears and
  re-appends its whole document, so every keystroke in the filter field throws
  the user to the bottom.

- `storage.open_capture()`, shared by the CLI and the viewer. Whether a path is
  a session directory or a bare spool is one decision, and it was previously
  made inline by `export` — where the viewer would have had to make it again,
  and eventually differently.

- A batched loader. A capture is read from a zero-delay timer that hands
  control back to the event loop between batches, so a large file does not
  hold the GUI thread for the whole read. No thread and no lock: that is the
  right shape for a file, which is fast and finite.

### Fixed (phase 4, found by looking at the screen)

- **`FastHeader` had silently removed the column titles.** Skipping
  `super().initStyleOptionForIndex` avoids the quadratic selection query — and
  also skips the part that fills in the section's *text*, so the header painted
  empty. Nothing failed: the suite passed and the benchmark improved. Only a
  screenshot showed it. The cheap half is reimplemented now and the titles are
  back, at a small cost against the broken version — both figures were taken
  against a stand-in model, and neither survives contact with the real one; see
  the corrected table above.

- **The detail pane clipped and overlapped its rows.** A word-wrapped `QLabel`
  reports a minimum height of about one line, which a scroll area takes as
  permission to compress; the form was squeezed below the height its text
  needed instead of scrolling. It is sized from the layout's `heightForWidth`
  at the viewport width now.

- **The detail pane compared a saved record against the current wall clock**
  and labelled the result a clock difference. A record captured this morning is
  not "36,000 seconds out"; it is from this morning. The host clock is shown
  only for a live capture, where the two really are readings of one moment. The
  device's UTC offset — the fact this project's timestamp rule turns on — is
  now a field of its own, true either way.

### Added (phase 4, the model)

- **`RecordModel`** — the table model: a plain list of retained items, its own
  filtered index, and a bounded head. Records arriving under a filter test only
  themselves and append, so the steady state is O(batch); only a filter
  *change* rescans.

- **The marker invariant, implemented at one choke point.** A gap or an
  eviction notice is exempt from filtering *by type*, before any predicate
  runs. A filter says which records the user wants; a marker says whether the
  answer is complete, and hiding it makes the filtered view lie about its own
  completeness. `is_record()` is a `TypeGuard`, so the type checker proves a
  filter is only ever handed a `Record` — the invariant and the types cannot
  drift apart.

- **A gap and an eviction do not render the same.** One says the records are
  gone and nothing buffered them; the other says they are in the capture on
  disk and merely not on screen. The eviction notice is updated rather than
  accumulated — twenty evictions are one fact about the view, not twenty rows
  of noise at the top of it.

- `Filter` as a value object. An invalid regular expression raises at
  construction rather than becoming a filter that quietly matches nothing: a
  user halfway through typing `[com` has an incomplete pattern, not an empty
  log, and a view that empties itself as they type is indistinguishable from a
  device that stopped talking. A process term matches a pid exactly and a name
  loosely, so `97` does not match `launchd[9712]`.

### Changed (phase 4, the model)

- **ADR 0004's `QSortFilterProxyModel` figure does not reproduce.** It records
  roughly 66× and calls the proxy "a frozen window". Re-measured on PySide6
  6.11.1 at 100,000 records, changing the filter to a message substring, best
  of three with a view attached: this model 0.130 s, the proxy's built-in regex
  over a role 0.607 s, a Python `filterAcceptsRow` 0.642 s. About **4.7×**, and
  nothing froze. The decision is unchanged — 4.7× is worth having, and the row
  cap, eviction notice and marker exemption all need a model we own — but it no
  longer rests on that number.

### Fixed (phase 4, the model)

- **A run of repeated cells could exhaust the stack.** Blanking a cell that
  repeats the row above asked what the row above *displayed*, which asks
  whether that row was itself a repeat, all the way to the top of the run —
  recursion whose depth is the length of the run. A capture with 100,000
  consecutive records from one process crashed; the tests had runs of three and
  saw nothing. It compares the underlying fields now, which is O(1). Found by
  benchmarking, not by the suite, and the regression test uses a run of 5,000.

### Added (phase 4)

- **The GUI shell**, behind the optional `gui` extra: `pip install 'ostrace[gui]'`,
  then `ostrace-gui`. Menu bar, filter row, record table, detail pane and status
  bar, themed and running — with no data in it yet. The CLI is unaffected and
  Qt is never imported unless the viewer is launched, so a missing extra
  produces one sentence naming the command to run rather than a traceback.

- **A screenshot workflow**, `workflow_dispatch` only, rendering the window on
  macOS and Windows in both colour schemes and uploading the images. This is
  the answer to the constraint that runs through the whole project: there is no
  Mac here, Qt silently relocates macOS menu items by matching their text, and
  a passing test suite says nothing about either.

  Two measurements shaped it. `QWidget.render()` produces real pixels under the
  `offscreen` platform plugin on a widget that was never shown, so macOS needs
  no display, no window manager and no xvfb. But that plugin's font database is
  **empty on Windows** — every glyph renders as a tofu box while `QFontMetrics`
  keeps returning plausible numbers — so Windows uses the native plugin, and no
  test may assert a font metric offscreen. The capture tool refuses to write a
  picture it knows is unreadable, because an unreadable screenshot still looks
  like evidence.

- **`FastHeader`**, a `QHeaderView` that does not ask the selection model which
  columns are selected. QTBUG-59478 has been open since 2017 and its fix was
  abandoned the same year. Measured at 200,000 rows × 6, `selectAll()`:

  | header | time | `flags()` calls |
  | --- | ---: | ---: |
  | stock `QHeaderView` | 5.98 s | 1,200,689 |
  | `FastHeader` | 2.92 s | 683 |

  About 2×, with the column titles still on screen. Asserted in CI on call
  counts rather than elapsed time, because a wall-clock threshold on a shared
  runner is a flaky test in a performance test's clothes.

  This shipped as *"541×, the single biggest lever"*, from a run against a
  stand-in model whose `flags()` returns a constant. Against the model that
  ships, the header is not the whole cost and the prebuilt `_flags` rule has
  already made each of those million calls cheap, so the two savings overlap
  rather than add. Corrected before the release rather than published.

- **A theme that is a function from a colour scheme to a `QPalette`**, rather
  than colours read out of the platform. `QStyleHints.setColorScheme()` is a
  no-op under the offscreen plugin, so the naive approach cannot be tested or
  screenshotted at all. As a function it can: CI asserts every severity colour
  against WCAG AA in both schemes, and the screenshot job forces either scheme
  on any platform. Colour is never the only cue — the Level column stays text
  and the two urgent levels carry a glyph.

- A `gui` pytest marker and a CI job that runs those tests on Linux, Windows
  and macOS under one interpreter — the opposite shape to the existing sweep,
  because what they verify is portability across operating systems rather than
  across Python versions.

### Added (phase 4 groundwork)

- [`docs/design/gui.md`](docs/design/gui.md) — the GUI behaviour contract,
  written before the code the way `docs/formats/` was. It fixes what breaks
  follow, what a filter may never hide, what "pause" is allowed to touch, and
  what the user is told when records go missing.

  The load-bearing rule is that a marker — a gap, a view eviction, a
  connect — is exempt from filtering by type, at the one choke point, before
  any predicate runs. A filter says which records the user wants; a marker says
  whether the answer is complete, and hiding it makes the filtered view lie.
  No surveyed log viewer guarantees this.

### Changed (phase 4 groundwork)

- **Half of [ADR 0004](docs/adr/0004-pyside6-with-custom-filtered-model.md)'s
  performance table did not survive re-measurement** on PySide6 6.11.1, and is
  superseded by `docs/design/gui.md` §11. Overriding `multiData()` is
  *marginally slower* in PySide6 (0.96–0.99×), not the biggest available win:
  the span has to be iterated from Python, so seven inbound crossings become
  one inbound plus about fourteen outbound. The `flags()` caching figure was
  overstated by roughly 15× (~1.3×, not 20×). The horizontal header, recorded
  there as a footnote, is worth about 2× — overriding
  `initStyleOptionForIndex` removes 1,200,006 of 1,200,689 `flags()` calls,
  which is the *cause* the caching rule was treating rather than a second
  independent win. The `QListView` figures were fixed in Qt 6.8, which this
  project already pins.

  The decision itself — PySide6 with a hand-written filtered model — is
  unaffected.

### Fixed (found on hardware)

- **`aclose()` did not stop a running stream.** It closed the lockdown session,
  returned in a millisecond and reported success — while the records kept
  coming, because they arrive over a *second* socket: `os_trace_relay` is a
  service connection that lockdown merely starts, and closing lockdown does not
  touch it. Measured on an `iPhone18,2`: 8,239 further records in the five
  seconds after "closing", and the orphaned service left the next capture unable
  to stream at all. `_stream_once` never closed the service on the ordinary path
  either, so every connection leaked one.

  Nothing in CI could have caught this. The stubbed tests replace
  `_stream_once`, which is the only place the service connection exists — so the
  one function that owns the socket was the one function no test ran. It now
  has two device tests of its own.

- **A deliberate stop was indistinguishable from a dropped cable.** `aclose()`
  works by closing the socket the stream is reading, so the failing read looks
  exactly like an outage. With reconnection enabled the source answered a stop
  by reconnecting to the device it had just been asked to release, and wrote a
  gap for an outage that never happened. Stopping is now a clean end of stream
  rather than an error — a stop button that reports a failure every time is a
  stop button nobody trusts.

### Changed

A review pass over phases 0 and 1 tightened several things before they had
callers to break:

- Naming a capture is one decision and now lives entirely in `paths.py`. It was
  split, and the halves cancelled out: the suffix was applied with
  `Path.with_suffix`, which *replaces* the last dotted component, so a device
  called `iPhone 15.1` produced `iPhone-15.ostrace` and lost the timestamp that
  makes the name unique.
- Errors declare whether they are `recoverable`, and the reconnect loop asks
  them instead of enumerating types. A device that was never trusted used to be
  retried thirty times before its hint appeared, with a fabricated gap written
  into the session file for an outage that never happened.
- Every source is an async context manager, declared on the protocol. Only one
  of the two implemented it, so the teardown pattern the tests establish would
  have failed the first time it met a replay fixture.
- The `-O` guard moved from package import to `OsTraceSource`. It is a
  constraint of one library, and offline replay was being blocked by it.
- `DeviceInfo` carries its platform rather than the label hardcoding "iOS", and
  `Record.platform` is required rather than defaulted.
- Reading device identity uses the value dictionary the lockdown client already
  holds: one round trip became none, where it used to be seven before the first
  record could arrive.
- Deriving a process name from its path is cached, and `Record.image` no longer
  builds a `PurePosixPath` per access — together about 40% of the measured
  per-record ingest cost, and it takes `pathlib` off `model.py`'s import path.
- Scanning a capture for gaps no longer decodes every record on the way past.
- Dropped from `compat.py`: the subprocess helpers, which supported an
  architecture ADR 0002 rejected, and the platform constants, which the module's
  own rules left with no legal caller.
- `Environment :: X11 Applications :: Qt` was dropped while there was no
  graphical interface, and is declared again now that phase 4 ships one,
  alongside the Win32 and macOS environment classifiers.

### Security

The repository's own configuration is now what a public project is expected to
have. Most of it is invisible until it is missing:

- **`SECURITY.md` pointed at a page that did not exist.** It asks reporters to
  use GitHub Private Vulnerability Reporting, which was never enabled, so the
  link returned 404 and no fallback address was published. Anyone following the
  documented process reached a dead end. Enabled.
- **Actions are pinned to full-length commit SHAs**, and the repository now
  rejects a tag reintroduced by hand. A tag is mutable by whoever owns the
  action's repository; a SHA is not. Dependabot runs weekly for actions rather
  than monthly, because a pin is only as good as the bumps that get merged.
- **`actions/checkout` no longer persists `GITHUB_TOKEN` into `.git/config`.**
  Neither workflow pushes anything, so the credential existed only for a later
  step -- including whatever `pip install -e .` chooses to execute -- to find.
- **The GitHub release is cut with `gh` rather than a third-party action.** That
  was the only step running non-GitHub code, and the only one holding
  `contents: write`.
- **`zizmor` lints the workflows**, in CI and in pre-commit. The workflows are
  the part of this repository with real privilege: one holds an OIDC identity
  that can publish to PyPI, which no Python file here can do.
- **A release cannot be cancelled halfway.** `release.yml` queues instead;
  cancelling between "published to PyPI" and "attached to the GitHub release"
  would leave a version that exists in one place and not the other.
- Dependabot alerts and security updates, CodeQL default setup over both Python
  and the workflows, immutable releases, and a ruleset that blocks force-pushing
  or deleting `main` -- with no bypass, since an admin exemption set to "always"
  is the same as not having the rule.

[Unreleased]: https://github.com/BerkayCaglar/ostrace/commits/main
