"""Explicit migration impact over supplied fixtures, with no authority selection."""

from typing import Any

from .common import canonical_json
from .policy import Policy, policy_to_dict, validate_policy
from .suite import evaluate_suite, validate_suite


def compare_policies(before: Policy | dict[str, Any], after: Policy | dict[str, Any],
                     suite: Any) -> dict[str, Any]:
    """Compare definitions and observed verdicts; neither policy overrides the other."""
    old, new = validate_policy(before), validate_policy(after)
    fixtures = validate_suite(suite)
    old_report, new_report = evaluate_suite(old, fixtures), evaluate_suite(new, fixtures)
    old_rules = {r["rule_id"]: r for r in policy_to_dict(old)["rules"]}
    new_rules = {r["rule_id"]: r for r in policy_to_dict(new)["rules"]}
    changes = {"added": sorted(new_rules.keys() - old_rules.keys()),
               "removed": sorted(old_rules.keys() - new_rules.keys()),
               "modified": sorted(key for key in old_rules.keys() & new_rules.keys()
                                  if canonical_json(old_rules[key]) != canonical_json(new_rules[key])),
               "order_changed": [r.rule_id for r in old.rules] != [r.rule_id for r in new.rules]}
    cases = []
    for left, right in zip(old_report["cases"], new_report["cases"], strict=True):
        a, b = left["evaluation"], right["evaluation"]
        a_rules = {r["rule_id"]: r for r in a["rule_results"]}
        b_rules = {r["rule_id"]: r for r in b["rule_results"]}
        cases.append({"case_id": left["case_id"], "before_passed": a["passed"],
                      "after_passed": b["passed"], "verdict_changed": a["passed"] != b["passed"],
                      "changed_rule_results": sorted(key for key in a_rules.keys() | b_rules.keys()
                          if a_rules.get(key) != b_rules.get(key))})
    return {"before_policy_id": old.policy_id, "after_policy_id": new.policy_id,
            "rule_changes": changes, "cases": cases,
            "verdict_change_count": sum(c["verdict_changed"] for c in cases),
            "newly_passing": [c["case_id"] for c in cases if not c["before_passed"] and c["after_passed"]],
            "newly_failing": [c["case_id"] for c in cases if c["before_passed"] and not c["after_passed"]],
            "before_matches_expectations": old_report["matches_expectations"],
            "after_matches_expectations": new_report["matches_expectations"],
            "comparison_scope": "supplied fixtures only; no policy recommendation"}
