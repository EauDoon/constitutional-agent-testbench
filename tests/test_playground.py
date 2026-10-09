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

    Returns the Export result callback, the verdict variable, the dialog
    modules, the root window, and the three text widgets (policy, response,
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
    return {"export": commands["Export result"], "evaluate": commands["Evaluate"],
            "verdict": verdict,
            "filedialog": module.filedialog, "messagebox": module.messagebox,
            "result_box": result_box, "root": fake.Tk.return_value,
            "policy_editor": policy_editor, "response_editor": response_editor,
            "labels": [call.kwargs.get("text") for call in fake.Label.call_args_list],
            "buttons": list(commands)}


def _bindings(widget) -> dict:
    return {call.args[0]: call.args[1] for call in widget.bind.call_args_list}


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


class PlaygroundKeyboardTests(unittest.TestCase):
    def test_editors_move_focus_and_evaluate_from_the_keyboard(self) -> None:
        window = _headless_playground(PASSING.read_text(encoding="utf-8"))
        for name in ("policy_editor", "response_editor"):
            with self.subTest(editor=name):
                bindings = _bindings(window[name])
                self.assertEqual(
                    set(bindings), {"<Tab>", "<Shift-Tab>", "<Control-Return>"}
                )
                event = MagicMock(name="event")
                self.assertEqual(bindings["<Tab>"](event), "break")
                event.widget.tk_focusNext.return_value.focus_set.assert_called_once_with()
                self.assertEqual(bindings["<Shift-Tab>"](event), "break")
                event.widget.tk_focusPrev.return_value.focus_set.assert_called_once_with()

    def test_root_shortcuts_evaluate_and_export(self) -> None:
        window = _headless_playground(PASSING.read_text(encoding="utf-8"))
        bindings = _bindings(window["root"])
        self.assertEqual(set(bindings), {"<Control-Return>", "<Control-s>"})
        window["verdict"].set.reset_mock()
        self.assertEqual(
            _bindings(window["response_editor"])["<Control-Return>"](MagicMock()), "break"
        )
        self.assertEqual(window["verdict"].set.call_args.args[0],
                         "PASS — 5 of 5 rules satisfied")
        window["filedialog"].asksaveasfilename.return_value = ""
        self.assertEqual(bindings["<Control-s>"](MagicMock()), "break")
        window["filedialog"].asksaveasfilename.assert_called_once()
        self.assertFalse(window["messagebox"].showerror.called)

    def test_button_labels_stay_stable_and_shortcuts_are_shown(self) -> None:
        window = _headless_playground(PASSING.read_text(encoding="utf-8"))
        # README and the export tests refer to these exact labels.
        self.assertEqual(window["buttons"], ["Evaluate", "Export result"])
        self.assertIn(
            "Ctrl+Enter evaluates; Ctrl+S exports; Tab moves between fields.",
            window["labels"],
        )

    def test_window_opens_with_the_verdict_for_the_loaded_documents(self) -> None:
        window = _headless_playground(PASSING.read_text(encoding="utf-8"))
        self.assertEqual(window["verdict"].set.call_args.args[0],
                         "PASS — 5 of 5 rules satisfied")
        self.assertIn("RULE_SATISFIED", window["result_box"].insert.call_args.args[1])
        self.assertFalse(window["messagebox"].showerror.called)

        failing = _headless_playground(FAILING.read_text(encoding="utf-8"))
        self.assertTrue(failing["verdict"].set.call_args.args[0].startswith("FAIL — 4 of 5"))

    def test_invalid_input_on_open_sets_the_verdict_without_a_dialog(self) -> None:
        window = _headless_playground("{ not json")
        self.assertTrue(window["verdict"].set.call_args.args[0].startswith("INVALID — "))
        self.assertFalse(window["messagebox"].showerror.called)
        self.assertFalse(window["result_box"].delete.called)

    def test_explicit_evaluate_still_reports_invalid_input_in_a_dialog(self) -> None:
        window = _headless_playground("{ not json")
        window["evaluate"]()
        self.assertEqual([call.args[0] for call in window["messagebox"].showerror.call_args_list],
                         ["Invalid input"])
        self.assertTrue(window["verdict"].set.call_args.args[0].startswith("INVALID — "))
        window["result_box"].delete.assert_called_once_with("1.0", "end")


if __name__ == "__main__":
    unittest.main()
