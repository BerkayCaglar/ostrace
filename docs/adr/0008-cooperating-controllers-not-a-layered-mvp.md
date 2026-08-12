---
status: accepted
date: 2026-08-12
decision-makers: Berkay ÇAĞLAR
---

# Decompose MainWindow into cooperating controllers, not a layered MVP

## Context and Problem Statement

`MainWindow` was 2,155 lines. It ran the capture, decided the theme, derived
the tail, encoded the settings, built the menus and said every sentence the
user reads — and the sentences were interleaved with the machinery, so neither
could be read or tested without the other.

The obvious answer is a layered architecture: a view that only paints, a
presenter that holds the logic, a model beneath both. That answer was
considered and rejected.

## Decision Drivers

- The tests are the constraint. A rule about parking a thread should not need a
  toolbar and a minimap to assert, and a rule about what a strip of text says
  should not need a device.
- The design document makes claims about *this window's surface* —
  `following` is derived on every read, a notice is never hidden by a filter.
  A decomposition that moved those claims somewhere else would make the
  document false without changing any behaviour.
- Nobody is coming to reuse these pieces. There is one window.

## Decision

**Cooperating controllers, each owning one mechanism, with the window keeping
presentation.**

Five objects came out, in this order: `WindowSettings` (what is remembered),
the action factory (how the menus are built), `CaptureController` (running a
capture), `FollowController` (staying at the bottom), `ThemePolicy` (which
scheme is in force). Each is testable alone; three of them have tests that
build no window at all.

**Not a layered MVP.** The layers a presenter would draw are not where this
program's seams are. Its hard parts are a thread that may not stop, a scheme
that arrives three ways, a tail that must be derived rather than stored — and
each of those is a *mechanism*, not a layer. Splitting by layer would have cut
every one of them in half.

**The window keeps every user-facing sentence**, all nine banner wordings, the
title, the placeholder, the enable/disable fan-out, and the verb wiring: every
menu, toolbar and context entry is an action the window already owns. That is
its identity rather than a leftover.

**Filter orchestration stays on the window.** It was priced and it buys
nothing: no backlog item is waiting on it, no test is hard to write because of
it, and moving it would put the filter bar, the banner and the model swap in
three places that all have to agree.

**A centralized banner policy engine was rejected.** Twenty `show_message`
sites are each correctly placed; what was wrong was that two of them tracked
what was showing by comparing a string and by keeping a flag. The mechanism was
the bug, not the distribution — a notice carries a key now, and the sites did
not move.

## Consequences

`MainWindow` is 1,811 lines: presentation policy, and a target rather than a
shortfall. It was expected to land near 1,100–1,200, and it will after the view
layer and the storage facade are cut; that is packages E and F, not this one.

Three bugs a user meets came out of the decomposition rather than out of a bug
report — a paused view whose resume cleared somebody else's notice, a widened
filter that did the same, and a stop-timeout that grew memory without bound.
Each was found by asking what a piece was actually responsible for.

Two rules that were true and untested are now pinned: a restored theme still
outranks the system, and a new model puts the tail back on. Both survived every
existing test while being wrong.

## Confirmation

Each controller ships with mutation evidence: the rule is removed, the suite is
run, and the test that goes red is named in the pull request. Across packages
C and D, thirty-eight mutations were run and **five found gaps that no test
covered** — every one of those closed before merge.

The strongest is not a test failure at all. Removing `CaptureController`'s wait
over parked threads aborts the process with exit `0xC0000409`, which is the
`qFatal` on a running `QThread` that ADR 0007 exists to prevent.
