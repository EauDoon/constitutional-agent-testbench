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
    EvaluationResult,
    Policy,
    check_order_conformance,
    evaluate_response,
    generate_synthetic_cases,
    validate_policy,
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
