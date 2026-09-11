"""Regression checks for practical corpus authoring workflows."""
import copy
import unittest

from test_corpus import policy, suite
from constitutional_agent_testbench import WorkflowInputError


class CorpusAuthoringTests(unittest.TestCase):

    def test_validate_suite_command_and_invalid_input(self):
        import io
        import json
        from contextlib import redirect_stdout, redirect_stderr
        from unittest.mock import patch
        from constitutional_agent_testbench.cli import main
        for raw, expected in ((suite(), 0), ({"cases": []}, 2)):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err), patch("sys.stdin", io.StringIO(json.dumps(raw))):
                self.assertEqual(main(["validate-suite", "-"]), expected)
            result = json.loads(out.getvalue() or err.getvalue())
            if expected == 0:
                self.assertEqual(result, {"valid": True, "suite_version": "1.0", "case_count": 3})

    def test_capture_assertions_is_owned_and_refuses_regressions(self):
        from constitutional_agent_testbench import capture_assertions, evaluate_suite
        raw = suite()
        captured = capture_assertions(policy(), raw)
        self.assertEqual(captured["suite_version"], "1.1")
        self.assertEqual(captured["cases"][1]["expected_rules"]["r"]["reason_code"], "FIELD_MISSING")
        self.assertTrue(evaluate_suite(policy(), captured)["matches_expectations"])
        self.assertNotIn("expected_rules", raw["cases"][0])
        captured["cases"][1]["expected_rules"]["r"]["reason_code"] = "VALUE_NOT_FALSE"
        with self.assertRaises(WorkflowInputError):
            capture_assertions(policy(), captured)
        raw["cases"][0]["expected_passed"] = False
        with self.assertRaises(WorkflowInputError):
            capture_assertions(policy(), raw)

    def test_corpus_diff_distinguishes_json_types_and_assertion_changes(self):
        from constitutional_agent_testbench import diff_suites
        raw, changed = suite(), suite()
        self.assertTrue(diff_suites(raw, changed)["identical"])
        changed["cases"][0]["response"]["action"] = 0
        changed["cases"][1]["response"]["private"] = "SYNTHETIC_PRIVATE"
        changed["cases"].reverse()
        result = diff_suites(raw, changed)
        self.assertEqual(len(result["modified"]), 2)
        self.assertTrue(result["order_changed"])
        self.assertNotIn("SYNTHETIC_PRIVATE", str(result))
        changed["cases"].pop()
        self.assertEqual(diff_suites(raw, changed)["removed"], ["pass"])
        changed["cases"][0]["case_id"] = "new"
        self.assertEqual(diff_suites(raw, changed)["added"], ["new"])

    def test_shards_cover_every_case_once_and_validate_partitions(self):
        from constitutional_agent_testbench import shard_suite
        raw = suite()
        parts = [shard_suite(raw, {"index": i, "count": 2}) for i in range(2)]
        self.assertEqual([c["case_id"] for c in parts[0]["cases"]], ["pass", "wrong"])
        self.assertEqual(sorted(c["case_id"] for p in parts for c in p["cases"]), ["missing", "pass", "wrong"])
        parts[0]["cases"][0]["response"].clear()
        self.assertEqual(raw, suite())
        for partition in ({"index": True, "count": 2}, {"index": 2, "count": 2},
                          {"index": 0, "count": 4}, {"index": 0, "count": 0}, {}):
            with self.assertRaises(WorkflowInputError):
                shard_suite(raw, partition)

    def test_outcome_selection_separates_expected_failure_from_regression(self):
        from constitutional_agent_testbench import select_outcomes
        raw = suite()
        raw["cases"][0]["expected_passed"] = False
        selected = select_outcomes(policy(), raw, "mismatched")
        self.assertEqual([c["case_id"] for c in selected["cases"]], ["pass"])
        self.assertFalse(selected["cases"][0]["expected_passed"])
        self.assertEqual(len(select_outcomes(policy(), raw, "failed")["cases"]), 2)
        self.assertEqual(len(select_outcomes(policy(), raw, "matched")["cases"]), 2)
        for selection in ("unknown", {}, True):
            with self.assertRaises(WorkflowInputError):
                select_outcomes(policy(), raw, selection)
        with self.assertRaises(WorkflowInputError):
            select_outcomes(policy(), suite(), "mismatched")

    def test_deduplication_preserves_assertions_conflicts_and_json_types(self):
        from constitutional_agent_testbench import deduplicate_suite
        raw = suite()
        for identifier in ("copy", "contradiction", "numeric", "asserted"):
            case = copy.deepcopy(raw["cases"][0])
            case["case_id"] = identifier
            raw["cases"].append(case)
        raw["suite_version"] = "1.1"
        raw["cases"][-3]["expected_passed"] = False
        raw["cases"][-2]["response"]["action"] = 0
        raw["cases"][-1]["expected_rules"] = {"r": {"passed": True, "reason_code": "RULE_SATISFIED"}}
        result = deduplicate_suite(raw)
        self.assertEqual([c["case_id"] for c in result["cases"]], ["pass", "missing", "wrong", "contradiction", "numeric", "asserted"])
        self.assertEqual(result, deduplicate_suite(result))
        self.assertEqual(len(raw["cases"]), 7)

    def test_assertion_audit_finds_stale_ids_wrong_kinds_and_impossible_verdicts(self):
        from constitutional_agent_testbench import audit_assertions, capture_assertions
        raw = capture_assertions(policy(), suite())
        self.assertTrue(audit_assertions(policy(), raw)["fully_asserted"])
        raw["cases"][0]["expected_passed"] = False
        raw["cases"][1]["expected_rules"]["r"]["reason_code"] = "VALUE_NOT_EQUAL"
        raw["cases"][2]["expected_rules"]["stale"] = {"passed": False, "reason_code": "FIELD_MISSING"}
        result = audit_assertions(policy(), raw)
        self.assertFalse(result["assertions_compatible"])
        self.assertTrue(result["cases"][0]["contradictory_verdict"])
        self.assertEqual(result["cases"][1]["incompatible_reason_rule_ids"], ["r"])
        self.assertEqual(result["cases"][2]["unknown_rule_ids"], ["stale"])
        self.assertTrue(audit_assertions(policy(), suite())["assertions_compatible"])
        self.assertFalse(audit_assertions(policy(), suite())["fully_asserted"])
