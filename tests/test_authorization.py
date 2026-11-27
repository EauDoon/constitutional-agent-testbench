"""Signed authorization decisions in the Consequence Rail v0.1 format."""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from constitutional_agent_testbench import _ed25519
from constitutional_agent_testbench import authorization as A
from constitutional_agent_testbench.cli import main
from constitutional_agent_testbench.common import load_json, parse_json_text

ROOT = Path(__file__).resolve().parents[1]
RAIL = ROOT / "examples" / "rail"
VECTORS = load_json(ROOT / "tests" / "fixtures" / "rail-authorization-vectors.json")
POLICY = load_json(RAIL / "refund-policy.json")
ACTION = load_json(RAIL / "refund-proposal.json")
OVER_LIMIT = load_json(RAIL / "refund-proposal-over-limit.json")
TRUST = load_json(RAIL / "trusted-keys.json")
ALLOW = load_json(RAIL / "refund-allow.decision.json")
DENY = load_json(RAIL / "refund-deny.decision.json")
INSIDE = "2026-11-28T02:31:00.000Z"
KEY_ID = VECTORS["authorizer"]["key_id"]
# The rail's deterministic demo authorizer key. Its seed is a public label, so
# the key is a published test key and never a secret.
DEMO_SEED = hashlib.sha256(
    b"consequence-rail/v0.1/authorization-decision-signing-key/not-a-secret").digest()

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
except ImportError:  # pragma: no cover - exercised on lanes without the extra
    Ed25519PrivateKey = None


def demo_private_pem() -> bytes:
    key = Ed25519PrivateKey.from_private_bytes(DEMO_SEED)
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


def run_cli(arguments: list[str]) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = main(arguments)
    return code, stdout.getvalue(), stderr.getvalue()


