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
            conflict = len({case["expected_passed"] for case in cases}) > 1
            asserted = {}
            for case in cases:
                for identifier, assertion in case.get("expected_rules", {}).items():
                    if identifier in asserted and asserted[identifier] != assertion:
                        conflict = True
                    asserted[identifier] = assertion
            duplicates.append({"case_ids": [case["case_id"] for case in cases],
                               "conflicting_expectations": conflict})
    return bounded_artifact({"suite_version": fixtures["suite_version"],
        "case_count": len(fixtures["cases"]), "unique_response_count": len(groups),
        "expected_pass_count": sum(case["expected_passed"] for case in fixtures["cases"]),
        "duplicate_responses": duplicates,
        "consistent_expectations": not any(group["conflicting_expectations"] for group in duplicates)})


def diff_suites(suite, incoming):
    """Report changes by stable case ID, never by copying candidate values."""
    left, right = validate_suite(suite), validate_suite(incoming)
    old = {case["case_id"]: case for case in left["cases"]}
    new = {case["case_id"]: case for case in right["cases"]}
    modified = []
    for identifier in sorted(old.keys() & new.keys()):
        changed = [field for field in ("response", "expected_passed", "expected_rules")
                   if (field in old[identifier]) != (field in new[identifier])
                   or canonical_json(old[identifier].get(field)) != canonical_json(new[identifier].get(field))]
        if changed:
            modified.append({"case_id": identifier, "changed_fields": changed})
    return bounded_artifact({"added": sorted(new.keys() - old.keys()),
        "removed": sorted(old.keys() - new.keys()), "modified": modified,
        "order_changed": list(old) != list(new),
        "version_changed": left["suite_version"] != right["suite_version"],
        "identical": canonical_json(left) == canonical_json(right), "values_included": False})
