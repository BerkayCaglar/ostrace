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
┌────────────────────────────────────────────────────────────────────────┐
│ Capture  Edit  View  Help                                              │
├────────────────────────────────────────────────────────────────────────┤
│ ▯ iPhone ▾ │ ▷ Capture  ‖ Pause  ⏏ Disconnect │ 🗀 ⭳ │ ⌃ ⌄            │
├────────────────────────────────────────────────────────────────────────┤
│ Level ▾  Process [___≠]  Subsystem [___≠]  Search [___.*]  Filters ▾  │
├──────────┬───────┬──────────┬────────────┬──────────┬─────────────────┤
│ Time     │ Level │ Process  │ Subsystem  │ Category │ Message         │
├──────────┼───────┼──────────┼────────────┼──────────┼─────────────────┤
│ 01:10:31 │ ERROR │ dasd[83] │ com.apple… │ default  │ Unable to dere… │
├──────────┴───────┴──────────┴────────────┴──────────┴─────────────────┤
│ detail pane — every field of the selected record                       │
├────────────────────────────────────────────────────────────────────────┤
│ ● 1,204 rec/s │ iPhone · iOS 26.5.2 │ 1.2M records │ 0 gaps            │
└────────────────────────────────────────────────────────────────────────┘
```

**The toolbar and the device selector were built after 0.1.0's first pass**,
having been drawn here before either was decided and then left out of phase 4.
Until they existed, Capture, Pause, Disconnect, Open and Export were menu items
and shortcuts only, and the viewer captured from whichever USB device answered
first — `OsTraceSource` has always taken a udid and nothing passed one, so with
two devices attached the choice was invisible.

The toolbar carries the device selector, the three capture verbs with their
labels, Open and Export as icons, and the jump to the previous or next error.
Every button drives an action that already exists with a shortcut and a menu
item, so it is a second route to a verb rather than a second implementation.
Capture, Pause and Disconnect keep their text because those three differ in
consequence — one starts a device stream, one freezes a view, one releases the
hardware — and a row of unlabelled glyphs is what makes a tool look dated.

There are six columns, not five: `Category` was in §2's table from the start
and missing from here.

The status bar always shows the gap count, **including when it is zero**.
Wireshark bug 12005: a `Dropped` counter rendered only when non-zero silently
regressed to never rendering, and nobody could tell "no drops" from "counter
broken". A number that is always there is falsifiable; one that appears only on
bad news is not.

---

## 2. Columns, and what the detail pane is for

`Record` has eleven fields and the table shows six. The split is not about
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

### The marker kinds are not one kind

| Marker | Means | Recoverable? |
| --- | --- | --- |
| **Gap** | Records the device emitted and nothing received. `Gap(start, end, reason)`, written to the session file | **No.** Gone forever |
| **Evicted** | The view hit its row cap and dropped its own oldest rows | **Yes.** Still in the capture on disk |

Connect and disconnect were listed here as a third kind and are **not rows**.
They are lifecycle, not discontinuity: nothing is missing from the log because
a capture started, and the invariant above is about whether an absence can be
trusted. They surface as banner and status-bar state instead. A device that
*leaves mid-capture* does produce a discontinuity, and that is a `Gap`.

**Gap and Evicted must not render as the same row.** They look alike and mean
opposite things: one says the data is gone, the other says the data is on disk
and merely not on screen. Rendering an eviction as a `Gap` would make the GUI
lie about the session file. The eviction row says so in its own words — *"…
earlier records are in the capture but not in this view"*. It says where the
records are; it does not offer to take you there, and an earlier draft of this
paragraph promised a jump that was never built.

Every tool surveyed gets the eviction case wrong by saying nothing at all:
Logcat's `trimToSize()` is silent, the AWS toolkit silently trims 10,000 lines
while faithfully reporting *server-side* sampling, and Console.app "holds no
more than a few seconds of data before it starts throwing away old lines" —
that last one at exactly this project's throughput. Copy Logcat's one good
habit: cut on a record boundary.

Gap wording follows the plaintext exporter, so the same event reads the same
in both places: `---- gap {start} to {end} ({reason}) --------------------`,
built by `exporters.plaintext.gap_line`, which the table calls rather than
spelling out. The exporter's line is not itself specified in `docs/formats/` —
an earlier version of this sentence cited that rule for it, which was a
citation to nothing — so the rule is simply that there is one spelling and the
exporter owns it. The table passes full timestamps where the exporter passes
times of day, because a table has a Time column beside it and a text file does
not.

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

Gaps and errors also belong in a **minimap** (Wireshark's Intelligent
Scrollbar, klogg's overview strip). It is the only mechanism found that reveals
a discontinuity outside the viewport, and the alternative is a user who never
learns the hole exists.

Built as a strip rather than a `QScrollBar` subclass: a scrollbar is drawn by
the platform style, and painting into its groove means fighting a different set
of metrics on each platform — blind, on the one that cannot be tested here.

Its resolution has to be right in *both* directions, and getting either wrong
produces a confident lie. Errors are dense, so they are summarised into buckets
anchored to row numbers — pixel bands move as rows arrive, which forced a full
rescan measured at 282 ms over 200,000 rows against 0.59 ms for buckets. Gaps
and marks are rare and are the whole point, so they are placed exactly: by
bucket, two gaps in a short capture lit 79 bands out of 180.

**It also shows where the reader is.** Without that the strip says *what* is in
the capture and not *where you are in it*, which makes it a picture rather than
a map — and the click-to-jump it has always had is aiming at a target the
reader cannot see themselves on. The marker is a translucent fill with a solid
edge, drawn last: the fill has to be a wash or it hides the errors it is
supposed to locate you among, and the edge has to be solid or the marker
disappears on the long quiet stretches where there are no stripes for a wash to
be seen against — which are exactly the stretches somebody is scrolling to get
across. It is never drawn thinner than three pixels, because forty rows on
screen out of two hundred thousand rounds to nothing and a marker that rounds
away teaches the reader that the strip has none.

The range is pushed in by the window rather than pulled from the table: a strip
that reached for a table would be one that only works next to one. It is fed
from the table's own `viewport_changed`, which covers scrolling, resizing,
arrivals and trims — deliberately **not** from the capture tick, because a
file that is not being captured has no ticks and the marker would sit at the
top of every capture anybody opened.

---

## 4. Follow

**Follow is derived from the viewport on every repaint. It is never a stored
bit.** Logcat computes its toggle from caret plus scrollbar; Console.app stored
a flag and shipped an eleven-month tail-breaks-on-selection bug. A stored bit
can disagree with the view, and then the button is lying.

**Breaks follow:** selecting a row, scrolling up by any amount, an explicit
jump. **Does not break follow:** horizontal scrolling.

Since 0.2.0 the derivation lives in `gui/follow.py` rather than on the window,
and the rule survives the move intact: `MainWindow.following` still answers on
every read, by asking the object that also does the scrolling. Two inputs are
*noted* there — whether the view was at the bottom when a person last moved it,
and that a scroll has happened and not yet been read, because `actionTriggered`
arrives before the scrollbar's value changes. Neither is the answer. What this
section forbids is storing the conclusion, and nothing does.

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

Resuming *clears the selection*, which is what "stay" means once selection
breaks follow: a caret parked on the last row is exactly the evidence of a
reader who has stopped tailing, so leaving it there would break the tail again
on the very next record.

**`Esc` is the other half and does only its own half.** It lets go of the
selected row and moves nothing. It briefly did more — forcing the at-bottom
state and scrolling there, on the reasoning that letting go of a row is asking
for the tail back — and against a real capture that reads as `Esc` throwing the
reader to the end of the log from wherever they were, which is precisely where
they had chosen not to be. It is also unnecessary: follow is derived from the
viewport, so deselecting at the bottom resumes the tail on its own and
deselecting half way up does not. Only `Ctrl+End` asks for the end.

**The indicator is built, and it is also the control.** It sits at the end of
the status bar, says `Following` or `Not following`, and pressing it does the
other one — Logcat, Wireshark, DebugView and klogg all carry the same thing,
and all four put the state on it rather than the verb, because "am I still
seeing the newest records" is asked at a glance. It was missing, and the state
was therefore derived correctly and shown nowhere: clicking a row stops the
tail on purpose, and the two ways back were a key nobody had been told about
and a menu item two levels down.

**One derivation, read by both.** `MainWindow.following` is the whole of it;
`_follow` acts on it and the status bar shows it, so the indicator cannot come
to a different conclusion from the behaviour. An indicator computed separately
would be the Console.app bug with a second face.

Putting the state on screen immediately exposed a promise this section had not
been keeping: the second press of `Ctrl+End` resumed nothing for a reader who
had *scrolled* away rather than clicked away, because it cleared the selection
and scrolled without restoring the at-bottom state. It goes through the same
`set_following` as the button now.

The control is live only during a capture. There is no tail to follow in a
file, and a control that is enabled with nothing to do is one that has to be
tried before it can be understood.

**How far behind is beside it, and is derived the same way.** `Not following`
says the tail has stopped and says nothing about whether five records or fifty
thousand have gone past since, which is the question the reader actually has.
`MainWindow.behind` answers it from the row at the bottom edge of the viewport
rather than by counting arrivals: O(1), and right after a filter change, a trim
or a jump — each of which moves the reader relative to the end without a record
arriving at all. A partially visible row at that edge counts as behind, which
errs towards "you have not read this one".

**It is silent more often than it speaks**, and both silences are rules rather
than omissions. Following, because a followed view is at the end by definition —
including in the hundred milliseconds where `_follow` has coalesced the
scrolling and the view has not caught up, which is several times a second of
every capture and would otherwise flicker. And in a file, because a capture that
is not running has no arrivals: every row below the viewport has been there
since it opened. That second silence is asked of the control's own enabled
state, so the count goes quiet exactly when the button beside it does.

This is the `set_shown` rule and not the gap-count rule. A gap counter that
appears only on bad news is indistinguishable from a broken one; here "nothing
behind" and "not counting" are the same state, so there is no ambiguity for an
always-present zero to resolve.

---

## 5. Filtering and highlighting

**Two verbs over one expression language.** Filter removes rows; highlight
marks them in place. Wireshark, Procmon, DebugView and lnav all converge here,
and they compose: filter to `Error`, then highlight `404` within it.

Two refinements worth taking: a **gutter indicator**, so a highlight hit is
visible when the message column is truncated, and a **per-term hit count**,
which turns highlight into a free live aggregate.

> **Both verbs exist as of 0.3.0, and both refinements went in with the
> second.** Phase 4 built only the filter; 0.2.0 washed the *filter's* search
> term inside the Message cell and said in the same breath that this was the
> cheap eighty per cent, because one field cannot narrow and mark at the same
> time.
>
> The two are separate values and travel on separate signals, because they cost
> different things — a filter change re-tests every retained row and moves the
> reader, a highlight change repaints forty — and because `Filter` equality is
> what decides whether the model rescans. Changing what is marked must not do
> that.
>
> **They share one wash.** Two colours would have to be measured against the
> contrast floor, sit far enough apart to be nameable, and then be explained;
> what distinguishes the highlight is that it has a gutter tick, a count, and
> chevrons that stop at it. Their spans are merged before drawing, because a
> translucent wash painted twice is darker than the colour that was held to the
> floor.
>
> **The gutter indicator's premise was measured rather than assumed.** Over the
> 8,000 committed fixture messages, the fraction of hits elided out of the
> Message column: `error` 40.5% at 1280 px and 29.8% at 1920, `connection` 34.1%
> and 16.8%, `timeout` 44.0% and 8.0%, `xpc` 5.8% and 1.9%, `assert` 1.5% and
> 0.0%. A third of the hits on the commonest terms are invisible at the default
> width, and widening the window barely moves the worst of them, because the
> messages that mention a word late are the long ones.

**Filtering is incremental.** Each arriving batch tests only the new records
and appends matching indices — O(batch). Only a filter *change* rescans.

This is the hand-written index list from ADR 0004 rather than
`QSortFilterProxyModel` — but **the ADR's figure for that does not reproduce**.
Re-measured on PySide6 6.11.1 at 100,000 records, changing the filter to a
message substring, best of three with a view attached: this model 0.130 s, the
proxy with its built-in regex over a role 0.607 s, the proxy with
`filterAcceptsRow` written in Python 0.642 s. About **4.7×**, not 66×, and
nothing here is the six-second freeze the ADR describes.

The decision stands on the smaller margin plus control of the row cap, the
eviction notice and the marker exemption — not on the original number.

> Note for anyone reading the prior-art research: it recommends implementing
> the marker exemption inside `QSortFilterProxyModel.filterAcceptsRow()`. The
> insight is right and the location is not available to us. The exemption goes
> at the head of our own predicate, which is the same choke point.

**Selection and viewport anchor to record identity across a filter change, not
to a row number.** After a rescan, resolve the focused record to its new row;
if it did not survive, fall back to the nearest survivor.

This is rare, though an earlier draft of this section overstated how rare by
claiming nobody had solved it. **lnav has**, and by a different route: it
anchors on the log message's *timestamp*, which works in its LOG view and which
it deliberately does not attempt in TEXT view, where timestamps are not parsed.
Wireshark #16318 is genuinely still open since 3.0.7 (*"requires some Qt
interface wizardry"*), and Logcat rebuilds its document on each filter change.

Anchoring on the record's position in the source sequence rather than on its
timestamp is not a claim to be more accurate. Measured across two captures off
an `iPhone18,2` at roughly 1,000 records/s — 39,786 records — **every timestamp
was unique**, so timestamp anchoring would have resolved every one of them. The
reason to use identity is narrower: it needs nothing parsed out of the record,
so it cannot degrade on a source whose timestamps are coarse, absent or
non-monotonic, and there is no tie to break.

**0.1.0 ships the fielded bar, not an expression language.** This section
argued for one copy-pasteable text field with history, citing Google's stated
reason for rewriting Logcat's filters in 2023 — that a dialog-built filter
cannot be shared. §1's own sketch drew a level combo and three fields, and that
is what exists. The two halves of this document never agreed with each other.

The fielded version is defensible for four terms over a fixed schema, and it
is what a first release can be sure is right. What it gives up is real and is
the reason to revisit: a filter that cannot be pasted into an issue, and no
history.

> **0.2.0 took both of those back without adding a parser.** The bar is now
> `Level ▾  Process [___≠]  Subsystem [___≠]  Search [___.*]  Filters ▾`: the
> `Regex` checkbox moved *inside* the Search field, because a checkbox sitting
> after three fields does not say which of them it applies to, and the two `≠`
> toggles went in the same way for the same reason. `Filters ▾` carries the
> last ten unnamed and the ones you named.
>
> The pasteable half is `Edit ▸ Copy Filter`, which writes the filter as one
> line — `level:error -process:backupd` — spelled in
> [../formats/filter-text-form.md](../formats/filter-text-form.md). It is
> **emitted and not parsed**: this release ships the half that costs nothing
> and leaves the reader, with the rule it must follow written down for whoever
> adds one. The threshold semantics survive either way — Apple's level values are
not severity-ordered, so it is a threshold over our own enum, expressed here as
a combo rather than as `level:`.

**Half of what the text field was for is now covered without one.** The two
things it bought were *saying what is in front of you without retyping it* and
*going back to what you typed yesterday*. Neither needs a parser.

**Right-clicking a row offers its process and its subsystem.** The values come
off the *record*, not the cell — the table blanks a cell that repeats the row
above, so a right-click half way down a run of one process would otherwise
offer to filter by nothing. A marker row is offered neither, because it has
neither, and an entry that filtered by the empty string would quietly mean
"everything", which is the opposite of narrowing. The other entries on the menu
are the window's existing actions: a context menu with its own copy or its own
mark would be a second implementation to keep in step with the first.

Narrowing **adds** to the standing filter rather than replacing it. The
right-click is almost always the second step — somebody already at `Error and
above` who spots one noisy process is asking for the errors *from it*.

**The last ten filters are offered, unnamed.** Naming is the expensive half and
going back is the useful one, and a viewer that asks for a name before it will
remember anything gets asked for nothing. A filter is remembered when it has
**stood for two seconds**, not when it is applied: every keystroke applies, so
remembering on apply would fill the list with `d`, `da`, `das`, `dasd` — three
entries nobody asked for, pushing out the ones they did.

They survive a restart, and that is not the same decision as §1's refusal to
remember the *applied* filter. A filter that comes back applied is one the user
has to remember they set, which is "where did my logs go" with a longer fuse; a
filter that is merely on a menu changes nothing until somebody picks it. Stored
as JSON per entry so a line written by another version can be dropped on its
own — a window that refuses to open because a remembered filter is malformed
has turned a convenience into a way of losing the application.

---

## 6. States that must be visible

A paused stream looks exactly like a quiet device. An over-narrow filter looks
exactly like a dead one. Every invisible state gets a **persistent in-view
banner with a recovery action**, not a toolbar icon:

| State | Banner | Action | 0.1.0 |
| --- | --- | --- | --- |
| Paused | Capture is paused | Resume | ships, without the *N* buffered |
| Everything filtered out | All *N* records are hidden by the filter | Clear filter | ships |
| No device | wording from the error | Retry | ships |
| Empty capture | This capture contains no records | Open another | ships |
| Disconnected mid-capture | Device stopped answering — reconnecting | Disconnect | ships |
| Capture stopped | wording from the error | Diagnose… | ships (not listed here originally) |
| Capture finished | *N* records | Export… | ships (not listed here originally) |
| Paused queue overflowed | *N* records did not fit; they are in the file | Resume | ships (not listed here originally) |
| Truncated capture opened | the tail is missing | Dismiss | ships (not listed here originally) |

Logcat ships the first two with a one-click **Clear filter**; they are the two
that generate support questions everywhere else.

**The reconnect is built, and it needed something the stream could not give.**
`sources/os_trace.py` retries an outage for up to a minute, and the viewer used
to say nothing while it did: the user saw a stream that had stopped and found
out what had happened only when a `Gap` row appeared or the capture gave up.

The `Gap` is not enough on its own and never could be. It is the *record* of an
outage and stays that — it travels in the stream in position, which is where
its meaning is — but it can only be written once the device is back, and the
question somebody staring at a stalled window has is being asked several
seconds earlier. So `OsTraceSource` takes an `on_state` callback and says
`reconnecting` before it waits and `streaming` after it reconnects.

Three things about that callback are deliberate. It is a **constructor argument
on the concrete source**, not a method on `LogSource`: reporting a connection is
a property of one implementation, and a consumer that took the protocol and
reached for a method only one side has is what that protocol exists to prevent.
The two words live in `sources/base.py` rather than in `sources/os_trace.py`,
because the listener is a *window* and importing them from there would pull
pymobiledevice3 — 90 distributions — into the path that merely opens a saved
capture, and would make the window unimportable under `-O`. And a listener that
raises is **swallowed**: the records are the product and the notification is a
courtesy, so a device released because a banner threw would lose everything the
device says next.

The window turns it into a banner offering `Disconnect`, which is the only
decision left — the source is already retrying. Coming back clears that banner
and *only* that one, matched on its own message: a pause raised during the
outage is a different state that is still true, and clearing it would leave the
view frozen with nothing on screen saying why.

**Two dead ends got the right action rather than a second Retry.** A capture
that ran and then died now offers `Diagnose…`, because pressing Capture again
is one click away on the toolbar and what the user does not have is any way to
find out why — see §6a. A capture that finished offers `Export…`, which until
now was a moment nothing marked at all: the records stopped arriving and the
window said so in no way a person notices.

---

## 6a. The Doctor window

The checks in `devices/doctor.py` have existed since phase 1 and only
`ostrace doctor` could run them, so somebody who installed this for the window
met a dead end at exactly the moment something was wrong. It is reachable from
`Help`, on `Ctrl+Shift+D`, and offered as the action on the banner of a capture
that died.

It **runs on a thread**. `doctor.run` opens a lockdown session and waits on
sockets with a two-second timeout apiece; on the interface thread that is a
window frozen for as long as the diagnosis takes, which is longest in exactly
the case somebody is running it. `Run Again` is guarded while one is in flight,
because a second lockdown against a device is the thing this project already
knows stalls the first.

Each check is a row with its status **as a word** — `ok`, `warn`, `FAIL`,
`skipped` — never as a colour alone, per §10, and this window is read by
somebody already having a bad time, often over a screen share. A hint gets a
child row rather than a third column, because the hints are sentences and the
details are phrases, and in one column every row would be as tall as the
longest hint.

**The report can be copied out**, because the reason to run this is usually to
tell somebody else what it said, and a wall of text nobody can select is one
that gets photographed.

Non-modal, and shown rather than executed: the answer is often "unlock the
phone", which is a thing to do while the window stays open.

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

**Disconnecting finishes the capture, and a finished capture is exportable.**
The window adopts the session file the moment the capture thread ends, whether
it ended because the user disconnected or because the device went away.
Anything less makes the export a dead end: told to disconnect, the user
disconnects and is told to disconnect.

**A running capture is exportable too, as a snapshot.** This section used to
refuse it outright, on the grounds that a file growing under the exporter
produces a report whose end is arbitrary. The objection is real; the refusal
was the wrong answer to it, on two counts.

The end is only arbitrary while it goes *unstated*. Every exporter here already
declares its own omissions, so the honest form of "this report stops somewhere"
is a sentence saying where — which is what `exporters.notes` is for, and it now
carries one. A snapshot that says it is a snapshot has a declared end, not an
arbitrary one, and the sentence has to say the thing a reader would otherwise
assume: the last record in it is where *the file had got to*, not where the
device stopped.

And it was already built. `storage.spool` emits a `Z_SYNC_FLUSH` boundary as it
writes, precisely so that a reader can decompress everything up to the last one;
its module docstring says live export during capture depends on it. The
capability had been there since phase 1 and the window declined to use it.

Disconnect remains the way to finish a capture. It is no longer a prerequisite
for getting anything out of one.

ostrace spools to disk, so pause can keep its promise honestly and needs no
ring buffer. Grafana promises "no gap" while backing it with a 1,000-line ring
that silently overwrites; CloudWatch buffers about ten seconds and then drops
the *oldest*, tearing a hole in the middle of the timeline rather than
truncating the tail.

A bound *was* introduced — 100,000 records, in `gui.pump` — and it emits an
**`Eviction`**, not the `Gap` this paragraph originally promised. That promise
contradicted §3: those records are in the session file, and calling their
absence from the view a gap would be the lie §3 forbids. Same for the model's
own row cap.

---

## 8. Keyboard

**Alias both traditions rather than choosing between them.** klogg binds
find-next to `F3` *and* `n` *and* `Ctrl+G`, and jump-to-bottom to `Ctrl+End`
*and* `Shift+G`, shipping on Windows and macOS — this project's exact target
pair.

**The table is generated, not written.** `gui/shortcuts.py` holds one list of
bindings; the window builds its actions from it and the `F1` sheet renders it.
klogg's fourth trap is a key table in a manual that drifted from the code, and
this makes drift impossible rather than discouraged. Run `F1` for the current
list.

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

**`F3` follows the toolbar; the per-kind keys do not.** The two chevrons were
wired to errors and nothing else, which is the right default and a poor answer
to "I am reading this capture for gaps today". The target is a toolbar control
now, and `F3` / `Shift+F3` — the find-next key on Windows and klogg's — mean
*next of whatever I am looking for*. Every kind keeps its own explicit binding,
so choosing a target in the toolbar never takes a key away from somebody who
already knows `Ctrl+Shift+G`.

**`Ctrl+J` goes to a time.** It is the only navigation in the program that
correlates the log with the world outside it — somebody watched their phone
misbehave at twenty past two, and every other way of finding that moment is
scrolling. It accepts a clock reading (`14:22:31`, `14:22:31.500`) or an offset
from where the reader is (`+30s`, `-2m`), and lands on the first row *at or
after* the result, markers included: a gap is often the thing being looked for,
and skipping it would make the one row that explains a silence the one row this
cannot reach.

Three rules the parser keeps, none of them cosmetic. The timezone comes from
the anchor row, which carries the *device's* offset — building a target on the
host's clock would search a different zone silently. A date-less reading means
that reading on the anchor's day, so a capture running through midnight reads
`00:05` as the day the reader is in rather than the day the capture started;
`2026-08-10 00:05` says the other thing when the other thing is meant. And the
anchor is the selected row, or the top of the screen when nothing is selected —
not the first row of the capture, which is where the reader was an hour of
scrolling ago.

The search is a scan rather than a bisection. A device log arrives in roughly
chronological order and is not guaranteed sorted — the relay interleaves
subsystems — and a binary search over a nearly-sorted sequence answers
confidently and wrongly. At 200,000 rows a full scan measures 86 ms, the worst
case where nothing matches; landing halfway is 38 ms. Best of three, offscreen,
against the shipping model with a view attached. It is spent on a keypress a
person made, and it buys an answer that is right rather than one that is fast.

**`Ctrl+Q` quits, beside the standard key.** `StandardKey.Quit` is `⌘Q` on
macOS and, on Windows, a key called `Exit` — measured, not assumed:
`QKeySequence.keyBindings` answers `['Exit']` there. No keyboard has that key,
so on the platform this is developed on the only way out was the window's close
button. Qt resolves `Ctrl+Q` to the same `⌘Q` on macOS, so the alias costs
nothing where it is not needed.

**The single-letter aliases are safe because of `ShortcutOverride`, and that is
now asserted.** `E`, `M`, `N`, `/`, `[` and `]` are window-level shortcuts and
the filter bar is full of line edits in the same window. What stops `e` jumping
to the next error instead of typing a letter is that Qt offers the key to the
focused widget first and a line edit claims anything it would insert. Nothing
in the code says so, which is why a test does: a future field that did not
claim the key would break the filter bar silently, and the aliases would look
like the culprit.

**Icons do not appear in menus.** The toolbar and the menus share their action
objects, so an icon put on one for the toolbar's sake is drawn by the other in
the column a checkmark occupies: `Next Error` and `Previous Error` rendered in
the View menu with what reads as a tick and an indicator beside them, two items
above a `Dark Mode` whose tick is real. `_action` clears
`setIconVisibleInMenu` for every action it builds.

**Menu items are grouped by the bindings table, not by hand.** `Binding.group`
carries the run an item belongs to and the window draws a separator wherever it
changes, so an added or reordered item lands in the right run without anybody
remembering to move a divider. The View menu was eleven items in one undivided
column before this.

---

## 9. Detail pane

A **bottom panel**. 0.1.0 does not have the separate cheap **in-row expansion**
on `Right`/`Left` that Console.app pairs it with, and therefore has neither of
the stream semantics that would have gone with it — *row expansion keeps the
stream running; opening the detail panel pauses it*. Here the panel is always
present and neither of them pauses anything, which is consistent, if less
expressive than the pair.

**Two columns of fields and a message block**, not one column of everything.
The first version was a single-column form of twelve rows, which against a real
window is mostly empty space with a stack of labels down the left edge: the
fields are short, the message is long, and giving `PID` the same width as a
message means neither is laid out for what it is. The fields fill the width in
pairs, top to bottom in each column so that the clock fields stay together, and
the message gets a block of its own in the table's own monospaced face — the
pane is where people go to read the awkward messages, the ones with alignment
or a hex dump in them.

**It carries a close control, and the control asks rather than acts.** `Esc`
was the only way to let go of a record, which is a key you have to be told
about. The `✕` emits and the window turns that into a deselect; the pane never
hides itself.

**The pane can be put away, and that is a different verb from the `✕`.**
`Ctrl+I` and a ticked item in `View` hide and show it — the item is what makes
it recoverable, which is the objection the paragraph above was answering when
hiding did not exist at all. So there are two controls a keystroke apart and
they must not read as the same one: the `✕` **lets go of the row** and its
accessible name says exactly that, because `✕` on its own is announced as
"multiplication sign" and would otherwise be read as closing the pane.

The visibility is remembered between sessions and restored *through the menu
item*, not around it: a window that opened with the pane hidden and the item
ticked would need two presses to show it, the first of which appears to do
nothing.

`QSplitter` gives a hidden child's size back when it is shown again, so nothing
here saves or restores the split. That was two lines until the test claiming to
cover them stayed green with them removed. The assertion is kept — a pane that
came back bigger than it went away is one there is no way to put right that a
second press does not undo — but it pins Qt's behaviour rather than ours.

Do not budget performance work for the detail pane. Wireshark's own guidance
names real-time list update, **colouring rules** and name resolution as the
cost centres. The delegate is what to optimise. Also from Wireshark: never
recompute the whole list on a selection change — that is what made its
auto-scroll jump (bug 12130).

The *interval between updates* preference this section asked for is not
exposed. It exists as two measured constants instead: `pump.TICK_MS` (50 ms,
draining) and `main._FOLLOW_MIN_MS` (100 ms, scrolling). Splitting those two
apart is what stopped the tail repainting the whole viewport fifteen times a
second; making either one a setting is a later decision.

---

## 10. Theme

**The theme is a function from a colour scheme to a `QPalette`.** It is not a
set of colours read out of the platform, and it is not a stylesheet.

This originally said "seeded from the OS palette at run time", and the
implementation deliberately does the opposite: `gui/theme.py` holds sixteen
hex literals per scheme. Seeding from the platform would make the output
depend on the platform, which is the one thing a GUI that cannot be run on
macOS must not do — the same argument ADR 0004 used to choose Qt. Determinism
is what lets CI assert every severity colour against WCAG AA on all three
operating systems and lets the screenshot job force either scheme anywhere.

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

**Which scheme is in force is a separate question from what a scheme looks
like**, and since 0.2.0 it has a separate module: `gui/theme_policy.py` decides
between chosen, followed and remembered, and `gui/theme.py` stays the function
from a scheme to a palette. The rule it holds is that the operating system is
the **default, not the authority** — once somebody picks a theme, in this
session or an earlier one, the system stops being consulted. Two halves move on
every change and both every time: the application palette, and whatever a
window resolved once and held. A switch that moved only one of them is a bug
this project has already shipped.

**A mark has its own colour, and it is not the accent.** The first attempt
borrowed one and produced a marked row identical to a selected one — the user
could not tell what they had marked from what they had merely clicked. Marks
are amber against the blue selection, and every severity foreground is checked
against the mark tint as well as against `Base`: a mark that makes an Error
unreadable hides the line somebody cared enough to annotate.

**Colour is never the only cue for severity.** The Level column is text and
stays text. A background tint at 14% sits at roughly 1.12–1.22:1 against `Base`
— nowhere near a legibility threshold, which is an argument for tinting as
*reinforcement* and never as *information*. `ERROR` and `FAULT` additionally
carry a leading glyph, so a screenshot survives being printed, and a
colour-blind reader loses nothing.

**One object owns the switch, and it is the window.** `colorSchemeChanged` was
answered twice — by `gui.app`, unconditionally, and by the window, only while
the user had expressed no preference — and two listeners under different rules
is one rule that does not hold. Picking a theme and then letting the operating
system change its own moved the palette and the chrome stylesheet while the
table, the model, the minimap and the icons stayed where the user had put them:
a dark window with a white log in the middle of it, which reads as a broken
dark mode rather than as a preference being honoured. `gui.app` themes the
application once at startup and connects nothing.

**A colour used for two jobs eventually gets one of them wrong.** The scrollbar
handle was painted in `border-strong`, which is also `QPalette.Dark` and
`Shadow`. For a shadow, "darker than the surface" is the entire job; for a
handle it is the bug — in the dark scheme that token is `#0f1116` against a
`#101216` track, a contrast of **1.01:1**, painted correctly and invisible. The
handle has its own token now, and both schemes clear 3:1 against their own
track, which is WCAG 2.1's non-text threshold and is asserted alongside the
severity contrasts. The light handle was never invisible and was under the line
too, at 1.64:1.

