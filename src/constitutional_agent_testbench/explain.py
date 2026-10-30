"""Value-free path and type diagnostics layered on the unchanged evaluator."""

from typing import Any

from .common import json_type_name
from .evaluator import _compile, _evaluate_compiled
from .policy import Policy, Rule, validate_policy

_NUMBER_TYPES = ["integer", "number"]
_LENGTH_TYPES = ["array", "object", "string"]


def _expected_types(rule: Rule) -> list[str] | None:
    """Observed-type names that can satisfy the rule, derived from the policy only.

    ``number`` brings in ``integer``, so ``observed_type in expected_types`` is a
    necessary condition for a pass. ``None`` means any type (``required_field``).
    """

    if rule.kind == "equals":
        return [json_type_name(rule.value)]
    if rule.kind == "one_of":
        return sorted({json_type_name(value) for value in rule.values})
    if rule.kind == "false":
        return ["boolean"]
    if rule.kind == "empty_list":
        return ["array"]
    if rule.kind == "type":
        return sorted(set(rule.types) | ({"integer"} if "number" in rule.types else set()))
    if rule.kind == "range":
        return list(_NUMBER_TYPES)
    if rule.kind == "length":
        return list(_LENGTH_TYPES)
    return None


def _violated_bound(rule: Rule, observed: Any) -> str | None:
    """Name the bound a failed range or length rule crossed, without its value."""

    if rule.kind == "range" and json_type_name(observed) in _NUMBER_TYPES:
        measured = observed
    elif rule.kind == "length" and json_type_name(observed) in _LENGTH_TYPES:
        measured = len(observed)
    else:
        return None
    if rule.minimum is not None and measured < rule.minimum:
        return "minimum"
    return "maximum"


def explain_response(policy: Policy | dict[str, Any], response: Any) -> dict[str, Any]:
    """Explain traversal and type failures without copying response or policy values."""
    current = validate_policy(policy)
    result = _evaluate_compiled(current.policy_id, _compile(current), response)
    explanations = []
    for rule, item in zip(current.rules, result["rule_results"], strict=True):
        current_value = response
        traversed = []
        detail: dict[str, Any] = {"rule_id": item["rule_id"], "reason_code": item["reason_code"],
                                  "path": item["path"], "resolution": "resolved",
                                  "expected_types": _expected_types(rule)}
        for segment in item["path"].split("."):
            if not isinstance(current_value, dict):
                detail.update(resolution="parent_not_object", at=".".join(traversed))
                break
            traversed.append(segment)
            if segment not in current_value:
                detail.update(resolution="member_absent", at=".".join(traversed))
                break
            current_value = current_value[segment]
        if detail["resolution"] == "resolved":
            detail["observed_type"] = json_type_name(current_value)
            if not item["passed"]:
                bound = _violated_bound(rule, current_value)
                if bound is not None:
                    detail["violated_bound"] = bound
        explanations.append(detail)
    return {"evaluation": result, "explanations": explanations,
            "values_included": False}
