from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from constitutional_agent_testbench.cli import main
from constitutional_agent_testbench.common import MAX_JSON_INPUT_BYTES, load_json
from constitutional_agent_testbench.precedence import check_order_conformance


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "examples" / "policy.json"
PASSING_RESPONSE = ROOT / "examples" / "passing-response.json"
FAILING_RESPONSE = ROOT / "examples" / "failing-response.json"


def run_cli(arguments: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = main(arguments)
    return exit_code, stdout.getvalue(), stderr.getvalue()


class CliTests(unittest.TestCase):
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
