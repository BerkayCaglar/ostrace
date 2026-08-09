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

The repository is public, so these were captured with a filter that dropped
records originating from installed third-party applications: their paths carry
app container UUIDs and their messages carry whatever the app chose to log.

**That filter was scoped to the wrong thing, and a later audit found what it
missed.** It selected on the process a record came *from*, so it never inspected
the contents of records from `cloudd`, `backupd`, `wifid`, `bluetoothd`,
`SpringBoard` and the rest — which is exactly where the device's own identifiers
travel. A system daemon logging your Wi-Fi BSSID is still logging your Wi-Fi
BSSID. Roughly 1,000 records carried something, and every one of them is now
redacted in place:

| Redacted | Why |
| --- | --- |
| Wi-Fi SSID and BSSID | A BSSID resolves to a street address through public wardriving databases. |
| Paired Bluetooth device addresses | Identify the owner's accessories, and are stable. |
| Device UDID, `X-CloudKit-DeviceID` | Permanent hardware identifiers; neither can be reset. |
| iCloud DSID, CloudKit account and container user IDs | Resolve to one Apple ID. |
| `x-apple-mmcs-auth`, upload receipts, presigned S3 signing material | Capability tokens for the owner's iCloud storage. |
| ETags, `protectionInfoTag`, CloudKit record digests, SHA-512 digests | Derived from the owner's own backup content. |
| Third-party bundle identifiers reaching system daemons | An inventory of what is installed. |

Redacted **in place**, not dropped: the record counts above are load-bearing in
a dozen assertions, and the level and subsystem distributions are what several
tests are actually about. Each value was replaced by `<redacted>`, or — where
the shape is what the parser sees — by a same-shaped synthetic (`02:00:5e:…`
for a MAC, matching digit counts for a numeric id). Nothing else in the record
was touched, and the rewrite went through this project's own `SpoolReader` and
`SpoolWriter`, verified byte-identical on a no-op pass first.

What remains is system daemon output: `cloudd`, `backupd`, `nsurlsessiond`,
`wifid`, `kernel` and similar. Long digit runs still appear in it — inodes, TCP
sequence numbers, Biome stream timestamps, file IDs — and were checked rather
than assumed harmless. So were the ~60 CoreBluetooth peer UUIDs: those are
host-scoped and rotate, and mean nothing off the device that minted them.

The lesson worth keeping: **filter on what a record says, not on who said it.**

`<private>` markers are Apple's own redaction, applied on the device before the
data ever reached the capture tool. They are preserved verbatim; several tests
depend on their presence.

## Regenerating

Attach a device and capture through `ostrace` itself. Then, before committing:

1. Drop records from installed third-party applications.
2. Sweep the *contents* of what is left for the categories in the table above.
   Grepping for known values is not enough — the audit that produced that table
   found the `x-apple-mmcs-auth` tokens only after enumerating every
   high-entropy token in the capture and classifying each one.
3. Re-read a sample by eye. A capture contains whatever the device happened to
   be doing at the time, and the next one will contain something this list does
   not predict.
