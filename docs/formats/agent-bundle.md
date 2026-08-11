# Format: agent bundle

**Version:** 1
**Rationale:** [ADR 0005](../adr/0005-agent-bundle-export-format.md)
**Implemented by:** `ostrace.exporters.agent_bundle`

This document is the contract. Once the format ships, changing anything marked
**contract** below is a breaking change: bundles already written to disk stay
valid forever, and readers must be able to trust their shape.

---

## Shape

An agent bundle is a directory. Exporting produces:

```
<name>-bundle/
├── CLAUDE.md          generated documentation, auto-loaded by Claude Code
├── session.log        every record, one per line          <- the main data file
├── errors.log         Error and Fault only, with line-number pointers
├── patterns.tsv       distinct message templates, with counts
├── processes.tsv      record count per process
├── subsystems.tsv     record count per subsystem
├── timeline.tsv       per-minute counts and line-number pointers
└── gaps.tsv           where the capture has holes
```

All files are UTF-8 with LF line endings, on every platform. **Contract.**
Every file is written on every export, including with nothing to put in it: a
file that appears only on bad news cannot be told from a file nobody wrote.

## `session.log` — **contract**

Six tab-separated columns, one record per physical line, no header row:

```
timestamp <TAB> level <TAB> process[pid] <TAB> subsystem <TAB> category <TAB> message
```

| Column | Contents |
| --- | --- |
| `timestamp` | `YYYY-MM-DDTHH:MM:SS`, device local time |
| `level` | One of `Debug` `Info` `Notice` `User Action` `Error` `Fault` |
| `process[pid]` | e.g. `dasd[83]`. A parenthesised part is the emitting library: `backboardd(ColourSensorFilterPlugin)[70]` |
| `subsystem` | e.g. `com.apple.network`, or `-` when the record carries none |
| `category` | e.g. `default`, or `-` |
| `message` | The message, always on one physical line — see escaping |

Empty fields are written as `-`, never as an empty string. An empty field
between two tabs is ambiguous to read and easy to mis-split; a literal `-` is
not. **Contract.**

The level set is exactly what iOS emits, taken from a real device rather than
from the legacy text format: `Debug`, `Info`, `Notice`, `User Action`, `Error`,
`Fault`. There is no `Warning` and no `Critical` — the predecessor tool listed
both because it was reading a text stream that used different names. `Warning`
becomes reachable if an Android source is added; a level being absent from a
capture means the device emitted none, not that it was filtered out.

Records appear in the order the device delivered them. Under load the device
itself can emit slightly out of chronological order — measured at about 0.065%
of records. The export preserves arrival order and does not sort, because
sorting would hide the fact.

### Escaping — **contract**

The message is folded to a single physical line:

| Character | Written as |
| --- | --- |
| newline (`\n`, `\r\n`, `\r`) | `\n` (backslash, `n`) |
| tab | `\t` |
| backslash | `\\` |

Backslash is escaped first, so a message containing a literal two-character
`\n` sequence round-trips correctly and is distinguishable from a real newline.

This is what makes **every grep hit a complete record**, carrying its own
timestamp, level and process. It is the most important property of the format.

## `errors.log`

Records at `Error` or `Fault`. Seven columns — the six from
`session.log`, prefixed by the **`session.log` line number** (1-based):

```
line <TAB> timestamp <TAB> level <TAB> process[pid] <TAB> subsystem <TAB> category <TAB> message
```

No header row, for the same reason `session.log` has none: this is data, and a
header would be a line that looks like a record and is not one.

The pointer is the point: it turns "what was happening around this error" into a
bounded read of a known range rather than another search.

## `patterns.tsv`

Distinct message templates with counts, most frequent first. Header row present.

```
count <TAB> level <TAB> process <TAB> subsystem <TAB> first_line <TAB> template
```

A template is the message with variable parts normalised: runs of two or more
digits to `<N>`, decimals to `<F>`, hex to `<HEX>`, UUIDs to `<UUID>`, paths to
`<PATH>`.

**A row is one `(level, process, subsystem, template)`, not one template.** The
same normalised message emitted by four processes is four rows, because the
question this file answers is *which* component is repeating itself — a count
that merged them would say a template is frequent without saying where. The
row count is therefore at or above the template count: on this project's own
fixture, 944 rows for 921 templates.

