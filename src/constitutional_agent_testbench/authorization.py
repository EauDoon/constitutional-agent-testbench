"""Signed authorization decisions bound to one exact action.

A decision says whether one JSON action passed every rule of one policy. It
is signed with an authorizer's Ed25519 key over the exact action digest, so
an executor such as Consequence Rail can accept it only for that action,
only before it expires, and only under a key it trusts in the authorizer
role. The agent that proposes an action therefore cannot approve it.

The wire format is Consequence Rail's ``AuthorizationDecision`` v0.1. Every
digest uses the rail profile: SHA-256 over canonical JSON (keys sorted by
UTF-16 code unit, ECMAScript number text, ``JSON.stringify`` string escapes),
encoded as unpadded base64url. Testbench receipts keep their own
``sha256-canonical-json-v1`` hex digests; the two profiles are separate.

Verification uses only the standard library. Signing needs the optional
``cryptography`` package (``pip install constitutional-agent-testbench[signing]``)
or an external signer through :func:`authorization_signing_input` and
:func:`attach_signature`.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from . import _ed25519
from .common import (MAX_JSON_INPUT_BYTES, TestbenchError, bounded_canonical_json_size,
                     ensure_json_value)
from .evaluator import evaluate_response
from .policy import Policy, policy_to_dict, validate_policy

AUTHORIZATION_SCHEMA_VERSION = "consequence-rail/authorization-decision/v0.1"
TRUSTED_KEYS_SCHEMA_VERSION = "consequence-rail/trusted-keys/v0.1"
DIGEST_PROFILE = "sha256-rail-canonical-json-base64url"
#: The longest a decision may stay usable, matching the rail.
MAX_AUTHORIZATION_TTL_SECONDS = 86_400
DEFAULT_AUTHORIZATION_TTL_SECONDS = 300
#: The largest integer a JavaScript verifier reads without rounding.
MAX_SAFE_INTEGER = 2**53 - 1
MAX_KEYS_PER_ROLE = 32

DECISION_FIELDS = frozenset({
    "schema_version", "decision_id", "action_digest", "allow", "policy_id",
    "policy_digest", "evaluation_input_digest", "evaluation_digest",
    "require_recovery_preflight", "decided_at", "expires_at", "signature",
})
_SIGNATURE_FIELDS = frozenset({"algorithm", "key_id", "value"})
_DIGEST = re.compile(r"^[A-Za-z0-9_-]{43}$")
_SIGNATURE_VALUE = re.compile(r"^[A-Za-z0-9_-]{86}$")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_CONTROL = re.compile(r"[\u0000-\u001f\u007f-\u009f]")
_PEM = re.compile(
    r"^\s*-----BEGIN PUBLIC KEY-----\r?\n([A-Za-z0-9+/=\r\n]+)-----END PUBLIC KEY-----\s*$"
)
# DER prefix of an Ed25519 SubjectPublicKeyInfo: SEQUENCE, AlgorithmIdentifier
# 1.3.101.112, BIT STRING of 32 key bytes.
_ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")
_MAX_PEM_LENGTH = 4096


class AuthorizationInputError(TestbenchError):
    """Raised for a malformed decision, key set, timestamp or bindable value."""

    code = "INVALID_AUTHORIZATION"


class SigningUnavailableError(TestbenchError):
    """Raised when signing is requested without the optional signing backend."""

    code = "SIGNING_UNAVAILABLE"


# Canonical JSON, rail profile ------------------------------------------------

def _number_text(value: int | float) -> str:
    """ECMAScript Number::toString(10) for a finite double."""

    if isinstance(value, int):
        return str(value)
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    mantissa, _, exponent_text = repr(abs(value)).partition("e")
    whole, _, fraction = mantissa.partition(".")
    digits = whole + fraction
    point = len(whole) + (int(exponent_text) if exponent_text else 0)
    stripped = digits.lstrip("0")
    point -= len(digits) - len(stripped)
    digits = stripped.rstrip("0")
    k, n = len(digits), point
    if k <= n <= 21:
        text = digits + "0" * (n - k)
    elif 0 < n <= 21:
        text = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        text = "0." + "0" * -n + digits
    else:
        exponent = n - 1
        marker = "+" if exponent >= 0 else "-"
        head = digits if k == 1 else digits[0] + "." + digits[1:]
        text = f"{head}e{marker}{abs(exponent)}"
    return sign + text


_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f",
            "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _string_text(value: str) -> str:
    """``JSON.stringify`` escaping for a string without lone surrogates."""

    parts = ['"']
    for character in value:
        if character in _ESCAPES:
            parts.append(_ESCAPES[character])
        elif ord(character) < 0x20:
            parts.append(f"\\u{ord(character):04x}")
        else:
            parts.append(character)
    parts.append('"')
    return "".join(parts)


def _utf16_key(text: str) -> bytes:
    return text.encode("utf-16-be", "surrogatepass")


def _check_bindable(value: Any, label: str) -> None:
    """Refuse values whose rail digest could not tell two inputs apart.

    JavaScript reads ``1`` and ``1.0`` as one number, and ``0`` and ``-0.0``
    as one string, while the Testbench evaluator keeps them apart. Binding
    such a value would let two differently evaluated inputs share a digest.
    """

    try:
        ensure_json_value(value, label=label)
    except (TypeError, ValueError, RecursionError) as exc:
        raise AuthorizationInputError(f"{label} is not strict bounded JSON.") from exc
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, bool) or current is None:
            continue
        if isinstance(current, int):
            if abs(current) > MAX_SAFE_INTEGER:
                raise AuthorizationInputError(
                    f"{label} has an integer beyond 2**53 - 1, which a JavaScript verifier rounds.")
        elif isinstance(current, float):
            if (current.is_integer() and abs(current) <= MAX_SAFE_INTEGER) or (current == 0 and math.copysign(1.0, current) < 0):
                raise AuthorizationInputError(
                    f"{label} has a number such as 1.0 or -0.0 that the rail digest cannot "
                    "tell apart from an integer; write the integer form.")
        elif isinstance(current, str):
            if any(0xD800 <= ord(character) <= 0xDFFF for character in current):
                raise AuthorizationInputError(f"{label} has a lone surrogate.")
        elif isinstance(current, list):
            stack.extend(current)
        elif isinstance(current, dict):
            stack.extend(current)
            stack.extend(current.values())


def _write(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return _number_text(value)
    if isinstance(value, str):
        return _string_text(value)
    if isinstance(value, list):
        return "[" + ",".join(_write(item) for item in value) + "]"
    keys = sorted(value, key=_utf16_key)
    return "{" + ",".join(f"{_string_text(key)}:{_write(value[key])}" for key in keys) + "}"


def rail_canonical_json(value: Any) -> str:
    """Canonical JSON text in the Consequence Rail profile."""

    _check_bindable(value, "Value")
    return _write(value)


def rail_digest(value: Any) -> str:
    """SHA-256 of rail canonical JSON as 43 characters of unpadded base64url."""

    raw = hashlib.sha256(rail_canonical_json(value).encode("utf-8")).digest()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


# Timestamps ------------------------------------------------------------------

def _parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        raise AuthorizationInputError(
            f"{label} must be a UTC time such as 2026-11-28T02:30:00.000Z.")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise AuthorizationInputError(f"{label} is not a valid calendar time.") from exc
    return parsed.replace(tzinfo=timezone.utc)


def format_timestamp(moment: datetime) -> str:
    """Format an aware datetime as ``Date.toISOString()`` prints it."""

    if moment.tzinfo is None:
        raise AuthorizationInputError("Timestamps must carry a time zone.")
    utc = moment.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


def utc_now() -> str:
    """The current time in the decision timestamp format."""

    return format_timestamp(datetime.now(timezone.utc))


# Building and signing --------------------------------------------------------

def _body_without(decision: dict[str, Any], *fields: str) -> dict[str, Any]:
    return {key: value for key, value in decision.items() if key not in fields}


def _decision_id(body: dict[str, Any]) -> str:
    return "authz_" + rail_digest(_body_without(body, "decision_id", "signature"))[:20]


def build_authorization(
    policy: Policy | dict[str, Any],
    action: Any,
    *,
    decided_at: str,
    ttl_seconds: int = DEFAULT_AUTHORIZATION_TTL_SECONDS,
    require_recovery_preflight: bool = False,
) -> dict[str, Any]:
    """Evaluate ``action`` and return the unsigned decision body.

    ``allow`` is true only when every rule passes. The policy evaluates the
    action itself, so ``evaluation_input_digest`` equals ``action_digest``.
    Nothing here reads a clock: ``decided_at`` is explicit, so equal inputs
    give equal bodies.
    """

    current = validate_policy(policy)
    if not isinstance(action, dict):
        raise AuthorizationInputError("Action must be a JSON object.")
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not (
            1 <= ttl_seconds <= MAX_AUTHORIZATION_TTL_SECONDS):
        raise AuthorizationInputError(
            f"ttl_seconds must be an integer from 1 to {MAX_AUTHORIZATION_TTL_SECONDS}.")
    if not isinstance(require_recovery_preflight, bool):
        raise AuthorizationInputError("require_recovery_preflight must be a boolean.")
    decided = _parse_timestamp(decided_at, "decided_at")
    evaluation = evaluate_response(current, action)
    _check_bindable(action, "Action")
    policy_json = policy_to_dict(current)
    _check_bindable(policy_json, "Policy")
    action_digest = rail_digest(action)
    body: dict[str, Any] = {
        "schema_version": AUTHORIZATION_SCHEMA_VERSION,
        "action_digest": action_digest,
        "allow": evaluation["passed"],
        "policy_id": current.policy_id,
        "policy_digest": rail_digest(policy_json),
        "evaluation_input_digest": action_digest,
        "evaluation_digest": rail_digest(evaluation),
        "require_recovery_preflight": require_recovery_preflight,
        "decided_at": decided_at,
        "expires_at": format_timestamp(decided + timedelta(seconds=ttl_seconds)),
    }
    body["decision_id"] = _decision_id(body)
    return body


def authorization_signing_input(body: dict[str, Any]) -> bytes:
    """The exact bytes an authorizer key signs: canonical body without signature."""

    if not isinstance(body, dict):
        raise AuthorizationInputError("Decision body must be a JSON object.")
    return rail_canonical_json(_body_without(body, "signature")).encode("utf-8")


def _check_key_id(key_id: Any) -> str:
    if not isinstance(key_id, str) or not key_id or _CONTROL.search(key_id):
        raise AuthorizationInputError("key_id must be a non-empty string without control characters.")
    return key_id


def attach_signature(body: dict[str, Any], key_id: str, signature: bytes) -> dict[str, Any]:
    """Attach a raw 64-byte Ed25519 signature made by an external signer."""

    if not isinstance(signature, (bytes, bytearray)) or len(signature) != 64:
        raise AuthorizationInputError("An Ed25519 signature is exactly 64 bytes.")
    signed = _body_without(body, "signature")
    signed["signature"] = {
        "algorithm": "Ed25519",
        "key_id": _check_key_id(key_id),
        "value": base64.urlsafe_b64encode(bytes(signature)).rstrip(b"=").decode("ascii"),
    }
    _check_decision_shape(signed)
    return signed


def sign_authorization(body: dict[str, Any], private_key_pem: bytes | str, key_id: str) -> dict[str, Any]:
    """Sign a decision body with an unencrypted PKCS#8 Ed25519 private key.

    Uses the optional ``cryptography`` package, whose signing is constant
    time. Error messages never include key material.
    """

    _check_key_id(key_id)
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
    except ImportError as exc:
        raise SigningUnavailableError(
            "Signing needs the optional cryptography package: "
            "pip install 'constitutional-agent-testbench[signing]'.") from exc
    data = private_key_pem.encode("utf-8") if isinstance(private_key_pem, str) else private_key_pem
    try:
        key = load_pem_private_key(data, password=None)
    except (TypeError, ValueError) as exc:
        raise AuthorizationInputError(
            "Private key must be an unencrypted PKCS#8 PEM Ed25519 key.") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise AuthorizationInputError("Private key must be an Ed25519 key.")
    _check_decision_shape({**_body_without(body, "signature"), "signature": {
        "algorithm": "Ed25519", "key_id": key_id, "value": "A" * 86}})
    return attach_signature(body, key_id, key.sign(authorization_signing_input(body)))


def create_authorization(
    policy: Policy | dict[str, Any],
    action: Any,
    *,
    private_key_pem: bytes | str,
    key_id: str,
    decided_at: str,
    ttl_seconds: int = DEFAULT_AUTHORIZATION_TTL_SECONDS,
    require_recovery_preflight: bool = False,
) -> dict[str, Any]:
    """Evaluate one action and return its signed decision."""

    body = build_authorization(policy, action, decided_at=decided_at, ttl_seconds=ttl_seconds,
                               require_recovery_preflight=require_recovery_preflight)
    return sign_authorization(body, private_key_pem, key_id)


# Verification ----------------------------------------------------------------

def _check_decision_shape(decision: Any) -> tuple[datetime, datetime]:
    try:
        ensure_json_value(decision, label="Decision")
        bounded_canonical_json_size(decision, label="Decision", limit=MAX_JSON_INPUT_BYTES)
    except (TypeError, ValueError, RecursionError) as exc:
        raise AuthorizationInputError("Decision exceeds strict JSON limits.") from exc
    if not isinstance(decision, dict) or set(decision) != DECISION_FIELDS:
        raise AuthorizationInputError("Decision fields do not match AuthorizationDecision v0.1.")
    if decision["schema_version"] != AUTHORIZATION_SCHEMA_VERSION:
        raise AuthorizationInputError("Unsupported AuthorizationDecision schema version.")
    if not isinstance(decision["decision_id"], str) or not re.fullmatch(
            r"authz_[A-Za-z0-9_-]{20}", decision["decision_id"]):
        raise AuthorizationInputError("decision_id must be authz_ plus 20 base64url characters.")
    for field in ("action_digest", "policy_digest"):
        if not isinstance(decision[field], str) or not _DIGEST.fullmatch(decision[field]):
            raise AuthorizationInputError(f"{field} must be a 43-character base64url digest.")
    for field in ("evaluation_input_digest", "evaluation_digest"):
        value = decision[field]
        if value is not None and (not isinstance(value, str) or not _DIGEST.fullmatch(value)):
            raise AuthorizationInputError(f"{field} must be a digest or null.")
    if not isinstance(decision["allow"], bool) or not isinstance(
            decision["require_recovery_preflight"], bool):
        raise AuthorizationInputError("allow and require_recovery_preflight must be booleans.")
    if not isinstance(decision["policy_id"], str) or not decision["policy_id"]:
        raise AuthorizationInputError("policy_id must be a non-empty string.")
    decided = _parse_timestamp(decision["decided_at"], "decided_at")
    expires = _parse_timestamp(decision["expires_at"], "expires_at")
    if not decided < expires <= decided + timedelta(seconds=MAX_AUTHORIZATION_TTL_SECONDS):
        raise AuthorizationInputError(
            f"expires_at must be after decided_at and within {MAX_AUTHORIZATION_TTL_SECONDS} seconds.")
    signature = decision["signature"]
    if (not isinstance(signature, dict) or set(signature) != _SIGNATURE_FIELDS
            or signature["algorithm"] != "Ed25519"
            or not isinstance(signature["value"], str)
            or not _SIGNATURE_VALUE.fullmatch(signature["value"])):
        raise AuthorizationInputError("signature must be {algorithm: Ed25519, key_id, value}.")
    _check_key_id(signature["key_id"])
    return decided, expires


def _public_key_bytes(text: Any) -> bytes:
    match = _PEM.fullmatch(text) if isinstance(text, str) and len(text) <= _MAX_PEM_LENGTH else None
    if match is None:
        raise AuthorizationInputError("Each public_key_pem must be one Ed25519 SPKI PEM block.")
    try:
        der = base64.b64decode("".join(match.group(1).split()), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AuthorizationInputError("Each public_key_pem must be one Ed25519 SPKI PEM block.") from exc
    if len(der) != 44 or not der.startswith(_ED25519_SPKI_PREFIX):
        raise AuthorizationInputError("Each public_key_pem must be one Ed25519 SPKI PEM block.")
    return der[12:]


def trusted_authorizers(document: Any) -> dict[str, bytes]:
    """Read the ``authorizer`` role of a Consequence Rail trusted-keys document.

    Keys in the other roles (rail, connector, recovery) are never accepted
    for a decision, so a rail or connector key cannot approve an action.
    """

    if not isinstance(document, dict) or document.get("schema_version") != TRUSTED_KEYS_SCHEMA_VERSION:
        raise AuthorizationInputError(
            f"Trusted keys must be a {TRUSTED_KEYS_SCHEMA_VERSION} document.")
    allowed = {"schema_version", "rail", "connector", "recovery", "authorizer"}
    if set(document) - allowed:
        raise AuthorizationInputError("Trusted keys document has an unsupported field.")
    entries = document.get("authorizer", [])
    if not isinstance(entries, list) or len(entries) > MAX_KEYS_PER_ROLE:
        raise AuthorizationInputError(
            f"Trusted keys authorizer must be an array of at most {MAX_KEYS_PER_ROLE} keys.")
    keys: dict[str, bytes] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"key_id", "public_key_pem"}:
            raise AuthorizationInputError("Each authorizer key needs exactly key_id and public_key_pem.")
        key_id = _check_key_id(entry["key_id"])
        if key_id in keys:
            raise AuthorizationInputError("Authorizer key_id values must be unique.")
        keys[key_id] = _public_key_bytes(entry["public_key_pem"])
    return keys


def verify_authorization(
    decision: Any,
    trusted_keys: Any,
    *,
    action: Any = None,
    policy: Policy | dict[str, Any] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Check a decision's signature, binding, validity and, optionally, its evaluation.

    ``trusted_keys`` is a rail trusted-keys document; only its authorizer
    role counts. With ``action``, the decision must be bound to that action.
    With ``now``, it must be decided at or before and expire after it. With
    both ``policy`` and ``action``, the evaluation is recomputed and every
    bound field must match. Checks not requested report ``null``.
    """

    decided, expires = _check_decision_shape(decision)
    keys = trusted_authorizers(trusted_keys)
    key_id = decision["signature"]["key_id"]
    trusted = key_id in keys
    signature = base64.urlsafe_b64decode(decision["signature"]["value"] + "==")
    canonical_encoding = (
        base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii") == decision["signature"]["value"])
    signature_valid = trusted and canonical_encoding and _ed25519.verify(
        keys[key_id], authorization_signing_input(decision), signature)
    checks: dict[str, bool | None] = {
        "trusted_key": trusted,
        "signature": signature_valid,
        "decision_id": decision["decision_id"] == _decision_id(decision),
        "action_bound": None,
        "within_validity": None,
        "recomputed": None,
    }
    mismatched: list[str] = []
    if action is not None:
        checks["action_bound"] = rail_digest(action) == decision["action_digest"]
    if now is not None:
        moment = _parse_timestamp(now, "now")
        checks["within_validity"] = decided <= moment < expires
    if policy is not None:
        if action is None:
            raise AuthorizationInputError("Recomputing a decision needs the action as well as the policy.")
        expected = build_authorization(
            policy, action, decided_at=decision["decided_at"],
            ttl_seconds=1,
            require_recovery_preflight=decision["require_recovery_preflight"])
        mismatched = sorted(field for field in (
            "action_digest", "allow", "policy_id", "policy_digest",
            "evaluation_input_digest", "evaluation_digest")
            if expected[field] != decision[field])
        checks["recomputed"] = not mismatched
    return {
        "verified": all(value is not False for value in checks.values()),
        "allow": decision["allow"],
        "checks": checks,
        "decision_id": decision["decision_id"],
        "key_id": key_id,
        "mismatched_fields": mismatched,
        "verification_scope": (
            "signature under a trusted authorizer key and the requested bindings; "
            "a verified decision proves who decided, not that the policy is sufficient"),
    }