**The application mark is not themed.** `icons/app.svg` carries its own colours
and is rendered without substitution, at every size a desktop asks for. A
taskbar entry that changed colour with the theme would read as a different
program, and on macOS and Linux the icon is drawn by a shell that never asked
this application what scheme it is in.

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
| **Override `QHeaderView.initStyleOptionForIndex`** | **Keep, and the figure corrected — twice.** The header asks the selection model, per section, whether the whole column is selected; QTBUG-59478 has been open since 2017 and its fix was *abandoned* the same year. Measured at 200k rows × 6, `selectAll()` plus its repaint, best of three: **5.98 s → 2.92 s, about 2×**, `flags()` calls 1,200,689 → 683, titles still on screen. This row previously read *"the single biggest lever… 4.064 s → 0.008 s, 541×"*. That measurement is reproducible but it used a stand-in model whose `flags()` returns a constant and whose `data()` returns `"x"`; against the model that ships, the remaining 2.9 s is the selection model and the repaint, and the prebuilt `_flags` below has already made each of those million calls cheap. The two rules were treating the same wound and their savings do not add up. Implemented as `gui.widgets.log_table.FastHeader`, which reimplements the cheap half of the base method — skipping `super()` outright is faster still and paints a header with no titles, since that is also what fills in the section text. `setHighlightSections(False)` was measured as an alternative and does nothing: 5.93 s |
| `QTableView` only, never `QTreeView`/`QListView` | **Keep the rule.** The evidence is stale: the "20M `rowCount()` calls" figure was fixed by Qt change 601341, merged 2024-11-01 and backported to 6.8, which this project already pins. `QTableView` is still fastest |
| Cache the `flags()` return value | **Keep, restated.** Measured ~1.3× (3.47 s → 2.55 s at 200k), not 20×. The ADR's "7.760 s → 0.396 s" conflated time-inside-`flags()` with an operation total. It is one line and still worth it — but the calls it optimises are *caused* by the header, and `FastHeader` removes 1,200,006 of the 1,200,689 outright. Fix the cause first. Note the corollary, which took a second re-measurement to see: with this in place each remaining call is cheap, which is most of why removing them is worth 2× rather than 541× |
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

