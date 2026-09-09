"""Exercise full authoring/replay workflows through the public CLI boundary."""
import io
import json
import os
import stat
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from constitutional_agent_testbench.cli import main
from constitutional_agent_testbench.common import write_json, JsonOutputError


class CorpusCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.policy = self.save("policy.json", {"schema_version": "1.0", "policy_id": "demo",
            "rules": [{"rule_id": "r", "kind": "false", "path": "action"}]})
        self.suite = self.save("suite.json", {"suite_version": "1.1", "cases": [
            {"case_id": "pass", "response": {"action": False}, "expected_passed": True},
            {"case_id": "fail", "response": {}, "expected_passed": False,
             "expected_rules": {"r": {"passed": False, "reason_code": "FIELD_MISSING"}}}]})

    def save(self, name, data):
        path = self.root / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return str(path)

    def call(self, *arguments, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), patch("sys.stdin", io.StringIO(stdin)):
            code = main(list(arguments))
        return code, json.loads(out.getvalue() or err.getvalue())

    def test_export_and_replay_workflow_and_strict_regression(self):
        bundle = str(self.root / "bundle.json")
        self.assertEqual(self.call("create-replay", self.policy, self.suite, "--output", bundle),
                         (0, {"output_written": True}))
        self.assertEqual(self.call("replay", bundle, "--strict-exit")[0], 0)
        data = json.loads(Path(bundle).read_text())
        data["receipt"]["evaluation"]["matches_expectations"] = False
        Path(bundle).write_text(json.dumps(data))
        self.assertEqual(self.call("replay", bundle, "--strict-exit")[0], 1)
        self.assertEqual(self.call("replay", "-", "--strict-exit", stdin=json.dumps(data))[0], 1)

    def test_output_guard_precedes_read_and_protects_inputs_and_hardlinks(self):
        for target in ("-", self.policy, str(Path(self.policy).parent / "." / "policy.json")):
            with patch("constitutional_agent_testbench.cli._load_json_argument", side_effect=AssertionError("read")):
                self.assertEqual(self.call("inspect-policy", self.policy, "--output", target)[0], 2)
        alias = self.root / "hardlink.json"
        os.link(self.policy, alias)
        self.assertEqual(self.call("inspect-policy", self.policy, "--output", str(alias))[0], 2)
        self.assertIn("rules", json.loads(Path(self.policy).read_text()))

    def test_atomic_failure_keeps_previous_output_and_cleans_temporary_file(self):
        output = self.root / "saved.json"
        output.write_bytes(b"previous")
        with patch("constitutional_agent_testbench.common.os.replace", side_effect=OSError()):
            with self.assertRaises(JsonOutputError):
                write_json(output, {"complete": True})
        self.assertEqual(output.read_bytes(), b"previous")
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ["policy.json", "saved.json", "suite.json"])

    def test_multiple_stdin_unknown_selection_and_nonfinite_fail_closed(self):
        self.assertEqual(self.call("merge-suites", "-", "-")[0], 2)
        self.assertEqual(self.call("select-suite", self.suite, "-", stdin='["unknown"]')[0], 2)
        self.assertEqual(self.call("inspect-suite", "-", stdin='{"x":NaN}')[0], 2)
        self.assertEqual(self.call("replay", "-", stdin='{"replay_version":"1.0","replay_version":"1.0"}')[0], 2)

    def test_command_inventory_and_suite_operations(self):
        for command, inputs in (("inspect-policy", (self.policy,)), ("inspect-suite", (self.suite,)),
                                ("triage-suite", (self.policy, self.suite)), ("reduce-suite", (self.policy, self.suite))):
            self.assertEqual(self.call(command, *inputs)[0], 0)
        code, receipt = self.call("create-suite-receipt", self.policy, self.suite)
        self.assertEqual(code, 0)
        self.assertEqual(self.call("verify-suite-receipt", self.policy, self.suite, "-", "--strict-exit",
                                   stdin=json.dumps(receipt))[0], 0)
        code, selected = self.call("select-suite", self.suite, "-", stdin='["pass"]')
        self.assertEqual(code, 0)
        self.assertEqual(len(selected["cases"]), 1)


class AtomicExportPermissionsTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix" and hasattr(os, "fchmod"), "POSIX file modes unavailable")
    def test_existing_regular_mode_preserved_without_special_bits(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "shared.json"
            output.write_text("previous")
            output.chmod(0o2640)
            if stat.S_IMODE(output.stat().st_mode) != 0o2640:
                self.skipTest("filesystem cannot retain requested mode")
            write_json(output, {"complete": True})
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o640)
            self.assertEqual(json.loads(output.read_text()), {"complete": True})

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "fchmod"), "POSIX file modes unavailable")
    def test_new_file_is_private_and_symlink_target_is_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "private.json"
            write_json(output, {})
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            target = root / "target.json"
            target.write_text("unchanged")
            target.chmod(0o644)
            link = root / "link.json"
            link.symlink_to(target)
            write_json(link, {"new": True})
            self.assertFalse(link.is_symlink())
            self.assertEqual(stat.S_IMODE(link.stat().st_mode), 0o600)
            self.assertEqual(target.read_text(), "unchanged")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o644)
