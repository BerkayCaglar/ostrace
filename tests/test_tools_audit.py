# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The privacy gate on the committed fixtures, and the rules behind it.

The first test here is the one that matters: it is the same check CI runs, and
it is what stops a regenerated fixture reintroducing what an audit already took
out. The rest pin the individual rules, using synthetic values -- a test for a
leak detector must not itself contain a leak.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.helpers import ERRORS, MIXED, committed_captures, make_record

if TYPE_CHECKING:
    from types import ModuleType


def _load_tool() -> ModuleType:
    """Import ``tools/audit_capture.py`` without putting tools/ on sys.path.

    It is a command-line utility rather than a package module, so there is no
    import path to it. Loading it by location keeps it that way.
    """
    path = Path(__file__).resolve().parents[1] / "tools" / "audit_capture.py"
    spec = importlib.util.spec_from_file_location("audit_capture", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before execution: @dataclass resolves annotations through
    # ``sys.modules[cls.__module__]``, which is None until the name is bound.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


audit_capture = _load_tool()


@pytest.mark.parametrize(
    "fixture", committed_captures(), ids=lambda path: path.name.removesuffix(".jsonl.gz")
)
def test_the_committed_fixtures_carry_no_device_identifiers(fixture: Path) -> None:
    """The gate. If this fails, something is about to be published that should not be.

    A finding is not automatically a bug in the fixture -- it may be a value
    that is genuinely safe -- but it is always a decision for a human, recorded
    either as a redaction or as an entry in ``KNOWN_SYNTHETIC`` with a reason.

    Parametrised over what is *there*, not over a list. Both this and the CI
    step named the first two fixtures by hand, so the third would have been
    published unchecked by either.
    """
    findings = audit_capture.audit(audit_capture.read(fixture))
    assert findings == [], "\n" + "\n".join(str(f) for f in findings)


def test_the_gate_is_looking_at_something() -> None:
    """A gate that finds nothing to check passes, and means nothing.

    ``release.yml`` already says this in shell -- an empty glob is an error
    there rather than a green step -- and the reason is the same here: the
    discovery above turns a missing directory, a renamed suffix or a moved
    ``tests/`` into a silent pass with no fixtures audited at all.
    """
    found = {path.name for path in committed_captures()}

    assert {MIXED.name, ERRORS.name} <= found, "the known fixtures are not being audited"


class TestTheRulesCatchWhatTheyClaimTo:
    """Each rule against a synthetic value of the kind it exists to find."""

    def test_a_globally_unique_mac_is_a_finding(self) -> None:
        """``00:00:5E:00:53:xx`` is IANA's documentation range (RFC 7042).

        Globally unique as far as the rule is concerned -- the locally
        administered bit is clear, which is what it tests -- while belonging to
        nobody. Any other globally unique address would be somebody's.
        """
        record = make_record(
            message="CurrentBSS {a-network-name - 00:00:5E:00:53:01} {-49 dbm}",
            process="wifid",
        )
        findings = audit_capture.audit([record])
        assert [f.rule for f in findings] == ["globally-unique-mac"]

    def test_a_locally_administered_mac_is_not(self) -> None:
        """02:/06:/0a:/0e: are software-chosen and identify no hardware."""
        record = make_record(message="CurrentBSS {x - 02:00:5e:10:00:01}", process="wifid")
        assert audit_capture.audit([record]) == []

    def test_an_all_zero_mac_is_not(self) -> None:
        record = make_record(message="LQM-WiFi: TX(00:00:00:00:00:00) AC<SU>", process="wifid")
        assert audit_capture.audit([record]) == []

    def test_a_udid_shaped_token_is_a_finding(self) -> None:
        record = make_record(message="guid=00001111-2222333344445555&status=1")
        assert [f.rule for f in audit_capture.audit([record])] == ["device-udid"]

    def test_a_dsid_in_an_icloud_content_url_is_a_finding(self) -> None:
        record = make_record(message="URL: https://gateway.icloud.com:443/content/12345678901/put")
        assert [f.rule for f in audit_capture.audit([record])] == ["icloud-dsid"]

    def test_a_high_entropy_value_under_a_secret_field_name_is_a_finding(self) -> None:
        """The rule that generalises: it keys on the field name, not the value.

        Nothing had ``x-apple-mmcs-auth`` on a list of known-bad strings. What
        gives it away is a random-looking value sitting under a name that says
        it is a credential.
        """
        record = make_record(message="RequestHeader (x-apple-mmcs-auth:pJ2vQ8xLm4Nc7Ht0Wf3Zy6Bd)")
        rules = [f.rule for f in audit_capture.audit([record])]
        assert rules == ["secret-valued field 'x-apple-mmcs-auth'"]

    def test_the_abbreviated_spelling_is_caught_too(self) -> None:
        """``sig:`` and ``signature:`` are the same field; MMCS writes both."""
        record = make_record(message="expiry:08/09/2026 sig: 0123456789abcdef0123456789abcdef")
        assert [f.rule for f in audit_capture.audit([record])] == ["secret-valued field 'sig'"]

    def test_the_short_spellings_are_anchored(self) -> None:
        """``ref`` must not turn every ``preference:`` into a finding.

        The short names are matched only whole, or as the tail of a hyphenated
        name -- otherwise the vocabulary that makes this rule useful is also
        what makes it unusable.
        """
        record = make_record(message="preference: aGVsbG8gdGhlcmUgZnJpZW5kcw and more")
        assert audit_capture.audit([record]) == []

    def test_but_a_hyphenated_tail_still_matches(self) -> None:
        record = make_record(message="x-apple-mmcs-ref: fedcba9876543210fedcba9876543210")
        assert [f.rule for f in audit_capture.audit([record])] == [
            "secret-valued field 'x-apple-mmcs-ref'"
        ]

    def test_a_redacted_value_is_not_a_finding(self) -> None:
        record = make_record(message="RequestHeader (x-apple-mmcs-auth:<redacted>)")
        assert audit_capture.audit([record]) == []

    def test_apples_own_private_marker_is_not_a_finding(self) -> None:
        record = make_record(message="credentialForAccount is returning <private>")
        assert audit_capture.audit([record]) == []

    def test_a_third_party_bundle_id_is_a_finding(self) -> None:
        record = make_record(message="Checking for messages for com.somevendor.someapp")
        assert [f.rule for f in audit_capture.audit([record])] == ["third-party-bundle-id"]

    def test_an_apple_bundle_id_is_not(self) -> None:
        record = make_record(message="app<com.apple.springboard> asked for com.apple.Preferences")
        assert audit_capture.audit([record]) == []

    def test_a_dotted_name_that_is_not_an_identifier_is_not(self) -> None:
        """``Capped.Headroom.Current`` is a metric, not a bundle id."""
        record = make_record(message="HDR.State=Engaged | Capped.Headroom.Current=1.200")
        assert audit_capture.audit([record]) == []

    def test_an_apple_mime_type_is_not(self) -> None:
        record = make_record(message='"Content-Type" = ("application/vnd.com.apple.me.mmcs+proto")')
        assert audit_capture.audit([record]) == []


class TestTheCensus:
    """The half that finds the category nobody thought of."""

    def test_it_groups_tokens_by_what_precedes_them(self) -> None:
        records = [
            make_record(message="uploading w/newfangledtag: 7Kq2Vx9Lp4Rm8Ts1Wn6Yc3Bf5Gd0Hj"),
            make_record(message="uploading w/newfangledtag: 4Nz8Kt2Qw7Vb1Xs9Lp3Mc6Rf0Yd5Hg"),
        ]
        groups = audit_capture.census(records)
        assert any("newfangledtag" in context for context in groups)
        assert sum(len(v) for v in groups.values()) == 2

    def test_a_uuid_is_not_worth_a_humans_attention(self) -> None:
        """A capture is full of them and they mean nothing off the device."""
        record = make_record(message="requestUUID:11111111-2222-4333-8444-555555555555")
        assert audit_capture.census([record]) == {}

    def test_it_reads_every_field_not_just_the_message(self) -> None:
        """An earlier version censused ``message`` alone, so a token in a
        subsystem, a category or a path was seen by nothing at all."""
        record = make_record(message="nothing here")
        record = dataclasses.replace(record, category="Kx7Vn2Mq8Rw4Zt6Yb1Pd")
        assert audit_capture.census([record]) != {}

    def test_a_path_is_not(self) -> None:
        """Paths clear the entropy floor easily, and a capture is mostly paths."""
        record = make_record(message="/System/Library/PrivateFrameworks/CloudKitDaemon.framework")
        assert audit_capture.census([record]) == {}

    def test_a_symbol_name_is_not(self) -> None:
        record = make_record(message="boringssl_context_set_encryption_secrets_block_invoke")
        assert audit_capture.census([record]) == {}

    def test_but_an_encoded_secret_still_is(self) -> None:
        """The exclusions must not swallow the thing the census is for."""
        record = make_record(message="x-apple-mmcs-auth:Zm9vYmFyMTIzNDU2Nzg5MHF3ZXJ0eXVpb3A")
        assert audit_capture.census([record]) != {}


class TestRepeatedUuids:
    """A UUID seen once is noise. A UUID seen hundreds of times is an identifier."""

    def test_a_uuid_repeated_past_the_threshold_is_reported(self) -> None:
        """The shape that hid a backup snapshot id 947 records deep."""
        uuid = "AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE"
        records = [
            make_record(message=f"recordName=A:adaf:{uuid}:<redacted>:{i}")
            for i in range(audit_capture.UUID_REPEAT_THRESHOLD + 1)
        ]
        assert audit_capture.repeated_uuids(records) == {
            uuid: audit_capture.UUID_REPEAT_THRESHOLD + 1
        }

    def test_a_uuid_below_it_is_not(self) -> None:
        record = make_record(message="requestUUID:11111111-2222-4333-8444-555555555555")
        assert audit_capture.repeated_uuids([record]) == {}

    def test_a_known_synthetic_uuid_is_never_reported(self) -> None:
        """Including Apple's own sentinels, which recur in every real capture."""
        uuid = "FEEDEEEE-DDDD-CCCC-BBBB-0000000001F5"
        records = [
            make_record(message=f"currentPersona=Personal({uuid})")
            for _ in range(audit_capture.UUID_REPEAT_THRESHOLD + 5)
        ]
        assert audit_capture.repeated_uuids(records) == {}


def test_a_dsid_outside_a_url_is_a_finding() -> None:
    """A DSID is 10-12 digits: too short and too low-entropy for the key/value
    rule's floors, so it needs a rule of its own or it is invisible."""
    record = make_record(message="Match by altDSID - altDSID: 12345678902")
    assert [f.rule for f in audit_capture.audit([record])] == ["icloud-dsid"]


def test_the_tool_exits_non_zero_when_it_finds_something(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The exit code is the whole point of running it in CI."""
    from ostrace.storage.spool import SpoolWriter

    spool = tmp_path / "dirty.jsonl.gz"
    with SpoolWriter(spool) as writer:
        writer.write(make_record(message="guid=00001111-2222333344445555"))
    assert audit_capture.main([str(spool)]) == 1
    assert "device-udid" in capsys.readouterr().out


def test_the_tool_exits_zero_on_a_clean_capture(tmp_path: Path) -> None:
    from ostrace.storage.spool import SpoolWriter

    spool = tmp_path / "clean.jsonl.gz"
    with SpoolWriter(spool) as writer:
        writer.write(make_record(message="nothing to see here"))
    assert audit_capture.main([str(spool)]) == 0
