"""Run corpus preparation, review, regression selection and replay through the CLI."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from constitutional_agent_testbench.cli import main
from test_corpus import policy, suite


class CorpusAuthoringCliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.policy = self.save("policy.json", policy())
        self.suite = self.save("suite.json", suite())

    def save(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return str(path)

    def call(self, *arguments, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), patch("sys.stdin", io.StringIO(stdin)):
            code = main(arguments)
        return code, json.loads(out.getvalue() or err.getvalue())

    def test_import_capture_preflight_shard_and_replay(self):
        responses = self.save("responses.json", [{"action": False}, {}, {"action": True}])
        imported = str(self.root / "imported.json")
        self.assertEqual(self.call("import-responses", responses, "-", "--output", imported,
                                   stdin="[true, false, false]"), (0, {"output_written": True}))
        self.assertEqual(self.call("validate-suite", imported)[0], 0)
        captured = str(self.root / "captured.json")
        self.assertEqual(self.call("capture-assertions", self.policy, imported, "--output", captured)[0], 0)
        self.assertEqual(self.call("audit-assertions", self.policy, captured, "--strict-exit")[0], 0)
        self.assertEqual(self.call("check-suite", self.policy, captured, "--strict-exit")[0], 0)
        self.assertEqual(self.call("diff-suites", imported, captured, "--strict-exit")[0], 1)
        self.assertEqual(self.call("diff-suites", captured, captured, "--strict-exit")[0], 0)
        shard = str(self.root / "shard.json")
        self.assertEqual(self.call("shard-suite", captured, "-", "--output", shard,
                                   stdin='{"index":0,"count":2}')[0], 0)
        replay = str(self.root / "replay.json")
        self.assertEqual(self.call("create-replay", self.policy, shard, "--output", replay)[0], 0)
        self.assertEqual(self.call("replay", replay, "--strict-exit")[0], 0)
        self.assertEqual(self.call("deduplicate-suite", captured)[0], 0)
        code, failed = self.call("select-outcomes", self.policy, captured, "-", stdin='"failed"')
        self.assertEqual(code, 0)
        self.assertEqual(len(failed["cases"]), 2)
        migrated = policy()
        migrated["rules"][0].update(kind="equals", value=False)
        candidate = self.save("candidate.json", migrated)
        code, migration = self.call("migration-expectations", self.policy, candidate, captured, "--strict-exit")
        self.assertEqual(code, 1)
        self.assertEqual(migration["regressions"], ["case-003"])

    def test_all_new_inputs_are_protected_before_loading(self):
        calls = [
            ("validate-suite", self.suite),
            ("capture-assertions", self.policy, self.suite),
            ("diff-suites", self.suite, self.suite),
            ("shard-suite", self.suite, "partition.json"),
            ("select-outcomes", self.policy, self.suite, "selection.json"),
            ("deduplicate-suite", self.suite),
            ("audit-assertions", self.policy, self.suite),
            ("migration-expectations", self.policy, "candidate.json", self.suite),
            ("check-suite", self.policy, self.suite),
            ("import-responses", "responses.json", "expectations.json"),
        ]
        for arguments in calls:
            for source in arguments[1:]:
                with self.subTest(command=arguments[0], source=source):
                    with patch("constitutional_agent_testbench.cli._load_json_argument", side_effect=AssertionError("read")):
                        code, result = self.call(*arguments, "--output", source)
                    self.assertEqual(code, 2)
                    self.assertEqual(result["error"]["code"], "INVALID_COMMAND")

    def test_empty_selection_and_invalid_import_preserve_previous_export(self):
        output = self.root / "saved.json"
        output.write_bytes(b"previous")
        code, _ = self.call("select-outcomes", self.policy, self.suite, "-", "--output", str(output),
                            stdin='"mismatched"')
        self.assertEqual(code, 2)
        self.assertEqual(output.read_bytes(), b"previous")
        responses = self.save("responses.json", [{}])
        for text in ("[1]", "[false,false]", "[NaN]", "[]"):
            self.assertEqual(self.call("import-responses", responses, "-", "--output", str(output), stdin=text)[0], 2)
            self.assertEqual(output.read_bytes(), b"previous")
        self.assertEqual(self.call("import-responses", "-", "-")[0], 2)

    def test_incompatible_assertions_return_a_completed_failing_preflight(self):
        raw = suite()
        raw["suite_version"] = "1.1"
        raw["cases"][0]["expected_rules"] = {"stale": {"passed": True, "reason_code": "RULE_SATISFIED"}}
        path = self.save("stale.json", raw)
        for command in ("audit-assertions", "check-suite"):
            code, result = self.call(command, self.policy, path, "--strict-exit")
            self.assertEqual(code, 1)
            self.assertNotIn("error", result)
