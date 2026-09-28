"""The eval runner must reject fixtures that are not JSON objects."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from constitutional_agent_testbench.common import JsonInputError

import evals.runner as runner


class EvalRunnerFixtureTests(unittest.TestCase):
    def _write(self, directory: str, text: str) -> Path:
        path = Path(directory) / "case.json"
        path.write_text(text, encoding="utf-8")
        return path

    def test_non_object_case_documents_are_rejected(self) -> None:
        samples = (
            "true",
            "false",
            "null",
            "[]",
            "1",
            '"case"',
            '{"policy_path": "p.json", "input": {}, "expected": true}',
            '{"policy_path": "p.json", "input": {}, "expected": {"passed": true, "rules": []}}',
        )
        with tempfile.TemporaryDirectory() as directory:
            for text in samples:
                with self.subTest(text=text):
                    path = self._write(directory, text)
                    with self.assertRaises(runner.EvalCaseError) as raised:
                        runner.load_case_document(path)
                    self.assertIn("JSON object", str(raised.exception))

    def test_duplicate_json_keys_are_rejected(self) -> None:
        samples = (
            '{"policy_path": "p.json", "policy_path": "q.json", "input": {}, "expected": {"passed": true}}',
            '{"policy_path": "p.json", "input": {"a": 1, "a": 2}, "expected": {"passed": true}}',
            '{"policy_path": "p.json", "input": {}, "expected": {"passed": true, "passed": false}}',
        )
        with tempfile.TemporaryDirectory() as directory:
            for text in samples:
                with self.subTest(text=text):
                    path = self._write(directory, text)
                    with self.assertRaises(JsonInputError):
                        runner.load_case_document(path)
            policy = Path(directory) / "policy.json"
            policy.write_text(
                '{"schema_version": "1.0", "schema_version": "1.0", "policy_id": "p", "rules": []}',
                encoding="utf-8",
            )
            with self.assertRaises(JsonInputError):
                runner.load_policy_document(policy)


if __name__ == "__main__":
    unittest.main()
