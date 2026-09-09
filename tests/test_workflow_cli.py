"""Exercise new operator commands at their strict public boundary."""

import io
import json
from contextlib import redirect_stderr, redirect_stdout
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from constitutional_agent_testbench.cli import main


class WorkflowCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.policy = self.save("policy.json", {"schema_version": "1.0", "policy_id": "demo",
            "rules": [{"rule_id": "r", "path": "action", "kind": "false"}]})
        self.response = self.save("response.json", {"action": False})

    def save(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return str(path)

    def run_cli(self, *args, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), patch("sys.stdin", io.StringIO(stdin)):
            code = main(list(args))
        return code, json.loads(out.getvalue() or err.getvalue())

    def test_authoring_commands(self):
        code, result = self.run_cli("lint-policy", self.policy, "--strict-exit")
        self.assertEqual(code, 0)
        self.assertFalse(result["has_conflicts"])
        self.assertEqual(self.run_cli("explain", self.policy, "-", "--strict-exit", stdin="{}")[0], 1)
        code, result = self.run_cli("generate-probes", self.policy)
        self.assertEqual(code, 0)
        self.assertEqual(len(result["suite"]["cases"]), 3)

    def test_input_errors_are_controlled(self):
        self.assertEqual(self.run_cli("explain", "-", "-")[0], 2)
        self.assertEqual(self.run_cli("explain", self.policy, "-", stdin='{"a":1,"a":2}')[0], 2)
        self.assertEqual(self.run_cli("lint-policy", self.policy, "--strict")[0], 2)

    def test_suite_coverage_migration_and_receipt_workflow(self):
        _, probes = self.run_cli("generate-probes", self.policy)
        fixtures = self.save("suite.json", probes["suite"])
        for command in ("run-suite", "suite-coverage"):
            self.assertEqual(self.run_cli(command, self.policy, fixtures, "--strict-exit")[0], 0)
        self.assertEqual(self.run_cli("compare-policies", self.policy, self.policy,
                                     fixtures, "--strict-exit")[0], 0)
        _, receipt = self.run_cli("create-receipt", self.policy, self.response)
        self.assertEqual(self.run_cli("verify-receipt", self.policy, self.response, "-",
                                     "--strict-exit", stdin=json.dumps(receipt))[0], 0)
        receipt["evaluation"]["passed"] = False
        self.assertEqual(self.run_cli("verify-receipt", self.policy, self.response, "-",
                                     "--strict-exit", stdin=json.dumps(receipt))[0], 1)

    def test_new_commands_reject_multiple_stdin_and_invalid_fixtures(self):
        self.assertEqual(self.run_cli("compare-policies", self.policy, "-", "-")[0], 2)
        self.assertEqual(self.run_cli("verify-receipt", self.policy, "-", "-")[0], 2)
        self.assertEqual(self.run_cli("run-suite", self.policy, "-", stdin="[]")[0], 2)

    def test_coverage_gap_and_migration_have_strict_exit(self):
        fixtures = self.save("suite.json", {"suite_version": "1.0", "cases": [
            {"case_id": "one", "response": {"action": False}, "expected_passed": True}]})
        self.assertEqual(self.run_cli("suite-coverage", self.policy, fixtures, "--strict-exit")[0], 1)
        new = self.save("candidate.json", {"schema_version": "1.0", "policy_id": "new",
            "rules": [{"rule_id": "r", "path": "action", "kind": "equals", "value": True}]})
        self.assertEqual(self.run_cli("compare-policies", self.policy, new, fixtures, "--strict-exit")[0], 1)
