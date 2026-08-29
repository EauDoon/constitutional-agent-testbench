from __future__ import annotations

import unittest

from constitutional_agent_testbench.evaluator import (
    EvaluationInputError,
    evaluate_response,
)
from constitutional_agent_testbench.synthetic import (
    SyntheticGenerationError,
    generate_synthetic_cases,
)


def policy() -> dict:
    return {
        "schema_version": "1.0",
        "policy_id": "evaluation-policy",
        "rules": [
            {
                "rule_id": "summary-present",
                "kind": "required_field",
                "path": "summary",
            },
            {
                "rule_id": "decision-equals",
                "kind": "equals",
                "path": "decision",
                "value": "accept",
            },
            {
                "rule_id": "level-allowed",
                "kind": "one_of",
                "path": "level",
                "values": ["low", "moderate"],
            },
            {"rule_id": "blocked-false", "kind": "false", "path": "blocked"},
            {
                "rule_id": "actions-empty",
                "kind": "empty_list",
                "path": "actions",
            },
        ],
    }


def passing_response() -> dict:
    return {
        "actions": [],
        "blocked": False,
        "decision": "accept",
        "level": "low",
        "summary": "Synthetic example.",
    }


class EvaluatorTests(unittest.TestCase):
    def test_all_supported_rules_pass(self) -> None:
        result = evaluate_response(policy(), passing_response())
        self.assertTrue(result["passed"])
        self.assertEqual(
            {item["reason_code"] for item in result["rule_results"]},
            {"RULE_SATISFIED"},
        )

    def test_missing_fields_fail_closed(self) -> None:
        result = evaluate_response(policy(), {})
        self.assertFalse(result["passed"])
        self.assertEqual(
            {item["reason_code"] for item in result["rule_results"]},
            {"FIELD_MISSING"},
        )

    def test_stable_failure_reason_codes(self) -> None:
        response = passing_response()
        response.update(
            {"actions": ["synthetic"], "blocked": True, "decision": "decline", "level": "high"}
        )
        result = evaluate_response(policy(), response)
        by_rule = {item["rule_id"]: item["reason_code"] for item in result["rule_results"]}
        self.assertEqual(by_rule["decision-equals"], "VALUE_NOT_EQUAL")
        self.assertEqual(by_rule["level-allowed"], "VALUE_NOT_ALLOWED")
        self.assertEqual(by_rule["blocked-false"], "VALUE_NOT_FALSE")
        self.assertEqual(by_rule["actions-empty"], "VALUE_NOT_EMPTY_LIST")

    def test_json_boolean_is_not_integer_for_equals(self) -> None:
        typed_policy = {
            "schema_version": "1.0",
            "policy_id": "typed-policy",
            "rules": [
                {"rule_id": "number-one", "kind": "equals", "path": "value", "value": 1}
            ],
        }
        result = evaluate_response(typed_policy, {"value": True})
        self.assertFalse(result["passed"])

    def test_response_must_be_an_object(self) -> None:
        with self.assertRaises(EvaluationInputError):
            evaluate_response(policy(), [])

    def test_synthetic_generation_is_deterministic_and_verified(self) -> None:
        first = generate_synthetic_cases(policy())
        second = generate_synthetic_cases(policy())
        self.assertEqual(first, second)
        self.assertTrue(first["passing_case"]["evaluation"]["passed"])
        self.assertFalse(first["failing_case"]["evaluation"]["passed"])

    def test_synthetic_generation_preserves_valid_nested_values(self) -> None:
        nested_policy = {
            "schema_version": "1.0",
            "policy_id": "nested-policy",
            "rules": [
                {
                    "rule_id": "result-equals",
                    "kind": "equals",
                    "path": "result",
                    "value": {"decision": "allow"},
                },
                {
                    "rule_id": "decision-present",
                    "kind": "required_field",
                    "path": "result.decision",
                },
            ],
        }

        generated = generate_synthetic_cases(nested_policy)

        self.assertTrue(generated["passing_case"]["evaluation"]["passed"])
        self.assertEqual(
            generated["passing_case"]["response"],
            {"result": {"decision": "allow"}},
        )

    def test_conflicting_synthetic_constraints_fail_closed(self) -> None:
        conflicting = {
            "schema_version": "1.0",
            "policy_id": "conflicting-policy",
            "rules": [
                {"rule_id": "first", "kind": "equals", "path": "value", "value": 1},
                {"rule_id": "second", "kind": "equals", "path": "value", "value": 2},
            ],
        }
        with self.assertRaises(SyntheticGenerationError):
            generate_synthetic_cases(conflicting)


if __name__ == "__main__":
    unittest.main()