class Ed25519Tests(unittest.TestCase):
    """RFC 8032 section 7.1 vectors and malformed inputs."""

    VECTORS = (
        ("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
         "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
         "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
        ("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
         "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
         "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    )

    def test_rfc_vectors_verify(self) -> None:
        for public, message, signature in self.VECTORS:
            with self.subTest(public=public[:8]):
                self.assertTrue(_ed25519.verify(bytes.fromhex(public), bytes.fromhex(message),
                                                bytes.fromhex(signature)))

    def test_tampering_and_malformed_inputs_fail(self) -> None:
        public, message, signature = (bytes.fromhex(item) for item in self.VECTORS[1])
        flipped = bytearray(signature)
        flipped[5] ^= 1
        high_s = signature[:32] + (int.from_bytes(signature[32:], "little")
                                   + 2**252 + 27742317777372353535851937790883648493
                                   ).to_bytes(32, "little")
        cases = [
            (public, b"\x73", signature),
            (public, message, bytes(flipped)),
            (public, message, high_s),
            (public, message, signature[:63]),
            (public[:31], message, signature),
            (b"\xff" * 32, message, signature),
        ]
        for case in cases:
            with self.subTest(case=case[2][:4].hex()):
                self.assertFalse(_ed25519.verify(*case))

    def test_zero_x_point_decodes_only_with_a_clear_sign_bit(self) -> None:
        identity = (1).to_bytes(32, "little")
        self.assertIsNotNone(_ed25519._decode(identity))
        self.assertIsNone(_ed25519._decode((1 | 1 << 255).to_bytes(32, "little")))

    @unittest.skipIf(Ed25519PrivateKey is None, "needs the optional cryptography package")
    def test_agrees_with_openssl_on_random_messages(self) -> None:
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(serialization.Encoding.Raw,
                                               serialization.PublicFormat.Raw)
        for size in (0, 1, 31, 64, 1000):
            message = os.urandom(size)
            signature = key.sign(message)
            self.assertTrue(_ed25519.verify(public, message, signature))
            self.assertFalse(_ed25519.verify(public, message + b"x", signature))


class CanonicalJsonTests(unittest.TestCase):
    """The rail profile must reproduce Consequence Rail's bytes exactly."""

    def test_vectors_from_the_rail_implementation(self) -> None:
        for vector in VECTORS["canonical_vectors"]:
            value = parse_json_text(vector["json"])
            with self.subTest(json=vector["json"][:40]):
                self.assertEqual(A._write(value), vector["canonical"])
                raw = hashlib.sha256(vector["canonical"].encode("utf-8")).digest()
                self.assertEqual(base64.urlsafe_b64encode(raw).rstrip(b"=").decode(), vector["digest"])

    def test_action_digest_matches_the_rail(self) -> None:
        self.assertEqual(A.rail_digest(VECTORS["rail_signed_action"]), VECTORS["action_digest"])
        self.assertEqual(A.rail_digest(ACTION), VECTORS["action_digest"])

    def test_ecmascript_number_text(self) -> None:
        cases = {0.5: "0.5", -0.25: "-0.25", 1e21: "1e+21", 1.5e21: "1.5e+21", 1e-7: "1e-7",
                 1.25e-7: "1.25e-7", 0.000001: "0.000001", 123.456: "123.456",
                 1e20 + 0.0: "100000000000000000000", 5e-324: "5e-324", 7: "7", -0.0: "0"}
        for value, text in cases.items():
            with self.subTest(value=value):
                self.assertEqual(A._number_text(value), text)

    def test_keys_sort_by_utf16_code_unit(self) -> None:
        self.assertEqual(A.rail_canonical_json({"\uffff": 1, "\U0001f600": 2}),
                         '{"\U0001f600":2,"\uffff":1}')

    def test_values_the_digest_cannot_tell_apart_are_refused(self) -> None:
        for value in ({"a": 1.0}, {"a": -0.0}, {"a": 2**53}, {"a": [{"b": -(2**53)}]},
                      {"a": "\ud800"}, {"\udfff": 1}, {"a": float("nan")}, {"a": {1, 2}}):
            with self.subTest(value=repr(value)), self.assertRaises(A.AuthorizationInputError):
                A.rail_digest(value)
        self.assertEqual(A.rail_canonical_json({"a": 1e21, "b": 2**53 - 1, "c": 0.5}),
                         '{"a":1e+21,"b":9007199254740991,"c":0.5}')


class BuildAndVerifyTests(unittest.TestCase):
    def body(self, action=ACTION, **options):
        return A.build_authorization(POLICY, action, decided_at="2026-11-28T02:30:00.000Z", **options)

    def test_body_binds_action_policy_and_evaluation(self) -> None:
        body = self.body()
        self.assertTrue(body["allow"])
        self.assertEqual(body["action_digest"], VECTORS["action_digest"])
        self.assertEqual(body["evaluation_input_digest"], body["action_digest"])
        self.assertEqual(body["expires_at"], "2026-11-28T02:35:00.000Z")
        self.assertEqual(body["decision_id"], ALLOW["decision_id"])
        self.assertEqual(A._body_without(ALLOW, "signature"), body)
        self.assertFalse(self.body(OVER_LIMIT)["allow"])
        self.assertTrue(self.body(require_recovery_preflight=True)["require_recovery_preflight"])

    def test_invalid_build_options_fail_closed(self) -> None:
        bad = [
            dict(action=["not", "an", "object"]),
            dict(ttl_seconds=0), dict(ttl_seconds=86_401), dict(ttl_seconds=True), dict(ttl_seconds=1.5),
            dict(require_recovery_preflight="yes"),
        ]
        for options in bad:
            with self.subTest(options=options), self.assertRaises(A.AuthorizationInputError):
                self.body(**options)
        for decided_at in ("2026-11-28T02:30:00Z", "2026-02-30T00:00:00.000Z", 5):
            with self.subTest(decided_at=decided_at), self.assertRaises(A.AuthorizationInputError):
                A.build_authorization(POLICY, ACTION, decided_at=decided_at)
        with self.assertRaises(A.AuthorizationInputError):
            self.body({**ACTION, "parameters": {"amount_minor": 1.0, "currency": "USD"}})

    def test_shipped_decisions_verify_fully(self) -> None:
        for decision, action, allow in ((ALLOW, ACTION, True), (DENY, OVER_LIMIT, False)):
            with self.subTest(allow=allow):
                report = A.verify_authorization(decision, TRUST, action=action, policy=POLICY, now=INSIDE)
                self.assertTrue(report["verified"], report)
                self.assertIs(report["allow"], allow)
                self.assertEqual(report["mismatched_fields"], [])
                self.assertTrue(all(report["checks"].values()))

    def test_decision_signed_by_the_rail_verifies(self) -> None:
        trust = {"schema_version": A.TRUSTED_KEYS_SCHEMA_VERSION, "authorizer": [VECTORS["authorizer"]]}
        report = A.verify_authorization(VECTORS["rail_signed_decision"], trust,
                                        action=VECTORS["rail_signed_action"], now=INSIDE)
        self.assertTrue(report["verified"], report)
        self.assertIsNone(report["checks"]["recomputed"])

    def test_failed_bindings_are_reported(self) -> None:
        report = A.verify_authorization(ALLOW, TRUST, action=OVER_LIMIT, policy=POLICY,
                                        now="2026-11-28T02:35:00.000Z")
        self.assertFalse(report["verified"])
        self.assertEqual(report["checks"]["action_bound"], False)
        self.assertEqual(report["checks"]["within_validity"], False)
        self.assertIn("allow", report["mismatched_fields"])
        early = A.verify_authorization(ALLOW, TRUST, now="2026-11-28T02:29:59.999Z")
        self.assertFalse(early["checks"]["within_validity"])

    def test_tampered_fields_break_the_signature(self) -> None:
        for field, value in (("allow", False), ("policy_id", "other"),
                             ("require_recovery_preflight", True)):
            tampered = {**ALLOW, field: value}
            with self.subTest(field=field):
                report = A.verify_authorization(tampered, TRUST)
                self.assertFalse(report["verified"])
                self.assertFalse(report["checks"]["signature"])

    def test_keys_outside_the_authorizer_role_are_not_trusted(self) -> None:
        moved = {"schema_version": A.TRUSTED_KEYS_SCHEMA_VERSION, "rail": TRUST["authorizer"]}
        report = A.verify_authorization(ALLOW, moved)
        self.assertFalse(report["verified"])
        self.assertFalse(report["checks"]["trusted_key"])
        self.assertFalse(report["checks"]["signature"])

    def test_non_canonical_signature_encoding_fails(self) -> None:
        value = ALLOW["signature"]["value"]
        last = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_".index(value[-1])
        sibling = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"[last ^ 1]
        decision = copy.deepcopy(ALLOW)
        decision["signature"]["value"] = value[:-1] + sibling
        self.assertFalse(A.verify_authorization(decision, TRUST)["verified"])

    def test_malformed_decisions_and_key_sets_raise(self) -> None:
        def changed(**fields):
            return {**ALLOW, **fields}

        decisions = [
            [], {**ALLOW, "extra": 1}, changed(schema_version="v0"), changed(decision_id="authz_x"),
            changed(action_digest="hex"), changed(evaluation_digest=1), changed(allow="yes"),
            changed(policy_id=""), changed(expires_at=ALLOW["decided_at"]),
            changed(expires_at="2026-11-29T02:30:00.001Z"),
            changed(signature={"algorithm": "RS256", "key_id": KEY_ID, "value": "A" * 86}),
            changed(signature={**ALLOW["signature"], "key_id": "bad\u0007id"}),
        ]
        for decision in decisions:
            with self.subTest(decision=str(decision)[:60]), self.assertRaises(A.AuthorizationInputError):
                A.verify_authorization(decision, TRUST)
        entry = TRUST["authorizer"][0]
        key_sets = [
            {}, {"schema_version": A.TRUSTED_KEYS_SCHEMA_VERSION, "other": []},
            {"schema_version": A.TRUSTED_KEYS_SCHEMA_VERSION, "authorizer": {}},
            {"schema_version": A.TRUSTED_KEYS_SCHEMA_VERSION, "authorizer": [entry, entry]},
            {"schema_version": A.TRUSTED_KEYS_SCHEMA_VERSION, "authorizer": [{"key_id": "k"}]},
            {"schema_version": A.TRUSTED_KEYS_SCHEMA_VERSION,
             "authorizer": [{**entry, "public_key_pem": "not a key"}]},
            {"schema_version": A.TRUSTED_KEYS_SCHEMA_VERSION,
             "authorizer": [{**entry, "public_key_pem":
                             "-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----\n"}]},
            {"schema_version": A.TRUSTED_KEYS_SCHEMA_VERSION,
             "authorizer": [{**entry, "public_key_pem":
                             "-----BEGIN PUBLIC KEY-----\nA!==\n-----END PUBLIC KEY-----\n"}]},
        ]
        for key_set in key_sets:
            with self.subTest(key_set=str(key_set)[:60]), self.assertRaises(A.AuthorizationInputError):
                A.verify_authorization(ALLOW, key_set)
        with self.assertRaises(A.AuthorizationInputError):
            A.verify_authorization(ALLOW, TRUST, policy=POLICY)
        with self.assertRaises(A.AuthorizationInputError):
            A.verify_authorization(ALLOW, TRUST, now="yesterday")
        with self.assertRaises(A.AuthorizationInputError):
            A.authorization_signing_input([])

    def test_external_signer_path(self) -> None:
        body = self.body()
        message = A.authorization_signing_input(body)
        self.assertEqual(message, A.authorization_signing_input(ALLOW))
        signature = base64.urlsafe_b64decode(ALLOW["signature"]["value"] + "==")
        self.assertEqual(A.attach_signature(body, KEY_ID, signature), ALLOW)
        with self.assertRaises(A.AuthorizationInputError):
            A.attach_signature(body, KEY_ID, b"short")
        with self.assertRaises(A.AuthorizationInputError):
            A.attach_signature(body, "", signature)

    def test_timestamps_follow_date_to_iso_string(self) -> None:
        from datetime import datetime, timedelta, timezone

        moment = datetime(2026, 11, 28, 10, 30, 0, 123999, tzinfo=timezone(timedelta(hours=8)))
        self.assertEqual(A.format_timestamp(moment), "2026-11-28T02:30:00.123Z")
        with self.assertRaises(A.AuthorizationInputError):
            A.format_timestamp(datetime(2026, 11, 28))
        self.assertRegex(A.utc_now(), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")


class SigningTests(unittest.TestCase):
    def test_missing_backend_is_a_controlled_error(self) -> None:
        body = A.build_authorization(POLICY, ACTION, decided_at="2026-11-28T02:30:00.000Z")
        with patch.dict("sys.modules", {"cryptography": None,
                                        "cryptography.hazmat.primitives.asymmetric.ed25519": None}):
            with self.assertRaises(A.SigningUnavailableError):
                A.sign_authorization(body, "unused", KEY_ID)

    @unittest.skipIf(Ed25519PrivateKey is None, "needs the optional cryptography package")
    def test_signing_reproduces_the_shipped_decisions(self) -> None:
        for action, expected in ((ACTION, ALLOW), (OVER_LIMIT, DENY)):
            decision = A.create_authorization(
                POLICY, action, private_key_pem=demo_private_pem().decode("ascii"), key_id=KEY_ID,
                decided_at="2026-11-28T02:30:00.000Z")
            self.assertEqual(decision, expected)

    @unittest.skipIf(Ed25519PrivateKey is None, "needs the optional cryptography package")
    def test_wrong_keys_are_rejected_without_echoing_them(self) -> None:
        from cryptography.hazmat.primitives.asymmetric import ec

        body = A.build_authorization(POLICY, ACTION, decided_at="2026-11-28T02:30:00.000Z")
        other = ec.generate_private_key(ec.SECP256R1()).private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        for key in (b"-----BEGIN PRIVATE KEY-----\nnope\n-----END PRIVATE KEY-----\n", other):
            with self.subTest(key=key[:20]), self.assertRaises(A.AuthorizationInputError) as raised:
                A.sign_authorization(body, key, KEY_ID)
            self.assertNotIn("nope", str(raised.exception))


class CommandLineTests(unittest.TestCase):
    def test_verify_authorization_command(self) -> None:
        arguments = ["verify-authorization", str(RAIL / "refund-allow.decision.json"),
                     str(RAIL / "trusted-keys.json"), "--action", str(RAIL / "refund-proposal.json"),
                     "--policy", str(RAIL / "refund-policy.json"), "--now", INSIDE, "--strict-exit"]
        code, stdout, stderr = run_cli(arguments)
        self.assertEqual((code, stderr), (0, ""))
        self.assertTrue(json.loads(stdout)["verified"])
        late = arguments[:-3] + ["--now", "2026-11-28T03:00:00.000Z", "--strict-exit"]
        self.assertEqual(run_cli(late)[0], 1)
        # Without --now the current time applies, long after the example expired.
        self.assertEqual(run_cli(arguments[:3] + ["--strict-exit"])[0], 1)

    def test_verify_authorization_usage_errors(self) -> None:
        base = ["verify-authorization", str(RAIL / "refund-allow.decision.json"),
                str(RAIL / "trusted-keys.json")]
        for extra in (["--policy", str(RAIL / "refund-policy.json")], ["--action", "-", "--policy", "-"]):
            with self.subTest(extra=extra):
                code, _stdout, stderr = run_cli(base + extra)
                self.assertEqual(code, 2)
                self.assertEqual(json.loads(stderr)["error"]["code"], "INVALID_COMMAND")

    def test_authorize_needs_a_readable_key_file(self) -> None:
        base = ["authorize", str(RAIL / "refund-policy.json"), str(RAIL / "refund-proposal.json"),
                "--key-id", KEY_ID, "--private-key"]
        with tempfile.TemporaryDirectory() as folder:
            large = Path(folder) / "large.pem"
            large.write_bytes(b"x" * 20_000)
            for path, code in (("-", "INVALID_COMMAND"), (folder, "INVALID_JSON_INPUT"),
                               (str(large), "INVALID_JSON_INPUT")):
                with self.subTest(path=path):
                    status, _stdout, stderr = run_cli(base + [path])
                    self.assertEqual(status, 2)
                    self.assertEqual(json.loads(stderr)["error"]["code"], code)
            with patch("builtins.open", side_effect=PermissionError("denied")):
                status, _stdout, stderr = run_cli(base + [str(large)])
            self.assertEqual(json.loads(stderr)["error"]["code"], "INVALID_JSON_INPUT")
        status, _stdout, stderr = run_cli(["authorize", "-", "-", "--key-id", KEY_ID,
                                           "--private-key", str(RAIL / "refund-policy.json")])
        self.assertEqual((status, json.loads(stderr)["error"]["code"]), (2, "INVALID_COMMAND"))

    @unittest.skipIf(Ed25519PrivateKey is None, "needs the optional cryptography package")
    def test_authorize_command_signs_allow_and_deny(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            key = Path(folder) / "authorizer.pem"
            key.write_bytes(demo_private_pem())
            for action, expected, strict in (("refund-proposal.json", ALLOW, 0),
                                             ("refund-proposal-over-limit.json", DENY, 1)):
                arguments = ["authorize", str(RAIL / "refund-policy.json"), str(RAIL / action),
                             "--private-key", str(key), "--key-id", KEY_ID,
                             "--decided-at", "2026-11-28T02:30:00.000Z", "--strict-exit"]
                with self.subTest(action=action):
                    code, stdout, stderr = run_cli(arguments)
                    self.assertEqual((code, stderr), (strict, ""))
                    self.assertEqual(json.loads(stdout), expected)
                    self.assertNotIn("PRIVATE", stdout)
            code, stdout, _stderr = run_cli(arguments[:-3] + ["--ttl-seconds", "60",
                                                             "--require-recovery-preflight"])
            decision = json.loads(stdout)
            elapsed = (A._parse_timestamp(decision["expires_at"], "e")
                       - A._parse_timestamp(decision["decided_at"], "d"))
            self.assertEqual(elapsed.total_seconds(), 60)
            self.assertTrue(decision["require_recovery_preflight"])


if __name__ == "__main__":
    unittest.main()
