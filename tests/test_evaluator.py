from __future__ import annotations

import json
import unittest
from importlib.resources import files

import constitutional_agent_testbench as cat
from constitutional_agent_testbench.common import MAX_JSON_INPUT_BYTES
from constitutional_agent_testbench import evaluator
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
    def test_package_exports_the_evaluation_contract(self) -> None:
        self.assertIs(cat.EvaluationInputError, EvaluationInputError)
        self.assertEqual(
            set(cat.EvaluationResult.__required_keys__),
            {"passed", "policy_id", "rule_results"},
        )
        self.assertEqual(
            set(cat.RuleResult.__required_keys__),
            {"kind", "passed", "path", "reason_code", "rule_id"},
        )
        self.assertTrue((files("constitutional_agent_testbench") / "py.typed").is_file())

    def test_evaluation_result_uses_the_public_key_set(self) -> None:
        result = evaluate_response(policy(), passing_response())
        self.assertEqual(set(result), {"passed", "policy_id", "rule_results"})
        self.assertEqual(
            set(result["rule_results"][0]),
            {"kind", "passed", "path", "reason_code", "rule_id"},
        )

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
            {"summary": float("inf")},
            {"summary": float("-inf")},
        ):
            with self.subTest(response=response), self.assertRaises(EvaluationInputError):
                evaluate_response(policy(), response)

    def test_rejects_programmatic_response_larger_than_the_input_limit(self) -> None:
        response = passing_response()
        response["summary"] = "x" * MAX_JSON_INPUT_BYTES

        with self.assertRaisesRegex(EvaluationInputError, "byte limit"):
            evaluate_response(policy(), response)

    def test_response_must_be_an_object(self) -> None:
        with self.assertRaises(EvaluationInputError):
            evaluate_response(policy(), [])

    def test_synthetic_generation_is_deterministic_and_verified(self) -> None:
        first = generate_synthetic_cases(policy())
        second = generate_synthetic_cases(policy())
        self.assertEqual(first, second)
        self.assertEqual(set(first), {"failing_case", "passing_case", "policy_id"})
        self.assertEqual(set(first["passing_case"]), {"evaluation", "response"})
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




    def test_one_of_canonicalizes_the_observed_value_once_per_rule(self) -> None:
        from constitutional_agent_testbench import evaluator
        from constitutional_agent_testbench.common import canonical_json

        observed = {"blob": "x" * 4000, "nested": {"a": [1, 2, 3]}}
        document = {
            "schema_version": "1.0",
            "policy_id": "work-bound",
            "rules": [
                {
                    "rule_id": "level-allowed",
                    "kind": "one_of",
                    "path": "level",
                    "values": [f"candidate-{index}" for index in range(64)],
                },
                {
                    "rule_id": "other-allowed",
                    "kind": "one_of",
                    "path": "other",
                    "values": [f"candidate-{index}" for index in range(64)],
                },
            ],
        }
        response = {"level": observed, "other": observed}
        seen: list[object] = []
        original = evaluator.canonical_json

        def counting(value):
            seen.append(value)
            return canonical_json(value)

        evaluator.canonical_json = counting
        try:
            result = evaluate_response(document, response)
        finally:
            evaluator.canonical_json = original

        self.assertFalse(result["passed"])
        self.assertEqual(sum(1 for value in seen if value is observed), 2)

    def test_one_of_keeps_strict_json_equality(self) -> None:
        document = {
            "schema_version": "1.0",
            "policy_id": "one-of-strict",
            "rules": [
                {
                    "rule_id": "flag-allowed",
                    "kind": "one_of",
                    "path": "flag",
                    "values": [True, 1, 1.0, "1", {"a": 1}, [1, 2], None],
                }
            ],
        }
        for observed, expected in (
            (True, True),
            (1, True),
            (1.0, True),
            ("1", True),
            ({"a": 1}, True),
            ([1, 2], True),
            (None, True),
            (False, False),
            (0, False),
            ("true", False),
            ([2, 1], False),
        ):
            with self.subTest(observed=observed):
                result = evaluate_response(document, {"flag": observed})
                self.assertEqual(result["passed"], expected)
                self.assertEqual(
                    result["rule_results"][0]["reason_code"],
                    "RULE_SATISFIED" if expected else "VALUE_NOT_ALLOWED",
                )


def single_rule_policy(rule: dict) -> dict:
    return {
        "schema_version": "1.0",
        "policy_id": "numeric-literal-policy",
        "rules": [{"rule_id": "x-rule", "path": "x", **rule}],
    }


