"""The eval runner must reject malformed fixtures before it uses them."""

from __future__ import annotations

import copy
import json
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

    def test_malformed_case_fields_are_rejected(self) -> None:
        valid = {
            "id": "case",
            "source": "synthetic",
            "policy_path": "examples/policy.json",
            "input": {},
            "expected": {
                "passed": False,
                "rules": {"summary-present": {"passed": False, "reason_code": "FIELD_MISSING"}},
            },
        }
        outside = "../" * (len(runner.REPO_ROOT.resolve().parts) + 1) + "policy.json"
        mutations = {
            "non-string policy_path": lambda case: case.update(policy_path=5),
            "empty policy_path": lambda case: case.update(policy_path=""),
            "absolute policy_path": lambda case: case.update(
                policy_path=str(runner.REPO_ROOT.resolve() / "examples" / "policy.json")),
            "rooted policy_path": lambda case: case.update(policy_path="/examples/policy.json"),
            "parent policy_path": lambda case: case.update(policy_path="../policy.json"),
            "escaping policy_path": lambda case: case.update(policy_path=outside),
            "non-object input": lambda case: case.update(input=[]),
            "missing expected.passed": lambda case: case["expected"].pop("passed"),
            "extra expected key": lambda case: case["expected"].update(note="x"),
            "non-object rule entry": lambda case: case["expected"]["rules"].update(
                {"summary-present": True}),
            "extra rule entry key": lambda case: case["expected"]["rules"]["summary-present"].update(
                note="x"),
            "missing reason_code": lambda case: case["expected"]["rules"]["summary-present"].pop(
                "reason_code"),
            "non-string reason_code": lambda case: case["expected"]["rules"]["summary-present"].update(
                reason_code=1),
            "unknown top-level key": lambda case: case.update(notes="x"),
            "id differs from stem": lambda case: case.update(id="other"),
            "missing id": lambda case: case.pop("id"),
            "non-string id": lambda case: case.update(id=1),
            "non-string source": lambda case: case.update(source=["x"]),
        }
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(directory, json.dumps(valid))
            self.assertEqual(runner.load_case_document(path), valid)
            for label, mutate in mutations.items():
                with self.subTest(mutation=label):
                    case = copy.deepcopy(valid)
                    mutate(case)
                    path = self._write(directory, json.dumps(case))
                    with self.assertRaises(runner.EvalCaseError) as raised:
                        runner.load_case_document(path)
                    self.assertIn("case.json", str(raised.exception))

    def test_policy_path_resolves_inside_the_repository(self) -> None:
        resolved = runner.case_policy_path("examples/policy.json", "case.json")
        self.assertEqual(resolved, (runner.REPO_ROOT / "examples" / "policy.json").resolve())

    def test_numeric_zero_and_one_are_not_pass_states(self) -> None:
        for actual, expected in ((True, 1), (False, 0), (True, 1.0), (False, 0.0)):
            with self.subTest(actual=actual, expected=expected):
                with self.assertRaises(AssertionError):
                    runner.passed_states_match(actual, expected, "passed")
        runner.passed_states_match(True, True, "passed")
        runner.passed_states_match(False, False, "passed")


if __name__ == "__main__":
    unittest.main()