## 11a. What the window says to something that cannot see it

Two rules, and both were broken in the way that leaves a suite green.

**A control whose only label is an icon has no name.** A tooltip is not a name:
it needs a pointer hovering over it. Every icon-only control now carries one —
the four unlabelled toolbar buttons, whose accessible name is the action's text
with the accelerator marker stripped because `&Export…` is read aloud as
"ampersand Export"; the overview strip, which is a control drawn entirely by us
with no text and no icon to infer a purpose from; the detail pane's `✕`; and
the two buttons whose text is an *answer* rather than a question — the device
button says a device name and the jump button says `Errors`, so read out alone
neither gives any clue that the thing is settable. The filter fields get
`setBuddy` as well as a name, because a `QLabel` beside a field is a label to
somebody looking at it and nothing at all to anything reading the window.

**A widget that announces state by appearing announces it to nobody who is not
looking at that part of the screen.** Every state §6 calls "must be visible"
arrives in the banner, and a screen reader follows focus, which the banner
never takes. It raises `QAccessible.Event.Alert` — the one event announced
without focus — and sets its accessible name to the message first, because the
alert carries no text of its own and what gets announced is whatever the name
says at the moment it fires.

None of this needs a screen reader to test. Qt's accessibility interface is
queryable from the same process, which is what makes these assertions rather
than a manual pass somebody has to remember to repeat. The alert is observed by
standing in for `QAccessible` in the banner's own module: PySide6 exposes no
update handler to listen with, and `updateAccessibility` is a no-op while
nothing is reading the screen, so a test that merely called it would pass
whatever event it raised, including none.

