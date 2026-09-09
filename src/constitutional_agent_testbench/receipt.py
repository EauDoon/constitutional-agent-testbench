"""Recomputable digest-bound receipts, without signatures or trusted timestamps."""

import hashlib
import re
from typing import Any

from .common import (MAX_JSON_INPUT_BYTES, TestbenchError, bounded_canonical_json_size,
                     canonical_json, ensure_json_value, stable_json)
from .evaluator import evaluate_response
from .policy import Policy, policy_to_dict, validate_policy


class ReceiptInputError(TestbenchError):
    code = "INVALID_RECEIPT"


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def create_receipt(policy: Policy | dict[str, Any], response: Any) -> dict[str, Any]:
    """Bind a validated policy and response to their recomputable evaluation."""
    current = validate_policy(policy)
    evaluation = evaluate_response(current, response)
    result = {"receipt_version": "1.0", "digest_algorithm": "sha256-canonical-json-v1",
            "policy_digest": _digest(policy_to_dict(current)), "response_digest": _digest(response),
            "evaluation": evaluation}
    try:
        bounded_canonical_json_size(result, label="Receipt", limit=MAX_JSON_INPUT_BYTES)
        if len(stable_json(result).encode("utf-8")) > MAX_JSON_INPUT_BYTES:
            raise ValueError("Formatted receipt is too large.")
    except ValueError as exc:
        raise ReceiptInputError("Receipt output exceeds the 1,000,000-byte limit.") from exc
    return result


def verify_receipt(policy: Policy | dict[str, Any], response: Any, receipt: Any) -> dict[str, Any]:
    """Recompute every binding. A successful result proves consistency, not authorship."""
    try:
        ensure_json_value(receipt, label="Receipt")
        bounded_canonical_json_size(receipt, label="Receipt", limit=MAX_JSON_INPUT_BYTES)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ReceiptInputError("Receipt exceeds strict JSON limits.") from exc
    keys = {"receipt_version", "digest_algorithm", "policy_digest", "response_digest", "evaluation"}
    if not isinstance(receipt, dict) or set(receipt) != keys:
        raise ReceiptInputError("Receipt fields do not match version 1.0.")
    if receipt["receipt_version"] != "1.0" or receipt["digest_algorithm"] != "sha256-canonical-json-v1":
        raise ReceiptInputError("Receipt version or digest algorithm is unsupported.")
    for key in ("policy_digest", "response_digest"):
        if not isinstance(receipt[key], str) or not re.fullmatch(r"[0-9a-f]{64}", receipt[key]):
            raise ReceiptInputError("Receipt digest must be lowercase SHA-256 hex.")
    expected = create_receipt(policy, response)
    mismatches = sorted(key for key in keys if canonical_json(receipt[key]) != canonical_json(expected[key]))
    return {"verified": not mismatches, "mismatched_fields": mismatches,
            "verification_scope": "recomputed input and evaluation consistency; no authenticity claim"}
