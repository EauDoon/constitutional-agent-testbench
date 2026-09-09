"""Value-free inspection for policy and fixture authors."""

from collections import Counter

from .policy import validate_policy
from .workflow import WorkflowInputError, bounded_artifact
from .common import canonical_json
from .suite import validate_suite


def inspect_policy(policy):
    """Inventory declared paths and relationships without copying constraint values."""
    current = validate_policy(policy)
    if len(current.rules) > 256:
        raise WorkflowInputError("Policy inspection supports at most 256 rules.")
    paths = sorted({rule.path for rule in current.rules})
    return bounded_artifact({"policy_id": current.policy_id, "schema_version": current.schema_version,
            "rule_count": len(current.rules), "path_count": len(paths),
            "kind_counts": dict(sorted(Counter(rule.kind for rule in current.rules).items())),
            "paths": [{"path": path,
                       "rule_ids": [r.rule_id for r in current.rules if r.path == path],
                       "ancestor_paths": [p for p in paths if path.startswith(p + ".")]}
                      for path in paths]})


def inspect_suite(suite):
    """Identify duplicate inputs and contradictory expectations without response values."""
    fixtures = validate_suite(suite)
    groups = {}
    for case in fixtures["cases"]:
        groups.setdefault(canonical_json(case["response"]), []).append(case)
    duplicates = []
    for cases in groups.values():
        if len(cases) > 1:
            expectations = {canonical_json({k: v for k, v in case.items()
                                           if k not in {"case_id", "response"}}) for case in cases}
            duplicates.append({"case_ids": [case["case_id"] for case in cases],
                               "conflicting_expectations": len(expectations) > 1})
    return bounded_artifact({"suite_version": fixtures["suite_version"],
        "case_count": len(fixtures["cases"]), "unique_response_count": len(groups),
        "expected_pass_count": sum(case["expected_passed"] for case in fixtures["cases"]),
        "duplicate_responses": duplicates,
        "consistent_expectations": not any(group["conflicting_expectations"] for group in duplicates)})
