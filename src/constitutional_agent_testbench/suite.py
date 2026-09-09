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
REASON_CODES = {"RULE_SATISFIED", "FIELD_MISSING", "VALUE_NOT_EQUAL",
                "VALUE_NOT_ALLOWED", "VALUE_NOT_FALSE", "VALUE_NOT_EMPTY_LIST"}


def _validate_assertions(expected):
    if not isinstance(expected, dict):
        raise SuiteInputError("Expected rules must be an object of rule assertions.")
    for identifier, assertion in expected.items():
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", identifier)
                or not isinstance(assertion, dict) or set(assertion) != {"passed", "reason_code"}
                or type(assertion["passed"]) is not bool
                or not isinstance(assertion["reason_code"], str)
                or assertion["reason_code"] not in REASON_CODES
                or assertion["passed"] != (assertion["reason_code"] == "RULE_SATISFIED")):
            raise SuiteInputError("Rule assertions require valid IDs, boolean passed and a consistent reason code.")


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
    if suite["suite_version"] not in ("1.0", "1.1") or not isinstance(cases, list) or not 1 <= len(cases) <= MAX_SUITE_CASES:
        raise SuiteInputError("Suite version must be 1.0 or 1.1 with 1 to 256 cases.")
    seen = set()
    for case in cases:
        required = {"case_id", "response", "expected_passed"}
        allowed = required | ({"expected_rules"} if suite["suite_version"] == "1.1" else set())
        if not isinstance(case, dict) or not required <= set(case) <= allowed:
            raise SuiteInputError("Each case requires only case_id, response and expected_passed.")
        identifier = case["case_id"]
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", identifier) or identifier in seen:
            raise SuiteInputError("Case identifiers must be unique valid identifiers.")
        seen.add(identifier)
        if not isinstance(case["response"], dict) or type(case["expected_passed"]) is not bool:
            raise SuiteInputError("Each response must be an object and expected_passed a boolean.")
        if "expected_rules" in case:
            _validate_assertions(case["expected_rules"])
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
        if fixtures["suite_version"] == "1.1":
            actual = {row["rule_id"]: {"passed": row["passed"], "reason_code": row["reason_code"]}
                      for row in evaluation["rule_results"]}
            mismatches = sorted(identifier for identifier, expected in case.get("expected_rules", {}).items()
                                if actual.get(identifier) != expected)
            cases[-1]["rule_assertion_mismatches"] = mismatches
            cases[-1]["matches_expectation"] &= not mismatches
    return {"suite_version": fixtures["suite_version"], "policy_id": current.policy_id,
            "matches_expectations": all(case["matches_expectation"] for case in cases),
            "case_count": len(cases), "mismatch_count": sum(not case["matches_expectation"] for case in cases),
            "cases": cases}
