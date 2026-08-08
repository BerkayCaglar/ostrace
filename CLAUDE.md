# ostrace

Cross-platform iOS log viewer. Done: phases 0 and 1 (model, sources, storage)
and phase 3a (`devices`, `capture`, `doctor`). Not built: phase 2 (analysis,
exporters), the `export` subcommand that depends on it, and the GUI.

Read when relevant, rather than up front: `docs/adr/` for why decisions were
taken, `docs/formats/` for the on-disk contracts, `CONTRIBUTING.md` for setup,
`docs/README.md` for the phase table.

<!-- Deliberately not @-imports: those load at launch and would put the whole
     docs tree in context every session for no benefit. Also note that any bare
     @-prefixed token in this file IS parsed as an import, which is why the
     pytest marker below is backticked. -->

## Commands

```bash
pip install -e . --group dev     # PEP 735, needs pip >= 25.1 -- not .[dev]
ruff check . && ruff format --check .
zizmor --persona=regular .github/workflows
mypy --platform linux && mypy --platform win32 && mypy --platform darwin
pytest -m "not device"
```

All of these run in CI. mypy runs three times on purpose: it narrows `sys.platform`
to whatever it runs on, so a single pass leaves the other platforms' branches
unchecked — which is where the bugs would be, since only Windows can be tested
here.

Clone with full history. The version comes from git tags via hatch-vcs and a
shallow clone builds as `0.0.0`.

## Hard rules

Each of these has cost real time at least once.

- **Validate parsers against `tests/fixtures/` captures, never against
  hand-written log lines.** A previous iteration matched 0% of real device
  output for weeks because its samples contained a syslog hostname field that
  real output does not have. The tests passed the whole time.
- **Never run device code under `-O` / `PYTHONOPTIMIZE`.** pymobiledevice3's
  stream loop is `assert await self.service.recvall(1) == b"\x02"`;
  optimisation strips the `assert` *including the `await` inside it*, which
  desynchronises the wire protocol and yields garbage instead of an error.
  `OsTraceSource` refuses to construct when the flag is set.
- **Only `compat.py` may branch on the operating system** or touch a
  platform-specific attribute. Write the literal `sys.platform == "win32"`
  form, not a named constant — type checkers narrow on the literal and not on a
  constant, and the three-platform mypy run depends on that.
- **Mark unverified macOS assumptions `# UNVERIFIED-MACOS`** so they can be
  grepped and confirmed. There is no Mac here; that code is written blind.
- **Only `paths.py` decides where files go.** Building a path from a literal is
  how the predecessor ended up unable to run anywhere but Windows.
- **Timestamps are timezone-aware, carrying the *device's* offset.** The host is
  a different clock in a frequently different zone. A naive timestamp is
  rejected on read rather than guessed at.
- **Do not bump the exact `ruff` / `mypy` pins to make an error go away.**
- **Actions are referenced by full commit SHA, never by tag**, with the release
  in a trailing comment. A tag can be repointed by whoever owns the action; the
  repository enforces this, so a tag ref fails the run rather than the review.
  Let Dependabot do the bumping — it rewrites the SHA and the comment together.
- Two SPDX lines at the top of every new source file, matching the existing ones.

## Architecture

The load-bearing constraint is the `LogSource` protocol in `sources/base.py`.
Its surface is small on purpose: a recorded session must be substitutable for a
live device in every test, which is what lets CI cover the pipeline on three
operating systems with no hardware.

- Consumers take a `LogSource`. Never a concrete source, and never a method one
  implementation has and the other does not.
- New sources inherit `SourceCloseMixin` rather than re-implementing the async
  context manager pair. Its `aclose()` raises rather than defaulting to a no-op,
  so forgetting to release something is loud instead of a slow socket leak.
- `Gap` travels *in* the stream, in position. A gap that happened between these
  two records and not those two loses its meaning through a side channel.
- `stream()` can block indefinitely without yielding — a quiet device goes
  silent for tens of seconds. Drive any timeout from a separate task; waiting
  for the next record in order to notice time has passed is a hang.
- Nothing outside `sources/` and `devices/` imports pymobiledevice3. `errors.py`
  translates its exceptions by class *name* so the dependency stays confined.

## Tests

- `` `@pytest.mark.device` `` means a physical iPhone is required. It is
  excluded in CI. Never add it to a test that could run against a fixture, and
  never add it to make CI green.
- Fixtures are real captures from an `iPhone18,2` on iOS 26.5.2, filtered to
  system processes. `tests.helpers.make_record` synthetics are fine for
  round-tripping our own file format and wrong for anything asserting how
  device output is interpreted.
- New behaviour ships with a test. A bug fix ships with the test that fails
  without it.

## Etiquette

Update `CHANGELOG.md` under `## [Unreleased]` for anything user-visible.
Conventional-ish commit subjects. One logical change per pull request.

<!-- The agent-bundle exporter (phase 2) generates a CLAUDE.md *inside each
     exported capture* to orient an agent investigating that log. That is a
     build artifact and has nothing to do with this file. -->

`docs/formats/` specifies contracts before they are implemented, and the README
documents CLI subcommands that do not exist yet. Neither is a bug to fix.
