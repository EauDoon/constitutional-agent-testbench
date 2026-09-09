import copy
import unittest
from unittest.mock import patch
from pathlib import Path

from constitutional_agent_testbench.authoring import lint_policy
from constitutional_agent_testbench.authoring import AuthoringLimitError
from constitutional_agent_testbench.common import load_json, parse_json_text, stable_json
from constitutional_agent_testbench.explain import explain_response
from constitutional_agent_testbench.evaluator import EvaluationInputError
from constitutional_agent_testbench.suite import evaluate_suite, validate_suite, SuiteInputError
from constitutional_agent_testbench.coverage import suite_coverage
from constitutional_agent_testbench.compare import compare_policies
from constitutional_agent_testbench.probes import generate_rule_probes
from constitutional_agent_testbench.synthetic import SyntheticGenerationError
from constitutional_agent_testbench.receipt import create_receipt, verify_receipt, ReceiptInputError


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


class ComparisonTests(unittest.TestCase):
    def test_migration_and_definition_changes(self):
        report = compare_policies(policy(rule()), policy(rule(kind="equals", value=True)), suite())
        self.assertEqual(report["rule_changes"]["modified"], ["r"])
        self.assertEqual(report["newly_failing"], ["pass"])
        self.assertEqual(report["newly_passing"], [])
        self.assertFalse(report["after_matches_expectations"])

    def test_reorder_is_visible_without_verdict_drift(self):
        old = policy(rule(), rule("present", "required_field"))
        new = copy.deepcopy(old)
        new["rules"].reverse()
        report = compare_policies(old, new, suite())
        self.assertTrue(report["rule_changes"]["order_changed"])
        self.assertEqual(report["verdict_change_count"], 0)
        self.assertEqual(report["cases"][0]["changed_rule_results"], [])

    def test_added_and_removed_rules(self):
        report = compare_policies(policy(rule()), policy(rule("new")), suite())
        self.assertEqual(report["rule_changes"]["removed"], ["r"])
        self.assertEqual(report["rule_changes"]["added"], ["new"])


class ProbeTests(unittest.TestCase):
    def test_verified_round_trip_and_collateral(self):
        raw = policy(rule(), rule("present", "required_field"))
        report = generate_rule_probes(raw)
        self.assertTrue(evaluate_suite(raw, report["suite"])["matches_expectations"])
        self.assertEqual(report["probes"][0]["failed_rule_ids"], ["present", "r"])
        self.assertEqual(report["probes"][1]["failed_rule_ids"], ["r"])
        reloaded = parse_json_text(stable_json(report))
        self.assertTrue(evaluate_suite(raw, reloaded["suite"])["matches_expectations"])

    def test_all_rule_kinds(self):
        raw = policy(rule("equal", "equals", "a", value=None),
                     rule("allowed", "one_of", "b", values=["synthetic-probe-0"]),
                     rule("empty", "empty_list", "c"))
        report = generate_rule_probes(raw)
        self.assertEqual(len(report["probes"]), 6)
        self.assertTrue(evaluate_suite(raw, report["suite"])["matches_expectations"])

    def test_rule_limit_and_conflict(self):
        for raw in (policy(*(rule(str(i), path=f"field{i}") for i in range(65))),
                    policy(rule(), rule("conflict", "equals", value=True))):
            with self.assertRaises(SyntheticGenerationError):
                generate_rule_probes(raw)


class ReceiptTests(unittest.TestCase):
    def test_round_trip_and_key_order(self):
        raw = policy(rule())
        response = {"z": 1, "action": False}
        receipt = create_receipt(raw, response)
        self.assertTrue(verify_receipt(raw, {"action": False, "z": 1}, receipt)["verified"])
        self.assertNotIn("response", receipt)

    def test_tamper_wrong_inputs_and_bool_integer(self):
        raw = policy(rule())
        receipt = create_receipt(raw, {"action": False})
        receipt["evaluation"]["passed"] = 1
        self.assertEqual(verify_receipt(raw, {"action": False}, receipt)["mismatched_fields"], ["evaluation"])
        fresh = create_receipt(raw, {"action": False})
        report = verify_receipt(raw, {"action": True}, fresh)
        self.assertEqual(report["mismatched_fields"], ["evaluation", "response_digest"])

    def test_rejects_unknown_fields_and_bad_digests(self):
        for mutate in (lambda r: r.update(extra=True), lambda r: r.update(policy_digest="wrong")):
            raw = policy(rule())
            receipt = create_receipt(raw, {})
            mutate(receipt)
            with self.assertRaises(ReceiptInputError):
                verify_receipt(raw, {}, receipt)

    def test_policy_identity_and_rule_order_are_bound(self):
        raw = policy(rule(), rule("present", "required_field"))
        receipt = parse_json_text(stable_json(create_receipt(raw, {"action": False})))
        changed = copy.deepcopy(raw)
        changed["rules"].reverse()
        self.assertEqual(verify_receipt(changed, {"action": False}, receipt)["mismatched_fields"],
                         ["evaluation", "policy_digest"])
        changed = copy.deepcopy(raw)
        changed["policy_id"] = "new-policy"
        self.assertFalse(verify_receipt(changed, {"action": False}, receipt)["verified"])


class OperatorBoundaryTests(unittest.TestCase):
    def test_authoring_work_limit(self):
        raw = policy(rule("parent", "equals", "action", value={"name": False}),
                     rule("child", "false", "action.name"))
        with patch("constitutional_agent_testbench.authoring.MAX_AUTHORING_WORK_BYTES", 1):
            with self.assertRaises(AuthoringLimitError):
                lint_policy(raw)

    def test_suite_work_limit(self):
        with patch("constitutional_agent_testbench.suite.MAX_SUITE_POLICY_BYTES", 1):
            with self.assertRaises(SuiteInputError):
                evaluate_suite(policy(rule()), suite())

    def test_probe_output_limit(self):
        with patch("constitutional_agent_testbench.probes.MAX_JSON_INPUT_BYTES", 300):
            with self.assertRaises(SyntheticGenerationError):
                generate_rule_probes(policy(rule()))

    def test_receipt_output_limit(self):
        with patch("constitutional_agent_testbench.receipt.MAX_JSON_INPUT_BYTES", 10):
            with self.assertRaises(ReceiptInputError):
                create_receipt(policy(rule()), {})

    def test_bundled_operator_fixtures(self):
        root = Path(__file__).resolve().parents[1] / "examples"
        raw = load_json(root / "policy.json")
        fixtures = load_json(root / "regression-suite.json")
        self.assertTrue(evaluate_suite(raw, fixtures)["matches_expectations"])
        self.assertEqual(suite_coverage(raw, fixtures)["rules_with_both_outcomes"], 5)
        migration = compare_policies(raw, load_json(root / "migration-policy.json"), fixtures)
        self.assertEqual(migration["newly_failing"], ["passing"])

    def test_public_api_and_version(self):
        import constitutional_agent_testbench as package
        self.assertEqual(package.__version__, "0.3.0")
        for name in ("lint_policy", "explain_response", "evaluate_suite", "suite_coverage",
                     "compare_policies", "generate_rule_probes", "create_receipt", "verify_receipt"):
            self.assertTrue(callable(getattr(package, name)))


class AuthoringTests(unittest.TestCase):
    def test_strict_types_and_no_mutation(self):
        raw = policy(rule(), rule("n", "equals", value=0))
        before = copy.deepcopy(raw)
        self.assertTrue(lint_policy(raw)["has_conflicts"])
        self.assertEqual(raw, before)

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
