"""Command line interface with stable JSON output."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Any

from .common import (
    TestbenchError,
    load_json,
    load_json_stream,
    stable_json,
    write_json,
)
from .evaluator import evaluate_response
from .policy import validate_policy
from .precedence import check_order_conformance
from .synthetic import generate_synthetic_cases


class CliUsageError(TestbenchError):
    """Raised for invalid command line arguments."""

    code = "INVALID_COMMAND"


class _HelpRequested(Exception):
    """Argparse already printed help; main() should return success."""


def _usage_error_message(message: str) -> str:
    """Map argparse failures onto stable, path-free usage errors."""

    lowered = message.lower()
    if "invalid choice" in lowered:
        return "Unknown command. Use --help to list available commands."
    if "unrecognized arguments" in lowered:
        return "Unknown option or extra argument. Use --help to inspect usage."
    if "required: command" in lowered:
        return "A command is required. Use --help to list available commands."
    if "required" in lowered or "expected" in lowered or "too few" in lowered:
        return "Missing required argument. Use --help to inspect usage."
    return "Command arguments are invalid. Use --help to inspect usage."


class JsonArgumentParser(argparse.ArgumentParser):
    """Argument parser that reports failures through the JSON error contract."""

    def error(self, message: str) -> None:
        raise CliUsageError(_usage_error_message(message))

    def exit(self, status: int = 0, message: str | None = None) -> None:
        if status == 0 and message is None:
            raise _HelpRequested()
        if message:
            raise CliUsageError(_usage_error_message(message))
        raise CliUsageError("Command arguments are invalid. Use --help to inspect usage.")


def _build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        prog="constitutional-agent-testbench",
        description="Evaluate structured JSON responses against declared rules.",
        epilog=(
            "Results are JSON on stdout. Controlled errors are JSON on stderr "
            "with exit code 2. Policy and response paths accept '-' for "
            "standard input; at most one argument per command may use it. "
            "playground does not read '-' as standard input. generate-synthetic "
            "--output writes a file and does not accept '-'."
        ),
        allow_abbrev=False,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate-policy",
        help="Validate a version 1.0 policy.",
        description="Validate a version 1.0 policy and report its identifier and schema version.",
        allow_abbrev=False,
    )
    validate_parser.add_argument("policy", help="policy path, or - for standard input")

    evaluate_parser = subparsers.add_parser(
        "evaluate",
        help="Evaluate a candidate response.",
        description=(
            "Evaluate a candidate response against a version 1.0 policy. "
            "Completed evaluations return exit code 0 even when passed is false "
            "unless --strict-exit is supplied."
        ),
        allow_abbrev=False,
    )
    evaluate_parser.add_argument("policy", help="policy path, or - for standard input")
    evaluate_parser.add_argument("response", help="response path, or - for standard input")
    evaluate_parser.add_argument(
        "--strict-exit",
        action="store_true",
        help="return 1 for valid nonconformance",
    )

    order_parser = subparsers.add_parser(
        "check-order",
        help="Exhaustively check peer-rule order conformance.",
        description=(
            "Run PrecedenceTrace against one fixed response and two to seven "
            "declared peer rules. Completed checks return exit code 0 even when "
            "the report is nonconforming unless --strict-exit is supplied."
        ),
        allow_abbrev=False,
    )
    order_parser.add_argument("policy", help="policy path, or - for standard input")
    order_parser.add_argument("response", help="response path, or - for standard input")
    order_parser.add_argument(
        "--strict-exit",
        action="store_true",
        help="return 1 for valid drift or nonconformance",
    )

    synthetic_parser = subparsers.add_parser(
        "generate-synthetic",
        help="Generate verified synthetic cases.",
        description=(
            "Generate a verified passing and failing case from a valid policy. "
            "Without --output the bundle is printed on stdout. --output writes "
            "the bundle to a file and prints a path-free acknowledgement; it "
            "does not accept '-'."
        ),
        allow_abbrev=False,
    )
    synthetic_parser.add_argument("policy", help="policy path, or - for standard input")
    synthetic_parser.add_argument(
        "--output",
        metavar="PATH",
        help="write the case bundle to PATH instead of stdout; does not accept '-'",
    )

    playground_parser = subparsers.add_parser(
        "playground",
        help="Open the offline policy playground.",
        description=(
            "Open the offline policy playground, or run its headless smoke check. "
            "Optional policy and response arguments are file paths; '-' is not "
            "read as standard input."
        ),
        allow_abbrev=False,
    )
    playground_parser.add_argument(
        "policy",
        nargs="?",
        help="optional policy file path",
    )
    playground_parser.add_argument(
        "response",
        nargs="?",
        help="optional response file path",
    )
    playground_parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="run the headless playground smoke check without opening a window",
    )
    return parser


def _load_json_argument(path: str) -> Any:
    if path != "-":
        return load_json(path)
    return load_json_stream(getattr(sys.stdin, "buffer", sys.stdin))


def _run_command(arguments: argparse.Namespace) -> dict[str, Any]:
    if arguments.command == "playground":
        if arguments.policy == "-" or arguments.response == "-":
            raise CliUsageError(
                "playground does not read policy or response JSON from standard input."
            )
        from .playground import run_playground
        return run_playground(arguments.policy, arguments.response, smoke_test=arguments.smoke_test)
    input_paths = [arguments.policy]
    if arguments.command in {"evaluate", "check-order"}:
        input_paths.append(arguments.response)
    if input_paths.count("-") > 1:
        raise CliUsageError(
            "Only one JSON input may be read from standard input per command."
        )

    raw_policy = _load_json_argument(arguments.policy)
    policy = validate_policy(raw_policy)

    if arguments.command == "validate-policy":
        return {
            "policy_id": policy.policy_id,
            "schema_version": policy.schema_version,
            "valid": True,
        }

    if arguments.command == "evaluate":
        response = _load_json_argument(arguments.response)
        return evaluate_response(policy, response)

    if arguments.command == "check-order":
        response = _load_json_argument(arguments.response)
        return check_order_conformance(policy, response)

    if arguments.output == "-":
        raise CliUsageError(
            "generate-synthetic --output writes a file and does not accept '-'."
        )

    bundle = generate_synthetic_cases(policy)
    if arguments.output:
        write_json(arguments.output, bundle)
        return {"output_written": True, "policy_id": policy.policy_id}
    return bundle


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line interface and return a process exit code."""

    try:
        arguments = _build_parser().parse_args(argv)
        result = _run_command(arguments)
    except _HelpRequested:
        return 0
    except TestbenchError as exc:
        error = {"error": {"code": exc.code, "message": str(exc)}}
        sys.stderr.write(stable_json(error))
        return 2
    except (OverflowError, RecursionError, TypeError, ValueError):
        error = {
            "error": {
                "code": "INVALID_DATA",
                "message": "Input data could not be processed as strict JSON.",
            }
        }
        sys.stderr.write(stable_json(error))
        return 2

    sys.stdout.write(stable_json(result))
    if getattr(arguments, "strict_exit", False):
        if arguments.command == "evaluate":
            return 0 if result.get("passed") is True else 1
        if arguments.command == "check-order":
            return 0 if result.get("conforms_within_coverage") is True else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
