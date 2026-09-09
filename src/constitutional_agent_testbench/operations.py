"""CLI adapter for inspection and corpus workflows; all inputs are strict JSON."""

from .inspection import inspect_policy, inspect_suite


# Command: (ordered JSON inputs, library function, strict success field).
COMMANDS = {"inspect-policy": (("policy",), inspect_policy, None)}
COMMANDS["inspect-suite"] = (("suite",), inspect_suite, "consistent_expectations")


def add_operation_parsers(subparsers):
    for name, (fields, _, strict_field) in COMMANDS.items():
        parser = subparsers.add_parser(name, help=f"Run {name} locally.", allow_abbrev=False)
        for field in fields:
            parser.add_argument(field, help=f"{field} JSON path, or - for stdin")
        if strict_field:
            parser.add_argument("--strict-exit", action="store_true")


def run_operation(arguments, load):
    fields, function, _ = COMMANDS[arguments.command]
    return function(*(load(getattr(arguments, field)) for field in fields))