---

## 11b. Qt behaviours that do not fail the way you expect

Three of them, each of which cost a debugging session, and none of which
announces itself as the cause.

**A modal `exec` does not fail a test — it hangs it.** The job sits there until
something kills it, and the traceback names nothing. So anything ending in one
is split in two: a method that *builds* and a method that *shows*. Three pairs
follow this — `export_dialog` / `export_capture`, `ask_for_time` /
`go_to_time`, `row_menu` / `_on_context_menu` — and every one of them was
written after a run had to be killed. New code that opens a dialog, a message
box or a context menu splits the same way, and the test drives the first half.

**`setChecked` emits `toggled`; only a person emits `clicked`.** A control that
*reports* derived state therefore has to sync through `clicked`, or block
signals around `setChecked` — otherwise reporting the state is indistinguishable
from choosing it and the handler fires, which is a loop when the handler is what
computes the state. This project has walked into it twice, once with the theme
checkbox and once with the follow indicator; §4's "one derivation, read by both"
is the rule that survived it.

Related, and the same shape: connecting `QAction.setChecked` to a
`QToolButton.clicked` binds the *parameterless* overload and calls it with no
argument. PySide reports that on stderr and otherwise swallows it.

**A `QThread` still running when Python drops its last reference aborts the
process.** Not an exception — `0xC0000409` on Windows, which cannot be caught
and leaves no traceback. Anything owning a thread waits for it on the way out;
`DoctorWindow.closeEvent` is the example, because that window is closable two
seconds into a socket timeout.

