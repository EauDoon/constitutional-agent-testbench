from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from constitutional_agent_testbench.evaluator import EvaluationInputError
from constitutional_agent_testbench.playground import evaluate_documents, run_playground


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "examples" / "policy.json"


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


if __name__ == "__main__":
    unittest.main()
