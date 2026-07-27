"""Command line interface with stable JSON output."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Any

from .common import TestbenchError, load_json, stable_json, write_json
from .evaluator import evaluate_response
from .policy import validate_policy
from .precedence import check_order_conformance
from .synthetic import generate_synthetic_cases


class CliUsageError(TestbenchError):
    """Raised for invalid command line arguments."""

    code = "INVALID_COMMAND"


class JsonArgumentParser(argparse.ArgumentParser):
    """Argument parser that reports failures through the JSON error contract."""

    def error(self, message: str) -> None:
        raise CliUsageError("Command arguments are invalid.")


def _build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        prog="constitutional-agent-testbench",
        description="Evaluate structured JSON responses against declared rules.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate-policy", help="Validate a version 1.0 policy."
    )
    validate_parser.add_argument("policy")

    evaluate_parser = subparsers.add_parser(
        "evaluate", help="Evaluate a candidate response."
    )
    evaluate_parser.add_argument("policy")
    evaluate_parser.add_argument("response")

    order_parser = subparsers.add_parser(
        "check-order",
        help="Exhaustively check peer-rule order conformance.",
    )
    order_parser.add_argument("policy")
    order_parser.add_argument("response")

    synthetic_parser = subparsers.add_parser(
        "generate-synthetic", help="Generate verified synthetic cases."
    )
    synthetic_parser.add_argument("policy")
    synthetic_parser.add_argument("--output")
    return parser


def _run_command(arguments: argparse.Namespace) -> dict[str, Any]:
    raw_policy = load_json(arguments.policy)
    policy = validate_policy(raw_policy)

    if arguments.command == "validate-policy":
        return {
            "policy_id": policy.policy_id,
            "schema_version": policy.schema_version,
            "valid": True,
        }

    if arguments.command == "evaluate":
        response = load_json(arguments.response)
        return evaluate_response(policy, response)

    if arguments.command == "check-order":
        response = load_json(arguments.response)
        return check_order_conformance(policy, response)

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