---

## 12. What CI can and cannot verify

`QWidget.grab()` and `QWidget.render()` produce **real pixels under the
offscreen plugin**, on a widget that was never shown *(measured)*. So a
screenshot needs no display, no window manager and no xvfb — including on
macOS, which was for a long time the only way this project was going to see its
own macOS UI. It is no longer the only way; see the hands-on pass at the end of
this section, which the screenshot job is what made worth doing.

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

The two images in the README come from there. The **macOS pair does not**, and
the difference is the point: under `offscreen` the interface font resolves to
Qt's generic `Sans Serif` rather than to `.AppleSystemUIFont`, so the job's own
macOS picture is right about layout, palette and elision and wrong about the
one thing a reader looks at a macOS screenshot for. Those two were rendered
under `cocoa` on a real Mac. Anyone regenerating them needs one; regenerating
the Windows pair needs only the job.

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

### The first hands-on pass, on macOS 26.3.1

Run on a `Mac16,10` with PySide6 6.11.1 and Python 3.13.14. Everything above
was written without one, so what follows says which of it was watched happening
rather than inferred.

**Confirmed as written.** `setColorScheme` really is a no-op under `offscreen`
— `colorScheme()` stays `Unknown`, the signal never fires — and `grab()` really
does produce pixels there. `menuBar().isNativeMenuBar()` is `True` under
`cocoa` and `False` under `offscreen`, which is exactly why the picture cannot
contain the menu bar and why the menu-role test above is the only guard for it.
Fusion is available. The empty-font-database trap is Windows-only: macOS
offscreen reports 181 families.

