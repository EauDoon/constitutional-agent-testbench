"""Whole-corpus consistency receipts. Digests do not establish authenticity."""
import re

from .common import canonical_json
from .policy import validate_policy, policy_to_dict
from .receipt import _digest
from .suite import validate_suite, evaluate_suite
from .workflow import bounded_artifact, WorkflowInputError


def create_suite_receipt(policy, suite):
    current, fixtures = validate_policy(policy), validate_suite(suite)
    return bounded_artifact({"suite_receipt_version": "1.0",
        "digest_algorithm": "sha256-canonical-json-v1", "policy_digest": _digest(policy_to_dict(current)),
        "suite_digest": _digest(fixtures), "evaluation": evaluate_suite(current, fixtures)})


def verify_suite_receipt(policy, suite, receipt):
    bounded_artifact(receipt)
    keys = {"suite_receipt_version", "digest_algorithm", "policy_digest", "suite_digest", "evaluation"}
    if (not isinstance(receipt, dict) or set(receipt) != keys
            or receipt["suite_receipt_version"] != "1.0"
            or receipt["digest_algorithm"] != "sha256-canonical-json-v1"):
        raise WorkflowInputError("Suite receipt fields, version or algorithm are invalid.")
    for key in ("policy_digest", "suite_digest"):
        if not isinstance(receipt[key], str) or not re.fullmatch(r"[0-9a-f]{64}", receipt[key]):
            raise WorkflowInputError("Suite receipt digests must be lowercase SHA-256 hex.")
    expected = create_suite_receipt(policy, suite)
    mismatches = sorted(key for key in keys if canonical_json(receipt[key]) != canonical_json(expected[key]))
    return {"verified": not mismatches, "mismatched_fields": mismatches,
            "verification_scope": "recomputed corpus consistency; no authenticity claim"}
