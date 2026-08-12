# Architecture decision records

Why the code looks the way it does. Format is [MADR 4.0.0](https://adr.github.io/madr/).

| # | Decision | Status |
| --- | --- | --- |
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | accepted |
| [0002](0002-use-pymobiledevice3-over-libimobiledevice-cli.md) | Read logs through pymobiledevice3's `os_trace_relay`, not the libimobiledevice CLI | accepted |
| [0003](0003-license-gpl-3-0-or-later.md) | License the project GPL-3.0-or-later | accepted |
| [0004](0004-pyside6-with-custom-filtered-model.md) | PySide6 with a hand-written filtered table model | accepted |
| [0005](0005-agent-bundle-export-format.md) | Export an "agent bundle" of flat text files, not a single document | accepted |
| [0006](0006-defer-wifi-capture.md) | Defer network (Wi-Fi) capture to a later release | accepted |
| [0007](0007-capture-lifecycle-the-pump-outlives-the-thread.md) | Capture lifecycle: no shared session class, and the pump outlives the thread | accepted |
| [0008](0008-cooperating-controllers-not-a-layered-mvp.md) | Decompose MainWindow into cooperating controllers, not a layered MVP | accepted |
| [0009](0009-keep-the-model-core-inside-the-qt-model.md) | Keep `RecordModel`'s core inside the Qt model; extract only pure arithmetic | accepted |

## Adding one

Copy the structure of an existing record, take the next number, and open it with
`status: proposed`. Once a decision is accepted, the *decision* is not edited
again — if it changes, write a new ADR that supersedes it and mark the old one
`superseded by NNNN`. The history is the point.

A *measurement* inside an accepted ADR is different, and is corrected where it
stands with a dated note that keeps the original figure visible. A number that
has been disproved does not become history by being left alone; it becomes a
wrong number in the document a future reader trusts. See
[ADR 0001](0001-record-architecture-decisions.md) and the correction in ADR
0004.

Write an ADR when a decision is one an outside reader would plausibly question,
or when it was taken against a serious alternative. Not for every choice.

The evidence these rest on lives in [../research/](../research/); ADRs link to
it rather than restating it.
