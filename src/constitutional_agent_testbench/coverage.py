"""Observed rule outcomes over explicit fixtures, not empirical safety claims."""

from typing import Any

from .policy import Policy
from .suite import evaluate_suite


def suite_coverage(policy: Policy | dict[str, Any], suite: Any) -> dict[str, Any]:
    """Count observed rule pass/fail and reason-code coverage on a validated suite."""
    report = evaluate_suite(policy, suite)
    rules: dict[str, dict[str, Any]] = {}
    for case in report["cases"]:
        for item in case["evaluation"]["rule_results"]:
            row = rules.setdefault(item["rule_id"], {"rule_id": item["rule_id"],
                "path": item["path"], "passed_cases": 0, "failed_cases": 0,
                "reason_counts": {}})
            row["passed_cases" if item["passed"] else "failed_cases"] += 1
            reasons = row["reason_counts"]
            reasons[item["reason_code"]] = reasons.get(item["reason_code"], 0) + 1
    rows = sorted(rules.values(), key=lambda row: row["rule_id"])
    for row in rows:
        row["both_outcomes_observed"] = row["passed_cases"] > 0 and row["failed_cases"] > 0
    return {"policy_id": report["policy_id"], "case_count": report["case_count"],
            "rules": rows, "rules_with_both_outcomes": sum(row["both_outcomes_observed"] for row in rows),
            "unexercised_failures": [row["rule_id"] for row in rows if not row["failed_cases"]],
            "unexercised_passes": [row["rule_id"] for row in rows if not row["passed_cases"]],
            "coverage_scope": "observed fixture outcomes only"}
