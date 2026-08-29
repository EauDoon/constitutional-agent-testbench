"""Deterministic generation of neutral synthetic evaluation cases."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, TypedDict

from .common import TestbenchError, canonical_json
from .evaluator import EvaluationResult, evaluate_response
from .policy import Policy, Rule, validate_policy


class SyntheticGenerationError(TestbenchError):
    """Raised when a policy cannot yield a verified synthetic pair."""

    code = "SYNTHETIC_GENERATION_FAILED"


class SyntheticCase(TypedDict):
    """One verified synthetic response and its evaluation."""

    evaluation: EvaluationResult
    response: dict[str, Any]


class SyntheticCaseBundle(TypedDict):
    """Verified passing and failing cases derived from one policy."""

    failing_case: SyntheticCase
    passing_case: SyntheticCase
    policy_id: str


def _choose_value(rules: list[Rule]) -> Any:
    fixed_values: list[Any] = []
    allowed_groups: list[tuple[Any, ...]] = []
    for rule in rules:
        if rule.kind == "equals":
            fixed_values.append(rule.value)
        elif rule.kind == "false":
            fixed_values.append(False)
        elif rule.kind == "empty_list":
            fixed_values.append([])
        elif rule.kind == "one_of":
            allowed_groups.append(rule.values)

    if fixed_values:
        selected = fixed_values[0]
        marker = canonical_json(selected)
        if any(canonical_json(value) != marker for value in fixed_values[1:]):
            raise SyntheticGenerationError(
                "Policy has conflicting constraints and no synthetic pass can be verified."
            )
        for allowed in allowed_groups:
            if not any(canonical_json(value) == marker for value in allowed):
                raise SyntheticGenerationError(
                    "Policy has conflicting constraints and no synthetic pass can be verified."
                )
        return deepcopy(selected)

    if allowed_groups:
        for candidate in allowed_groups[0]:
            marker = canonical_json(candidate)
            if all(
                any(canonical_json(value) == marker for value in allowed)
                for allowed in allowed_groups[1:]
            ):
                return deepcopy(candidate)
        raise SyntheticGenerationError(
            "Policy has conflicting constraints and no synthetic pass can be verified."
        )

    return None


def _assign_path(document: dict[str, Any], path: str, value: Any) -> None:
    segments = path.split(".")
    current = document
    for segment in segments[:-1]:
        existing = current.get(segment)
        if existing is None:
            current[segment] = {}
        elif not isinstance(existing, dict):
            raise SyntheticGenerationError(
                "Policy has incompatible nested paths and no synthetic pass can be verified."
            )
        current = current[segment]
    current[segments[-1]] = deepcopy(value)


def _delete_path(document: dict[str, Any], path: str) -> bool:
    segments = path.split(".")
    current: Any = document
    for segment in segments[:-1]:
        if not isinstance(current, dict) or segment not in current:
            return False
        current = current[segment]
    if not isinstance(current, dict) or segments[-1] not in current:
        return False
    del current[segments[-1]]
    return True


def generate_synthetic_cases(
    policy: Policy | dict[str, Any],
) -> SyntheticCaseBundle:
    """Build and verify one passing and one failing synthetic response."""

    validated_policy = validate_policy(policy)
    by_path: dict[str, list[Rule]] = {}
    for rule in validated_policy.rules:
        by_path.setdefault(rule.path, []).append(rule)

    passing_response: dict[str, Any] = {}
    ordered_paths = sorted(by_path, key=lambda path: (path.count("."), path))
    for path in ordered_paths:
        path_policy = Policy(
            policy_id=validated_policy.policy_id,
            rules=tuple(by_path[path]),
        )
        if evaluate_response(path_policy, passing_response)["passed"]:
            continue
        _assign_path(passing_response, path, _choose_value(by_path[path]))

    passing_evaluation = evaluate_response(validated_policy, passing_response)
    if not passing_evaluation["passed"]:
        raise SyntheticGenerationError(
            "Policy constraints could not produce a verified synthetic passing case."
        )

    failing_response = deepcopy(passing_response)
    if not _delete_path(failing_response, validated_policy.rules[0].path):
        raise SyntheticGenerationError(
            "A verified synthetic failing case could not be constructed."
        )
    failing_evaluation = evaluate_response(validated_policy, failing_response)
    if failing_evaluation["passed"]:
        raise SyntheticGenerationError(
            "A verified synthetic failing case could not be constructed."
        )

    return {
        "failing_case": {
            "evaluation": failing_evaluation,
            "response": failing_response,
        },
        "passing_case": {
            "evaluation": passing_evaluation,
            "response": passing_response,
        },
        "policy_id": validated_policy.policy_id,
    }
