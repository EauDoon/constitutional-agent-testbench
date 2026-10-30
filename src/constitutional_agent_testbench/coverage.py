"""Observed rule outcomes over explicit fixtures, not empirical safety claims."""

from typing import Any

from .evaluator import FAILURE_REASON_BY_KIND, REASON_MISSING, REASON_SATISFIED
from .policy import Policy
from .suite import evaluate_suite


def reachable_reason_codes(kind: str) -> list[str]:
    """Every reason code a valid rule of this kind can emit, sorted.

    All of them are reachable for every valid rule: a schema 1.1 type list that
    admits every JSON value is rejected, so its failure code can always fire.
    """

    codes = {REASON_SATISFIED, REASON_MISSING}
    if kind in FAILURE_REASON_BY_KIND:
        codes.add(FAILURE_REASON_BY_KIND[kind])
    return sorted(codes)


def suite_coverage(policy: Policy | dict[str, Any], suite: Any) -> dict[str, Any]:
    """Count observed rule pass/fail and reason-code coverage on a validated suite."""
    report = evaluate_suite(policy, suite)
    rules: dict[str, dict[str, Any]] = {}
    for case in report["cases"]:
        for item in case["evaluation"]["rule_results"]:
            row = rules.setdefault(item["rule_id"], {"rule_id": item["rule_id"],
                "path": item["path"], "kind": item["kind"], "passed_cases": 0,
                "failed_cases": 0, "reason_counts": {}})
            row["passed_cases" if item["passed"] else "failed_cases"] += 1
            reasons = row["reason_counts"]
            reasons[item["reason_code"]] = reasons.get(item["reason_code"], 0) + 1
    rows = sorted(rules.values(), key=lambda row: row["rule_id"])
    for row in rows:
        row["both_outcomes_observed"] = row["passed_cases"] > 0 and row["failed_cases"] > 0
        row["unexercised_reason_codes"] = [code for code in reachable_reason_codes(row["kind"])
                                           if code not in row["reason_counts"]]
    return {"policy_id": report["policy_id"], "case_count": report["case_count"],
            "rules": rows, "rules_with_both_outcomes": sum(row["both_outcomes_observed"] for row in rows),
            "unexercised_failures": [row["rule_id"] for row in rows if not row["failed_cases"]],
            "unexercised_passes": [row["rule_id"] for row in rows if not row["passed_cases"]],
            "rules_with_all_reason_codes": sum(not row["unexercised_reason_codes"] for row in rows),
            "rules_missing_reason_codes": [row["rule_id"] for row in rows
                                           if row["unexercised_reason_codes"]],
            "coverage_scope": "observed fixture outcomes only"}
