# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Sweep a capture for identifiers that must not be published.

This exists because a filter that looked right was scoped to the wrong thing.
It dropped records *emitted by* installed third-party applications and never
read the contents of what system daemons logged -- which is exactly where a
device's identifiers travel. `cloudd` logging an iCloud DSID, `wifid` logging
the BSSID of the access point in the room, `storekitd` logging the device UDID:
all system output, all filtered in, all published.

So this reads the contents, and its two halves answer different questions.

**The rules** answer "is a thing we already know about present?" They are what
CI gates the committed fixtures on, and they are cheap to state: a globally
unique MAC address, a UDID-shaped token, a DSID in an iCloud content URL, a
reverse-DNS bundle identifier that is not Apple's.

**The key/value rule** answers the more useful question: "is a high-entropy
value sitting next to a word that means it is a secret?" That one generalises.
Nobody had `x-apple-mmcs-auth` on a list -- it was found by looking at every
high-entropy token in the capture and asking what each one was, and the answer
turned out to be a capability token for the owner's iCloud storage. A rule that
keys on the *vocabulary of the field name* rather than on the value would have
caught it the first time, along with `X-CloudKit-DeviceID`, `X-Amz-Signature`,
`protectionInfoTag` and the upload receipts.

`--census` is the manual half: every high-entropy token in the capture, grouped
by the text that precedes it, for a human to classify before committing. It is
not a gate -- a real capture is full of legitimate opaque UUIDs -- but it is the
step that finds the category nobody thought of. Run it when regenerating
fixtures, and read it.

What this cannot do, stated plainly, because a gate whose limits are unwritten
gets trusted for things it never checked:

* **It cannot recognise a name.** An SSID is a word somebody chose; a device
  name is another. There is no shape to match. The tripwire for an SSID is that
  it travels next to a BSSID and a BSSID is a MAC, so the network rule fires
  and a human reads the line. Nothing covers a device name at all.
* **It only reads captures.** CI points it at the fixtures. It cannot see a
  real identifier pasted into a ``.py`` or a ``.md`` -- which has happened, in
  this repository, twice.
* **A digest written positionally has no key to key on.** ``chunk ==> <hex>``
  and ``mmcs put container 1:\\t<handle>`` both carry values of exactly the kind
  the key/value rule exists for, with no word in front of them. Both were found
  in the census, and only after somebody read past the top of it.
* **A colon-less MAC, a 40-hex legacy UDID and a bare device serial** have no
  rule, because every pattern that matches them also matches thousands of QUIC
  connection ids and inode numbers. The census is where they would surface.

Nothing here replaces reading a sample by eye.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ostrace.model import Record
from ostrace.storage.session import SessionReader
from ostrace.storage.spool import SpoolReader

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

#: Below this, a token is structured rather than random -- a path, a symbol name.
MIN_ENTROPY = 3.0

#: Shorter than this and a "secret" is not one, whatever it sits next to.
MIN_SECRET_LENGTH = 16

#: Tokens shorter than this are not worth a human's attention in the census.
#: 16 rather than 20 because the key/value rule's own floor is 16: anything
#: between the two would otherwise be invisible to both halves at once.
MIN_CENSUS_LENGTH = 16

#: A UUID repeated more often than this is not per-operation noise. It is a
#: stable identifier for *something*, and a human should say what. This is the
#: shape that hid a backup-snapshot id 947 records deep behind a `<redacted>`
#: that had already been written beside it.
UUID_REPEAT_THRESHOLD = 25

#: Placeholders. Apple writes the first; this project writes the second.
PLACEHOLDERS = frozenset({"<private>", "<redacted>", "(null)", "null", "nil", "none", ""})

