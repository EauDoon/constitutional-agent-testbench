"""Compile-once evaluation must match the public per-call evaluator exactly."""

import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from constitutional_agent_testbench import evaluator, precedence, probes, suite, synthetic
from constitutional_agent_testbench.common import load_json, stable_json
from constitutional_agent_testbench.evaluator import evaluate_response
from constitutional_agent_testbench.precedence import check_order_conformance
from constitutional_agent_testbench.probes import generate_rule_probes
from constitutional_agent_testbench.suite import evaluate_suite

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

NESTED_POLICY = {
    "schema_version": "1.0",
    "policy_id": "nested-seven",
    "rules": [
        {"rule_id": "summary", "kind": "required_field", "path": "summary"},
        {"rule_id": "decision", "kind": "equals", "path": "decision", "value": "accept"},
        {"rule_id": "risk", "kind": "one_of", "path": "risk_level", "values": ["low", "moderate"]},
        {"rule_id": "blocked", "kind": "false", "path": "blocked"},
        {"rule_id": "actions", "kind": "empty_list", "path": "actions"},
        {"rule_id": "model", "kind": "required_field", "path": "meta.model"},
        {"rule_id": "lang", "kind": "one_of", "path": "meta.lang", "values": ["en", "fr", 1, 1.0]},
    ],
}
NESTED_RESPONSES = (
    {"summary": "s", "decision": "accept", "risk_level": "low", "blocked": False,
     "actions": [], "meta": {"model": "m", "lang": "en"}},
    {"summary": "s", "decision": "reject", "risk_level": "high", "blocked": 0,
     "actions": [1], "meta": {"lang": True}},
    {"decision": "accept", "meta": "flat", "blocked": False, "actions": []},
)


def _generic(policy, response):
    """A wrapper is not the built-in by identity, so it takes the guarded path."""

    return evaluate_response(policy, response)


def _count_validations():
    """Patch every module-level validate_policy reference with a shared counter."""

    stack = ExitStack()
    calls = []

    def counting(original):
        def wrapped(raw):
            calls.append(1)
            return original(raw)
        return wrapped

    for module in (evaluator, suite, probes, synthetic):
        stack.enter_context(patch.object(module, "validate_policy",
                                         counting(module.validate_policy)))
    return stack, calls


class SuiteEqualityTests(unittest.TestCase):
    def test_suite_rows_equal_per_case_public_evaluation(self):
        pairs = [
            ("policy.json", "regression-suite.json"),
            ("policy.json", "assertion-suite.json"),
            ("migration-policy.json", "regression-suite.json"),
            ("release-approval/policy-before.json", "release-approval/suite-before.json"),
            ("release-approval/policy-after.json", "release-approval/suite-after.json"),
            ("release-approval/policy-before.json", "release-approval/suite-after.json"),
        ]
        for policy_name, suite_name in pairs:
            raw_policy = load_json(EXAMPLES / policy_name)
            fixtures = load_json(EXAMPLES / suite_name)
            with self.subTest(policy=policy_name, suite=suite_name):
                report = evaluate_suite(raw_policy, fixtures)
                for case, row in zip(fixtures["cases"], report["cases"], strict=True):
                    self.assertEqual(row["evaluation"],
                                     evaluate_response(raw_policy, case["response"]))

    def test_equals_and_one_of_keep_literal_number_and_boolean_forms(self):
        raw_policy = {"schema_version": "1.0", "policy_id": "literal", "rules": [
            {"rule_id": "one", "kind": "equals", "path": "one", "value": 1},
            {"rule_id": "choice", "kind": "one_of", "path": "choice", "values": [0, "x"]},
        ]}
        cases = [({"one": 1, "choice": 0}, True), ({"one": 1.0, "choice": 0}, False),
                 ({"one": True, "choice": 0}, False), ({"one": 1, "choice": False}, False),
                 ({"one": 1, "choice": 0.0}, False), ({"one": 1, "choice": "x"}, True)]
        fixtures = {"suite_version": "1.0", "cases": [
            {"case_id": f"c{index}", "response": response, "expected_passed": expected}
            for index, (response, expected) in enumerate(cases)]}
        report = evaluate_suite(raw_policy, fixtures)
        self.assertTrue(report["matches_expectations"])
        for (response, _expected), row in zip(cases, report["cases"], strict=True):
            self.assertEqual(row["evaluation"], evaluate_response(raw_policy, response))


