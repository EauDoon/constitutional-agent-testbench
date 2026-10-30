"""Deterministic response evaluation with stable reason codes."""

from __future__ import annotations

from typing import Any, Literal, NamedTuple, TypedDict

from .common import (
    MAX_JSON_INPUT_BYTES,
    TestbenchError,
    bounded_canonical_json_size,
    canonical_json,
    ensure_json_value,
    get_field,
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

#: The closed reason-code vocabulary, derived once from the constants above so
#: callers that must accept or classify reason codes cannot drift from the ones
#: this module can actually emit.
REASON_CODES = frozenset({
    REASON_SATISFIED,
    REASON_MISSING,
    REASON_NOT_EQUAL,
    REASON_NOT_ALLOWED,
    REASON_NOT_FALSE,
    REASON_NOT_EMPTY_LIST,
})

#: The reason code that can be emitted when a rule kind's constraint is violated.
FAILURE_REASON_BY_KIND = {
    "equals": REASON_NOT_EQUAL,
    "one_of": REASON_NOT_ALLOWED,
    "false": REASON_NOT_FALSE,
    "empty_list": REASON_NOT_EMPTY_LIST,
}


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


class _CompiledRule(NamedTuple):
    """A validated rule with its constraint markers serialized once.

    ``None`` markers mean "not compiled": the rule is then matched lazily, which
    suits the one-off checks that synthesis and lint make on candidate values.
    """

    rule: Rule
    marker: str | None = None
    markers: frozenset[str] | None = None


def _compile_rule(rule: Rule) -> _CompiledRule:
    if rule.kind == "equals":
        return _CompiledRule(rule, marker=_canonical_marker(rule.value))
    if rule.kind == "one_of":
        markers = (_canonical_marker(value) for value in rule.values)
        return _CompiledRule(
            rule, markers=frozenset(marker for marker in markers if marker is not None)
        )
    return _CompiledRule(rule)


def _compile(policy: Policy) -> tuple[_CompiledRule, ...]:
    """Serialize every equals and one_of constraint once for repeated evaluation.

    Callers pass an already validated policy, so suites, probes and order checks
    can evaluate many responses without re-validating or re-serializing it.
    """

    return tuple(_compile_rule(rule) for rule in policy.rules)


def _evaluate_compiled_rule(compiled: _CompiledRule, response: dict[str, Any]) -> RuleResult:
    rule = compiled.rule
    found, observed = get_field(response, rule.path)
    if not found:
        passed = False
        reason_code: ReasonCode = REASON_MISSING
    elif rule.kind == "required_field":
        passed = True
        reason_code = REASON_SATISFIED
    elif rule.kind == "equals":
        observed_marker = _canonical_marker(observed)
        expected_marker = compiled.marker
        if expected_marker is None:
            expected_marker = _canonical_marker(rule.value)
        passed = observed_marker is not None and observed_marker == expected_marker
        reason_code = REASON_SATISFIED if passed else REASON_NOT_EQUAL
    elif rule.kind == "one_of":
        # Match an allowed set without re-serializing the observed value per candidate.
        observed_marker = _canonical_marker(observed)
        if observed_marker is None:
            passed = False
        elif compiled.markers is not None:
            passed = observed_marker in compiled.markers
        else:
            passed = any(_canonical_marker(value) == observed_marker for value in rule.values)
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


def _evaluate_rule(rule: Rule, response: dict[str, Any]) -> RuleResult:
    """Evaluate one rule without compiling it, for one-off candidate checks."""

    return _evaluate_compiled_rule(_CompiledRule(rule), response)


def _check_response(response: Any) -> dict[str, Any]:
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
    return response


def _evaluate_checked(
    policy_id: str,
    compiled: tuple[_CompiledRule, ...],
    response: dict[str, Any],
) -> EvaluationResult:
    """Evaluate compiled rules, in order, against an already checked response."""

    rule_results = [_evaluate_compiled_rule(item, response) for item in compiled]
    return {
        "passed": all(result["passed"] for result in rule_results),
        "policy_id": policy_id,
        "rule_results": rule_results,
    }


def _evaluate_compiled(
    policy_id: str,
    compiled: tuple[_CompiledRule, ...],
    response: Any,
) -> EvaluationResult:
    """Check one response and evaluate it against a compiled, validated policy."""

    return _evaluate_checked(policy_id, compiled, _check_response(response))


def evaluate_response(
    policy: Policy | dict[str, Any], response: Any
) -> EvaluationResult:
    """Evaluate one JSON response against every rule in a validated policy."""

    validated_policy = validate_policy(policy)
    return _evaluate_compiled(
        validated_policy.policy_id, _compile(validated_policy), response
    )
