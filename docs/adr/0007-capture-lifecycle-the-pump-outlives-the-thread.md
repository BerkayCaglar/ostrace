---
status: accepted
date: 2026-08-12
decision-makers: Berkay ÇAĞLAR
---

# Capture lifecycle: no shared session class, and the pump outlives the thread

## Context and Problem Statement

A live capture is three moving parts: a `QThread` running
`ostrace.capture.capture` against a device, a `deque` it fills, and a `Pump` on
the interface thread that drains the deque into the model. The window owned all
three, interleaved with the sentences it says about them — nine banner wordings,
a title, a placeholder, and an enable/disable fan-out across six controls.

Two questions had to be answered before that could be cut apart.

**Should the command line and the viewer share a lifecycle object?** The
obvious symmetry says yes: both run a capture, both must release the device.

**What happens when a device will not let go?** `Disconnect` waits for the
capture thread, bounded, so that a stuck device cannot freeze the window. A
bounded wait can time out, and something has to be decided about what is left
running.

## Decision Drivers

- Letting go of a running `QThread` is not a leak. Qt's destructor calls
  `qFatal`, so the symptom is not a stuck capture, it is the viewer vanishing —
  measured here as exit `0xC0000409` with nothing printed.
- The thread keeps producing into the deque whether or not anybody is draining
  it, at up to 1,600 records a second.
- The command line has no event loop, no widgets and no user watching. Its
  lifecycle is `capture()` plus structured concurrency, and it is provable in
  that idiom.

## Decision

**`CaptureController(QObject)` in `gui/capture_controller.py`** owns the thread,
the pump, the bounded stop wait, parking, joining and saying where the session
went. It says nothing a user reads.

**No Qt-free `CaptureSession` beneath it.** The two callers do not share a
lifecycle; they share `capture()`, which is where the thing worth sharing —
release the device on every exit path, finalise the sidecar — already lives. A
common base class would have to be shaped by the harder of the two consumers
and would be exercised honestly by neither.

**The pump outlives the thread, never the reverse.** On a stop-timeout the
thread is parked *and its pump is parked with it, running and paused* until the
thread genuinely ends, at which point the pump takes a final drain and goes.
Paused is not stopped: the pump keeps its own `PAUSE_LIMIT` bound and evicts
with the notice the model already makes, which is the honest answer — those
records are in the session file, and no longer in the view.

**The connection vocabulary stays in `sources/base.py` and Qt-free.**
`CaptureState` is what the device *link* is doing and the command line reads it
too; `Lifecycle` is what the *capture* is doing and exists only in the viewer,
with states no link has: parked, and never started.

## Consequences

A stop that times out no longer grows memory without bound. The pump used to be
stopped at that moment while the thread went on producing, so the queue grew
with nobody draining it — and nothing said so, because a stopped pump reports
nothing.

The window is left with presentation, which is what it is for. It hears about a
capture through one state value and five events, and decides what each looks
like.

`path` and `is_running` are plain attribute reads rather than signals, and that
is a contract: the export snapshot asks immediately after joining the capture
thread, and a queued signal needs an event loop the joiner is not running.

Opening the finished session stays on the window. The controller says the file
is complete and where it is; opening it can fail, and what a reader is told when
it does is a sentence.

## Confirmation

The rules above are each pinned by a test that fails without them, verified by
removing the rule and running the suite:

- parking the pump stopped instead of paused;
- dropping a thread that outlived the wait instead of parking it;
- emitting the session path before the thread has really ended;
- a `stop()` that is not idempotent;
- a late link notification walking the lifecycle backwards.

The sixth is the one that does not fail a test. Removing the wait over parked
threads in `shutdown()` **aborts the process** — exit `0xC0000409`, no summary,
no traceback — which is the failure this decision exists to prevent, arriving
exactly as documented.
