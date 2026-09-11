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


def check_suite(policy, suite):
    """Combine existing diagnostics into a value-free local regression preflight."""
    from .policy import validate_policy
    from .suite import validate_suite
    from .authoring import lint_policy
    from .inspection import inspect_suite, audit_assertions
    current, fixtures = validate_policy(policy), validate_suite(suite)
    lint = lint_policy(current)
    inventory = inspect_suite(fixtures)
    assertions = audit_assertions(current, fixtures)
    regression = triage_suite(current, fixtures)
    checks = {"no_policy_conflicts": not lint["has_conflicts"],
              "consistent_expectations": inventory["consistent_expectations"],
              "compatible_assertions": assertions["assertions_compatible"],
              "matches_expectations": regression["matches_expectations"]}
    return bounded_artifact({"policy_id": current.policy_id, "ready": all(checks.values()),
        "checks": checks, "policy_findings": lint["findings"],
        "duplicate_responses": inventory["duplicate_responses"],
        "assertions": assertions, "regressions": regression,
        "scope": "local fixture preflight; not a safety or satisfiability proof"})
