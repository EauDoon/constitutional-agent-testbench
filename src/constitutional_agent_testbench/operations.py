"""CLI adapter for inspection and corpus workflows; all inputs are strict JSON."""

from .inspection import inspect_policy, inspect_suite
from .curation import merge_suites, select_suite, reduce_suite
from .triage import triage_suite
from .corpus_receipt import create_suite_receipt, verify_suite_receipt
from .replay import create_replay_bundle, replay_bundle


from .suite import validate_suite_report
from .curation import capture_assertions, shard_suite, select_outcomes, deduplicate_suite, import_responses
from .inspection import diff_suites, audit_assertions
from .compare import migration_expectations
from .triage import check_suite

# Command: (ordered JSON inputs, library function, strict success field).
COMMANDS = {"inspect-policy": (("policy",), inspect_policy, None)}
COMMANDS["inspect-suite"] = (("suite",), inspect_suite, "consistent_expectations")
COMMANDS["merge-suites"] = (("suite", "incoming"), merge_suites, None)
COMMANDS["select-suite"] = (("suite", "selection"), select_suite, None)
COMMANDS["triage-suite"] = (("policy", "suite"), triage_suite, "matches_expectations")
COMMANDS["reduce-suite"] = (("policy", "suite"), reduce_suite, None)
COMMANDS["create-suite-receipt"] = (("policy", "suite"), create_suite_receipt, None)
COMMANDS["verify-suite-receipt"] = (("policy", "suite", "receipt"), verify_suite_receipt, "verified")
COMMANDS["create-replay"] = (("policy", "suite"), create_replay_bundle, None)
COMMANDS["replay"] = (("bundle",), replay_bundle, "replay_passed")
COMMANDS["validate-suite"] = (('suite',), validate_suite_report, None)
COMMANDS["capture-assertions"] = (('policy', 'suite'), capture_assertions, None)
COMMANDS["diff-suites"] = (('suite', 'incoming'), diff_suites, 'identical')
COMMANDS["shard-suite"] = (('suite', 'partition'), shard_suite, None)
COMMANDS["select-outcomes"] = (('policy', 'suite', 'selection'), select_outcomes, None)
COMMANDS["deduplicate-suite"] = (('suite',), deduplicate_suite, None)
COMMANDS["audit-assertions"] = (('policy', 'suite'), audit_assertions, 'assertions_compatible')
COMMANDS["migration-expectations"] = (('policy', 'candidate', 'suite'), migration_expectations, 'no_regressions')
COMMANDS["check-suite"] = (('policy', 'suite'), check_suite, 'ready')
COMMANDS["import-responses"] = (('responses', 'expectations'), import_responses, None)

# One-line purpose per table-driven command, worded from docs/OPERATOR.md and
# docs/CORPUS.md. Used as both the --help listing entry and the description.
COMMAND_HELP = {
    "inspect-policy": "Inventory rule kinds, paths and ancestors without values.",
    "inspect-suite": (
        "Find repeated responses and conflicting expectations without values; "
        "strict exit fails on conflicting expectations."
    ),
    "merge-suites": "Append two same-version suites; duplicate case IDs fail closed.",
    "select-suite": "Select exact case IDs from a suite, preserving source order.",
    "triage-suite": (
        "Group failed expectations by rule, path and reason; strict exit fails "
        "on mismatched expectations."
    ),
    "reduce-suite": "Keep a deterministic subset that preserves every observed outcome.",
    "create-suite-receipt": "Bind a suite and its results to a recomputable receipt.",
    "verify-suite-receipt": (
        "Recompute a suite receipt; strict exit fails on inconsistent bindings."
    ),
    "create-replay": "Package policy, suite and receipt into one portable replay bundle.",
    "replay": (
        "Recompute a replay bundle; strict exit needs valid bindings and "
        "matching expectations."
    ),
    "validate-suite": "Validate a version 1.0 or 1.1 suite without evaluating a policy.",
    "capture-assertions": (
        "Record observed rule results as version 1.1 assertions once existing "
        "expectations match."
    ),
    "diff-suites": (
        "Report case, field and order changes without values; strict exit fails "
        "on any difference."
    ),
    "shard-suite": "Split a suite into one round-robin shard.",
    "select-outcomes": "Select matched, mismatched, passed or failed cases into a new suite.",
    "deduplicate-suite": "Keep the first case of each identical response and expectation.",
    "audit-assertions": (
        "Check rule assertions against the policy; strict exit fails on "
        "incompatible assertions."
    ),
    "migration-expectations": (
        "Compare expectation outcomes between two policies; strict exit fails "
        "on regressions."
    ),
    "check-suite": (
        "Run lint, consistency, assertion and regression preflight; strict exit "
        "requires all four."
    ),
    "import-responses": "Import a response array with an explicit expected-verdict array.",
}


def add_operation_parsers(subparsers):
    for name, (fields, _, strict_field) in COMMANDS.items():
        summary = COMMAND_HELP[name]
        parser = subparsers.add_parser(name, help=summary, description=summary, allow_abbrev=False)
        for field in fields:
            parser.add_argument(field, help=f"{field} JSON path, or - for stdin")
        parser.add_argument("--output", metavar="PATH", help="atomically export JSON; never overwrite an input")
        if strict_field:
            parser.add_argument(
                "--strict-exit",
                action="store_true",
                help=f"return 1 unless the result's {strict_field} is true",
            )


def run_operation(arguments, load):
    fields, function, _ = COMMANDS[arguments.command]
    return function(*(load(getattr(arguments, field)) for field in fields))
