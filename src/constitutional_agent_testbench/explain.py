"""Value-free path diagnostics layered on the unchanged evaluator."""

from typing import Any

from .evaluator import evaluate_response
from .policy import Policy, validate_policy


def explain_response(policy: Policy | dict[str, Any], response: Any) -> dict[str, Any]:
    """Explain traversal failures without copying response or policy values."""
    current = validate_policy(policy)
    result = evaluate_response(current, response)
    explanations = []
    for item in result["rule_results"]:
        current_value = response
        traversed = []
        detail = {"rule_id": item["rule_id"], "reason_code": item["reason_code"],
                  "path": item["path"], "resolution": "resolved"}
        for segment in item["path"].split("."):
            if not isinstance(current_value, dict):
                detail.update(resolution="parent_not_object", at=".".join(traversed))
                break
            traversed.append(segment)
            if segment not in current_value:
                detail.update(resolution="member_absent", at=".".join(traversed))
                break
            current_value = current_value[segment]
        explanations.append(detail)
    return {"evaluation": result, "explanations": explanations,
            "values_included": False}
