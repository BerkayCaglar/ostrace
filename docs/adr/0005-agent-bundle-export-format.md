---
status: accepted
date: 2026-08-08
decision-makers: Berkay ÇAĞLAR
---

# Export an "agent bundle" of flat text files, not a single document

## Context and Problem Statement

The original export target was a document to paste into a chat window. That is
not how the tool is actually used. The real workflow is: point a coding agent
at a directory and say "the bug is in here, investigate."

That agent will not read the log. It will `grep` it, count matches, then read
the specific line ranges around interesting hits. Its constraints are concrete:

- Shell tool output is truncated at 30,000 characters, **silently**. A bare `rg`
  over a large capture stops being complete after roughly 180 matches and
  nothing says so.
- Context is finite and shared with the actual task; every wasted token is one
  not spent on reasoning.
- Reading a 200,000-line file whole is not an option at any context size.

A single formatted report is close to the worst shape for this. It is optimised
for linear human reading, so it buries the structure an agent navigates by.

## Decision Drivers

- Every search hit must be self-describing — a grep result with no timestamp,
  level or process is a pointer the agent has to spend another call resolving.
- Aggregates must be precomputed. An agent should never have to count anything
  a generator could have counted once.
- Give the agent line numbers, so it can jump straight to a range.
- Nothing may silently truncate.
- The format must stay diff-friendly and greppable — plain text, no JSON that
  has to be parsed to be read.

## Considered Options

1. **A directory of flat, tab-separated files plus a generated `CLAUDE.md`.**
2. **One Markdown report.**
3. **JSONL only.**
4. **SQLite.**

## Decision Outcome

Chosen option: **an agent bundle** — a directory containing:

| File | Contents |
| --- | --- |
| `session.log` | Every record, one per line, tab-separated. The main data file. |
| `errors.log` | Error/Fault/Critical only. **First column is the `session.log` line number.** |
| `patterns.tsv` | Distinct message templates with counts. |
| `processes.tsv` | Record count per process. |
| `subsystems.tsv` | Record count per subsystem. |
| `timeline.tsv` | Per-minute counts and the first line number of each minute. |
| `CLAUDE.md` | Generated. Claude Code loads it automatically when it reads a file from this directory. |

`session.log` carries six columns:

```
timestamp <TAB> level <TAB> process[pid] <TAB> subsystem <TAB> category <TAB> message
```

Four properties do the work:

**One record per physical line, always.** Multi-line device messages are folded
into their parent record: newlines become `\n`, tabs `\t`, backslashes `\\`.
Every grep hit is therefore a complete record carrying its own timestamp, level
and process. This is the single most important property of the format — it is
what makes a one-line search result actionable without a follow-up read.

**Line numbers as pointers.** `errors.log` and `timeline.tsv` hold `session.log`
line numbers, so "show me the minute this started" is a read of a known range,
not a search.

**Precomputed aggregates.** `patterns.tsv` answers "is this error actually
unusual, or does it fire 14 times a minute normally?" without the agent
counting. iOS logs a great deal of routine chatter at `Error` level — Wi-Fi link
telemetry especially — and an agent that does not check frequency will confidently
report link-quality noise as the bug.

**A generated `CLAUDE.md`, held to a bounded length regardless of capture size.**
It documents the columns, gives one real record as an example, states the
capture's own statistics, and lists the gotchas that would otherwise mislead —
that `<private>` is Apple's redaction and not a defect in the export, that
one-second timestamp resolution means same-second ordering is arrival order and
not proven causality, that an absent level means none were emitted rather than
that they were filtered. It also states the 30,000-character truncation limit
explicitly and gives counted, paged search recipes.

### Consequences

- Good: an agent's first action can be a `count`, which costs almost nothing and
  sizes the problem before any content is read.
- Good: adding `subsystem` and `category` as columns (which
  [ADR 0002](0002-use-pymobiledevice3-over-libimobiledevice-cli.md) makes
  possible) enables `rg '\tcom\.apple\.network\t'` — every networking record
  across every process, in one search. This was not expressible in the old
  four-column format at all.
- Good: works with any agent and with a human at a shell. Nothing is
  Claude-specific except the filename `CLAUDE.md`.
- Bad: a directory of six files is less convenient to hand to a human than one
  document. The Markdown and AI-report exporters remain for that.
- Bad: escaping is a format contract. A bug in folding corrupts records in a way
  that is hard to notice. It gets dedicated round-trip tests.
- **The six-column layout is a public contract.** Adding a column later
  invalidates every bundle already on disk. This is why `Record` carries a
  `platform` field from day one, before there is any second platform to put in
  it.

### Confirmation

- Round-trip tests: fold then unfold reproduces the original message exactly,
  including messages that contain literal `\n` two-character sequences.
- The bundle generator is run over a real capture and the documented `rg`
  recipes are executed against the result, asserting the counts they claim.
- `CLAUDE.md` length is asserted to stay within budget for a capture two orders
  of magnitude larger than the test fixture.

## Pros and Cons of the Options

### One Markdown report

- Good, because it is what a human wants to read.
- Bad, because prose between records defeats line-oriented search, and a
  truncated record forces a follow-up read to recover its own timestamp.
- Retained as a separate exporter for the human case rather than rejected.

### JSONL only

- Good, because it is unambiguous and needs no escaping rules of our own.
- Bad, because every grep hit is then a whole JSON object — mostly punctuation
  and key names, burning context on syntax. Retained as a separate exporter for
  programmatic consumers.

### SQLite

- Good, because the aggregates would be queries rather than files.
- Bad, because an agent cannot grep it, cannot read it, and cannot diff it. It
  turns a text problem into a tooling problem.

## More Information

- [docs/formats/agent-bundle.md](../formats/agent-bundle.md) — the format contract.
- [docs/research/claude-code-log-investigation.md](../research/claude-code-log-investigation.md)
  — what agents actually do when investigating logs, which this format is built
  around.
