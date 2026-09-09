"""Bounded, explicit regression fixtures for local policy evaluation."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from .common import (MAX_JSON_INPUT_BYTES, TestbenchError,
                     bounded_canonical_json_size, ensure_json_value)
from .evaluator import evaluate_response
from .policy import Policy, policy_to_dict, validate_policy

MAX_SUITE_CASES = 256
MAX_SUITE_POLICY_BYTES = 32_000_000


class SuiteInputError(TestbenchError):
    code = "INVALID_SUITE"


def validate_suite(suite: Any) -> dict[str, Any]:
    """Return an owned copy of a strict 1.0 fixture suite."""
    try:
        ensure_json_value(suite, label="Suite")
        bounded_canonical_json_size(suite, label="Suite", limit=MAX_JSON_INPUT_BYTES)
    except (TypeError, ValueError, RecursionError) as exc:
        raise SuiteInputError("Suite exceeds strict JSON limits.") from exc
    if not isinstance(suite, dict) or set(suite) != {"suite_version", "cases"}:
        raise SuiteInputError("Suite requires only suite_version and cases.")
    cases = suite["cases"]
    if suite["suite_version"] != "1.0" or not isinstance(cases, list) or not 1 <= len(cases) <= MAX_SUITE_CASES:
        raise SuiteInputError("Suite version must be 1.0 with 1 to 256 cases.")
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"case_id", "response", "expected_passed"}:
            raise SuiteInputError("Each case requires only case_id, response and expected_passed.")
        identifier = case["case_id"]
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", identifier) or identifier in seen:
            raise SuiteInputError("Case identifiers must be unique valid identifiers.")
        seen.add(identifier)
        if not isinstance(case["response"], dict) or type(case["expected_passed"]) is not bool:
            raise SuiteInputError("Each response must be an object and expected_passed a boolean.")
    return deepcopy(suite)


def evaluate_suite(policy: Policy | dict[str, Any], suite: Any) -> dict[str, Any]:
    """Evaluate all cases; expectation failures remain distinct from nonconformance."""
    current = validate_policy(policy)
    fixtures = validate_suite(suite)
    size = bounded_canonical_json_size(policy_to_dict(current), label="Policy", limit=MAX_JSON_INPUT_BYTES)
    if size * len(fixtures["cases"]) > MAX_SUITE_POLICY_BYTES:
        raise SuiteInputError("Suite policy evaluation work exceeds the 32,000,000-byte limit.")
    cases = []
    for case in fixtures["cases"]:
        evaluation = evaluate_response(current, case["response"])
        cases.append({"case_id": case["case_id"], "expected_passed": case["expected_passed"],
                      "matches_expectation": evaluation["passed"] == case["expected_passed"],
                      "evaluation": evaluation})
    return {"suite_version": "1.0", "policy_id": current.policy_id,
            "matches_expectations": all(case["matches_expectation"] for case in cases),
            "case_count": len(cases), "mismatch_count": sum(not case["matches_expectation"] for case in cases),
            "cases": cases}
