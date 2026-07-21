"""Deterministic response evaluation with stable reason codes."""

from __future__ import annotations

from typing import Any

from .common import TestbenchError, ensure_json_value, get_field, json_values_equal
from .policy import Policy, Rule, validate_policy


class EvaluationInputError(TestbenchError):
    """Raised when a candidate response is not a JSON object."""

    code = "INVALID_RESPONSE"


REASON_SATISFIED = "RULE_SATISFIED"
REASON_MISSING = "FIELD_MISSING"
REASON_NOT_EQUAL = "VALUE_NOT_EQUAL"
REASON_NOT_ALLOWED = "VALUE_NOT_ALLOWED"
REASON_NOT_FALSE = "VALUE_NOT_FALSE"
REASON_NOT_EMPTY_LIST = "VALUE_NOT_EMPTY_LIST"


def _evaluate_rule(rule: Rule, response: dict[str, Any]) -> dict[str, Any]:
    found, observed = get_field(response, rule.path)
    if not found:
        passed = False
        reason_code = REASON_MISSING
    elif rule.kind == "required_field":
        passed = True
        reason_code = REASON_SATISFIED
    elif rule.kind == "equals":
        passed = json_values_equal(observed, rule.value)
        reason_code = REASON_SATISFIED if passed else REASON_NOT_EQUAL
    elif rule.kind == "one_of":
        passed = any(json_values_equal(observed, value) for value in rule.values)
        reason_code = REASON_SATISFIED if passed else REASON_NOT_ALLOWED
    elif rule.kind == "false":
        passed = observed is False
        reason_code = REASON_SATISFIED if passed else REASON_NOT_FALSE
    else:
        passed = isinstance(observed, list) and not observed
        reason_code = REASON_SATISFIED if passed else REASON_NOT_EMPTY_LIST

    return {
        "kind": rule.kind,
        "passed": passed,
        "path": rule.path,
        "reason_code": reason_code,
        "rule_id": rule.rule_id,
    }


def evaluate_response(
    policy: Policy | dict[str, Any], response: Any
) -> dict[str, Any]:
    """Evaluate one JSON response against every rule in a validated policy."""

    validated_policy = validate_policy(policy)
    if not isinstance(response, dict):
        raise EvaluationInputError("Candidate response must be a JSON object.")
    try:
        ensure_json_value(response, label="Candidate response")
    except (RecursionError, ValueError) as exc:
        raise EvaluationInputError(str(exc)) from exc

    rule_results = [
        _evaluate_rule(rule, response) for rule in validated_policy.rules
    ]
    return {
        "passed": all(result["passed"] for result in rule_results),
        "policy_id": validated_policy.policy_id,
        "rule_results": rule_results,
    }
