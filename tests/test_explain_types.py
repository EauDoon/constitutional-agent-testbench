"""explain reports value-free observed and expected JSON types and violated bounds."""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from constitutional_agent_testbench import explain
from constitutional_agent_testbench.common import load_json, stable_json
from constitutional_agent_testbench.explain import explain_response

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def policy(*rules, version="1.1"):
    return {"schema_version": version, "policy_id": "explain", "rules": list(rules)}


def rule(identifier, kind, path="field", **fields):
    return {"rule_id": identifier, "kind": kind, "path": path, **fields}


def detail(raw_rule, response, version="1.1"):
    return explain_response(policy(raw_rule, version=version), response)["explanations"][0]


class ExpectedAndObservedTypeTests(unittest.TestCase):
    def test_zero_under_a_false_rule_is_diagnosed_as_a_type_miss(self):
        raw = load_json(EXAMPLES / "policy.json")
        response = load_json(EXAMPLES / "passing-response.json") | {"blocked": 0}
        explanations = {item["rule_id"]: item for item in
                        explain_response(raw, response)["explanations"]}
        blocked = explanations["blocked-is-false"]
        self.assertEqual(blocked["observed_type"], "integer")
        self.assertEqual(blocked["expected_types"], ["boolean"])
        self.assertEqual(blocked["reason_code"], "VALUE_NOT_FALSE")
        self.assertIsNone(explanations["summary-present"]["expected_types"])
        self.assertEqual(explanations["summary-present"]["observed_type"], "string")

    def test_literal_form_and_number_admits_integer(self):
        item = detail(rule("e", "equals", value=1.0), {"field": 1}, version="1.0")
        self.assertEqual((item["expected_types"], item["observed_type"]), (["number"], "integer"))
        item = detail(rule("t", "type", types=["number"]), {"field": 1})
        self.assertEqual(item["expected_types"], ["integer", "number"])
        self.assertEqual(item["reason_code"], "RULE_SATISFIED")
        self.assertIn(item["observed_type"], item["expected_types"])

    def test_null_and_mixed_one_of_types(self):
        item = detail(rule("f", "false"), {"field": None}, version="1.0")
        self.assertEqual(item["observed_type"], "null")
        item = detail(rule("o", "one_of", values=["b", 2, "a", 1.5, None, True, [], {}]),
                      {"field": "c"}, version="1.0")
        self.assertEqual(item["expected_types"],
                         ["array", "boolean", "integer", "null", "number", "object", "string"])

    def test_every_kind_names_its_expected_types(self):
        cases = [
            (rule("e", "empty_list"), ["array"]),
            (rule("r", "range", minimum=0), ["integer", "number"]),
            (rule("l", "length", maximum=2), ["array", "object", "string"]),
            (rule("t", "type", types=["string", "null"]), ["null", "string"]),
            (rule("q", "required_field"), None),
        ]
        for raw, expected in cases:
            with self.subTest(kind=raw["kind"]):
                self.assertEqual(detail(raw, {"field": "x"})["expected_types"], expected)

    def test_unresolved_paths_carry_no_observed_type(self):
        absent = detail(rule("f", "false", "a.b"), {"a": {}}, version="1.0")
        self.assertEqual(absent["resolution"], "member_absent")
        self.assertNotIn("observed_type", absent)
        parent = detail(rule("f", "false", "a.b"), {"a": 3}, version="1.0")
        self.assertEqual(parent["resolution"], "parent_not_object")
        self.assertNotIn("observed_type", parent)
        self.assertEqual(parent["expected_types"], ["boolean"])


class ViolatedBoundTests(unittest.TestCase):
    def test_range_and_length_name_the_crossed_bound(self):
        cases = [
            (rule("r", "range", minimum=0, maximum=1), 2, "maximum"),
            (rule("r", "range", minimum=0, maximum=1), -0.5, "minimum"),
            (rule("r", "range", maximum=1), 1.5, "maximum"),
            (rule("l", "length", minimum=2), "a", "minimum"),
            (rule("l", "length", maximum=1), [1, 2], "maximum"),
            (rule("l", "length", minimum=1, maximum=1), {}, "minimum"),
        ]
        for raw, value, bound in cases:
            with self.subTest(rule=raw, value=value):
                self.assertEqual(detail(raw, {"field": value})["violated_bound"], bound)

    def test_no_bound_for_type_failures_or_passes(self):
        for raw, value in ((rule("r", "range", minimum=0), "1"),
                           (rule("l", "length", maximum=1), 5),
                           (rule("r", "range", minimum=0), 1),
                           (rule("t", "type", types=["string"]), 1)):
            with self.subTest(rule=raw, value=value):
                self.assertNotIn("violated_bound", detail(raw, {"field": value}))


class ValueFreeTests(unittest.TestCase):
    def test_no_response_value_or_length_appears_in_the_output(self):
        marker = "unique-marker-7f3a"
        raw = policy(rule("t", "type", "a", types=["integer"]),
                     rule("l", "length", "b", maximum=3),
                     rule("o", "one_of", "c", values=["x"]),
                     rule("r", "range", "d", maximum=1))
        response = {"a": marker, "b": marker * 3, "c": marker, "d": 12345.678}
        report = explain_response(raw, response)
        serialized = json.dumps(report)
        self.assertNotIn(marker, serialized)
        self.assertNotIn("12345", serialized)
        self.assertNotIn(str(len(marker) * 3), serialized)
        self.assertIs(report["values_included"], False)

    def test_evaluation_block_matches_the_public_evaluator(self):
        from constitutional_agent_testbench import evaluate_response

        raw = load_json(EXAMPLES / "typed-policy.json")
        response = load_json(EXAMPLES / "typed-failing-response.json")
        self.assertEqual(explain_response(raw, response)["evaluation"],
                         evaluate_response(raw, response))

    def test_policy_is_validated_once(self):
        raw = load_json(EXAMPLES / "policy.json")
        with patch.object(explain, "validate_policy", wraps=explain.validate_policy) as validate:
            explain_response(raw, load_json(EXAMPLES / "failing-response.json"))
        self.assertEqual(validate.call_count, 1)

    def test_output_is_stable(self):
        raw = load_json(EXAMPLES / "typed-policy.json")
        response = load_json(EXAMPLES / "typed-failing-response.json")
        self.assertEqual(stable_json(explain_response(raw, response)),
                         stable_json(explain_response(raw, response)))


if __name__ == "__main__":
    unittest.main()
