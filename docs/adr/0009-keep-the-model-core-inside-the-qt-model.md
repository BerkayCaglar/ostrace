---
status: accepted
date: 2026-08-12
decision-makers: Berkay ÇAĞLAR
---

# Keep `RecordModel`'s core inside the Qt model; extract only pure arithmetic

## Context and Problem Statement

`RecordModel` holds every row, the filter, the marks, the minimap buckets and
the eviction accounting, and it is a `QAbstractTableModel`. Its hardest method
is `_trim`: a bisection, two off-by-ones and a decision about which Qt bracket
to open, where the wrong bracket silently corrupts a view's idea of its own
rows.

The tempting answer is a `ViewBuffer` — a Qt-free class holding the rows and
the arithmetic, with a thin `QAbstractTableModel` on top. It was proposed and
rejected.

## Decision Drivers

- Everything hard about this class is *entangled with Qt on purpose*.
  `beginRemoveRows`/`endRemoveRows` must bracket the mutation they describe,
  and `beginInsertRows` is not interchangeable with it. A buffer that mutated
  underneath a model would have to tell the model what it had just done, which
  is the same coupling with an extra hop and a chance to disagree.
- The arithmetic that is *not* entangled is small, and it is all of the risk.
- 200,000 rows and 1,600 arrivals a second. Every indirection is on the ingest
  path.

## Decision

**The rows, the filter, the marks and the bracketing stay inside the Qt model.
Only pure arithmetic comes out.**

Two functions did, and one method changed shape:

- `plan_trim` (`gui/markers.py`) works out what a trim will do and returns a
  `TrimPlan`: how many source rows leave, what the survivors shift by, how many
  view rows go, whether a notice is added or replaced. `_trim` becomes plan,
  open the bracket the plan names, apply the slices, close, emit. The
  bracketing and the mutation stay adjacent, which is the property that
  matters.
- `fit_budgets` (`gui/columns.py`) is column fitting, which was arithmetic on a
  widget for no reason other than where it was written.
- `RecordModel.clear()` empties in place, replacing the window's model swap.

**No `ViewBuffer`.** The audit behind this counted the Qt touch points in the
class and they are not a layer: they are interleaved with every mutation, by
design, because that is what a `QAbstractTableModel` is for.

## Consequences

The trim's arithmetic is now tested against a second, deliberately naive
implementation over ten thousand generated shapes, in a file that imports no
Qt. That is a different kind of evidence from a careful reading, and it caught
nothing on the day — which is the point of writing it before the next change
rather than after it.

`clear()` deleted a class of bug rather than a block of code: a model that is
never abandoned cannot be the half of a pair nobody released.

The cost was measured, because an extraction on the ingest path is not free
until it is. `_trim` over 20,001 dropped rows: **44.0 ms before, 45.1 ms
after**, against a tripwire of 70 ms agreed in advance. `append` at a batch of
80 into 200,000 retained rows is unchanged at 0.051 ms median.

## Confirmation

Six mutations against the trim algebra, each restored: the notice not
shortening the shift, a replaced notice unaccounted for, the bisection off by
one, the margin ignored, a gap-only drop inventing a notice, and marks shifted
by the wrong amount. All six go red.

The last is the one worth naming. Marks are held by source index precisely so a
trim moves them with their records, and nothing asserted it: a mark shifted by
`drop` instead of `offset` lands the reader on the record *beside* the one they
marked, which is a wrong answer that looks like a right one. It is caught by
one test, and that test did not exist before this change.
