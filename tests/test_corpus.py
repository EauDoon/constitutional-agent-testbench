"""Corpus authoring contracts, including privacy and compatibility."""
import copy
import unittest

from constitutional_agent_testbench.inspection import inspect_policy
from constitutional_agent_testbench.inspection import inspect_suite
from constitutional_agent_testbench.curation import merge_suites, select_suite
from constitutional_agent_testbench.workflow import WorkflowInputError
from constitutional_agent_testbench.triage import triage_suite
from constitutional_agent_testbench.curation import reduce_suite
from constitutional_agent_testbench.coverage import suite_coverage
from constitutional_agent_testbench.corpus_receipt import create_suite_receipt, verify_suite_receipt
from constitutional_agent_testbench.replay import create_replay_bundle, replay_bundle
from constitutional_agent_testbench.suite import SuiteInputError, evaluate_suite, validate_suite


def policy():
    return {"schema_version": "1.0", "policy_id": "corpus", "rules": [
        {"rule_id": "r", "kind": "false", "path": "action"}]}


def suite():
    return {"suite_version": "1.0", "cases": [
        {"case_id": "pass", "response": {"action": False}, "expected_passed": True},
        {"case_id": "missing", "response": {}, "expected_passed": False},
        {"case_id": "wrong", "response": {"action": True}, "expected_passed": False}]}


class InspectionTests(unittest.TestCase):
    def test_duplicate_responses_and_conflicting_expectations(self):
        raw = suite()
        duplicate = copy.deepcopy(raw["cases"][0])
        duplicate.update(case_id="contradiction", expected_passed=False)
        raw["cases"].append(duplicate)
        result = inspect_suite(raw)
        self.assertFalse(result["consistent_expectations"])
        self.assertEqual(result["duplicate_responses"][0]["case_ids"], ["pass", "contradiction"])
        self.assertNotIn("response", result["duplicate_responses"][0])
        duplicate["response"]["action"] = 0
        self.assertTrue(inspect_suite(raw)["consistent_expectations"])

    def test_policy_inventory_does_not_copy_values(self):
        raw = policy()
        raw["rules"].append({"rule_id": "child", "kind": "equals", "path": "action.name", "value": "SYNTHETIC_PRIVATE"})
        before = copy.deepcopy(raw)
        result = inspect_policy(raw)
        self.assertEqual(result["paths"][1]["ancestor_paths"], ["action"])
        self.assertEqual(result["rule_count"], 2)
        self.assertNotIn("SYNTHETIC_PRIVATE", str(result))
        self.assertEqual(raw, before)


class CurationTests(unittest.TestCase):
    def test_reduction_retains_explicit_assertion_coverage(self):
        raw = suite()
        raw["suite_version"] = "1.1"
        asserted = copy.deepcopy(raw["cases"][0])
        asserted["case_id"] = "asserted"
        asserted["expected_rules"] = {"r": {"passed": True, "reason_code": "RULE_SATISFIED"}}
        raw["cases"].append(asserted)
        self.assertIn("asserted", [c["case_id"] for c in reduce_suite(policy(), raw)["cases"]])

    def test_reduction_keeps_reason_coverage_and_all_regressions(self):
        raw = suite()
        duplicate = copy.deepcopy(raw["cases"][0])
        duplicate["case_id"] = "redundant"
        raw["cases"].append(duplicate)
        result = reduce_suite(policy(), raw)
        self.assertEqual(result, suite())
        self.assertEqual(reduce_suite(policy(), raw), result)
        self.assertEqual(suite_coverage(policy(), raw)["rules"][0]["reason_counts"].keys(),
                         suite_coverage(policy(), result)["rules"][0]["reason_counts"].keys())
        raw["cases"][3]["expected_passed"] = False
        reduced = reduce_suite(policy(), raw)
        self.assertIn("redundant", [case["case_id"] for case in reduced["cases"]])
        self.assertFalse(evaluate_suite(policy(), reduced)["matches_expectations"])

    def test_selection_is_exact_and_preserves_original_order(self):
        result = select_suite(suite(), ["wrong", "pass"])
        self.assertEqual([c["case_id"] for c in result["cases"]], ["pass", "wrong"])
        for selection in ([], ["missing-id"], ["pass", "pass"], "pass", [True]):
            with self.assertRaises(WorkflowInputError):
                select_suite(suite(), selection)

    def test_merge_preserves_order_and_rejects_collisions(self):
        left, right = suite(), suite()
        for case in right["cases"]:
            case["case_id"] += "-new"
        merged = merge_suites(left, right)
        self.assertEqual(len(merged["cases"]), 6)
        merged["cases"][0]["response"].clear()
        self.assertTrue(left["cases"][0]["response"])
        with self.assertRaises(SuiteInputError):
            merge_suites(left, left)

    def test_merge_enforces_combined_case_limit(self):
        left = suite()
        left["cases"] = [{"case_id": str(i), "response": {}, "expected_passed": False} for i in range(256)]
        with self.assertRaises(SuiteInputError):
            merge_suites(left, suite())