#: Values a previous audit has already classified as safe to publish.
KNOWN_SYNTHETIC = frozenset(
    {
        "00008030-001A2B3C4D5E6F70",  # stand-in device UDID
        "10000000001",  # stand-in iCloud DSID
        "00000000-0000-4000-8000-000000000001",  # stand-in CloudKit account
        "00000000-0000-4000-8000-000000000002",  # stand-in backup snapshot id
        "00000000000000000000000000000001",  # stand-in container user id
        "redacted-ssid",
        # Apple's own sentinels, present verbatim in real captures. Listed so
        # that the next auditor does not have to re-derive that they are not
        # somebody's redaction: the persona family appears in five variants.
        "FEEDEEEE-DDDD-CCCC-BBBB-0000000001F5",
        "FEEDEEEE-DDDD-CCCC-BBBB-3333000001F5",
        "FEEDEEEE-DDDD-CCCC-BBBB-5555000001F5",
        "FFFFEEEE-DDDD-CCCC-BBBB-AAAA00000000",
        "FFFFEEEE-DDDD-CCCC-BBBB-AAAA000001F5",
    }
)

#: Reverse-DNS prefixes that say nothing about who owns the device.
#: ``vnd.com.apple`` covers Apple's own MIME types, which are shaped like
#: bundle identifiers and are not one.
BUNDLE_ALLOWED = ("com.apple", "apple.", "vnd.com.apple", "com.example")

#: A reverse-DNS identifier starts with one of these. Requiring it is what
#: keeps ``Capped.Headroom.Current`` and ``Location.PointOfInterest.Category``
#: -- dotted names that are not identifiers -- out of the results.
TLDS = (
    "com|org|net|io|co|dev|me|app|info|xyz|cloud|vnd|edu|gov|mil"
    "|uk|tr|de|fr|nl|jp|cn|ru|us|ca|au|se|no|fi|pl|es|it|br|in"
)

#: Field names whose value is, by the name's own admission, a secret or an id.
#: ``sig`` and ``ref`` earn their places separately from ``signature`` and
#: ``reference``: MMCS writes both spellings and the long one does not match
#: the short one. Both gaps were found by the census after the rules had been
#: written and had passed, which is the whole argument for having a census.
#: They are anchored to the end of the field name, so ``preference`` and
#: ``design`` do not match while ``mmcs-ref`` does.
SECRET_WORDS = (
    "auth",
    "token",
    "secret",
    "credential",
    "signature",
    "receipt",
    "digest",
    "checksum",
    "etag",
    "deviceid",
    "object-?id",
    "guid",
    "udid",
    "dsid",
    "sha[0-9]*",
    "apikey",
    "api-key",
    "passwd",
    "password",
)

#: Field names that must match exactly, or as the tail of a hyphenated name.
SECRET_WORDS_ANCHORED = ("sig", "ref")

_SECRET_KEY = re.compile(
    r"(?P<key>"
    r"[A-Za-z0-9_-]*(?:" + "|".join(SECRET_WORDS) + r")[A-Za-z0-9_-]*"
    r"|(?:[A-Za-z0-9]+-)*(?:" + "|".join(SECRET_WORDS_ANCHORED) + r")"
    r")"
    r"\s*[:=]\s*"
    r"(?P<value>[A-Za-z0-9+/=_-]{" + str(MIN_SECRET_LENGTH) + r",})",
    re.IGNORECASE,
)

