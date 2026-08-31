from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from constitutional_agent_testbench.evaluator import EvaluationInputError
from constitutional_agent_testbench.playground import (
    evaluate_documents,
    format_verdict,
    run_playground,
)


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "examples" / "policy.json"
PASSING = ROOT / "examples" / "passing-response.json"
FAILING = ROOT / "examples" / "failing-response.json"


class PlaygroundTests(unittest.TestCase):
    def test_smoke_and_evaluation_reject_the_same_non_object_responses(self) -> None:
        policy_text = POLICY.read_text(encoding="utf-8")
        for payload in ("[]", "null", "true", "1", '"text"'):
            with self.subTest(payload=payload):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    response = Path(temporary_directory) / "response.json"
                    response.write_text(payload, encoding="utf-8")
                    with self.assertRaises(EvaluationInputError):
                        run_playground(str(POLICY), str(response), smoke_test=True)

                with self.assertRaises(EvaluationInputError):
                    evaluate_documents(policy_text, payload)

    def test_smoke_ready_payload_is_unchanged(self) -> None:
        self.assertEqual(
            run_playground(str(POLICY), str(PASSING), smoke_test=True),
            {
                "playground": "ready",
                "offline": True,
                "export_requires_explicit_action": True,
            },
        )

    def test_live_verdict_names_failed_rules_without_candidate_values(self) -> None:
        policy_text = POLICY.read_text(encoding="utf-8")
        passing = evaluate_documents(
            policy_text, PASSING.read_text(encoding="utf-8")
        )
        failing = evaluate_documents(
            policy_text, FAILING.read_text(encoding="utf-8")
        )
        passing_line = format_verdict(passing)
        failing_line = format_verdict(failing)

        self.assertTrue(passing["passed"])
        self.assertEqual(passing_line, "PASS — 5 of 5 rules satisfied")
        self.assertFalse(failing["passed"])
        self.assertTrue(failing_line.startswith("FAIL — 4 of 5 rules failed ("))
        self.assertIn("decision-accepted: VALUE_NOT_EQUAL", failing_line)
        self.assertIn("risk-level-allowed: VALUE_NOT_ALLOWED", failing_line)
        self.assertIn("blocked-is-false: VALUE_NOT_FALSE", failing_line)
        self.assertIn("actions-empty: VALUE_NOT_EMPTY_LIST", failing_line)
        self.assertNotIn("decline", failing_line)
        self.assertNotIn("synthetic-item", failing_line)
        self.assertNotIn("high", failing_line)


if __name__ == "__main__":
    unittest.main()
