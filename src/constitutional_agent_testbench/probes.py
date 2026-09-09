"""Verified targeted synthetic mutations for bounded local regression suites."""

from copy import deepcopy
from typing import Any

from .common import MAX_JSON_INPUT_BYTES, bounded_canonical_json_size, canonical_json
from .evaluator import evaluate_response
from .policy import Policy, validate_policy
from .synthetic import (SyntheticGenerationError, _assign_path, _delete_path,
                        generate_synthetic_cases)

MAX_PROBE_RULES = 64


def generate_rule_probes(policy: Policy | dict[str, Any]) -> dict[str, Any]:
    """Create missing-field and wrong-value probes, verifying every target failure.

    A mutation can also fail related rules. Those collateral failures are reported;
    the output never claims isolated or exhaustive behavioral coverage.
    """
    current = validate_policy(policy)
    if len(current.rules) > MAX_PROBE_RULES:
        raise SyntheticGenerationError("Targeted probes support at most 64 rules.")
    passing = generate_synthetic_cases(current)["passing_case"]["response"]
    cases = [{"case_id": "baseline", "response": passing, "expected_passed": True}]
    probes = []
    for index, rule in enumerate(current.rules):
        modes = ["missing"] if rule.kind == "required_field" else ["missing", "wrong_value"]
        for mode in modes:
            response = deepcopy(passing)
            if mode == "missing":
                _delete_path(response, rule.path)
            else:
                if rule.kind == "false":
                    value: Any = True
                elif rule.kind == "empty_list":
                    value = [None]
                else:
                    forbidden = {canonical_json(v) for v in
                                 (rule.values if rule.kind == "one_of" else [rule.value])}
                    value = next(f"synthetic-probe-{n}" for n in range(257)
                                 if canonical_json(f"synthetic-probe-{n}") not in forbidden)
                _assign_path(response, rule.path, value)
            evaluation = evaluate_response(current, response)
            failed = sorted(r["rule_id"] for r in evaluation["rule_results"] if not r["passed"])
            if rule.rule_id not in failed:
                raise SyntheticGenerationError("A targeted failure could not be verified.")
            case_id = f"probe-{index}-{mode}"
            cases.append({"case_id": case_id, "response": response, "expected_passed": False})
            probes.append({"case_id": case_id, "target_rule_id": rule.rule_id,
                           "mutation": mode, "failed_rule_ids": failed})
            # Reject growing artifacts before retaining arbitrarily many large copies.
            try:
                bounded_canonical_json_size(cases, label="Probe cases", limit=MAX_JSON_INPUT_BYTES)
            except ValueError as exc:
                raise SyntheticGenerationError("Probe output exceeds the 1,000,000-byte limit.") from exc
    result = {"policy_id": current.policy_id, "suite": {"suite_version": "1.0", "cases": cases},
              "probes": probes, "coverage_scope": "verified synthetic mutations only"}
    try:
        bounded_canonical_json_size(result, label="Probe output", limit=MAX_JSON_INPUT_BYTES)
    except ValueError as exc:
        raise SyntheticGenerationError("Probe output exceeds the 1,000,000-byte limit.") from exc
    return result
