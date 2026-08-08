# Format: session file

**Version:** 1 (draft — the writer lands in phase 1)

A session file is the raw capture: what `ostrace capture` writes and what every
exporter reads. It is the archival format. The
[agent bundle](agent-bundle.md) and the other exports are derived from it and
can always be regenerated.

---

## Why a spool file rather than memory

An hour of capture at 1,200 records per second is around four million records.
Holding those in a Python list is not viable, and the predecessor tool's
in-memory approach is exactly what limited it.

So records are written to disk as they arrive and the viewer keeps only a
bounded window in memory. Capture length is then bounded by disk, not RAM.

## Shape

```
<name>.ostrace/
├── session.jsonl.gz     the records
└── session.json         metadata sidecar
```

## `session.jsonl.gz`

Gzip-compressed JSON Lines: one JSON object per line, one record per object.

JSON here and tab-separated text in the agent bundle is a deliberate split.
This file is written once and read by programs; it needs to be unambiguous and
to survive new fields being added. The bundle is read by humans and by agents
with grep; it needs to be terse. Optimising both for the same consumer would
compromise one of them.

### One property that is easy to get wrong

The file is written with `Z_SYNC_FLUSH` at record boundaries, so that **a
session file is readable while it is still being written**. Live export during
capture depends on this, and so does recovering a capture whose process was
killed.

The consequence is that a reader must tolerate a stream with no gzip trailer.
A tolerant reader that catches `EOFError` has to be careful to still yield the
final decoded record — an earlier implementation dropped the last line of every
unclosed file because the exception was caught before the final `yield`. There
is a regression test for exactly this.

### Record object

```json
{
  "ts": "2026-08-08T01:10:31.696620+03:00",
  "level": "NOTICE",
  "pid": 70,
  "process": "backboardd",
  "process_path": "/usr/libexec/backboardd",
  "subsystem": "com.apple.CoreBrightness.ColourSensorFilterPlugin",
  "category": "default",
  "thread_id": 13570622,
  "image_path": "/System/Library/HIDPlugins/ColourSensorFilterPlugin.plugin/...",
  "platform": "ios",
  "message": "[ALS] ts=861562.666 lux=3.830<private> ..."
}
```

`process_path` and `image_path` read backwards from the upstream field names
they come from, and the distinction matters. `process_path` is the process
executable; `image_path` is the binary that actually emitted the record, which is
usually a framework or plugin loaded into that process — they differ in roughly
nine records out of ten. Mapped the wrong way round, every plugin's output is
attributed to whichever host process happened to load it.

Keys with no value are **omitted rather than written as null**, so `subsystem`,
`category`, `thread_id` and `image_path` are absent on the roughly 3% of records
that carry no label. Readers must treat absent and null alike.

Timestamps are timezone-aware, carrying **the device's** UTC offset. The device
reports naive local time and the host is a different clock in a frequently
different zone, so the offset is read from lockdown (`TimeZoneOffsetFromUTC`) and
attached at capture. A record with no offset is rejected on read rather than
guessed at: a plausible wrong answer is worse than a visible one. Naive datetimes
are a bug class here, which is why ruff's `DTZ` rules are enabled.

Levels are written by **name**, never by number. The numeric values of
`Level` are spaced so that new levels can be inserted — Android's `WARN` when a
logcat source arrives — which would silently reinterpret every existing file if
numbers were stored. The names iOS produces are `DEBUG`, `INFO`, `NOTICE`,
`USER_ACTION`, `ERROR` and `FAULT`.

Note that Apple's own values are *not* severity-ordered: `SyslogLogLevel` on
iOS 26 is `NOTICE=0, INFO=1, DEBUG=2, USER_ACTION=3, ERROR=16, FAULT=17`. A
filter written against those numbers is silently wrong, which is why the mapping
into our own ordered enum is not cosmetic.

`platform` is present from day one, before there is a second platform to put in
it. Adding a field to a documented on-disk format later invalidates every file
already written; adding it now costs one constant.

Unknown fields must be ignored by readers, not rejected. That is what allows a
field to be added without a version bump.

### Gap markers

There is no auto-reconnect in `pymobiledevice3` — this project owns that loop.
When a connection drops and is re-established, records emitted during the gap
are unrecoverable. A gap is recorded explicitly:

```json
{"gap": true, "from": "2026-08-08T01:12:04+00:00", "to": "2026-08-08T01:12:09+00:00", "reason": "ConnectionTerminatedError"}
```

Exports state the gap rather than hiding it. A log with a silent hole in it is
worse than one with a labelled hole, because the reader draws conclusions from
the absence.

## `session.json`

Uncompressed metadata sidecar, written at capture start and updated at the end:

```json
{
  "format_version": 1,
  "ostrace_version": "0.1.0",
  "device": {
    "udid": "...",
    "name": "...",
    "product_type": "iPhone18,2",
    "product_version": "26.5.2",
    "connection": "usb"
  },
  "source": "os_trace_relay",
  "started_at": "2026-08-08T01:10:00+00:00",
  "ended_at": "2026-08-08T02:10:00+00:00",
  "record_count": 4218331,
  "gap_count": 2,
  "flags": { "historical": false }
}
```

`source` matters for interpretation: a session captured over the fallback
`syslog_relay` contains only the NOTICE tier and has no subsystem or category on
any record. An export must be able to say so rather than let a reader conclude
the device emitted nothing at DEBUG.

If `session.json` is missing or truncated — a capture killed mid-write —
`session.jsonl.gz` alone is still fully readable. The sidecar is metadata, never
an index.

## Retention

Session files are written under the user's data directory, resolved by
`platformdirs`; no path is hardcoded anywhere. On macOS the config and data
directories are the same location, so nothing may assume they differ.

Nothing is deleted automatically. An hour-long capture is on the order of tens
of megabytes compressed, and a log viewer that silently discards a user's
capture is a log viewer that loses the one they needed.
