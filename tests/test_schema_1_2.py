"""Policy schema 1.2: when guards, compare and each rules."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from constitutional_agent_testbench import (
    PolicyValidationError,
    audit_assertions,
    check_order_conformance,
    evaluate_response,
    evaluate_suite,
    explain_response,
    generate_rule_probes,
    generate_synthetic_cases,
    lint_policy,
    suite_coverage,
    validate_policy,
    validate_suite,
)
from constitutional_agent_testbench.coverage import reachable_reason_codes
from constitutional_agent_testbench.policy import policy_to_dict
from constitutional_agent_testbench.suite import SuiteInputError
from constitutional_agent_testbench.synthetic import SyntheticGenerationError

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((ROOT / "examples" / "conditional-policy.json").read_text("utf-8"))
PASSING = json.loads((ROOT / "examples" / "conditional-passing-response.json").read_text("utf-8"))
FAILING = json.loads((ROOT / "examples" / "conditional-failing-response.json").read_text("utf-8"))
REFUND = [{"path": "action_type", "values": ["refund.issue"]}]


def policy(*rules: dict, version: str = "1.2") -> dict:
    return {"schema_version": version, "policy_id": "schema-1-2", "rules": list(rules)}


def reasons(document: dict, response: dict) -> dict[str, str]:
    return {row["rule_id"]: row["reason_code"]
            for row in evaluate_response(document, response)["rule_results"]}


class ValidationTests(unittest.TestCase):
    def assert_invalid(self, document: dict, fragment: str) -> None:
        with self.assertRaises(PolicyValidationError) as raised:
            validate_policy(document)
        self.assertIn(fragment, str(raised.exception))

    def test_example_round_trips(self) -> None:
        validated = validate_policy(EXAMPLE)
        self.assertEqual(validate_policy(policy_to_dict(validated)), validated)
        self.assertEqual(validate_policy(validated), validated)
        self.assertEqual(policy_to_dict(validated)["rules"][3]["item"],
                         EXAMPLE["rules"][3]["item"])

    def test_new_kinds_and_guards_need_schema_1_2(self) -> None:
        self.assert_invalid(policy({"rule_id": "c", "kind": "compare", "path": "a", "op": "eq",
                                    "other_path": "b"}, version="1.1"), "unknown rule kind")
        self.assert_invalid(policy({"rule_id": "r", "kind": "required_field", "path": "a",
                                    "when": REFUND}, version="1.1"), "unknown when")

    def test_rejects_malformed_rules(self) -> None:
        cases = [
            ({"rule_id": "c", "kind": "compare", "path": "a", "op": "like", "other_path": "b"},
             "op must be one of"),
            ({"rule_id": "c", "kind": "compare", "path": "a", "op": "eq", "other_path": "a"},
             "must differ"),
            ({"rule_id": "c", "kind": "compare", "path": "a", "op": "eq"}, "missing other_path"),
            ({"rule_id": "c", "kind": "compare", "path": "a", "op": "eq", "other_path": "b..c"},
             "other_path is not a valid"),
            ({"rule_id": "e", "kind": "each", "path": "a", "item": []}, "item must be a JSON object"),
            ({"rule_id": "e", "kind": "each", "path": "a", "item": {"kind": "each"}}, "item kind"),
            ({"rule_id": "e", "kind": "each", "path": "a", "item": {"kind": "compare"}}, "item kind"),
            ({"rule_id": "e", "kind": "each", "path": "a",
              "item": {"kind": "false", "when": REFUND}}, "unknown when"),
            ({"rule_id": "e", "kind": "each", "path": "a", "item": {"kind": "equals"}},
             "missing value"),
            ({"rule_id": "e", "kind": "each", "path": "a",
              "item": {"kind": "range", "path": "x"}}, "minimum, maximum or both"),
            ({"rule_id": "e", "kind": "each", "path": "a",
              "item": {"kind": "false", "path": ".".join(["p"] * 32)}}, "path limit"),
            ({"rule_id": "w", "kind": "false", "path": "a", "when": []}, "1 to 8 conditions"),
            ({"rule_id": "w", "kind": "false", "path": "a", "when": REFUND * 9}, "1 to 8"),
            ({"rule_id": "w", "kind": "false", "path": "a", "when": ["x"]}, "must be a JSON object"),
            ({"rule_id": "w", "kind": "false", "path": "a",
              "when": [{"path": "b", "values": [1, 1]}]}, "duplicates"),
            ({"rule_id": "w", "kind": "false", "path": "a",
              "when": [{"path": "b", "value": 1}]}, "invalid fields"),
            ({"rule_id": "w", "kind": "false", "path": "a",
              "when": [{"path": "b", "values": []}]}, "non-empty"),
        ]
        for rule, fragment in cases:
            with self.subTest(rule=rule):
                self.assert_invalid(policy(rule), fragment)

    def test_policy_objects_reject_fields_of_another_kind(self) -> None:
        from dataclasses import replace

        validated = validate_policy(EXAMPLE)
        for index, change in ((0, {"op": "eq"}), (0, {"other_path": "x"}),
                              (2, {"item": validated.rules[0]}), (0, {"item_path": "x"})):
            broken = replace(validated, rules=tuple(
                replace(rule, **change) if position == index else rule
                for position, rule in enumerate(validated.rules)))
            with self.subTest(change=change), self.assertRaises(PolicyValidationError):
                validate_policy(broken)


class EvaluationTests(unittest.TestCase):
    def test_example_verdicts(self) -> None:
        self.assertTrue(evaluate_response(EXAMPLE, PASSING)["passed"])
        self.assertEqual(reasons(EXAMPLE, FAILING), {
            "known-action": "RULE_SATISFIED",
            "refund-within-limit": "RULE_NOT_APPLICABLE",
            "refund-at-most-order-total": "RULE_NOT_APPLICABLE",
            "recipients-allowlisted": "VALUE_ITEM_FAILED",
            "expires-after-request": "VALUE_COMPARISON_FAILED",
        })

    def test_guards(self) -> None:
        document = policy({"rule_id": "r", "kind": "range", "path": "amount", "maximum": 10,
                           "when": REFUND + [{"path": "mode", "values": ["live", "test"]}]})
        cases = [
            ({}, "RULE_NOT_APPLICABLE"),
            ({"action_type": "refund.issue"}, "RULE_NOT_APPLICABLE"),
            ({"action_type": "refund.issue", "mode": "dry"}, "RULE_NOT_APPLICABLE"),
            ({"action_type": "refund.issue", "mode": "test"}, "FIELD_MISSING"),
            ({"action_type": "refund.issue", "mode": "live", "amount": 11}, "VALUE_OUT_OF_RANGE"),
            ({"action_type": "refund.issue", "mode": "live", "amount": 3}, "RULE_SATISFIED"),
            ({"action_type": ["refund.issue"], "mode": "live"}, "RULE_NOT_APPLICABLE"),
        ]
        for response, expected in cases:
            with self.subTest(response=response):
                self.assertEqual(reasons(document, response)["r"], expected)

    def test_compare(self) -> None:
        def outcome(op: str, left, right) -> str:
            document = policy({"rule_id": "c", "kind": "compare", "path": "a", "op": op,
                               "other_path": "b"})
            response = {"a": left, "b": right}
            return reasons(document, response)["c"]

        satisfied = [("eq", 1, 1), ("eq", {"x": [1]}, {"x": [1]}), ("ne", 1, 1.0),
                     ("ne", True, 1), ("lt", 1, 2), ("lte", 2, 2.0), ("gt", 3, 2.5),
                     ("gte", 2**60, 2**60), ("lt", "2026-11-28T02:30:00.000Z", "2026-11-28T02:31:00.000Z"),
                     ("gte", "b", "a")]
        failed = [("eq", 1, 1.0), ("ne", "x", "x"), ("lt", 2, 2), ("gt", True, False),
                  ("lte", "1", 2), ("gte", None, None), ("lt", [1], [2]), ("gt", "a", "b")]
        for op, left, right in satisfied:
            with self.subTest(op=op, left=left, right=right):
                self.assertEqual(outcome(op, left, right), "RULE_SATISFIED")
        for op, left, right in failed:
            with self.subTest(op=op, left=left, right=right):
                self.assertEqual(outcome(op, left, right), "VALUE_COMPARISON_FAILED")
        document = policy({"rule_id": "c", "kind": "compare", "path": "a", "op": "eq",
                           "other_path": "b"})
        self.assertEqual(reasons(document, {"a": 1})["c"], "FIELD_MISSING")
        self.assertEqual(reasons(document, {"b": 1})["c"], "FIELD_MISSING")

    def test_each(self) -> None:
        document = policy(
            {"rule_id": "self", "kind": "each", "path": "tags",
             "item": {"kind": "type", "types": ["string"]}},
            {"rule_id": "sub", "kind": "each", "path": "rows",
             "item": {"kind": "range", "path": "cost.minor", "minimum": 0}},
        )
        cases = [
            ({"tags": [], "rows": []}, ("RULE_SATISFIED", "RULE_SATISFIED")),
            ({"tags": ["a", "b"], "rows": [{"cost": {"minor": 0}}]}, ("RULE_SATISFIED", "RULE_SATISFIED")),
            ({"tags": ["a", 1], "rows": [{"cost": {"minor": -1}}]}, ("VALUE_ITEM_FAILED", "VALUE_ITEM_FAILED")),
            ({"tags": "a", "rows": [{"cost": 5}]}, ("VALUE_ITEM_FAILED", "VALUE_ITEM_FAILED")),
            ({"rows": [{}]}, ("FIELD_MISSING", "VALUE_ITEM_FAILED")),
        ]
        for response, (first, second) in cases:
            with self.subTest(response=response):
                observed = reasons(document, response)
                self.assertEqual((observed["self"], observed["sub"]), (first, second))


class ToolingTests(unittest.TestCase):
    def test_synthetic_and_probes_cover_the_example(self) -> None:
        bundle = generate_synthetic_cases(EXAMPLE)
        self.assertTrue(bundle["passing_case"]["evaluation"]["passed"])
        self.assertFalse(bundle["failing_case"]["evaluation"]["passed"])
        probes = generate_rule_probes(EXAMPLE)
        targets = {probe["target_rule_id"] for probe in probes["probes"]}
        self.assertEqual(targets, {rule["rule_id"] for rule in EXAMPLE["rules"]})
        report = evaluate_suite(EXAMPLE, probes["suite"])
        self.assertTrue(report["matches_expectations"])

    def test_synthetic_meets_each_operator_and_length(self) -> None:
        for op in ("eq", "ne", "lt", "lte", "gt", "gte"):
            for preset in ({}, {"rule_id": "a-set", "kind": "equals", "path": "a", "value": 5},
                           {"rule_id": "b-set", "kind": "equals", "path": "b", "value": "m"},
                           {"rule_id": "b-null", "kind": "type", "path": "b", "types": ["null"]}):
                rules = [{"rule_id": "c", "kind": "compare", "path": "a", "op": op, "other_path": "b"}]
                if preset:
                    rules.append(preset)
                with self.subTest(op=op, preset=preset.get("rule_id")):
                    try:
                        bundle = generate_synthetic_cases(policy(*rules))
                    except SyntheticGenerationError:
                        # Only ordering against null has no satisfying value.
                        self.assertEqual(preset.get("rule_id"), "b-null")
                        self.assertIn(op, ("lt", "lte", "gt", "gte"))
                        continue
                    self.assertTrue(bundle["passing_case"]["evaluation"]["passed"])
        document = policy(
            {"rule_id": "each", "kind": "each", "path": "rows",
             "item": {"kind": "equals", "path": "kind", "value": "line"}},
            {"rule_id": "count", "kind": "length", "path": "rows", "minimum": 2})
        rows = generate_synthetic_cases(document)["passing_case"]["response"]["rows"]
        self.assertEqual(rows, [{"kind": "line"}, {"kind": "line"}])
        with self.assertRaises(SyntheticGenerationError):
            generate_synthetic_cases(policy(
                {"rule_id": "lt", "kind": "compare", "path": "a", "op": "lt", "other_path": "b"},
                {"rule_id": "a", "kind": "equals", "path": "a", "value": 2},
                {"rule_id": "b", "kind": "equals", "path": "b", "value": 1}))

    def test_failing_case_meets_a_guard_when_needed(self) -> None:
        document = policy({"rule_id": "r", "kind": "required_field", "path": "amount",
                           "when": REFUND})
        failing = generate_synthetic_cases(document)["failing_case"]
        self.assertEqual(failing["response"], {"action_type": "refund.issue"})

    def test_probe_values_for_each_items(self) -> None:
        document = policy(
            {"rule_id": "present", "kind": "each", "path": "rows",
             "item": {"kind": "required_field", "path": "id"}},
            {"rule_id": "self", "kind": "each", "path": "tags", "item": {"kind": "required_field"}},
            {"rule_id": "enum", "kind": "each", "path": "codes", "item": {"kind": "one_of",
                                                                          "values": ["a"]}},
            {"rule_id": "ne", "kind": "compare", "path": "x", "op": "ne", "other_path": "y"})
        probes = generate_rule_probes(document)
        self.assertTrue(evaluate_suite(document, probes["suite"])["matches_expectations"])

    def test_lint_respects_guards_and_new_kinds(self) -> None:
        document = policy(
            {"rule_id": "refund", "kind": "equals", "path": "fee", "value": 0, "when": REFUND},
            {"rule_id": "other", "kind": "equals", "path": "fee", "value": 5},
            {"rule_id": "again", "kind": "equals", "path": "fee", "value": 0, "when": REFUND},
            {"rule_id": "c1", "kind": "compare", "path": "a", "op": "lt", "other_path": "b"},
            {"rule_id": "c2", "kind": "compare", "path": "a", "op": "lt", "other_path": "c"},
            {"rule_id": "e1", "kind": "each", "path": "rows", "item": {"kind": "false"}},
            {"rule_id": "e2", "kind": "each", "path": "rows", "item": {"kind": "false"}})
        findings = lint_policy(document)["findings"]
        self.assertFalse(lint_policy(document)["has_conflicts"])
        self.assertEqual(sorted(tuple(item["rule_ids"]) for item in findings),
                         [("again", "refund"), ("e1", "e2")])

    def test_coverage_assertions_explain_and_order_check(self) -> None:
        self.assertEqual(reachable_reason_codes("compare", guarded=True),
                         ["FIELD_MISSING", "RULE_NOT_APPLICABLE", "RULE_SATISFIED",
                          "VALUE_COMPARISON_FAILED"])
        suite = {"suite_version": "1.1", "cases": [
            {"case_id": "pass", "response": PASSING, "expected_passed": True,
             "expected_rules": {"recipients-allowlisted": {"passed": True,
                                                            "reason_code": "RULE_NOT_APPLICABLE"}}},
            {"case_id": "fail", "response": FAILING, "expected_passed": False}]}
        self.assertTrue(evaluate_suite(EXAMPLE, suite)["matches_expectations"])
        self.assertTrue(audit_assertions(EXAMPLE, suite)["assertions_compatible"])
        unguarded = {**suite, "cases": [{**suite["cases"][0], "expected_rules": {
            "known-action": {"passed": True, "reason_code": "RULE_NOT_APPLICABLE"}}}]}
        self.assertFalse(audit_assertions(EXAMPLE, unguarded)["assertions_compatible"])
        with self.assertRaises(SuiteInputError):
            validate_suite({"suite_version": "1.1", "cases": [
                {"case_id": "x", "response": {}, "expected_passed": True,
                 "expected_rules": {"r": {"passed": False, "reason_code": "RULE_NOT_APPLICABLE"}}}]})
        rows = {row["rule_id"]: row for row in suite_coverage(EXAMPLE, suite)["rules"]}
        self.assertIn("RULE_NOT_APPLICABLE", rows["refund-within-limit"]["reason_counts"])
        self.assertNotIn("RULE_NOT_APPLICABLE", rows["known-action"]["unexercised_reason_codes"])
        details = {item["rule_id"]: item for item in explain_response(EXAMPLE, FAILING)["explanations"]}
        self.assertFalse(details["refund-within-limit"]["guard_met"])
        self.assertTrue(details["recipients-allowlisted"]["guard_met"])
        self.assertEqual(details["recipients-allowlisted"]["expected_types"], ["array"])
        self.assertEqual(details["expires-after-request"]["other_path"], "requested_at")
        self.assertNotIn("guard_met", details["known-action"])
        small = policy(*EXAMPLE["rules"][:4])
        self.assertTrue(check_order_conformance(small, PASSING)["conforms_within_coverage"])


if __name__ == "__main__":
    unittest.main()
