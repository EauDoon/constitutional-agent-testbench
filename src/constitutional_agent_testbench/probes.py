"""Verified targeted synthetic mutations for bounded local regression suites."""

from copy import deepcopy
from typing import Any

from .common import (MAX_JSON_INPUT_BYTES, bounded_canonical_json_size, canonical_json,
                     ensure_json_value, stable_json)
from .evaluator import _compile, _evaluate_rule
from .policy import Policy, Rule, validate_policy
from .synthetic import (SyntheticGenerationError, _assign_path, _candidate_view, _delete_path,
                        _verify, generate_synthetic_cases)
from .suite import SuiteInputError, validate_suite

MAX_PROBE_RULES = 64
#: The longest boundary string or array a length probe builds.
MAX_LENGTH_PROBE = 4096
_PROBE_MENU: tuple[Any, ...] = (None, False, 0, 0.5, "synthetic-probe", [], {})


def _filter_probe_value(rule: Rule) -> Any:
    """First value verified to fail a type, range or length rule; boundaries first.

    One always exists: a type rule cannot admit every JSON value, every
    non-number fails a range rule, and every number fails a length rule.
    """

    boundaries: list[Any] = []
    if rule.kind == "range":
        if rule.maximum is not None:
            boundaries.append(rule.maximum + 1)
        if rule.minimum is not None:
            boundaries.append(rule.minimum - 1)
    elif rule.kind == "length":
        if rule.maximum is not None and rule.maximum + 1 <= MAX_LENGTH_PROBE:
            boundaries.extend(["s" * (int(rule.maximum) + 1), [None] * (int(rule.maximum) + 1)])
        if rule.minimum:
            boundaries.append("")
    for value in (*boundaries, *_PROBE_MENU):
        if not _evaluate_rule(rule, _candidate_view(rule.path, value))["passed"]:
            return value
    raise SyntheticGenerationError("A targeted failure could not be verified.")


def generate_rule_probes(policy: Policy | dict[str, Any]) -> dict[str, Any]:
    """Create missing-field and wrong-value probes, verifying every target failure.

    A mutation can also fail related rules. Those collateral failures are reported;
    the output never claims isolated or exhaustive behavioral coverage.
    """
    current = validate_policy(policy)
    if len(current.rules) > MAX_PROBE_RULES:
        raise SyntheticGenerationError("Targeted probes support at most 64 rules.")
    # Compile once: each probe evaluation reuses the serialized constraints, so the
    # rule cap and the accumulating output cap bound the work, not policy size.
    compiled = _compile(current)
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
                elif rule.kind in ("type", "range", "length"):
                    value = _filter_probe_value(rule)
                else:
                    forbidden = {canonical_json(v) for v in
                                 (rule.values if rule.kind == "one_of" else [rule.value])}
                    value = next(f"synthetic-probe-{n}" for n in range(257)
                                 if canonical_json(f"synthetic-probe-{n}") not in forbidden)
                _assign_path(response, rule.path, value)
            evaluation = _verify(current.policy_id, compiled, response)
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
        validate_suite(result["suite"])
        ensure_json_value(result, label="Probe output")
        bounded_canonical_json_size(result, label="Probe output", limit=MAX_JSON_INPUT_BYTES)
        if len(stable_json(result).encode("utf-8")) > MAX_JSON_INPUT_BYTES:
            raise ValueError("Formatted probe output is too large.")
    except (ValueError, SuiteInputError) as exc:
        raise SyntheticGenerationError("Probe output exceeds strict JSON or suite limits.") from exc
    return result