_MAC = re.compile(r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f:])")
_UDID = re.compile(r"(?<![0-9A-Za-z-])[0-9A-Fa-f]{8}-[0-9A-Fa-f]{16}(?![0-9A-Za-z-])")
_DSID_URL = re.compile(r"icloud\.com[^\s\"']*?/content/(?P<dsid>\d{6,})")
_BUNDLE = re.compile(r"\b(?:" + TLDS + r")\.(?:[A-Za-z0-9_-]+\.)+[A-Za-z0-9_-]+\b", re.IGNORECASE)
_TOKEN = re.compile(rf"[A-Za-z0-9+/=_-]{{{MIN_CENSUS_LENGTH},}}")
_UUID = re.compile(r"^[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}$")
_ANY_UUID = re.compile(r"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}")
#: A DSID is 10-12 digits: too short for MIN_SECRET_LENGTH and too low-entropy
#: for MIN_ENTROPY, so the key/value rule can never see one. It needs its own.
_DSID_KEYED = re.compile(r"\b(?:alt)?dsid\b\s*[:=]\s*(?P<dsid>\d{6,})", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    """One thing in one record that should not be published."""

    rule: str
    value: str
    index: int
    process: str
    excerpt: str

    def __str__(self) -> str:
        return (
            f"  [{self.index}] {self.rule}: {self.value!r}\n        {self.process}: {self.excerpt}"
        )


def entropy(text: str) -> float:
    """Shannon entropy per character, in bits."""
    if not text:
        return 0.0
    counts = Counter(text)
    n = len(text)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def _is_prose(token: str) -> bool:
    """True for absolute paths and symbol names.

    Both clear the entropy floor comfortably -- mixed case and punctuation see
    to that -- and a capture is mostly made of them, so leaving them in buries
    the census in the thing it exists to surface. A path announces itself by
    its leading slash. A symbol name has no digits and none of base64's
    padding: an encoded secret essentially always has one or the other.
    """
    if token.startswith("/"):
        return True
    return not any(c.isdigit() for c in token) and "+" not in token and "=" not in token


def _excerpt(message: str, at: int, width: int = 90) -> str:
    start = max(0, at - width // 3)
    return message[start : start + width].replace("\n", " ")


def _is_locally_administered(mac: str) -> bool:
    """True for the 02:/06:/0a:/0e: ranges, which are not globally unique.

    A locally administered address is chosen by software and identifies no
    hardware, so it cannot be traced to a device or an access point.
    """
    return bool(int(mac[:2], 16) & 0b10)


def _searchable(record: Record) -> str:
    """Every field a value could hide in.

    ``subsystem`` and ``category`` were missing from this list, so nothing --
    neither the rules nor the census -- ever looked at them. They are the two
    fields a reader is least likely to check by eye, being short and repetitive
    and usually ``com.apple.something``.
    """
    parts = [
        record.message,
        record.process,
        record.process_path,
        record.image_path or "",
        record.subsystem or "",
        record.category or "",
    ]
    return "\n".join(parts)


def _check_network(text: str) -> Iterator[tuple[str, str, int]]:
    for match in _MAC.finditer(text):
        mac = match.group(0)
        if mac == "00:00:00:00:00:00" or _is_locally_administered(mac):
            continue
        yield (
            "globally-unique-mac",
            mac,
            match.start(),
        )


def _check_identifiers(text: str) -> Iterator[tuple[str, str, int]]:
    for match in _UDID.finditer(text):
        if match.group(0) not in KNOWN_SYNTHETIC:
            yield "device-udid", match.group(0), match.start()
    for match in _DSID_URL.finditer(text):
        if match.group("dsid") not in KNOWN_SYNTHETIC:
            yield "icloud-dsid", match.group("dsid"), match.start("dsid")
    for match in _DSID_KEYED.finditer(text):
        if match.group("dsid") not in KNOWN_SYNTHETIC:
            yield "icloud-dsid", match.group("dsid"), match.start("dsid")


def _check_secrets(text: str) -> Iterator[tuple[str, str, int]]:
    for match in _SECRET_KEY.finditer(text):
        value = match.group("value")
        if value.lower() in PLACEHOLDERS or value in KNOWN_SYNTHETIC:
            continue
        if entropy(value) < MIN_ENTROPY:
            continue
        yield f"secret-valued field {match.group('key')!r}", value, match.start("value")


def _check_bundles(text: str) -> Iterator[tuple[str, str, int]]:
    for match in _BUNDLE.finditer(text):
        token = match.group(0)
        if token.lower().startswith(BUNDLE_ALLOWED):
            continue
        # A dotted path or a file name is not a bundle identifier.
        if "/" in token or token.rsplit(".", 1)[-1].lower() in {
            "app",
            "framework",
            "plist",
            "db",
            "log",
            "py",
            "com",
            "xpc",
            "dylib",
        }:
            continue
        yield "third-party-bundle-id", token, match.start()


CHECKS = (_check_network, _check_identifiers, _check_secrets, _check_bundles)


def audit(records: Iterable[Record]) -> list[Finding]:
    """Every rule violation in the stream, in order."""
    findings: list[Finding] = []
    for index, record in enumerate(records):
        text = _searchable(record)
        for check in CHECKS:
            for rule, value, at in check(text):
                findings.append(Finding(rule, value, index, record.process, _excerpt(text, at)))
    return findings


def census(records: Iterable[Record]) -> dict[str, set[str]]:
    """High-entropy tokens grouped by the text that precedes them.

    Grouped by context rather than listed flat because that is how a human
    classifies them: forty tokens after ``protectionInfoTag=`` are one decision,
    not forty.

    Every searchable field, not just the message. An earlier version read only
    ``message``, which left ``subsystem``, ``category`` and both paths censused
    by nothing at all.
    """
    groups: dict[str, set[str]] = defaultdict(set)
    for record in records:
        text = _searchable(record)
        for match in _TOKEN.finditer(text):
            token = match.group(0)
            if token in KNOWN_SYNTHETIC or _UUID.match(token) or _is_prose(token):
                continue
            if entropy(token) < MIN_ENTROPY:
                continue
            before = text[max(0, match.start() - 34) : match.start()]
            groups[before.replace("\n", " ").strip() or "(line start)"].add(token)
    return groups


def repeated_uuids(records: Iterable[Record]) -> dict[str, int]:
    """UUIDs occurring more than :data:`UUID_REPEAT_THRESHOLD` times.

    The census drops UUIDs, and it is right to: a capture is full of them and
    a UUID seen once is a per-operation correlation value that means nothing
    off the device. A UUID seen *hundreds* of times is a different animal --
    it is a stable identifier for a thing the capture keeps referring to, and
    the human has to say what that thing is.

    This exists because the previous audit missed exactly one: a backup
    snapshot id, 947 occurrences, sitting inside a ``recordName=`` whose
    neighbouring digest had already been replaced with ``<redacted>``. Dropping
    it from the census meant it was never once offered for a decision.
    """
    counts: Counter[str] = Counter()
    for record in records:
        for match in _ANY_UUID.finditer(_searchable(record)):
            token = match.group(0)
            if token not in KNOWN_SYNTHETIC:
                counts[token] += 1
    return {u: n for u, n in counts.items() if n > UUID_REPEAT_THRESHOLD}


def read(path: Path) -> list[Record]:
    """Records from a session directory or a bare spool file."""
    reader = SessionReader(path).spool if path.is_dir() else SpoolReader(path)
    return [item for item in reader.items() if isinstance(item, Record)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="audit_capture",
        description="Sweep a capture for identifiers that must not be published.",
    )
    parser.add_argument("paths", nargs="+", type=Path, help="session directories or spool files")
    parser.add_argument(
        "--census",
        action="store_true",
        help="also list every high-entropy token, grouped by context, for classification",
    )
    args = parser.parse_args(argv)

    total = 0
    for path in args.paths:
        if not path.exists():
            print(f"{path}: no such capture", file=sys.stderr)
            return 2
        records = read(path)
        findings = audit(records)
        total += len(findings)
        status = f"{len(findings)} finding(s)" if findings else "clean"
        print(f"{path} -- {len(records)} records, {status}")
        for finding in findings:
            print(finding)
        if args.census:
            repeats = repeated_uuids(records)
            if repeats:
                print(
                    f"\n  UUIDs repeated more than {UUID_REPEAT_THRESHOLD} times "
                    f"-- stable identifiers, say what each one is:"
                )
                for uuid, count in sorted(repeats.items(), key=lambda kv: -kv[1]):
                    print(f"    {count:5d}x  {uuid}")
            groups = census(records)
            print(
                f"\n  census: {sum(len(v) for v in groups.values())} tokens "
                f"in {len(groups)} contexts. Read all of it -- the last two "
                f"findings were below the point somebody stopped scrolling."
            )
            for before, tokens in sorted(groups.items(), key=lambda kv: -len(kv[1])):
                sample = sorted(tokens)[0]
                print(f"    {len(tokens):5d}x  ...{before!r} -> {sample[:60]}")

    if total:
        print(
            f"\n{total} finding(s). Each is either something to redact or something to add "
            f"to KNOWN_SYNTHETIC in this file, with a comment saying why it is safe.",
            file=sys.stderr,
        )
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
