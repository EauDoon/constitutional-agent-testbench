"""Command line interface with stable JSON output."""

from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path
from collections.abc import Sequence
from typing import Any

from ._version import __version__
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
from .authoring import lint_policy
from .explain import explain_response
from .probes import generate_rule_probes
from .suite import evaluate_suite
from .coverage import suite_coverage
from .compare import compare_policies
from .receipt import create_receipt, verify_receipt
from .operations import COMMANDS, add_operation_parsers, run_operation


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
            "with exit code 2. Every JSON input path accepts '-' for "
            "standard input; at most one argument per command may use it. "
            "playground does not read '-' as standard input. Every command "
            "except playground accepts --output PATH to write the JSON result "
            "atomically instead of printing it; --output never accepts '-' and "
            "creates missing parent directories. Commands with --strict-exit "
            "return 1 for a valid negative result."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"constitutional-agent-testbench {__version__}",
        help="print the installed package version and exit",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_operation_parsers(subparsers)

    for name, inputs, help_text in (
        ("run-suite", ("suite",), "Run explicit fixture expectations; strict exit fails on mismatches."),
        ("suite-coverage", ("suite",), "Count observed rule outcomes; strict exit requires both outcomes per rule."),
        ("compare-policies", ("candidate", "suite"), "Compare migration impact; strict exit fails on changed rule results."),
        ("create-receipt", ("response",), "Bind inputs to a recomputable evaluation receipt."),
        ("verify-receipt", ("response", "receipt"), "Recompute a receipt; strict exit fails on inconsistent bindings."),
    ):
        command_parser = subparsers.add_parser(name, help=help_text,
                                               description=help_text, allow_abbrev=False)
        for field in ("policy", *inputs):
            command_parser.add_argument(field, help=f"{field} path, or - for standard input")
        if name != "create-receipt":
            command_parser.add_argument("--strict-exit", action="store_true",
                                        help="return 1 when the command's stated condition fails")

    for name, help_text in (
        ("lint-policy", "Find conservative policy conflicts and duplicate constraints."),
        ("explain", "Explain response failures without displaying candidate values."),
        ("generate-probes", "Generate verified targeted mutations and a regression suite."),
    ):
        command_parser = subparsers.add_parser(name, help=help_text,
                                               description=help_text, allow_abbrev=False)
        command_parser.add_argument("policy", help="policy path, or - for standard input")
        if name == "explain":
            command_parser.add_argument("response", help="response path, or - for standard input")
        if name != "generate-probes":
            command_parser.add_argument("--strict-exit", action="store_true",
                                        help="return 1 for a conflict or failed evaluation")

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
    for name, command_parser in subparsers.choices.items():
        if name not in COMMANDS and name not in {"playground", "generate-synthetic"}:
            command_parser.add_argument("--output", metavar="PATH", help="atomically export JSON; never overwrite an input")
    return parser


def _relax_required_arguments(parser: argparse.ArgumentParser) -> None:
    """Allow a probe parse to finish when required positionals are absent.

    argparse reports missing required arguments before unrecognized ones, so an
    unknown option is otherwise classified as a missing path.
    """

    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            action.required = False
            for subparser in set(action._name_parser_map.values()):
                _relax_required_arguments(subparser)
            continue
        if action.option_strings:
            continue
        action.required = False
        if action.nargs is None:
            action.nargs = "?"


def _is_option_token(token: str) -> bool:
    """True for an option-like token, not for ``-`` or a negative number."""

    if len(token) < 2 or not token.startswith("-"):
        return False
    body = token[1:]
    if body[:1].isdigit() or (body[:1] == "." and len(body) > 1 and body[1].isdigit()):
        return False
    return True


def _option_takes_value(action: argparse.Action) -> bool:
    return action.nargs is None or (isinstance(action.nargs, int) and action.nargs > 0)


