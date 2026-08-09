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

- **Help ▸ About**, which is now the only place the viewer says which version
  it is. The application has always known — nothing displayed it.

### Removed

- **Edit ▸ Settings…**, which opened nothing. Nothing in this release is
  configurable, and an inert Preferences item is worst on the platform its
  menu-role machinery exists for: macOS moves it into the application menu,
  where it is the item people press without looking.

### Fixed

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

### Changed

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

## [0.1.0] - 2026-08-09

The first release, and the first entry: everything here is new, so the sections
below are the order it was built in rather than a diff against a version that
does not exist. Where a measurement contradicted a decision, the entry says so
rather than quietly adopting the new number.

What you get is a command line (`devices`, `capture`, `doctor`, `export` with
six formats) and a graphical viewer (`ostrace-gui`), on Windows, macOS and
Linux, reading Apple's unified log over `os_trace_relay` — subsystem, category,
thread and emitting library included, at DEBUG level and above.

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

[Unreleased]: https://github.com/BerkayCaglar/ostrace/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/BerkayCaglar/ostrace/releases/tag/v0.1.0
