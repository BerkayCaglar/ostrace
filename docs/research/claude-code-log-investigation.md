# How a coding agent actually investigates a log

**Date:** 2026-08-08
**Feeds:** [ADR 0005](../adr/0005-agent-bundle-export-format.md)
**Scope:** written against Claude Code specifically, because that is the target,
but the constraints generalise to any agent with shell and file-read tools.

---

## The workflow being designed for

This is worth stating precisely, because it is not the workflow most log
exporters assume.

The user does **not** paste a log into a chat window. They point an agent at a
directory and describe a symptom: *"the app freezes when returning from
background — the logs are in here, find out why."* The agent then investigates
with its own tools.

An exporter built for the paste-into-chat workflow optimises for a document that
reads well top to bottom. An exporter built for this one optimises for something
quite different: **being searched.**

## What the agent actually does

The observed pattern, in order:

1. **Orient.** List the directory. Read anything that looks like documentation.
   Get a sense of scale before reading any data.
2. **Search, not read.** Run `grep`/`rg` for the symptom, for error levels, for
   a process name. Almost never read a large file whole — and at 200,000 lines,
   never.
3. **Narrow by counting.** Ask how many matches there are before asking for
   their content.
4. **Read a range.** Once an interesting line number is known, read the lines
   *around* it. The surrounding records from other processes are the causal
   context, and this step is usually what actually explains the finding.
5. **Delegate breadth.** For a wide investigation, spawn a subagent so raw
   search hits stay out of the main context.

Step 4 is the one most log formats make hard, and it is the step that produces
the answer.

## The constraints that shape the format

### Shell output truncates silently at 30,000 characters

This is the single most consequential constraint, and it fails in the worst
possible way: quietly. A bare `rg 'Error' session.log` over a large capture stops
producing output partway through, and nothing in the result says it was cut. The
agent sees a plausible, complete-looking result set and reasons from it.

At an average record length around 165 characters, that ceiling is reached at
roughly **180 matches**.

Two things follow. The generated `CLAUDE.md` must state the limit and give
recipes that count first and then page (`rg -c`, then `rg -n … | head -n 50`).
And the file-reading tool, whose paging parameters are explicit and safe, should
be preferred over raw shell search wherever it will do.

### Context is finite and it is shared

Every token spent on log formatting is one not spent on reasoning about the bug.
This is the argument against JSON as the primary format: every grep hit becomes
a whole object, most of which is punctuation and repeated key names.

It is also the argument for precomputing aggregates. An agent that has to count
occurrences itself pays for every line it counts. A generator that counted them
once, at export time, hands over the same fact for the price of one small file.

### A search hit must be self-describing

This is the property the whole format is built around.

If a record can span multiple physical lines, then a grep hit is a fragment: it
may not carry its own timestamp, level or process, and recovering them costs a
second tool call. Multiply that across dozens of hits and the investigation is
mostly bookkeeping.

So every record occupies exactly one physical line. Multi-line device messages
are folded into their parent record — real newlines become `\n`, tabs `\t`,
backslashes `\\`. **Every grep hit is a complete record.**

### Line numbers are the cheapest possible pointer

`errors.log` puts the corresponding `session.log` line number in its first
column. `timeline.tsv` maps each minute to the first line number of that minute.
Both turn "show me what was happening around this" from a search into a bounded
read.

## `CLAUDE.md`, and why it is generated

Claude Code loads a `CLAUDE.md` from a directory automatically when it reads a
file from that directory. Putting one in the bundle means the agent gets the
format documentation without anyone having to explain it, and without it
occupying context until it is relevant.

The generated file has to do four things, and stay bounded in length regardless
of whether the capture is 6,000 records or 2,000,000:

1. **State the scale up front** and say plainly: never read `session.log` whole.
2. **Document the columns**, with one real record from this capture as the
   example. A real line is worth more than a schema, because it shows what the
   values actually look like.
3. **Summarise this capture** — time range, record count, level distribution,
   the most frequent error patterns with their line numbers.
4. **List the gotchas that would otherwise mislead.**

That fourth section earns its length. The specific traps:

- **`<private>` is Apple's own redaction**, emitted by the device. That data
  never reached the capture tool. An agent that treats it as a defect in the
  export will chase the wrong thing.
- **Timestamps have one-second resolution in the text format**, and iOS
  interleaves processes faster than that. Same-second ordering is arrival order,
  **not proven causality**. Without this stated, an agent will confidently
  assert that A caused B.
- **iOS logs a great deal of routine chatter at `Error` level** — Wi-Fi link
  telemetry especially. In one 6,409-record capture, 312 records were
  Error-or-worse and the top five patterns were all `wifid` link-quality
  telemetry firing 14 times each. An agent that does not check
  `patterns.tsv` for frequency will report noise as the symptom. This is
  probably the highest-value line in the file.
- **`kernel(apfs)` means the kernel logging through a subsystem**; `kernel()` is
  the kernel with no subsystem tag. They look like different processes and are
  not.
- **Only levels the device actually emitted are present.** An absent `Warning`
  count means none were logged, not that they were filtered out.

## Verification

The claims above are testable and are tested, rather than assumed:

- The documented `rg` recipes are executed against a generated bundle and their
  claimed counts asserted.
- Fold/unfold is round-tripped, including messages that already contain a
  literal `\n` two-character sequence.
- `CLAUDE.md` length is asserted against a capture two orders of magnitude
  larger than the fixture, since the whole point is that it does not grow with
  the log.

## What this format deliberately does not do

It does not summarise, cluster or diagnose on the agent's behalf beyond
frequency counting. An exporter that decides which errors matter is an exporter
that can hide the one that did. `patterns.tsv` reports what repeated and how
often; deciding what that means is the agent's job, and it has the full record
set to check any conclusion against.