Single digits are deliberately left alone: `endpoint 5` and `endpoint 7` are
usually different things, while `port 49152` and `port 49153` are the same
thing twice. `<HEX>` also covers hex with no `0x` to announce it — operation
identifiers, content references, protection tags — but only runs of six or more
characters that mix letters and digits, so an English word is not mistaken for
an identifier. iOS emits those constantly and they are pure identity; measured
on this project's own fixture, recognising them folds 1,164 templates down to
921.

A capture with an implausible number of distinct templates stops learning new
ones at a cap. When that happens the generated `CLAUDE.md` says so and gives the
number affected — every other file still counts those records, and only their
template is missing. Silence there would read as "this is everything".

This file answers the question that decides whether a finding is real: *is this
error unusual, or does it fire fourteen times a minute normally?* iOS logs a
great deal of routine chatter at `Error` level, and an investigation that skips
this step reports link-quality telemetry as the bug.

## `processes.tsv`, `subsystems.tsv`

Counts per process and per subsystem, most frequent first. Header row present.

```
count <TAB> errors <TAB> process
count <TAB> errors <TAB> subsystem
```

`errors` is the count at `Error` and above — the useful ratio being "this
process is 3% of the log but 60% of the errors".

## `timeline.tsv`

Per-minute activity with a line-number pointer. Header row present.

```
minute <TAB> records <TAB> errors <TAB> first_line
```

`minute` is `YYYY-MM-DDTHH:MM` — the `session.log` timestamp without its
seconds, so a row can be matched against the log by prefix. It carries the date
because a capture that runs past midnight would otherwise sort its second hour
before its first.

Reading a range around a spike is how an investigation gets from "something
happened at 00:05" to a cause.

## `gaps.tsv` — **contract**

Where the capture has holes. Header row present, one row per gap, in capture
order.

```
start <TAB> end <TAB> seconds <TAB> reason
```

| Column | Contents |
| --- | --- |
| `start` | ISO 8601 with the device's UTC offset |
| `end` | ISO 8601 with the device's UTC offset |
| `seconds` | Duration to three decimal places |
| `reason` | Why the stream broke, escaped as in `session.log` |

**Header only means no gaps**, which is not the same as the file being absent.

`reason` is prose for a person to read — free text, no vocabulary, nothing may
switch on it — carried through from the session file, where the same rule and
its history are recorded. Bundles exported from a session written by 0.1.1 or
earlier can therefore hold a `pymobiledevice3` class name in this column, and
are as valid as one holding a sentence.

This file exists because a gap is not a record and therefore cannot live in
`session.log` without breaking the one-record-per-line rule every recipe here
depends on. Without it a gap appeared nowhere a search could reach: `grep`
over `session.log` reads straight across the hole, `timeline.tsv` shows a quiet
minute, and the only mention was in `CLAUDE.md`, which is explicitly outside
this contract. An absence that a reader takes for silence is the single
conclusion this format exists to prevent.

## `CLAUDE.md`

Generated per bundle. **Bounded length regardless of capture size** — a bundle
of two million records must not produce a longer `CLAUDE.md` than one of six
thousand. It documents the columns, shows one real record from this capture,
states the capture's statistics and most frequent error patterns, gives counted
and paged search recipes, and lists the traps that mislead readers of iOS logs.

It is not part of the machine-readable contract; it may be rewritten freely as
the advice improves.

## Reading a bundle

```bash
# how many errors, before asking for any content
rg -c '\t(Error|Fault)\t' session.log

# one subsystem, across every process -- not expressible before six columns
rg -n '\tcom\.apple\.network\t' session.log | head -n 50

# what dominates by volume
head -n 30 patterns.tsv
```

Shell tool output truncates at 30,000 characters, **silently**. The generated
`CLAUDE.md` divides that by *this capture's* mean written line length — measured
while `session.log` is written, not estimated from the message alone — and says
how many matches it works out to. At the 180-character mean of this project's
fixture that is 166, which an independent count over the written file agrees
with exactly. Always count before asking for content.

## Compatibility

The bundle is designed to be read with `grep`, a text editor, or nothing at all.
There is deliberately no index, no binary sidecar and no schema file to parse.

Adding a **new file** to the bundle is not a breaking change. Adding, removing
or reordering a **column** in an existing file is, and requires a format version
bump.
