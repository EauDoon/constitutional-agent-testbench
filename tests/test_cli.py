from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from constitutional_agent_testbench.cli import main
from constitutional_agent_testbench.common import (
    JsonInputError,
    MAX_JSON_INPUT_BYTES,
    load_json,
    load_json_stream,
)
from constitutional_agent_testbench.playground import evaluate_documents
from constitutional_agent_testbench.precedence import check_order_conformance


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "examples" / "policy.json"
PASSING_RESPONSE = ROOT / "examples" / "passing-response.json"
FAILING_RESPONSE = ROOT / "examples" / "failing-response.json"


def run_cli(
    arguments: list[str], *, stdin_text: str | None = None
) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    stdin_context = (
        patch.object(sys, "stdin", io.StringIO(stdin_text))
        if stdin_text is not None
        else nullcontext()
    )
    with stdin_context, redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = main(arguments)
    return exit_code, stdout.getvalue(), stderr.getvalue()


class CliTests(unittest.TestCase):
    def test_binary_stream_rejects_invalid_utf8(self) -> None:
        with self.assertRaises(JsonInputError):
            load_json_stream(io.BytesIO(b'"\xff"'))

    def test_binary_stream_counts_utf8_bytes(self) -> None:
        oversized_json = b'"' + "\U0001f4a1".encode("utf-8") * 250_000 + b'"'

        with self.assertRaises(JsonInputError):
            load_json_stream(io.BytesIO(oversized_json))

    def test_validate_policy_accepts_bounded_standard_input(self) -> None:
        exit_code, stdout, stderr = run_cli(
            ["validate-policy", "-"],
            stdin_text=POLICY.read_text(encoding="utf-8"),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(json.loads(stdout)["policy_id"], "public-example-policy")

    def test_evaluate_accepts_response_from_standard_input(self) -> None:
        exit_code, stdout, stderr = run_cli(
            ["evaluate", str(POLICY), "-"],
            stdin_text=PASSING_RESPONSE.read_text(encoding="utf-8"),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertTrue(json.loads(stdout)["passed"])

    def test_standard_input_keeps_the_file_size_limit(self) -> None:
        exit_code, stdout, stderr = run_cli(
            ["validate-policy", "-"],
            stdin_text=" " * (MAX_JSON_INPUT_BYTES + 1),
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["error"]["code"], "INVALID_JSON_INPUT")

    def test_command_rejects_two_standard_input_arguments(self) -> None:
        exit_code, stdout, stderr = run_cli(
            ["evaluate", "-", "-"],
            stdin_text=POLICY.read_text(encoding="utf-8"),
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(
            json.loads(stderr),
            {
                "error": {
                    "code": "INVALID_COMMAND",
                    "message": (
                        "Only one JSON input may be read from standard input per "
                        "command."
                    ),
                }
            },
        )

    def test_validate_policy_returns_stable_json(self) -> None:
        exit_code, stdout, stderr = run_cli(["validate-policy", str(POLICY)])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            json.loads(stdout),
            {
                "policy_id": "public-example-policy",
                "schema_version": "1.0",
                "valid": True,
            },
        )

    def test_evaluation_failure_is_data_not_a_process_error(self) -> None:
        exit_code, stdout, stderr = run_cli(
            ["evaluate", str(POLICY), str(FAILING_RESPONSE)]
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertFalse(json.loads(stdout)["passed"])

    def test_invalid_command_uses_the_json_error_contract(self) -> None:
        exit_code, stdout, stderr = run_cli(["unknown-command"])

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(
            json.loads(stderr),
            {
                "error": {
                    "code": "INVALID_COMMAND",
                    "message": "Command arguments are invalid.",
                }
            },
        )

    def test_oversize_input_uses_the_bounded_json_error_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "oversize.json"
            input_path.write_bytes(b" " * (MAX_JSON_INPUT_BYTES + 1))
            exit_code, stdout, stderr = run_cli(
                ["validate-policy", str(input_path)]
            )

            self.assertEqual(exit_code, 2)
            self.assertEqual(stdout, "")
            self.assertNotIn(str(input_path), stderr)
            self.assertEqual(
                json.loads(stderr)["error"]["code"],
                "INVALID_JSON_INPUT",
            )

    def test_generated_output_acknowledgement_does_not_echo_the_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "nested" / "cases.json"
            exit_code, stdout, stderr = run_cli(
                ["generate-synthetic", str(POLICY), "--output", str(output_path)]
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertNotIn(str(output_path), stdout)
            self.assertEqual(
                json.loads(stdout),
                {
                    "output_written": True,
                    "policy_id": "public-example-policy",
                },
            )
            self.assertTrue(json.loads(output_path.read_text(encoding="utf-8")))

    def test_passing_example_succeeds_through_the_cli(self) -> None:
        exit_code, stdout, stderr = run_cli(
            ["evaluate", str(POLICY), str(PASSING_RESPONSE)]
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertTrue(json.loads(stdout)["passed"])

    def test_strict_exit_distinguishes_valid_nonconformance(self) -> None:
        exit_code, stdout, stderr = run_cli(
            ["evaluate", str(POLICY), str(FAILING_RESPONSE), "--strict-exit"]
        )
        self.assertEqual(exit_code, 1)
        self.assertEqual(stderr, "")
        self.assertFalse(json.loads(stdout)["passed"])

    def test_strict_exit_keeps_conformance_at_zero(self) -> None:
        exit_code, stdout, stderr = run_cli(
            ["check-order", str(POLICY), str(PASSING_RESPONSE), "--strict-exit"]
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertTrue(json.loads(stdout)["conforms_within_coverage"])

    def test_playground_smoke_is_offline_and_nonwriting(self) -> None:
        exit_code, stdout, stderr = run_cli(["playground", "--smoke-test"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(json.loads(stdout)["export_requires_explicit_action"], True)

    def test_playground_without_tkinter_uses_the_json_error_contract(self) -> None:
        with patch.dict(sys.modules, {"tkinter": None}):
            exit_code, stdout, stderr = run_cli(["playground"])

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(
            json.loads(stderr)["error"]["code"],
            "PLAYGROUND_UNAVAILABLE",
        )

    def test_playground_editor_uses_strict_bounded_json(self) -> None:
        policy_text = POLICY.read_text(encoding="utf-8")
        passing_text = PASSING_RESPONSE.read_text(encoding="utf-8")
        self.assertTrue(evaluate_documents(policy_text, passing_text)["passed"])
        with self.assertRaises(JsonInputError):
            evaluate_documents(policy_text, '{"decision":"one","decision":"two"}')
        with self.assertRaises(JsonInputError):
            evaluate_documents(policy_text, '{"decision":NaN}')

    def test_check_order_reports_conformance_as_result_data(self) -> None:
        exit_code, stdout, stderr = run_cli(
            ["check-order", str(POLICY), str(PASSING_RESPONSE)]
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        report = json.loads(stdout)
        self.assertEqual(report["status"], "PRESENTATION_ONLY_DRIFT")
        self.assertTrue(report["conforms_within_coverage"])
        self.assertEqual(report["coverage"]["orders_evaluated"], 120)
        self.assertEqual(report["coverage"]["evaluations_performed"], 360)
        self.assertEqual(
            report,
            check_order_conformance(load_json(POLICY), load_json(PASSING_RESPONSE)),
        )

    def test_check_order_refuses_to_label_sampling_as_exhaustive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            policy_path = Path(temporary_directory) / "large-policy.json"
            response_path = Path(temporary_directory) / "response.json"
            policy_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "policy_id": "large-order-policy",
                        "rules": [
                            {
                                "rule_id": f"rule-{index}",
                                "kind": "required_field",
                                "path": f"value{index}",
                            }
                            for index in range(8)
                        ],
                    }
                ),
                encoding="utf-8",
            )
            response_path.write_text("{}", encoding="utf-8")

            exit_code, stdout, stderr = run_cli(
                ["check-order", str(policy_path), str(response_path)]
            )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["error"]["code"], "ORDER_CHECK_TOO_LARGE")


if __name__ == "__main__":
    unittest.main()
