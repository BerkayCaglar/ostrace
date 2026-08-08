# Test fixtures

Real captures from a physical device, committed so that the whole pipeline is
testable with nothing attached. `ostrace.sources.replay` reads them and the rest
of the code cannot tell them apart from a live device.

| File | Records | Contents |
| --- | ---: | --- |
| `ios26-mixed.jsonl.gz` | 5,000 | A normal five seconds of an idle device. 97% carry a subsystem; DEBUG dominates. |
| `ios26-errors.jsonl.gz` | 3,000 | Error-heavy, sampled from seven minutes of capture. ~2,200 Error and 63 Fault. |

Both were captured from an `iPhone18,2` running iOS 26.5.2 over
`com.apple.os_trace_relay`, and written through `ostrace`'s own record mapping
and spool writer. That is deliberate: the fixture is then evidence that the real
mapping handles real field values, not merely that the file format round-trips.

**Fixtures are captured, never written by hand.** A previous iteration of this
tool matched 0% of real device output for weeks because its tests used invented
log lines containing a syslog hostname field that real output does not have. The
tests passed the entire time.

## What was filtered out, and why

The repository is public, so these went through a deliberate filter before being
committed:

- **Records from installed third-party applications** — dropped entirely. Their
  paths contain app container UUIDs and their messages contain whatever the app
  chose to log. System daemons do not.
- **Account-linkable identifiers** — dropped. Specifically, iCloud content URLs,
  which carry the account DSID in a path segment. Dropping the handful of
  affected records keeps every other record verbatim, which redacting would not.

What remains is system daemon output: `cloudd`, `backupd`, `nsurlsessiond`,
`wifid`, `kernel` and similar. Long digit runs still appear in it — inodes, TCP
sequence numbers, Biome stream timestamps, file IDs — and were checked rather
than assumed harmless.

`<private>` markers are Apple's own redaction, applied on the device before the
data ever reached the capture tool. They are preserved verbatim; several tests
depend on their presence.

## Regenerating

Attach a device and capture through `ostrace` itself. Rerun the same privacy
filter, and re-read a sample by eye before committing — a capture contains
whatever the device happened to be doing at the time.
