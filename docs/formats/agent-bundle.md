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
└── timeline.tsv       per-minute counts and line-number pointers
```

All files are UTF-8 with LF line endings, on every platform. **Contract.**

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

A template is the message with variable parts normalised: numbers to `<N>`,
floats to `<F>`, hex to `<HEX>`, UUIDs to `<UUID>`, paths to `<PATH>`. Messages
that normalise identically are collapsed into one row.

`<HEX>` also covers hex with no `0x` to announce it — operation identifiers,
content references, protection tags. iOS emits those constantly and they are
pure identity; measured on this project's own fixture, recognising them folds
1,677 templates down to 1,431.

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

Shell tool output truncates at 30,000 characters, **silently**. At an average
record length around 165 characters that is reached at roughly 180 matches.
Always count before asking for content.

## Compatibility

The bundle is designed to be read with `grep`, a text editor, or nothing at all.
There is deliberately no index, no binary sidecar and no schema file to parse.

Adding a **new file** to the bundle is not a breaking change. Adding, removing
or reordering a **column** in an existing file is, and requires a format version
bump.
