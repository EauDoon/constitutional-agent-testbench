"""suite-coverage reports reachable reason codes no case exercised."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from constitutional_agent_testbench.cli import main
from constitutional_agent_testbench.common import load_json
from constitutional_agent_testbench.coverage import reachable_reason_codes, suite_coverage
from constitutional_agent_testbench.evaluator import FAILURE_REASON_BY_KIND

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
POLICY = EXAMPLES / "policy.json"

# Every rule both passes and fails, but the only failure is a missing field, so
# no value check ever ran.
MISSING_ONLY = {"suite_version": "1.0", "cases": [
    {"case_id": "pass", "expected_passed": True, "response": {
        "actions": [], "blocked": False, "decision": "accept", "risk_level": "low",
        "summary": "Synthetic example."}},
    {"case_id": "empty", "expected_passed": False, "response": {}},
]}


class LibraryTests(unittest.TestCase):
    def test_missing_only_corpus_lists_every_unexercised_value_code(self):
        report = suite_coverage(load_json(POLICY), MISSING_ONLY)
        self.assertEqual(report["rules_with_both_outcomes"], 5)
        self.assertEqual(report["unexercised_failures"], [])
        self.assertEqual(report["unexercised_passes"], [])
        rows = {row["rule_id"]: row for row in report["rules"]}
        self.assertEqual(rows["blocked-is-false"]["unexercised_reason_codes"], ["VALUE_NOT_FALSE"])
        self.assertEqual(rows["blocked-is-false"]["kind"], "false")
        self.assertEqual(rows["decision-accepted"]["unexercised_reason_codes"], ["VALUE_NOT_EQUAL"])
        self.assertEqual(rows["risk-level-allowed"]["unexercised_reason_codes"], ["VALUE_NOT_ALLOWED"])
        self.assertEqual(rows["actions-empty"]["unexercised_reason_codes"], ["VALUE_NOT_EMPTY_LIST"])
        self.assertEqual(rows["summary-present"]["unexercised_reason_codes"], [])
        self.assertEqual(report["rules_with_all_reason_codes"], 1)
        self.assertEqual(report["rules_missing_reason_codes"],
                         ["actions-empty", "blocked-is-false", "decision-accepted",
                          "risk-level-allowed"])

    def test_bundled_regression_suite_exercises_every_reachable_code(self):
        report = suite_coverage(load_json(POLICY), load_json(EXAMPLES / "regression-suite.json"))
        self.assertEqual(report["rules_missing_reason_codes"], [])
        self.assertEqual(report["rules_with_all_reason_codes"], 5)

    def test_required_field_rows_list_at_most_two_codes(self):
        self.assertEqual(reachable_reason_codes("required_field"), ["FIELD_MISSING", "RULE_SATISFIED"])
        raw = {"schema_version": "1.0", "policy_id": "presence", "rules": [
            {"rule_id": "present", "kind": "required_field", "path": "a"}]}
        report = suite_coverage(raw, {"suite_version": "1.0", "cases": [
            {"case_id": "c", "response": {"a": 1}, "expected_passed": True}]})
        self.assertEqual(report["rules"][0]["unexercised_reason_codes"], ["FIELD_MISSING"])

    def test_every_kind_reaches_its_own_failure_code(self):
        for kind, code in FAILURE_REASON_BY_KIND.items():
            with self.subTest(kind=kind):
                self.assertEqual(reachable_reason_codes(kind),
                                 sorted({"RULE_SATISFIED", "FIELD_MISSING", code}))

    def test_schema_1_1_kinds_list_their_own_failure_codes(self):
        raw = load_json(EXAMPLES / "typed-policy.json")
        passing = load_json(EXAMPLES / "typed-passing-response.json")
        report = suite_coverage(raw, {"suite_version": "1.0", "cases": [
            {"case_id": "pass", "response": passing, "expected_passed": True},
            {"case_id": "empty", "response": {}, "expected_passed": False}]})
        expected = {"type": ["VALUE_WRONG_TYPE"], "range": ["VALUE_OUT_OF_RANGE"],
                    "length": ["VALUE_LENGTH_OUT_OF_RANGE"], "false": ["VALUE_NOT_FALSE"]}
        for row in report["rules"]:
            with self.subTest(rule=row["rule_id"]):
                self.assertEqual(row["unexercised_reason_codes"], expected[row["kind"]])
        failing = load_json(EXAMPLES / "typed-failing-response.json")
        report = suite_coverage(raw, {"suite_version": "1.0", "cases": [
            {"case_id": "pass", "response": passing, "expected_passed": True},
            {"case_id": "fail", "response": failing, "expected_passed": False},
            {"case_id": "empty", "response": {}, "expected_passed": False}]})
        self.assertEqual(report["rules_missing_reason_codes"],
                         ["actions-is-array", "blocked-is-false"])


class CliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.suite = self.root / "missing-only.json"
        self.suite.write_text(json.dumps(MISSING_ONLY), encoding="utf-8")

    def run_cli(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(list(arguments))
        return code, json.loads(stdout.getvalue() or stderr.getvalue())

    def test_strict_reasons_catches_what_strict_exit_misses(self):
        base = ("suite-coverage", str(POLICY), str(self.suite))
        self.assertEqual(self.run_cli(*base, "--strict-exit")[0], 0)
        self.assertEqual(self.run_cli(*base, "--strict-reasons")[0], 1)
        self.assertEqual(self.run_cli(*base, "--strict-exit", "--strict-reasons")[0], 1)
        self.assertEqual(self.run_cli(*base)[0], 0)

    def test_combined_flags_fail_on_either_gap(self):
        outcome_gap = self.root / "outcome-gap.json"
        outcome_gap.write_text(json.dumps({"suite_version": "1.0", "cases": [
            MISSING_ONLY["cases"][0]]}), encoding="utf-8")
        base = ("suite-coverage", str(POLICY), str(outcome_gap))
        self.assertEqual(self.run_cli(*base, "--strict-exit")[0], 1)
        self.assertEqual(self.run_cli(*base, "--strict-reasons")[0], 1)
        self.assertEqual(self.run_cli(*base, "--strict-reasons", "--strict-exit")[0], 1)

    def test_regression_suite_passes_strict_reasons(self):
        code, report = self.run_cli("suite-coverage", str(POLICY),
                                    str(EXAMPLES / "regression-suite.json"), "--strict-reasons")
        self.assertEqual(code, 0)
        self.assertEqual(report["rules_missing_reason_codes"], [])

    def test_misspelled_flag_is_still_rejected(self):
        code, error = self.run_cli("suite-coverage", str(POLICY), str(self.suite), "--strict-reason")
        self.assertEqual(code, 2)
        self.assertIn("error", error)

    def test_output_keeps_the_strict_exit_status(self):
        output = self.root / "coverage.json"
        code, display = self.run_cli("suite-coverage", str(POLICY), str(self.suite),
                                     "--strict-reasons", "--output", str(output))
        self.assertEqual(code, 1)
        self.assertEqual(display, {"output_written": True})
        self.assertEqual(load_json(output)["rules_with_all_reason_codes"], 1)

    def test_help_documents_the_flag(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(["suite-coverage", "--help"]), 0)
        self.assertIn("--strict-reasons", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
