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
