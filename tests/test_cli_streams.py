"""JSON process streams must preserve portable evidence regardless of locale."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from constitutional_agent_testbench.cli import main
from constitutional_agent_testbench.common import stable_json
from constitutional_agent_testbench.replay import create_replay_bundle, replay_bundle


class JsonStreamTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.policy = {"schema_version": "1.0", "policy_id": "synthetic", "rules": [
            {"rule_id": "r", "kind": "false", "path": "action"}]}
        self.suite = {"suite_version": "1.1", "cases": [{
            "case_id": "unicode", "response": {"action": False, "note": "SYNTHETIC_é雪💡"},
            "expected_passed": True,
            "expected_rules": {"r": {"passed": True, "reason_code": "RULE_SATISFIED"}}}]}
        self.policy_path = self.root / "policy.json"
        self.policy_path.write_text(stable_json(self.policy), encoding="utf-8")

    def test_stdout_preserves_unicode_and_lf_independent_of_text_encoding(self):
        expected = stable_json(create_replay_bundle(self.policy, self.suite)).encode("utf-8")
        for encoding, errors in (("ascii", "strict"), ("ascii", "replace"),
                                 ("ascii", "ignore"), ("latin-1", "replace"),
                                 ("utf-16", "strict")):
            with self.subTest(encoding=encoding, errors=errors):
                buffer = io.BytesIO()
                with io.TextIOWrapper(buffer, encoding=encoding, errors=errors, newline="\r\n") as stdout:
                    stderr = io.StringIO()
                    with redirect_stdout(stdout), redirect_stderr(stderr), patch(
                        "sys.stdin", io.StringIO(stable_json(self.suite))
                    ):
                        code = main(["create-replay", str(self.policy_path), "-"])
                    self.assertEqual(code, 0)
                    self.assertEqual(stderr.getvalue(), "")
                    self.assertEqual(buffer.getvalue(), expected)
                    self.assertTrue(replay_bundle(json.loads(buffer.getvalue()))["replay_passed"])

    def test_text_only_embedding_retains_complete_unicode(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout), patch("sys.stdin", io.StringIO(stable_json(self.suite))):
            code = main(["create-replay", str(self.policy_path), "-"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), create_replay_bundle(self.policy, self.suite))

    def test_stderr_is_utf8_json_even_for_nonascii_validation_diagnostics(self):
        malformed = dict(self.policy, **{"SYNTHETIC_雪": True})
        buffer = io.BytesIO()
        with io.TextIOWrapper(buffer, encoding="ascii", errors="replace", newline="\r\n") as stderr:
            stdout = io.StringIO()
            with redirect_stderr(stderr), redirect_stdout(stdout), patch(
                "sys.stdin", io.StringIO(stable_json(malformed))
            ):
                code = main(["validate-policy", "-"])
            self.assertEqual(code, 2)
            self.assertEqual(stdout.getvalue(), "")
            error = json.loads(buffer.getvalue().decode("utf-8"))
            self.assertEqual(error["error"]["code"], "INVALID_POLICY")
            self.assertIn("SYNTHETIC_雪", error["error"]["message"])
            self.assertNotIn(b"\r", buffer.getvalue())

if __name__ == "__main__":
    unittest.main()