class ValidationCountTests(unittest.TestCase):
    """Deterministic proxy for per-case cost: validation must not scale with cases."""

    def _suite(self, count):
        return {"suite_version": "1.0", "cases": [
            {"case_id": f"case-{index}", "response": {"action": index % 2 == 0},
             "expected_passed": index % 2 != 0} for index in range(count)]}

    def test_suite_validates_the_policy_once_regardless_of_case_count(self):
        raw_policy = {"schema_version": "1.0", "policy_id": "count", "rules": [
            {"rule_id": "action", "kind": "false", "path": "action"}]}
        counts = []
        for size in (1, 200):
            stack, calls = _count_validations()
            with stack:
                self.assertTrue(evaluate_suite(raw_policy, self._suite(size))["matches_expectations"])
            counts.append(len(calls))
        self.assertEqual(counts[0], counts[1])
        self.assertEqual(counts[0], 1)

    def test_probes_validate_a_constant_number_of_times_regardless_of_rule_count(self):
        def policy_with(count):
            return {"schema_version": "1.0", "policy_id": "probe-count", "rules": [
                {"rule_id": f"r{index}", "kind": "one_of", "path": f"f{index}",
                 "values": ["a", "b"]} for index in range(count)]}

        counts = []
        for size in (1, 32):
            stack, calls = _count_validations()
            with stack:
                generate_rule_probes(policy_with(size))
            counts.append(len(calls))
        self.assertEqual(counts[0], counts[1])


class CheckOrderFastPathTests(unittest.TestCase):
    def _assert_identical(self, raw_policy, response):
        fast = check_order_conformance(raw_policy, response)
        generic = check_order_conformance(raw_policy, response, evaluator=_generic)
        self.assertEqual(stable_json(fast), stable_json(generic))
        return fast

    def test_builtin_fast_path_reports_match_the_guarded_path_byte_for_byte(self):
        raw_policy = load_json(EXAMPLES / "policy.json")
        for name in ("passing-response.json", "failing-response.json"):
            with self.subTest(response=name):
                self._assert_identical(raw_policy, load_json(EXAMPLES / name))
        # All seven nested rules on the mixed failure; the other responses use a
        # five-rule subset that keeps both nested paths, so the suite stays fast.
        report = self._assert_identical(NESTED_POLICY, NESTED_RESPONSES[1])
        self.assertEqual(report["coverage"]["orders_evaluated"], 5040)
        subset = dict(NESTED_POLICY, rules=NESTED_POLICY["rules"][1:3] + NESTED_POLICY["rules"][4:])
        for response in NESTED_RESPONSES:
            with self.subTest(response=response):
                report = self._assert_identical(subset, response)
                self.assertEqual(report["coverage"]["orders_evaluated"], 120)

    def test_builtin_identity_skips_guards_and_custom_evaluators_keep_them(self):
        raw_policy = load_json(EXAMPLES / "policy.json")
        response = load_json(EXAMPLES / "passing-response.json")
        with patch.object(precedence, "_run_evaluator",
                          wraps=precedence._run_evaluator) as guarded:
            check_order_conformance(raw_policy, response)
            self.assertEqual(guarded.call_count, 0)
            check_order_conformance(raw_policy, response, evaluator=_generic)
            self.assertEqual(guarded.call_count, 360)

    def test_fast_path_keeps_the_per_result_byte_limit(self):
        raw_policy = load_json(EXAMPLES / "policy.json")
        response = load_json(EXAMPLES / "passing-response.json")
        with patch.object(precedence, "MAX_EVALUATOR_RESULT_BYTES", 10):
            with self.assertRaisesRegex(precedence.OrderCheckTooLargeError, "per-result"):
                check_order_conformance(raw_policy, response)
            with self.assertRaisesRegex(precedence.OrderCheckTooLargeError, "per-result"):
                check_order_conformance(raw_policy, response, evaluator=_generic)


if __name__ == "__main__":
    unittest.main()