class AssertionTests(unittest.TestCase):
    def test_duplicate_partial_assertions_can_be_compatible(self):
        raw = suite()
        raw["suite_version"] = "1.1"
        duplicate = copy.deepcopy(raw["cases"][0])
        duplicate["case_id"] = "duplicate"
        duplicate["expected_rules"] = {"r": {"passed": True, "reason_code": "RULE_SATISFIED"}}
        raw["cases"].append(duplicate)
        self.assertTrue(inspect_suite(raw)["consistent_expectations"])

    def test_wrong_failure_reason_is_a_regression(self):
        raw = suite()
        raw["suite_version"] = "1.1"
        raw["cases"][1]["expected_rules"] = {"r": {"passed": False, "reason_code": "VALUE_NOT_FALSE"}}
        result = evaluate_suite(policy(), raw)
        self.assertFalse(result["matches_expectations"])
        self.assertEqual(result["cases"][1]["rule_assertion_mismatches"], ["r"])
        raw["cases"][1]["expected_rules"]["r"]["reason_code"] = "FIELD_MISSING"
        self.assertTrue(evaluate_suite(policy(), raw)["matches_expectations"])
        raw["cases"][1]["expected_rules"]["removed"] = {"passed": False, "reason_code": "FIELD_MISSING"}
        self.assertFalse(evaluate_suite(policy(), raw)["matches_expectations"])

    def test_v10_report_shape_and_rejection_remain_unchanged(self):
        raw = suite()
        result = evaluate_suite(policy(), raw)
        self.assertEqual(set(result["cases"][0]), {"case_id", "expected_passed", "matches_expectation", "evaluation"})
        raw["cases"][0]["expected_rules"] = {}
        with self.assertRaises(SuiteInputError):
            validate_suite(raw)

    def test_v11_rejects_malformed_assertions(self):
        for expected in ({"r": {"passed": 1, "reason_code": "RULE_SATISFIED"}},
                         {"r": {"passed": False, "reason_code": "RULE_SATISFIED"}},
                         {"r": {"passed": False, "reason_code": "invented"}},
                         {"bad id": {"passed": False, "reason_code": "FIELD_MISSING"}}):
            raw = suite()
            raw["suite_version"] = "1.1"
            raw["cases"][0]["expected_rules"] = expected
            with self.assertRaises(SuiteInputError):
                validate_suite(raw)


class TriageTests(unittest.TestCase):
    def test_reports_only_regressions_and_never_candidate_values(self):
        raw = suite()
        raw["cases"][0]["response"] = {"action": "SYNTHETIC_PRIVATE"}
        raw["cases"][1]["expected_passed"] = True
        result = triage_suite(policy(), raw)
        self.assertEqual([c["case_id"] for c in result["mismatches"]], ["pass", "missing"])
        self.assertFalse(result["matches_expectations"])
        self.assertNotIn("SYNTHETIC_PRIVATE", str(result))
        self.assertEqual(len(result["failure_groups"]), 2)

    def test_unexpected_pass_remains_visible_without_failed_rules(self):
        raw = suite()
        raw["cases"][0]["expected_passed"] = False
        mismatch = triage_suite(policy(), raw)["mismatches"][0]
        self.assertTrue(mismatch["actual_passed"])
        self.assertEqual(mismatch["failed_rule_ids"], [])


class CorpusReceiptTests(unittest.TestCase):
    def test_receipt_binds_case_order_assertions_and_all_results(self):
        raw = suite()
        receipt = create_suite_receipt(policy(), raw)
        self.assertTrue(verify_suite_receipt(policy(), raw, receipt)["verified"])
        self.assertNotIn("response", str(receipt))
        raw["cases"].reverse()
        self.assertFalse(verify_suite_receipt(policy(), raw, receipt)["verified"])
        raw = suite()
        raw["cases"][0]["expected_passed"] = False
        self.assertFalse(verify_suite_receipt(policy(), raw, receipt)["verified"])
        receipt["evaluation"]["matches_expectations"] = 1
        self.assertFalse(verify_suite_receipt(policy(), suite(), receipt)["verified"])

    def test_malformed_receipt_and_size_limits_fail_closed(self):
        from unittest.mock import patch
        receipt = create_suite_receipt(policy(), suite())
        receipt["suite_digest"] = "bad"
        with self.assertRaises(WorkflowInputError):
            verify_suite_receipt(policy(), suite(), receipt)
        with patch("constitutional_agent_testbench.workflow.MAX_JSON_INPUT_BYTES", 10):
            with self.assertRaises(WorkflowInputError):
                create_suite_receipt(policy(), suite())


class ReplayTests(unittest.TestCase):
    def test_portable_bundle_recomputes_instead_of_trusting_claims(self):
        bundle = create_replay_bundle(policy(), suite())
        self.assertTrue(replay_bundle(bundle)["replay_passed"])
        bundle["suite"]["cases"][0]["response"]["private"] = "SYNTHETIC_PRIVATE"
        result = replay_bundle(bundle)
        self.assertFalse(result["verified"])
        self.assertIsNone(result["matches_expectations"])
        self.assertNotIn("SYNTHETIC_PRIVATE", str(result))
        bundle["command"] = "never-execute"
        with self.assertRaises(WorkflowInputError):
            replay_bundle(bundle)

    def test_consistent_failing_regression_is_not_a_passing_replay(self):
        raw = suite()
        raw["cases"][0]["expected_passed"] = False
        result = replay_bundle(create_replay_bundle(policy(), raw))
        self.assertTrue(result["verified"])
        self.assertFalse(result["matches_expectations"])
        self.assertFalse(result["replay_passed"])
