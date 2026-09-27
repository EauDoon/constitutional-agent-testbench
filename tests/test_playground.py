from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from constitutional_agent_testbench.common import JsonOutputError
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


def _headless_playground(response_text: str):
    """Run the playground against a fake Tk and return its window controls.

    Returns the Export result callback, the verdict variable, the messagebox
    module, and the three text widgets in creation order (policy, response,
    result). The fake lets the real export path run without a display.
    """

    policy_editor, response_editor, result_box = (MagicMock(name=n) for n in
                                                  ("policy", "response", "result"))
    policy_editor.get.return_value = POLICY.read_text(encoding="utf-8")
    response_editor.get.return_value = response_text
    verdict = MagicMock(name="verdict")
    fake = MagicMock(name="tkinter")
    fake.Text.side_effect = [policy_editor, response_editor, result_box]
    fake.StringVar.return_value = verdict
    module = MagicMock(name="tkinter_module")
    for name in ("Tk", "Label", "Frame", "Button", "Text", "StringVar"):
        setattr(module, name, getattr(fake, name))
    with patch.dict(sys.modules, {"tkinter": module,
                                  "tkinter.filedialog": module.filedialog,
                                  "tkinter.messagebox": module.messagebox}):
        run_playground(None, None)
    commands = {call.kwargs["text"]: call.kwargs["command"]
                for call in fake.Button.call_args_list}
    return {"export": commands["Export result"], "verdict": verdict,
            "filedialog": module.filedialog, "messagebox": module.messagebox,
            "result_box": result_box}


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

    def test_failed_export_is_not_reported_as_invalid_input(self) -> None:
        window = _headless_playground(PASSING.read_text(encoding="utf-8"))
        window["filedialog"].asksaveasfilename.return_value = str(POLICY.parent / "chosen.json")
        with patch("constitutional_agent_testbench.playground.write_json",
                   side_effect=JsonOutputError("Unable to write the requested JSON output.")):
            window["export"]()

        self.assertEqual([call.args[0] for call in window["messagebox"].showerror.call_args_list],
                         ["Export failed"])
        # The evaluation succeeded, so the live verdict must still say so.
        self.assertEqual(window["verdict"].set.call_args.args[0],
                         "PASS — 5 of 5 rules satisfied")
        self.assertIn("RULE_SATISFIED", window["result_box"].insert.call_args.args[1])

    def test_rejected_input_still_reports_invalid_input(self) -> None:
        window = _headless_playground("{ not json")
        with patch("constitutional_agent_testbench.playground.write_json") as writer:
            window["export"]()
            self.assertFalse(window["filedialog"].asksaveasfilename.called)
            self.assertFalse(writer.called)
        self.assertEqual([call.args[0] for call in window["messagebox"].showerror.call_args_list],
                         ["Invalid input"])
        self.assertTrue(window["verdict"].set.call_args.args[0].startswith("INVALID — "))
        window["result_box"].delete.assert_called_once_with("1.0", "end")


if __name__ == "__main__":
    unittest.main()
