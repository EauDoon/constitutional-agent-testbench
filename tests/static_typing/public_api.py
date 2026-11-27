"""Downstream-consumer typing fixture for the installed public API.

CI type-checks this file with mypy against the installed package, which also
proves the PEP 561 ``py.typed`` marker ships. It is never imported by the unit
suite: the file name does not match ``test*.py`` and the directory has no
``__init__.py``. Do not rename the directory ``typing``; unittest discovery puts
``tests/`` on ``sys.path`` and that name would shadow the standard library.
"""

from __future__ import annotations

from typing import Any

from constitutional_agent_testbench import (
    DecisionLogInputError,
    EvaluationResult,
    compare_decision_log,
    import_decision_log,
    normalize_decision_log,
    parse_decision_log_text,
    attach_signature,
    authorization_signing_input,
    build_authorization,
    create_authorization,
    rail_canonical_json,
    rail_digest,
    sign_authorization,
    trusted_authorizers,
    verify_authorization,
    Policy,
    audit_assertions,
    capture_assertions,
    check_order_conformance,
    check_suite,
    compare_policies,
    create_receipt,
    create_replay_bundle,
    create_suite_receipt,
    deduplicate_suite,
    diff_suites,
    evaluate_response,
    evaluate_suite,
    explain_response,
    generate_rule_probes,
    generate_synthetic_cases,
    import_responses,
    inspect_policy,
    inspect_suite,
    lint_policy,
    merge_suites,
    migration_expectations,
    reduce_suite,
    replay_bundle,
    select_outcomes,
    select_suite,
    shard_suite,
    suite_coverage,
    triage_suite,
    validate_policy,
    validate_suite,
    validate_suite_report,
    verify_receipt,
    verify_suite_receipt,
)

policy: Policy = validate_policy(
    {
        "schema_version": "1.0",
        "policy_id": "typing-fixture",
        "rules": [
            {"rule_id": "decision", "kind": "equals", "path": "decision", "value": "approve"},
            {"rule_id": "blocked", "kind": "false", "path": "blocked"},
        ],
    }
)
response = {"decision": "approve", "blocked": False}

result: EvaluationResult = evaluate_response(policy, response)
passed: bool = result["passed"]
fixtures = generate_synthetic_cases(policy)


def typed_evaluator(candidate_policy: Policy, candidate: Any) -> EvaluationResult:
    return evaluate_response(candidate_policy, candidate)


def plain_evaluator(candidate_policy: Policy, candidate: Any) -> dict[str, Any]:
    return dict(evaluate_response(candidate_policy, candidate))


reports: list[dict[str, Any]] = [
    check_order_conformance(policy, response),
    check_order_conformance(policy, response, evaluator=evaluate_response),
    check_order_conformance(policy, response, evaluator=typed_evaluator),
    check_order_conformance(policy, response, evaluator=plain_evaluator),
]

# Every exported function, called with well-typed arguments, so ``mypy --strict``
# reports an untyped or mistyped public signature as a downstream consumer would.
suite: dict[str, Any] = {
    "suite_version": "1.0",
    "cases": [{"case_id": "approved", "response": response, "expected_passed": True}],
}
raw_policy: dict[str, Any] = {
    "schema_version": "1.0",
    "policy_id": "typing-fixture",
    "rules": [{"rule_id": "blocked", "kind": "false", "path": "blocked"}],
}
receipt: dict[str, Any] = create_receipt(policy, response)
suite_receipt: dict[str, Any] = create_suite_receipt(raw_policy, suite)
bundle: dict[str, Any] = create_replay_bundle(policy, suite)
artifacts: list[dict[str, Any]] = [
    verify_receipt(policy, response, receipt),
    verify_suite_receipt(policy, suite, suite_receipt),
    replay_bundle(bundle),
    lint_policy(policy),
    explain_response(policy, response),
    evaluate_suite(policy, suite),
    validate_suite(suite),
    validate_suite_report(suite),
    suite_coverage(policy, suite),
    compare_policies(policy, raw_policy, suite),
    migration_expectations(policy, raw_policy, suite),
    generate_rule_probes(policy),
    inspect_policy(policy),
    inspect_suite(suite),
    diff_suites(suite, suite),
    audit_assertions(policy, suite),
    merge_suites(suite, {"suite_version": "1.0", "cases": []}),
    select_suite(suite, ["approved"]),
    reduce_suite(policy, suite),
    capture_assertions(policy, suite),
    shard_suite(suite, {"index": 0, "count": 1}),
    select_outcomes(policy, suite, "passed"),
    deduplicate_suite(suite),
    import_responses([response], [True]),
    triage_suite(policy, suite),
    check_suite(policy, suite),
]
rule_count: int = inspect_policy(raw_policy)["rule_count"]

# Signed authorization decisions. Never executed: the key below is a placeholder.
decided_at: str = "2026-11-28T02:30:00.000Z"
body: dict[str, Any] = build_authorization(policy, response, decided_at=decided_at, ttl_seconds=60,
                                           require_recovery_preflight=False)
signing_input: bytes = authorization_signing_input(body)
signed: dict[str, Any] = attach_signature(body, "authorizer-key", bytes(64))
resigned: dict[str, Any] = sign_authorization(body, b"PEM", "authorizer-key")
created: dict[str, Any] = create_authorization(policy, response, private_key_pem="PEM",
                                               key_id="authorizer-key", decided_at=decided_at)
authorizers: dict[str, bytes] = trusted_authorizers({"schema_version": "", "authorizer": []})
verification: dict[str, Any] = verify_authorization(signed, {}, action=response, policy=policy,
                                                    now=decided_at)
digest_text: str = rail_digest(response) + rail_canonical_json(response)

# Decision logs from other engines.
log: Any = parse_decision_log_text('{"decision_id": "d1", "input": {}, "result": true}')
normalized: dict[str, Any] = normalize_decision_log(log, log_format="opa", result_path="allow",
                                                    decision_path=None, input_path=None)
imported_log: dict[str, Any] = import_decision_log(log, log_format="opa")
log_report: dict[str, Any] = compare_decision_log(policy, log, log_format="cedar",
                                                  input_path="context")
log_error_code: str = DecisionLogInputError.code
