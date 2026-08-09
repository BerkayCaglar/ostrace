---
status: accepted
date: 2026-08-08
decision-makers: Berkay ÇAĞLAR
---

# Record architecture decisions

## Context and Problem Statement

`ostrace` is a rewrite of a working single-file tool. Most of the design was
settled during a research phase whose reasoning — measurements against a real
device, licence analysis, GUI toolkit benchmarks — is far more valuable than the
conclusions on their own. Six months from now the conclusions will still be in
the code; the reasons will not be anywhere unless they are written down.

The specific failure this guards against: a future contributor (including the
author) sees `QSortFilterProxyModel` in the Qt documentation, notices this
project hand-rolls a filtered index list instead, assumes it was ignorance, and
"fixes" it — reintroducing a measured 4.7× regression, and giving up control of
the row cap, the eviction notice and the marker exemption with it.

## Decision Drivers

- The reasoning behind several decisions is counter-intuitive and looks like a
  mistake without it.
- Some decisions rest on measurements that are expensive to repeat (they need a
  physical device) or impossible to repeat (no Mac is available).
- Solo project: there is no colleague who remembers.

## Considered Options

1. **Architecture decision records** in `docs/adr/`, MADR format.
2. **A single long design document.**
3. **Comments in the code only.**
4. **Nothing.**

## Decision Outcome

Chosen option: **architecture decision records in MADR 4.0.0 format**, one file
per decision, numbered sequentially. A *decision* is never reversed by editing
the file that made it — that takes a later ADR marking it superseded.

A **measurement** in an ADR is corrected in place, in a dated note that keeps
the original number visible. This is not the same rule bent: the reason
decisions are immutable is that a reader must be able to see what was decided
and why, and a figure that has since been disproved serves that badly in the
other direction — it is a wrong number, standing, in the document a future
reader will trust. ADR 0004 carries the first of these.

MADR because it is the most widely used markdown ADR template, has a published
spec, and its "Considered Options" and "Pros and Cons" sections force the
alternatives to be written down. Recording *what was rejected and why* is the
part that actually prevents relitigation.

### Consequences

- Good: a rejected option that resurfaces has an answer already written.
- Good: each ADR names the evidence it rests on, so a decision can be
  re-examined when the evidence changes rather than on taste.
- Good: `docs/research/` holds the raw findings; the ADRs stay short and link
  out to them.
- Bad: every non-trivial decision now costs a file. Accepted; the alternative
  has a worse failure mode.
- Neutral: decisions are immutable. Changing one means a new ADR that marks the
  old one superseded, not an edit. Measurements are not: a figure that has been
  re-measured is corrected where it stands, with a dated note.

### Confirmation

An ADR exists for every decision that (a) an outside reader would plausibly
question, or (b) was decided against a serious alternative. The initial set is
0002–0006.

## More Information

- [MADR](https://adr.github.io/madr/) — the template used here.
- Michael Nygard, *Documenting Architecture Decisions* (2011) — the original
  formulation.