def _option_tables(
    parser: argparse.ArgumentParser,
) -> tuple[dict[str, bool], dict[str, dict[str, bool]]]:
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )

    def table(target: argparse.ArgumentParser) -> dict[str, bool]:
        found: dict[str, bool] = {}
        for action in target._actions:
            takes_value = _option_takes_value(action)
            for option in action.option_strings:
                found[option] = takes_value
        return found

    return table(parser), {
        name: table(subparser) for name, subparser in subparsers._name_parser_map.items()
    }


def _scan_unknown_option(tokens: list[str]) -> bool:
    """Find an unknown option argparse would hide behind another error.

    A value-taking flag does not consume a following option, so
    ``--output --bogus`` raises "expected one argument" before the unknown
    token is reported. An unknown option before an invalid command is reported
    as an unknown command instead.
    """

    main_options, by_command = _option_tables(_build_parser())
    command: str | None = None
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            return False
        if not _is_option_token(token):
            if command is None:
                command = token
            index += 1
            continue
        name, separator, _explicit = token.partition("=")
        lookup = name if separator else token
        options = by_command[command] if command in by_command else main_options
        if lookup not in options:
            return True
        if options[lookup] and not separator:
            following = index + 1
            if following < len(tokens) and not _is_option_token(tokens[following]):
                index = following + 1
                continue
        index += 1
    return False


def _requests_version(tokens: list[str]) -> bool:
    """True when --version precedes the command, where it is a top-level flag."""

    for token in tokens:
        if token == "--version":
            return True
        if token == "--" or not _is_option_token(token):
            return False
    return False


def _unknown_arguments(argv: Sequence[str] | None) -> bool:
    tokens = list(sys.argv[1:] if argv is None else argv)
    if any(token in {"-h", "--help"} for token in tokens):
        return False
    # The probe parse below would run the version action and print it a second
    # time. After a command, --version stays an unknown option.
    if _requests_version(tokens):
        return False
    if _scan_unknown_option(tokens):
        return True
    probe = _build_parser()
    _relax_required_arguments(probe)
    try:
        _namespace, extra = probe.parse_known_args(tokens)
    except (CliUsageError, _HelpRequested):
        return False
    return bool(extra)


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    if _unknown_arguments(argv):
        raise CliUsageError(
            "Unknown option or extra argument. Use --help to inspect usage."
        )
    return _build_parser().parse_args(argv)


def _is_blank_path(value: str) -> bool:
    """True when a path has no filename characters.

    ``str.strip`` covers Unicode spaces. Format and control characters such as
    a zero-width space or a BOM are blank as well, even though they are not
    stripped.
    """

    if not value.strip():
        return True
    return all(unicodedata.category(character)[0] in {"C", "Z"} for character in value)


def _guard_output(arguments):
    output = getattr(arguments, "output", None)
    if output is None:
        return
    if arguments.command == "generate-synthetic" and output == "-":
        raise CliUsageError("generate-synthetic --output writes a file and does not accept '-'.")
    if _is_blank_path(output) or output == "-":
        raise CliUsageError("--output writes a file and does not accept an empty path or '-'.")
    fields = (COMMANDS[arguments.command][0] if arguments.command in COMMANDS
              else ("policy", "response", "candidate", "suite", "receipt"))
    try:
        destination = Path(output)
        for field in fields:
            raw = getattr(arguments, field, None)
            if raw and raw != "-":
                source = Path(raw)
                if destination.resolve() == source.resolve() or (
                    destination.exists() and source.exists() and destination.samefile(source)
                ):
                    raise CliUsageError("Output must not overwrite a command input.")
    except (OSError, ValueError, RuntimeError) as exc:
        raise CliUsageError("Output destination could not be safely resolved.") from exc


def _load_json_argument(path: str) -> Any:
    if path != "-":
        return load_json(path)
    return load_json_stream(getattr(sys.stdin, "buffer", sys.stdin))


def _write_json_stream(stream, value: Any) -> None:
    """Emit UTF-8 and LF without locale encoding or newline translation.

    Real process streams expose a binary buffer. Text-only streams remain
    supported for callers embedding main(), including StringIO captures.
    """
    serialized = stable_json(value)
    binary = getattr(stream, "buffer", None)
    if binary is not None:
        binary.write(serialized.encode("utf-8"))
        binary.flush()
    else:
        stream.write(serialized)
        stream.flush()


