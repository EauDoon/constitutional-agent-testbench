"""Replay of other engines' decision logs against a Testbench policy."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from constitutional_agent_testbench import (DecisionLogInputError, compare_decision_log,
                                            evaluate_suite, import_decision_log,
                                            normalize_decision_log, parse_decision_log_text)
from constitutional_agent_testbench.cli import main
from constitutional_agent_testbench.decision_log import MAX_REPORTED_DISAGREEMENTS

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
POLICY = json.loads((EXAMPLES / "conditional-policy.json").read_text(encoding="utf-8"))
SIMPLE_POLICY = {"schema_version": "1.0", "policy_id": "simple",
                 "rules": [{"rule_id": "safe", "kind": "false", "path": "risky"}]}


def run_cli(*argv: str) -> tuple[int, dict]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(list(argv))
    return code, json.loads(stdout.getvalue() or stderr.getvalue())


class ParseTests(unittest.TestCase):
    def test_single_document_and_json_lines(self) -> None:
        self.assertEqual(parse_decision_log_text('[{"a": 1}]'), [{"a": 1}])
        self.assertEqual(parse_decision_log_text('{"a": 1}\n\n{"b": 2}\n'), [{"a": 1}, {"b": 2}])
        self.assertEqual(parse_decision_log_text('{"a": 1}\n'), {"a": 1})

    def test_rejects_bad_text(self) -> None:
        for text in ("", "nope", '{"a": 1}\n{"a": 1, "a": 2}', '{"a": 1}\n{"b": NaN}',
                     " " * 1_000_001):
            with self.subTest(text=text[:20]), self.assertRaises(DecisionLogInputError):
                parse_decision_log_text(text)
        with self.assertRaisesRegex(DecisionLogInputError, "line 2"):
            parse_decision_log_text('{"a": 1}\n{oops}')


class NormalizeTests(unittest.TestCase):
    def test_opa_events(self) -> None:
        log = [
            {"decision_id": "a", "path": "gate", "input": {"x": 1}, "result": {"allow": True}},
            {"decision_id": "b", "path": "gate", "input": {"x": 2}, "result": False},
            {"decision_id": "c", "path": "other", "input": {}, "result": True},
            {"path": "gate", "input": {"x": 3}, "result": {"decision": {"ok": True}}},
        ]
        with self.assertRaisesRegex(DecisionLogInputError, "result path"):
            normalize_decision_log(log, log_format="opa")
        normalized = normalize_decision_log(log[:3], log_format="opa", decision_path="gate")
        self.assertEqual(normalized["skipped"], 1)
        self.assertEqual([(d["decision_id"], d["allow"]) for d in normalized["decisions"]],
                         [("a", True), ("b", False)])
        nested = normalize_decision_log([log[3]], log_format="opa", result_path="decision.ok")
        self.assertEqual(nested["decisions"][0]["decision_id"], None)
        self.assertTrue(nested["decisions"][0]["allow"])

    def test_opa_fails_closed(self) -> None:
        cases = [
            ({"input": {}, "result": 1}, "boolean"),
            ({"input": {}, "result": {"allow": "yes"}}, "boolean"),
            ({"input": {}}, "input and result"),
            ({"result": True}, "input and result"),
            ({"input": {}, "result": True, "erased": ["/input/password"]}, "erased"),
            ({"input": {}, "result": True, "masked": ["/input/ssn"]}, "erased or masked"),
            ({"input": [1], "result": True}, "JSON object"),
            ("event", "JSON object"),
        ]
        for entry, message in cases:
            with self.subTest(entry=entry), self.assertRaisesRegex(DecisionLogInputError, message):
                normalize_decision_log([entry], log_format="opa")
        with self.assertRaisesRegex(DecisionLogInputError, "matched the decision path"):
            normalize_decision_log([{"path": "x", "input": {}, "result": True}],
                                   log_format="opa", decision_path="y")

    def test_cedar_records(self) -> None:
        log = [{"id": "r1", "request": {"context": {"x": 1}}, "decision": "Allow"},
               {"decision_id": "r2", "request": {"context": {"x": 2}}, "decision": "DENY"}]
        normalized = normalize_decision_log(log, log_format="cedar", input_path="context")
        self.assertEqual([(d["decision_id"], d["input"], d["allow"])
                          for d in normalized["decisions"]],
                         [("r1", {"x": 1}, True), ("r2", {"x": 2}, False)])
        for entry, message in (({"request": {}, "decision": "Maybe"}, "Allow or Deny"),
                               ({"request": {}}, "request and decision"),
                               ({"request": {}, "decision": True}, "Allow or Deny")):
            with self.subTest(entry=entry), self.assertRaisesRegex(DecisionLogInputError, message):
                normalize_decision_log([entry], log_format="cedar")
        with self.assertRaisesRegex(DecisionLogInputError, "input path"):
            normalize_decision_log([{"request": {}, "decision": "Allow"}], log_format="cedar",
                                   input_path="context")
        with self.assertRaisesRegex(DecisionLogInputError, "JSON object"):
            normalize_decision_log([{"request": {"context": 1}, "decision": "Allow"}],
                                   log_format="cedar", input_path="context")

    def test_generic_log(self) -> None:
        log = {"log_version": "1.0", "decisions": [
            {"decision_id": "g1", "input": {"risky": False}, "allow": True},
            {"input": {"risky": True}, "allow": False}]}
        self.assertEqual(len(normalize_decision_log(log, log_format="generic")["decisions"]), 2)
        bad = [
            ([], "generic decision log"),
            ({"log_version": "2.0", "decisions": []}, "generic decision log"),
            ({"log_version": "1.0", "decisions": {}}, "array"),
            ({"log_version": "1.0", "decisions": []}, "1 to 10,000"),
            ({"log_version": "1.0", "decisions": [{"input": {}, "allow": 1}]}, "boolean"),
            ({"log_version": "1.0", "decisions": [{"input": {}, "allow": True, "x": 1}]},
             "may have decision_id"),
        ]
        for value, message in bad:
            with self.subTest(value=value), self.assertRaisesRegex(DecisionLogInputError, message):
                normalize_decision_log(value, log_format="generic")

    def test_option_checks(self) -> None:
        log = [{"input": {}, "result": True}]
        for options, message in (({"log_format": "rego"}, "format"),
                                 ({"log_format": "opa", "result_path": "a..b"}, "result path"),
                                 ({"log_format": "opa", "input_path": ""}, "input path"),
                                 ({"log_format": "opa", "decision_path": ""}, "decision path")):
            with self.subTest(options=options), self.assertRaisesRegex(DecisionLogInputError, message):
                normalize_decision_log(log, **options)
        with self.assertRaisesRegex(DecisionLogInputError, "array, an object"):
            normalize_decision_log("log", log_format="opa")
        with self.assertRaisesRegex(DecisionLogInputError, "strict JSON limits"):
            normalize_decision_log([{"input": {}, "result": float("nan")}], log_format="opa")
        with self.assertRaisesRegex(DecisionLogInputError, "10,000"):
            normalize_decision_log([{"input": {}, "result": True}] * 10_001, log_format="opa")

    def test_inputs_are_copied(self) -> None:
        source = {"x": [1]}
        normalized = normalize_decision_log([{"input": source, "result": True}], log_format="opa")
        source["x"].append(2)
        self.assertEqual(normalized["decisions"][0]["input"], {"x": [1]})


class ImportTests(unittest.TestCase):
    def test_import_builds_a_suite_that_run_suite_checks(self) -> None:
        log = [{"decision_id": "keep-me", "input": {"risky": False}, "result": True},
               {"decision_id": "keep-me", "input": {"risky": True}, "result": True},
               {"decision_id": "not a valid id", "input": {"risky": True}, "result": False},
               {"input": {}, "result": False}]
        suite = import_decision_log(log, log_format="opa")
        self.assertEqual(suite["suite_version"], "1.0")
        self.assertEqual([case["case_id"] for case in suite["cases"]],
                         ["keep-me", "decision-00002", "decision-00003", "decision-00004"])
        self.assertEqual([case["expected_passed"] for case in suite["cases"]],
                         [True, True, False, False])
        report = evaluate_suite(SIMPLE_POLICY, suite)
        self.assertFalse(report["matches_expectations"])
        self.assertEqual([case["case_id"] for case in report["cases"]
                          if not case["matches_expectation"]], ["decision-00002"])

    def test_generated_identifier_collision(self) -> None:
        log = [{"decision_id": "decision-00002", "input": {}, "result": True},
               {"decision_id": "decision-00002", "input": {}, "result": True}]
        ids = [case["case_id"] for case in import_decision_log(log, log_format="opa")["cases"]]
        self.assertEqual(ids, ["decision-00002", "decision-00002-dup"])

    def test_import_limit(self) -> None:
        with self.assertRaisesRegex(DecisionLogInputError, "at most 256"):
            import_decision_log([{"input": {}, "result": True}] * 257, log_format="opa")


class CompareTests(unittest.TestCase):
    def test_counts_and_directions(self) -> None:
        log = [{"decision_id": "ok", "input": {"risky": False}, "result": True},
               {"decision_id": "loose", "input": {"risky": True}, "result": True},
               {"decision_id": "tight", "input": {"risky": False}, "result": False},
               {"input": {}, "result": False}]
        report = compare_decision_log(SIMPLE_POLICY, log, log_format="opa")
        self.assertFalse(report["agrees"])
        self.assertEqual((report["decisions"], report["agreed"], report["disagreed"]), (4, 2, 2))
        self.assertEqual((report["engine_more_permissive"], report["engine_more_restrictive"]),
                         (1, 1))
        self.assertEqual((report["engine_allowed"], report["testbench_passed"]), (2, 2))
        self.assertEqual(report["disagreements"][0], {
            "decision_id": "loose", "engine_allowed": True, "failed_rule_ids": ["safe"],
            "index": 2, "testbench_passed": False})
        self.assertFalse(report["values_included"])
        self.assertNotIn("risky", json.dumps(report))

    def test_truncation(self) -> None:
        log = [{"input": {"risky": True}, "result": True}] * (MAX_REPORTED_DISAGREEMENTS + 4)
        report = compare_decision_log(SIMPLE_POLICY, log, log_format="opa")
        self.assertEqual(report["disagreed"], MAX_REPORTED_DISAGREEMENTS + 4)
        self.assertEqual(len(report["disagreements"]), MAX_REPORTED_DISAGREEMENTS)
        self.assertTrue(report["disagreements_truncated"])

    def test_shipped_examples(self) -> None:
        opa = parse_decision_log_text(
            (EXAMPLES / "decision-logs" / "opa-decisions.jsonl").read_text(encoding="utf-8"))
        report = compare_decision_log(POLICY, opa, log_format="opa", decision_path="agent/gate")
        self.assertTrue(report["agrees"])
        self.assertEqual((report["decisions"], report["skipped"]), (4, 1))
        cedar = json.loads((EXAMPLES / "decision-logs" / "cedar-decisions.json")
                           .read_text(encoding="utf-8"))
        report = compare_decision_log(POLICY, cedar, log_format="cedar", input_path="context")
        self.assertEqual([(item["decision_id"], item["failed_rule_ids"])
                          for item in report["disagreements"]],
                         [("refund-002", ["refund-at-most-order-total"])])
        self.assertEqual(report["engine_more_permissive"], 1)


class CliTests(unittest.TestCase):
    def test_compare_and_import(self) -> None:
        policy = str(EXAMPLES / "conditional-policy.json")
        opa = str(EXAMPLES / "decision-logs" / "opa-decisions.jsonl")
        cedar = str(EXAMPLES / "decision-logs" / "cedar-decisions.json")
        code, report = run_cli("compare-decision-log", policy, opa, "--format", "opa",
                               "--decision-path", "agent/gate", "--strict-exit")
        self.assertEqual((code, report["agrees"]), (0, True))
        code, report = run_cli("compare-decision-log", policy, cedar, "--format", "cedar",
                               "--input-path", "context", "--strict-exit")
        self.assertEqual((code, report["disagreed"]), (1, 1))
        code, report = run_cli("compare-decision-log", policy, cedar, "--format", "cedar",
                               "--input-path", "context")
        self.assertEqual(code, 0)
        code, suite = run_cli("import-decision-log", cedar, "--format", "cedar",
                              "--input-path", "context")
        self.assertEqual((code, [case["case_id"] for case in suite["cases"]]),
                         (0, ["refund-001", "refund-002", "refund-003"]))

    def test_errors_and_stdin(self) -> None:
        policy = str(EXAMPLES / "conditional-policy.json")
        code, error = run_cli("compare-decision-log", policy, policy, "--format", "opa")
        self.assertEqual((code, error["error"]["code"]), (2, "INVALID_DECISION_LOG"))
        code, error = run_cli("compare-decision-log", "-", "-", "--format", "opa")
        self.assertEqual((code, error["error"]["code"]), (2, "INVALID_COMMAND"))
        code, error = run_cli("import-decision-log", policy)
        self.assertEqual((code, error["error"]["code"]), (2, "INVALID_COMMAND"))
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "log.jsonl"
            log.write_text('{"input": {"risky": false}, "result": true}\n', encoding="utf-8")
            code, error = run_cli("import-decision-log", str(log), "--format", "opa",
                                  "--output", str(log))
            self.assertEqual((code, error["error"]["code"]), (2, "INVALID_COMMAND"))
            stdin = io.TextIOWrapper(io.BytesIO(log.read_bytes()), encoding="utf-8")
            with stdin, mock.patch("sys.stdin", stdin):
                code, suite = run_cli("import-decision-log", "-", "--format", "opa")
            self.assertEqual((code, len(suite["cases"])), (0, 1))


if __name__ == "__main__":
    unittest.main()
