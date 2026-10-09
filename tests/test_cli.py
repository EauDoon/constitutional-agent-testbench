from __future__ import annotations

import codecs
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
    ENCODING_MESSAGE,
    MAX_JSON_INPUT_BYTES,
    JsonInputError,
    load_json,
    load_json_stream,
)
from constitutional_agent_testbench.playground import (
    evaluate_documents,
)
from constitutional_agent_testbench.playground import (
    main as playground_main,
)
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
                    "message": "Unknown command. Use --help to list available commands.",
                }
            },
        )
        self.assertNotIn("unknown-command", stderr)

    def test_missing_command_uses_the_json_error_contract(self) -> None:
        exit_code, stdout, stderr = run_cli([])

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(
            json.loads(stderr),
            {
                "error": {
                    "code": "INVALID_COMMAND",
                    "message": "A command is required. Use --help to list available commands.",
                }
            },
        )

    def test_unknown_option_uses_the_json_error_contract(self) -> None:
        exit_code, stdout, stderr = run_cli(
            ["validate-policy", "--bogus", str(POLICY)]
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(
            json.loads(stderr),
            {
                "error": {
                    "code": "INVALID_COMMAND",
                    "message": (
                        "Unknown option or extra argument. Use --help to inspect usage."
                    ),
                }
            },
        )
        self.assertNotIn("--bogus", stderr)
        self.assertNotIn(str(POLICY), stderr)

    def test_abbreviated_strict_exit_is_rejected(self) -> None:
        exit_code, stdout, stderr = run_cli(
            ["evaluate", str(POLICY), str(FAILING_RESPONSE), "--strict"]
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(
            json.loads(stderr)["error"]["code"],
            "INVALID_COMMAND",
        )
        self.assertIn("Unknown option or extra argument", stderr)

    def test_unknown_option_is_not_hidden_by_a_missing_positional(self) -> None:
        for arguments in (
            ["evaluate", "--bogus"],
            ["evaluate", "--strict"],
            ["inspect-policy", "--strict-exit"],
            ["validate-policy", "--bogus"],
        ):
            with self.subTest(arguments=arguments):
                exit_code, stdout, stderr = run_cli(arguments)
                self.assertEqual(exit_code, 2)
                self.assertEqual(stdout, "")
                self.assertEqual(
                    json.loads(stderr),
                    {
                        "error": {
                            "code": "INVALID_COMMAND",
                            "message": (
                                "Unknown option or extra argument. "
                                "Use --help to inspect usage."
                            ),
                        }
                    },
                )
                self.assertNotIn("--bogus", stderr)
                self.assertNotIn("--strict", stderr)

    def test_unknown_option_is_not_hidden_by_a_value_taking_flag(self) -> None:
        unknown = {
            "error": {
                "code": "INVALID_COMMAND",
                "message": (
                    "Unknown option or extra argument. Use --help to inspect usage."
                ),
            }
        }
        for arguments in (
            ["evaluate", str(POLICY), str(FAILING_RESPONSE), "--output", "--bogus"],
            ["generate-synthetic", str(POLICY), "--output", "--nope"],
            ["--output", "not-a-command"],
            ["lint-policy", str(POLICY), "--output", "--bogus"],
        ):
            with self.subTest(arguments=arguments):
                exit_code, stdout, stderr = run_cli(arguments)
                self.assertEqual(exit_code, 2)
                self.assertEqual(stdout, "")
                self.assertEqual(json.loads(stderr), unknown)

    def test_real_flag_after_output_stays_a_missing_argument(self) -> None:
        exit_code, stdout, stderr = run_cli(
            ["evaluate", str(POLICY), str(FAILING_RESPONSE), "--output", "--strict-exit"]
        )
        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(
            json.loads(stderr)["error"]["message"],
            "Missing required argument. Use --help to inspect usage.",
        )

    def test_valid_flag_without_positionals_stays_a_missing_argument(self) -> None:
        exit_code, stdout, stderr = run_cli(["evaluate", "--strict-exit"])

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(
            json.loads(stderr)["error"]["message"],
            "Missing required argument. Use --help to inspect usage.",
        )

    def test_missing_required_argument_uses_the_json_error_contract(self) -> None:
        exit_code, stdout, stderr = run_cli(["validate-policy"])

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(
            json.loads(stderr),
            {
                "error": {
                    "code": "INVALID_COMMAND",
                    "message": "Missing required argument. Use --help to inspect usage.",
                }
            },
        )

    def test_help_is_plain_text_and_lists_commands(self) -> None:
        exit_code, stdout, stderr = run_cli(["--help"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("validate-policy", stdout)
        self.assertIn("evaluate", stdout)
        self.assertIn("check-order", stdout)
        self.assertIn("generate-synthetic", stdout)
        self.assertIn("playground", stdout)
        self.assertIn("standard input", stdout)
        self.assertNotIn('"error"', stdout)

    def test_generate_synthetic_help_documents_output_path(self) -> None:
        exit_code, stdout, stderr = run_cli(["generate-synthetic", "--help"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("--output PATH", stdout)
        self.assertIn("does not accept '-'", stdout)
        self.assertIn("standard input", stdout)

    def test_playground_help_documents_optional_file_paths(self) -> None:
        exit_code, stdout, stderr = run_cli(["playground", "--help"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("optional policy file path", stdout)
        self.assertIn("--smoke-test", stdout)
        self.assertIn("headless playground smoke check", stdout)

    def test_generate_synthetic_rejects_output_dash(self) -> None:
        exit_code, stdout, stderr = run_cli(
            ["generate-synthetic", str(POLICY), "--output", "-"]
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertFalse(Path("-").exists())
        self.assertEqual(
            json.loads(stderr),
            {
                "error": {
                    "code": "INVALID_COMMAND",
                    "message": (
                        "generate-synthetic --output writes a file and does not "
                        "accept '-'."
                    ),
                }
            },
        )

    def test_playground_rejects_standard_input_token(self) -> None:
        exit_code, stdout, stderr = run_cli(["playground", "-", "--smoke-test"])

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(
            json.loads(stderr),
            {
                "error": {
                    "code": "INVALID_COMMAND",
                    "message": (
                        "playground does not read policy or response JSON from "
                        "standard input."
                    ),
                }
            },
        )

    def test_malformed_json_uses_the_json_error_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "broken.json"
            input_path.write_text("{", encoding="utf-8")
            exit_code, stdout, stderr = run_cli(["validate-policy", str(input_path)])

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertNotIn(str(input_path), stderr)
        self.assertEqual(json.loads(stderr)["error"]["code"], "INVALID_JSON_INPUT")

    def test_missing_input_does_not_echo_the_path(self) -> None:
        missing = ROOT / "examples" / "does-not-exist.json"
        exit_code, stdout, stderr = run_cli(["validate-policy", str(missing)])

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertNotIn(str(missing), stderr)
        self.assertEqual(json.loads(stderr)["error"]["code"], "INVALID_JSON_INPUT")

    def test_invalid_policy_uses_the_policy_error_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "empty-rules.json"
            input_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "policy_id": "empty-rules",
                        "rules": [],
                    }
                ),
                encoding="utf-8",
            )
            exit_code, stdout, stderr = run_cli(["validate-policy", str(input_path)])

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(
            json.loads(stderr),
            {
                "error": {
                    "code": "INVALID_POLICY",
                    "message": "Policy 'empty-rules' rules must be a non-empty JSON array.",
                    "policy_id": "empty-rules",
                }
            },
        )

    def test_invalid_policy_names_the_failing_rule(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "bad-rule.json"
            input_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "policy_id": "named-rule-policy",
                        "rules": [
                            {
                                "rule_id": "broken-path",
                                "kind": "required_field",
                                "path": "summary..text",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            exit_code, stdout, stderr = run_cli(["validate-policy", str(input_path)])

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertNotIn(str(input_path), stderr)
        self.assertEqual(
            json.loads(stderr),
            {
                "error": {
                    "code": "INVALID_POLICY",
                    "message": (
                        "Rule 'broken-path' at index 0 path is not a valid "
                        "object field path."
                    ),
                    "policy_id": "named-rule-policy",
                    "rule_id": "broken-path",
                    "rule_index": 0,
                }
            },
        )

    def test_non_object_response_uses_the_response_error_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            response_path = Path(temporary_directory) / "list-response.json"
            response_path.write_text("[]", encoding="utf-8")
            exit_code, stdout, stderr = run_cli(
                ["evaluate", str(POLICY), str(response_path)]
            )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["error"]["code"], "INVALID_RESPONSE")

    def test_strict_exit_keeps_invalid_input_at_two(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            response_path = Path(temporary_directory) / "list-response.json"
            response_path.write_text("[]", encoding="utf-8")
            exit_code, stdout, stderr = run_cli(
                ["evaluate", str(POLICY), str(response_path), "--strict-exit"]
            )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["error"]["code"], "INVALID_RESPONSE")

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

    def test_playground_console_forwards_smoke_test_from_argv(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.object(
                sys,
                "argv",
                ["constitutional-agent-testbench-playground", "--smoke-test"],
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = playground_main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {
                "export_requires_explicit_action": True,
                "offline": True,
                "playground": "ready",
            },
        )

    def test_playground_console_forwards_optional_paths(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = playground_main(
                [str(POLICY), str(PASSING_RESPONSE), "--smoke-test"]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(json.loads(stdout.getvalue())["playground"], "ready")

    def test_playground_console_forwards_help(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = playground_main(["--help"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn("--smoke-test", stdout.getvalue())
        self.assertIn("optional policy file path", stdout.getvalue())

    def test_playground_smoke_validates_a_supplied_response(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            response = Path(temporary_directory) / "response.json"
            response.write_text('{"decision":"one","decision":"two"}', encoding="utf-8")
            exit_code, stdout, stderr = run_cli(
                ["playground", str(POLICY), str(response), "--smoke-test"]
            )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["error"]["code"], "INVALID_JSON_INPUT")

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

    def test_uncontrolled_data_errors_exit_two_with_invalid_data(self) -> None:
        # Any data error that escapes a command's own validation must still
        # produce the documented JSON error and exit 2, never a traceback.
        for error in (ValueError, TypeError, OverflowError, RecursionError):
            with self.subTest(error=error.__name__), patch(
                "constitutional_agent_testbench.cli._run_command",
                side_effect=error("internal detail"),
            ):
                exit_code, stdout, stderr = run_cli(["validate-policy", str(POLICY)])
            self.assertEqual(exit_code, 2)
            self.assertEqual(stdout, "")
            payload = json.loads(stderr)["error"]
            self.assertEqual(payload["code"], "INVALID_DATA")
            self.assertNotIn("internal detail", stderr)


class StreamFailureTests(unittest.TestCase):
    """Unreadable streams fail closed with the generic read message."""

    def test_stream_read_errors_and_unexpected_payloads_fail_closed(self) -> None:
        class FailingStream:
            def read(self, _size: int) -> bytes:
                raise OSError("device detached")

        class NonTextStream:
            def read(self, _size: int) -> object:
                return 42

        surrogate_text = io.StringIO('"\ud800"')
        for label, stream in (
            ("read error", FailingStream()),
            ("non-text payload", NonTextStream()),
            ("lone surrogate text", surrogate_text),
        ):
            with self.subTest(stream=label):
                with self.assertRaises(JsonInputError) as raised:
                    load_json_stream(stream)  # type: ignore[arg-type]
                self.assertEqual(
                    str(raised.exception), "Unable to read the requested JSON input."
                )


class EncodingErrorTests(unittest.TestCase):
    """Encoding problems are named instead of looking like a missing file."""

    SAMPLES = {
        "utf-8-bom": codecs.BOM_UTF8 + b"{}",
        "utf-16-powershell": "{}".encode("utf-16"),
        "utf-16-be-bom": codecs.BOM_UTF16_BE + "{}".encode("utf-16-be"),
        "utf-32": "{}".encode("utf-32"),
        "invalid-utf-8": bytes([0x22, 0xFF, 0x22]),
    }

    def assert_encoding_error(self, exit_code: int, stdout: str, stderr: str) -> None:
        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        error = json.loads(stderr)["error"]
        self.assertEqual(error["code"], "INVALID_JSON_INPUT")
        self.assertEqual(error["message"], ENCODING_MESSAGE)
        self.assertIn("byte order mark", error["message"])

    def test_file_inputs_report_an_encoding_specific_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for name, payload in self.SAMPLES.items():
                with self.subTest(sample=name):
                    path = Path(directory) / f"{name}.json"
                    path.write_bytes(payload)
                    exit_code, stdout, stderr = run_cli(["validate-policy", str(path)])
                    self.assert_encoding_error(exit_code, stdout, stderr)
                    self.assertNotIn(str(path), stderr)

    def test_missing_file_keeps_the_read_failure_message(self) -> None:
        missing = ROOT / "examples" / "does-not-exist.json"
        exit_code, _stdout, stderr = run_cli(["validate-policy", str(missing)])
        self.assertEqual(exit_code, 2)
        self.assertEqual(
            json.loads(stderr)["error"]["message"],
            "Unable to read the requested JSON input.",
        )

    def test_binary_standard_input_with_a_bom_is_named(self) -> None:
        stdin = io.TextIOWrapper(io.BytesIO(codecs.BOM_UTF8 + POLICY.read_bytes()), encoding="utf-8")
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, "stdin", stdin), redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(["validate-policy", "-"])
        self.assert_encoding_error(exit_code, stdout.getvalue(), stderr.getvalue())

    def test_text_standard_input_with_a_bom_is_named(self) -> None:
        exit_code, stdout, stderr = run_cli(
            ["validate-policy", "-"],
            stdin_text=chr(0xFEFF) + POLICY.read_text(encoding="utf-8"),
        )
        self.assert_encoding_error(exit_code, stdout, stderr)

    def test_undecodable_text_stream_is_named(self) -> None:
        stream = io.TextIOWrapper(io.BytesIO(bytes([0x22, 0xFF, 0x22])), encoding="utf-8")
        with self.assertRaisesRegex(JsonInputError, "byte order mark"):
            load_json_stream(stream)

    def test_oversized_input_reports_the_limit_even_inside_a_character(self) -> None:
        # The bounded read stops inside a two-byte character; the limit, not a
        # decoding failure, is the accurate diagnosis.
        payload = b'"a' + chr(0xE9).encode("utf-8") * (MAX_JSON_INPUT_BYTES // 2) + b'"'
        with self.assertRaisesRegex(JsonInputError, "1,000,000-byte"):
            load_json_stream(io.BytesIO(payload))


if __name__ == "__main__":
    unittest.main()
