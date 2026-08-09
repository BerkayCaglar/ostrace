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
BSSID. 1,123 of the 8,000 records now carry a redaction — count them yourself;
that is a property of the files in front of you, not a claim about history:

| Redacted | Why |
| --- | --- |
| Wi-Fi SSID and BSSID | A BSSID resolves to a street address through public wardriving databases. |
| Paired Bluetooth device addresses | Identify the owner's accessories, and are stable. |
| Device UDID, `X-CloudKit-DeviceID` | Permanent hardware identifiers; neither can be reset. |
| iCloud DSID, CloudKit account and container user IDs | Resolve to one Apple ID. |
| `x-apple-mmcs-auth`, upload receipts, presigned S3 signing material | Capability tokens for the owner's iCloud storage. |
| ETags, `protectionInfoTag`, CloudKit record digests, SHA-512 digests, MMCS chunk signatures | Derived from the owner's own backup content. |
| Third-party bundle identifiers reaching system daemons | An inventory of what is installed. |
| The backup snapshot UUID | Not linkable to a person from outside, but it recurs 947 times and a redactor had already replaced the digest beside it. Half-scrubbing one string is how the next thing hides. |

Three of those rows were added by a **second, independent audit** run after the
first had finished and its tool was passing clean. It found MMCS chunk
signatures written as `chunk ==> <hex>` and container handles written as
`mmcs put container 1:\t<handle>` — the same classes as values already removed,
in a syntax with no key word in front of them, so no rule fired. Both were
sitting in the census output, below the point the first auditor stopped
scrolling. **Read all of the census, not the top of it.**

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

```bash
python tools/audit_capture.py path/to/capture --census
```

1. **Fix every finding.** Each is either something to redact or something to
   add to `KNOWN_SYNTHETIC` in that file, with a comment saying why it is safe.
   CI runs the same check against the committed fixtures, so a finding left
   unresolved fails the build rather than reaching a release.
2. **Read the census.** It lists every high-entropy token grouped by the text
   in front of it. This is the step that finds the category nobody has written
   a rule for yet: `x-apple-mmcs-auth` was found this way, and so — after the
   rules had been written and were passing — were the abbreviated `sig:` and
   `ref:` spellings of two fields whose long names were already covered.
3. **Re-read a sample by eye.** No rule recognises a *name*. An SSID is a word
   somebody chose, and the only reason the audit caught one is that an SSID
   travels next to a BSSID and a BSSID is a MAC address. A capture contains
   whatever the device happened to be doing at the time, and the next one will
   contain something none of this predicts.
