"""Compact value-free regression diagnosis over the unchanged evaluator."""
from .suite import evaluate_suite
from .workflow import bounded_artifact


def triage_suite(policy, suite):
    """Group observed rule failures only among cases that violated their assertions."""
    report = evaluate_suite(policy, suite)
    mismatches, groups = [], {}
    for case in report["cases"]:
        if case["matches_expectation"]:
            continue
        failed = [row for row in case["evaluation"]["rule_results"] if not row["passed"]]
        mismatches.append({"case_id": case["case_id"], "expected_passed": case["expected_passed"],
            "actual_passed": case["evaluation"]["passed"],
            "failed_rule_ids": [row["rule_id"] for row in failed],
            "rule_assertion_mismatches": case.get("rule_assertion_mismatches", [])})
        for row in failed:
            groups.setdefault((row["rule_id"], row["path"], row["reason_code"]), []).append(case["case_id"])
    return bounded_artifact({"policy_id": report["policy_id"], "case_count": report["case_count"],
        "matches_expectations": report["matches_expectations"], "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "failure_groups": [{"rule_id": key[0], "path": key[1], "reason_code": key[2], "case_ids": groups[key]}
                           for key in sorted(groups)], "values_included": False})
