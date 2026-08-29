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

    def test_required_field_accepts_null_but_rejects_absence(self) -> None:
        required = {
            "schema_version": "1.0",
            "policy_id": "null-policy",
            "rules": [
                {
                    "rule_id": "summary-present",
                    "kind": "required_field",
                    "path": "summary",
                }
            ],
        }
        present = evaluate_response(required, {"summary": None})
        self.assertTrue(present["passed"])
        self.assertEqual(present["rule_results"][0]["reason_code"], "RULE_SATISFIED")
        missing = evaluate_response(required, {})
        self.assertFalse(missing["passed"])
        self.assertEqual(missing["rule_results"][0]["reason_code"], "FIELD_MISSING")

    def test_nested_paths_do_not_traverse_arrays_or_scalars(self) -> None:
        nested = {
            "schema_version": "1.0",
            "policy_id": "nested-path-policy",
            "rules": [
                {
                    "rule_id": "decision-equals",
                    "kind": "equals",
                    "path": "result.decision",
                    "value": "allow",
                }
            ],
        }
        passing = evaluate_response(nested, {"result": {"decision": "allow"}})
        self.assertTrue(passing["passed"])
        for response in (
            {"result": [{"decision": "allow"}]},
            {"result": ["allow"]},
            {"result": None},
            {"result": "allow"},
            {"result": True},
        ):
            with self.subTest(response=response):
                result = evaluate_response(nested, response)
                self.assertFalse(result["passed"])
                self.assertEqual(result["rule_results"][0]["reason_code"], "FIELD_MISSING")

    def test_false_and_empty_list_keep_json_type_distinctions(self) -> None:
        typed = {
            "schema_version": "1.0",
            "policy_id": "typed-false-list",
            "rules": [
                {"rule_id": "blocked-false", "kind": "false", "path": "blocked"},
                {"rule_id": "actions-empty", "kind": "empty_list", "path": "actions"},
            ],
        }
        passing = evaluate_response(typed, {"blocked": False, "actions": []})
        self.assertTrue(passing["passed"])
        cases = (
            ({"blocked": 0, "actions": []}, "blocked-false", "VALUE_NOT_FALSE"),
            ({"blocked": "false", "actions": []}, "blocked-false", "VALUE_NOT_FALSE"),
            ({"blocked": None, "actions": []}, "blocked-false", "VALUE_NOT_FALSE"),
            ({"blocked": False, "actions": {}}, "actions-empty", "VALUE_NOT_EMPTY_LIST"),
            ({"blocked": False, "actions": [None]}, "actions-empty", "VALUE_NOT_EMPTY_LIST"),
            ({"blocked": False, "actions": ""}, "actions-empty", "VALUE_NOT_EMPTY_LIST"),
        )
        for response, rule_id, reason in cases:
            with self.subTest(response=response):
                result = evaluate_response(typed, response)
                by_rule = {
                    item["rule_id"]: item["reason_code"] for item in result["rule_results"]
                }
                self.assertFalse(result["passed"])
                self.assertEqual(by_rule[rule_id], reason)

    def test_malformed_response_values_fail_closed(self) -> None:
        for response in (
            None,
            "object",
            1,
            True,
            {"summary": object()},
            {"summary": float("nan")},
        ):
            with self.subTest(response=response), self.assertRaises(EvaluationInputError):
                evaluate_response(policy(), response)

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

