"""CLI adapter for inspection and corpus workflows; all inputs are strict JSON."""

from .inspection import inspect_policy, inspect_suite
from .curation import merge_suites, select_suite, reduce_suite
from .triage import triage_suite
from .corpus_receipt import create_suite_receipt, verify_suite_receipt
from .replay import create_replay_bundle, replay_bundle


from .suite import validate_suite_report

from .curation import capture_assertions

from .inspection import diff_suites

from .curation import shard_suite

from .curation import select_outcomes

from .curation import deduplicate_suite

from .inspection import audit_assertions

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


def add_operation_parsers(subparsers):
    for name, (fields, _, strict_field) in COMMANDS.items():
        parser = subparsers.add_parser(name, help=f"Run {name} locally.", allow_abbrev=False)
        for field in fields:
            parser.add_argument(field, help=f"{field} JSON path, or - for stdin")
        parser.add_argument("--output", metavar="PATH", help="atomically export JSON; never overwrite an input")
        if strict_field:
            parser.add_argument("--strict-exit", action="store_true")


def run_operation(arguments, load):
    fields, function, _ = COMMANDS[arguments.command]
    return function(*(load(getattr(arguments, field)) for field in fields))