def _run_command(arguments: argparse.Namespace) -> dict[str, Any]:
    if arguments.command == "playground":
        if arguments.policy == "-" or arguments.response == "-":
            raise CliUsageError(
                "playground does not read policy or response JSON from standard input."
            )
        from .playground import run_playground
        return run_playground(arguments.policy, arguments.response, smoke_test=arguments.smoke_test)
    if arguments.command == "generate-synthetic" and arguments.output == "-":
        raise CliUsageError(
            "generate-synthetic --output writes a file and does not accept '-'."
        )
    if arguments.command in COMMANDS:
        fields = COMMANDS[arguments.command][0]
        if sum(getattr(arguments, field) == "-" for field in fields) > 1:
            raise CliUsageError("Only one JSON input may be read from standard input per command.")
        return run_operation(arguments, _load_json_argument)
    input_paths = [getattr(arguments, field) for field in
                   ("policy", "response", "candidate", "suite", "receipt")
                   if hasattr(arguments, field)]
    if input_paths.count("-") > 1:
        raise CliUsageError(
            "Only one JSON input may be read from standard input per command."
        )

    raw_policy = _load_json_argument(arguments.policy)
    policy = validate_policy(raw_policy)

    if arguments.command == "run-suite":
        return evaluate_suite(policy, _load_json_argument(arguments.suite))
    if arguments.command == "suite-coverage":
        return suite_coverage(policy, _load_json_argument(arguments.suite))
    if arguments.command == "compare-policies":
        return compare_policies(policy, _load_json_argument(arguments.candidate),
                                _load_json_argument(arguments.suite))
    if arguments.command == "create-receipt":
        return create_receipt(policy, _load_json_argument(arguments.response))
    if arguments.command == "verify-receipt":
        return verify_receipt(policy, _load_json_argument(arguments.response),
                              _load_json_argument(arguments.receipt))

    if arguments.command == "lint-policy":
        return lint_policy(policy)
    if arguments.command == "explain":
        return explain_response(policy, _load_json_argument(arguments.response))
    if arguments.command == "generate-probes":
        return generate_rule_probes(policy)

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

    bundle = generate_synthetic_cases(policy)
    return bundle


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line interface and return a process exit code."""

    try:
        arguments = _parse_arguments(argv)
        _guard_output(arguments)
        result = _run_command(arguments)
        display = result
        if getattr(arguments, "output", None) is not None:
            write_json(arguments.output, result)
            display = {"output_written": True}
            if arguments.command == "generate-synthetic":
                display["policy_id"] = result["policy_id"]
        _write_json_stream(sys.stdout, display)
    except _HelpRequested:
        return 0
    except TestbenchError as exc:
        error = {"error": exc.public_error()}
        _write_json_stream(sys.stderr, error)
        return 2
    except (OverflowError, RecursionError, TypeError, ValueError):
        error = {
            "error": {
                "code": "INVALID_DATA",
                "message": "Input data could not be processed as strict JSON.",
            }
        }
        _write_json_stream(sys.stderr, error)
        return 2

    if getattr(arguments, "strict_exit", False):
        if arguments.command in COMMANDS:
            return 0 if result[COMMANDS[arguments.command][2]] else 1
        if arguments.command == "run-suite":
            return 0 if result["matches_expectations"] else 1
        if arguments.command == "suite-coverage":
            return 1 if result["unexercised_passes"] or result["unexercised_failures"] else 0
        if arguments.command == "compare-policies":
            return 1 if any(case["changed_rule_results"] or case["verdict_changed"]
                           for case in result["cases"]) else 0
        if arguments.command == "verify-receipt":
            return 0 if result["verified"] else 1
        if arguments.command == "lint-policy":
            return 1 if result["has_conflicts"] else 0
        if arguments.command == "explain":
            return 0 if result["evaluation"]["passed"] else 1
        if arguments.command == "evaluate":
            return 0 if result.get("passed") is True else 1
        if arguments.command == "check-order":
            return 0 if result.get("conforms_within_coverage") is True else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
