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
