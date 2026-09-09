"""Self-contained bounded replay data, never executable configuration."""
from copy import deepcopy

from .policy import policy_to_dict, validate_policy
from .suite import validate_suite
from .corpus_receipt import create_suite_receipt, verify_suite_receipt
from .workflow import WorkflowInputError, bounded_artifact


def create_replay_bundle(policy, suite):
    current, fixtures = validate_policy(policy), validate_suite(suite)
    return bounded_artifact({"replay_version": "1.0", "policy": policy_to_dict(current),
        "suite": fixtures, "receipt": create_suite_receipt(current, fixtures)})


def replay_bundle(bundle):
    """Recompute bundled evidence; consistency and matching expectations are separate."""
    bounded_artifact(bundle)
    if (not isinstance(bundle, dict) or set(bundle) != {"replay_version", "policy", "suite", "receipt"}
            or bundle["replay_version"] != "1.0"):
        raise WorkflowInputError("Replay bundle fields or version are invalid.")
    owned = deepcopy(bundle)
    verification = verify_suite_receipt(owned["policy"], owned["suite"], owned["receipt"])
    matched = owned["receipt"]["evaluation"]["matches_expectations"] if verification["verified"] else None
    return {"verified": verification["verified"], "matches_expectations": matched,
            "replay_passed": verification["verified"] and matched is True,
            "verification": verification, "values_included": False}