class NumericLiteralTests(unittest.TestCase):
    """Pin the documented contract: the numeric literal form decides equality.

    Equality is canonical-JSON equality, the same representation receipt
    digests bind, so 1 and 1.0, 1e2 and 100, and 0.0 and -0.0 are different
    values. Changing this would invalidate existing receipts and replay bundles.
    """

    def outcome(self, rule: dict, observed) -> tuple[bool, str]:
        result = evaluate_response(single_rule_policy(rule), {"x": observed})
        row = result["rule_results"][0]
        return row["passed"], row["reason_code"]

    def test_equals_integer_rejects_the_float_literal(self) -> None:
        rule = {"kind": "equals", "value": 1}
        self.assertEqual(self.outcome(rule, 1), (True, "RULE_SATISFIED"))
        self.assertEqual(self.outcome(rule, 1.0), (False, "VALUE_NOT_EQUAL"))

    def test_one_of_integer_rejects_an_exponent_literal(self) -> None:
        observed = json.loads('{"x": 1e2}')["x"]
        self.assertEqual(
            self.outcome({"kind": "one_of", "values": [100]}, observed),
            (False, "VALUE_NOT_ALLOWED"),
        )

    def test_fraction_and_exponent_literals_of_one_value_are_equal(self) -> None:
        # Both parse to the same float, so only the integer/non-integer split
        # and the sign of zero are significant, not the spelling.
        rule = {"kind": "equals", "value": 1.0}
        for text in ("1.0", "1e0", "1E0", "10e-1"):
            with self.subTest(literal=text):
                observed = json.loads(f'{{"x": {text}}}')["x"]
                self.assertEqual(self.outcome(rule, observed), (True, "RULE_SATISFIED"))

    def test_equals_zero_rejects_negative_zero(self) -> None:
        self.assertEqual(
            self.outcome({"kind": "equals", "value": 0.0}, -0.0),
            (False, "VALUE_NOT_EQUAL"),
        )

    def test_one_of_keeps_integer_and_float_literals_as_two_values(self) -> None:
        validated = cat.validate_policy(
            single_rule_policy({"kind": "one_of", "values": [1, 1.0]})
        )
        self.assertEqual(len(validated.rules[0].values), 2)

    def test_boolean_true_and_number_one_stay_unequal(self) -> None:
        self.assertEqual(
            self.outcome({"kind": "equals", "value": True}, 1),
            (False, "VALUE_NOT_EQUAL"),
        )
        self.assertEqual(
            self.outcome({"kind": "equals", "value": 1}, True),
            (False, "VALUE_NOT_EQUAL"),
        )


class ReasonCodeVocabularyTests(unittest.TestCase):
    """The declared vocabulary and the emitted vocabulary must be one set."""

    def test_literal_and_runtime_set_agree(self) -> None:
        self.assertEqual(set(evaluator.ReasonCode.__args__), set(evaluator.REASON_CODES))
        self.assertEqual(
            set(evaluator.FAILURE_REASON_BY_KIND.values()) | {"RULE_SATISFIED", "FIELD_MISSING"},
            set(evaluator.REASON_CODES),
        )

    def test_suite_assertions_use_the_evaluator_vocabulary(self) -> None:
        from constitutional_agent_testbench.suite import REASON_CODES as suite_codes

        self.assertEqual(set(suite_codes), set(evaluator.REASON_CODES))

    def test_every_emitted_reason_code_is_declared(self) -> None:
        document = {
            "schema_version": "1.0",
            "policy_id": "vocabulary",
            "rules": [
                {"rule_id": "a", "kind": "equals", "path": "a", "value": 1},
                {"rule_id": "b", "kind": "one_of", "path": "b", "values": ["x"]},
                {"rule_id": "c", "kind": "false", "path": "c"},
                {"rule_id": "d", "kind": "empty_list", "path": "d"},
                {"rule_id": "e", "kind": "required_field", "path": "e"},
            ],
        }
        seen = set()
        for response in ({}, {"a": 2, "b": "y", "c": True, "d": [1], "e": 0},
                         {"a": 1, "b": "x", "c": False, "d": [], "e": 0}):
            for row in evaluate_response(document, response)["rule_results"]:
                seen.add(row["reason_code"])
        self.assertEqual(seen, set(evaluator.REASON_CODES))


if __name__ == "__main__":
    unittest.main()
