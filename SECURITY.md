# Security Policy

## Supported versions

`ostrace` is pre-1.0. Only the latest release receives fixes.

## Reporting a vulnerability

Please report security issues through
[GitHub Private Vulnerability Reporting](https://github.com/BerkayCaglar/ostrace/security/advisories/new)
rather than opening a public issue.

Expect an acknowledgement within seven days. This is a solo, unfunded project,
so please read that as a good-faith target and not an SLA.

## What is in scope

`ostrace` reads logs from an iOS device you already control and writes them to
disk. The interesting risks are therefore about *data*, not remote code
execution:

- **Log contents are sensitive.** A capture can contain account identifiers,
  file paths, network endpoints and anything an app chose to log. Bugs that
  cause `ostrace` to write a capture somewhere unexpected, or to include data a
  user asked it to redact, are in scope.
- **Path handling.** Process names, image paths and subsystems come from the
  device and are attacker-influenceable in the sense that any installed app can
  choose them. Anything that lets those values escape a chosen output directory
  is in scope.
- **Export rendering.** Report generators must not let a crafted log message
  break out of the format it is being rendered into.

## What is out of scope

- Vulnerabilities in `pymobiledevice3` itself — report those
  [upstream](https://github.com/doronz88/pymobiledevice3/security).
- The fact that captured logs contain private data. That is the purpose of the
  tool; `<private>` redaction is applied by iOS before the data ever reaches us.
- Anything requiring physical access to an already-unlocked, already-paired
  device — that is the trust model of USB device pairing, not a defect here.
