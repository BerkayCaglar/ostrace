# Contributing

Thanks for looking. This is a small project; the setup is deliberately boring.

## Development setup

```bash
git clone https://github.com/BerkayCaglar/ostrace
cd ostrace
python -m venv .venv
```

Activate it (`.venv\Scripts\activate` on Windows, `source .venv/bin/activate`
elsewhere), then:

```bash
python -m pip install --upgrade pip
pip install -e . --group dev
```

`pip install --group` needs pip 25.1 or newer — hence the upgrade first. The
development dependencies live in a [PEP 735](https://peps.python.org/pep-0735/)
`[dependency-groups]` table rather than an extra, because they are not something
a user of the package should ever be able to install.

Clone with full history. The version comes from git tags via `hatch-vcs`; a
shallow clone builds as `0.0.0`.

## The checks CI runs

```bash
ruff check .
ruff format --check .
zizmor --persona=regular .github/workflows
mypy
pytest -m "not device"
```

`ruff`, `mypy` and `zizmor` are pinned to exact versions in
`[dependency-groups]`. New releases of any of them regularly add diagnostics,
and an unpinned linter turns "someone released a new ruff" into "the build is
red on an unrelated PR".

`zizmor` audits the workflow files. They are worth a linter of their own because
they are the only thing in this repository that runs with privilege: `ci.yml`
holds the repository token and `release.yml` holds an OIDC identity that can
publish to PyPI. If you change a workflow, note that actions are referenced by
full commit SHA rather than by tag — the repository rejects tag references, and
Dependabot updates the SHA and its trailing version comment together.

### Tests that need a device

Tests marked `@pytest.mark.device` need a physical iPhone attached over USB and
are excluded in CI. Run them locally with `pytest -m device`.

Everything else runs against committed fixtures in `tests/fixtures/`. That is
the point of the `sources/` boundary described in
[docs/adr/0002](docs/adr/0002-use-pymobiledevice3-over-libimobiledevice-cli.md):
`sources/replay.py` reads a recorded capture and the rest of the pipeline cannot
tell it apart from a live device.

## Things worth knowing before you write code

**Never validate a parser against hand-written sample lines.** A previous
iteration of this tool matched 0% of real device output for weeks, because the
tests used invented log lines that happened to contain a syslog hostname field
that real output does not have. Every parser test reads from a fixture captured
from an actual device.

**Never run under `-O` / `PYTHONOPTIMIZE`.** `pymobiledevice3`'s stream loop is
written as `assert await self.service.recvall(1) == b"\x02"`. Optimisation
strips `assert` statements *including the `await` inside them*, which
desynchronises the frame protocol and produces garbage instead of an error.
`OsTraceSource` raises when it is constructed. The check sits there rather than
at package import because it is a constraint of that one library — offline work
such as replaying a session or re-exporting a capture never touches it and is
not blocked by it.

**macOS is written blind.** The maintainer has no Mac. Every macOS-specific
assumption is marked `# UNVERIFIED-MACOS` in the source so it can be grepped and
confirmed by anyone who does. If you have one, checking those is genuinely the
most useful contribution available. The concrete rules — Qt menu roles,
`QFileDialog` filters, high-DPI, dark mode — are in the design notes under
[docs/](docs/).

**Do not use `QSortFilterProxyModel`.** Filtering 100k rows through it measures
around 6 seconds per filter change against 0.09 seconds for a direct predicate
over our own index list. See
[docs/adr/0004](docs/adr/0004-pyside6-with-custom-filtered-model.md).

## Licence headers

Every source file carries two lines, per the
[REUSE](https://reuse.software/spec/) convention:

```python
# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
```

The full licence text lives in `LICENSE` once, not repeated in every file.

## Commits and pull requests

- Conventional-ish subject lines (`fix:`, `feat:`, `docs:`, `refactor:`,
  `test:`, `ci:`). Not enforced by a hook; it just makes the changelog easier.
- One logical change per pull request.
- Update `CHANGELOG.md` under `## [Unreleased]` for anything user-visible.
- New behaviour comes with a test. Bug fixes come with the test that fails
  without the fix.

## Reporting a bug

Include the output of `ostrace doctor` once that exists; until then, your OS,
Python version, `ostrace --version`, device model and iOS version.

**Redact before you paste.** A capture can contain account identifiers, file
paths and anything an app decided to log.
