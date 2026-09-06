"""Deterministic response evaluation with stable reason codes."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from .common import (
    MAX_JSON_INPUT_BYTES,
    TestbenchError,
    bounded_canonical_json_size,
    canonical_json,
    ensure_json_value,
    get_field,
    json_values_equal,
)
from .policy import Policy, Rule, validate_policy


class EvaluationInputError(TestbenchError):
    """Raised when a candidate response is not valid strict JSON object input."""

    code = "INVALID_RESPONSE"


REASON_SATISFIED = "RULE_SATISFIED"
REASON_MISSING = "FIELD_MISSING"
REASON_NOT_EQUAL = "VALUE_NOT_EQUAL"
REASON_NOT_ALLOWED = "VALUE_NOT_ALLOWED"
REASON_NOT_FALSE = "VALUE_NOT_FALSE"
REASON_NOT_EMPTY_LIST = "VALUE_NOT_EMPTY_LIST"

ReasonCode = Literal[
    "RULE_SATISFIED",
    "FIELD_MISSING",
    "VALUE_NOT_EQUAL",
    "VALUE_NOT_ALLOWED",
    "VALUE_NOT_FALSE",
    "VALUE_NOT_EMPTY_LIST",
]


class RuleResult(TypedDict):
    """Public per-rule evaluation record."""

    kind: str
    passed: bool
    path: str
    reason_code: ReasonCode
    rule_id: str


class EvaluationResult(TypedDict):
    """Public evaluation of one response against every declared rule."""

    passed: bool
    policy_id: str
    rule_results: list[RuleResult]


def _canonical_marker(value: Any) -> str | None:
    try:
        return canonical_json(value)
    except (OverflowError, RecursionError, TypeError, ValueError):
        return None


def _one_of_matches(observed: Any, values: tuple[Any, ...]) -> bool:
    """Match an allowed set without re-serializing the observed value per candidate."""

    observed_marker = _canonical_marker(observed)
    if observed_marker is None:
        return False
    for value in values:
        value_marker = _canonical_marker(value)
        if value_marker is not None and value_marker == observed_marker:
            return True
    return False


def _evaluate_rule(rule: Rule, response: dict[str, Any]) -> RuleResult:
    found, observed = get_field(response, rule.path)
    if not found:
        passed = False
        reason_code: ReasonCode = REASON_MISSING
    elif rule.kind == "required_field":
        passed = True
        reason_code = REASON_SATISFIED
    elif rule.kind == "equals":
        passed = json_values_equal(observed, rule.value)
        reason_code = REASON_SATISFIED if passed else REASON_NOT_EQUAL
    elif rule.kind == "one_of":
        passed = _one_of_matches(observed, rule.values)
        reason_code = REASON_SATISFIED if passed else REASON_NOT_ALLOWED
    elif rule.kind == "false":
        passed = observed is False
        reason_code = REASON_SATISFIED if passed else REASON_NOT_FALSE
    elif rule.kind == "empty_list":
        passed = isinstance(observed, list) and not observed
        reason_code = REASON_SATISFIED if passed else REASON_NOT_EMPTY_LIST
    else:
        passed = False
        reason_code = REASON_MISSING

    return {
        "kind": rule.kind,
        "passed": passed,
        "path": rule.path,
        "reason_code": reason_code,
        "rule_id": rule.rule_id,
    }


def evaluate_response(
    policy: Policy | dict[str, Any], response: Any
) -> EvaluationResult:
    """Evaluate one JSON response against every rule in a validated policy."""

    validated_policy = validate_policy(policy)
    if not isinstance(response, dict):
        raise EvaluationInputError("Candidate response must be a JSON object.")
    try:
        ensure_json_value(response, label="Candidate response")
        bounded_canonical_json_size(
            response,
            label="Candidate response",
            limit=MAX_JSON_INPUT_BYTES,
        )
    except (RecursionError, TypeError, ValueError) as exc:
        raise EvaluationInputError(str(exc)) from exc

    rule_results = [
        _evaluate_rule(rule, response) for rule in validated_policy.rules
    ]
    return {
        "passed": all(result["passed"] for result in rule_results),
        "policy_id": validated_policy.policy_id,
        "rule_results": rule_results,
    }
