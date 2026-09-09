import copy
import unittest

from constitutional_agent_testbench.authoring import lint_policy
from constitutional_agent_testbench.explain import explain_response
from constitutional_agent_testbench.evaluator import EvaluationInputError
from constitutional_agent_testbench.suite import evaluate_suite, validate_suite, SuiteInputError
from constitutional_agent_testbench.coverage import suite_coverage


def policy(*rules):
    return {"schema_version": "1.0", "policy_id": "demo", "rules": list(rules)}


def rule(identifier="r", kind="false", path="action", **fields):
    return {"rule_id": identifier, "kind": kind, "path": path, **fields}


def suite():
    return {"suite_version": "1.0", "cases": [
        {"case_id": "pass", "response": {"action": False}, "expected_passed": True},
        {"case_id": "fail", "response": {}, "expected_passed": False}]}


class SuiteTests(unittest.TestCase):
    def test_expected_failure_is_success(self):
        report = evaluate_suite(policy(rule()), suite())
        self.assertTrue(report["matches_expectations"])
        changed = suite()
        changed["cases"][0]["response"]["action"] = 0
        self.assertEqual(evaluate_suite(policy(rule()), changed)["mismatch_count"], 1)

    def test_rejects_duplicates_unknowns_and_truthy_expectations(self):
        for mutate in (lambda s: s["cases"].append(s["cases"][0]),
                       lambda s: s.update(extra=True),
                       lambda s: s["cases"][0].update(expected_passed=1),
                       lambda s: s.update(cases=[]),
                       lambda s: s.update(cases=s["cases"] * 129)):
            raw = suite()
            mutate(raw)
            with self.assertRaises(SuiteInputError):
                validate_suite(raw)

    def test_owns_copy_and_hides_response_values(self):
        raw = suite()
        raw["cases"][0]["response"]["secret"] = "private-string"
        owned = validate_suite(raw)
        owned["cases"].clear()
        self.assertEqual(len(raw["cases"]), 2)
        self.assertNotIn("private-string", str(evaluate_suite(policy(rule()), raw)))


class CoverageTests(unittest.TestCase):
    def test_counts_and_gaps(self):
        raw = policy(rule(), rule("always-missing", "required_field", "other"))
        report = suite_coverage(raw, suite())
        self.assertEqual(report["rules_with_both_outcomes"], 1)
        self.assertEqual(report["unexercised_passes"], ["always-missing"])
        self.assertEqual(report["rules"][1]["reason_counts"],
                         {"RULE_SATISFIED": 1, "FIELD_MISSING": 1})

    def test_invalid_suite_fails_closed(self):
        with self.assertRaises(SuiteInputError):
            suite_coverage(policy(rule()), {"suite_version": "1.0", "cases": []})


class AuthoringTests(unittest.TestCase):
    def test_strict_types_and_no_mutation(self):
        raw = policy(rule(), rule("n", "equals", value=0))
        before = copy.deepcopy(raw)
        self.assertTrue(lint_policy(raw)["has_conflicts"])
        self.assertEqual(raw, before)


class ExplanationTests(unittest.TestCase):
    def test_absent_member_and_scalar_parent(self):
        raw = policy(rule(path="action.name"))
        absent = explain_response(raw, {})["explanations"][0]
        self.assertEqual((absent["resolution"], absent["at"]), ("member_absent", "action"))
        scalar = explain_response(raw, {"action": "sensitive-value"})
        self.assertEqual(scalar["explanations"][0]["resolution"], "parent_not_object")
        self.assertNotIn("sensitive-value", str(scalar))

    def test_null_is_present_and_invalid_input_rejected(self):
        raw = policy(rule(kind="required_field"))
        self.assertTrue(explain_response(raw, {"action": None})["evaluation"]["passed"])
        with self.assertRaises(EvaluationInputError):
            explain_response(raw, [])

    def test_ancestor_and_duplicates(self):
        raw = policy(rule(), rule("other"), rule("child", "required_field", "action.name"))
        codes = {item["code"] for item in lint_policy(raw)["findings"]}
        self.assertEqual(codes, {"DUPLICATE_CONSTRAINT", "INCOMPATIBLE_DESCENDANTS"})

    def test_valid_nested_domain_and_null_presence(self):
        raw = policy(rule("parent", "one_of", "action", values=[{}, {"name": None}]),
                     rule("child", "required_field", "action.name"))
        self.assertFalse(lint_policy(raw)["has_conflicts"])

    def test_three_way_empty_intersection(self):
        raw = policy(*(rule(str(i), "one_of", values=v) for i, v in
                       enumerate(([1, 2], [2, 3], [1, 3]))))
        self.assertTrue(lint_policy(raw)["has_conflicts"])