**Verified for the first time, natively.** The table above lists colour-scheme
switching as not verifiable in the offscreen lane, and that stands — but under
`cocoa` it works: `Light` → `Dark` moved `colorScheme()` and fired
`colorSchemeChanged`, which until now had only been watched on Windows.

**Contradicted.** `gui/fonts.py` named `SF Mono` as the macOS face. No stock
Mac resolves it — Apple keeps the SF family out of the font database — so what
the log has always been rendered in there is `Menlo`.

**Still not verified, and it is a real gap.** The machine drives one non-Retina
display, so every measurement here was taken at a device pixel ratio of **1.0**.
The rule that macOS reports an *integer* ratio where Windows reports a
fractional one is consistent with that and is not exercised by it: nothing in
this project has yet been rendered at 2×, which is what most Macs run at, and
the column-fitting arithmetic in §11 is exactly the kind of thing that would
show a defect there first.

The pass also found a bug the screenshot job had been rendering all along and
nobody had looked at: rebuilding the detail pane left the previous rows parented
and visible until the event loop drained, so the placeholder printed across
`Device time`. Interactive use never showed it. That is twice now that this pane
has been wrong in a way only a picture could reveal.

---

## 13. Deliberately out of scope for phase 4

- **Substring selection inside a message.** `QTableView` selects whole cells.
  *Row* copy ships — the selection behaviour is whole rows, so a copy always
  emits every column — and a read-only `QLineEdit` delegate does not. The
  detail pane covers the common case, as ADR 0004 already records. (This said
  "cell and row copy ship"; only row copy does.)
- **Context lines around a match** (`grep -C`). LogExpert's Back Spread / Fore
  Spread is the only GUI implementation found and the demand is real, but with
  process, subsystem and PID on every row a *relational* filter — everything
  else from this process around this moment — probably serves the need better.
  Decide after the filter language exists.
- **Per-pane follow.** Only relevant with two list panes, which phase 4 does
  not have. Noted because klogg's single shared flag has been issue #211 since
  2020 and retrofitting it is the expensive order.
- **A `Gap` reason taxonomy.** A session-format decision, not a GUI one (§3).
  Still out of scope, and now with one side of it settled: `reason` is
  documented as prose for a person, so a taxonomy would arrive as a second
  field beside it rather than as a vocabulary imposed on this one. What did
  change is that the prose is prose — the reasons that used to fall back to a
  `pymobiledevice3` class name are sentences now, which is a wording fix, not
  the taxonomy.
