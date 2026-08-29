"""Exhaustive order-conformance checks for declared peer rules."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Callable
from copy import deepcopy
from itertools import permutations
from math import factorial
from typing import Any

from .common import (
    MAX_JSON_INPUT_BYTES,
    TestbenchError,
    bounded_canonical_json_size,
    canonical_json,
    ensure_json_value,
)
from .evaluator import evaluate_response
from .policy import (
    Policy,
    PolicyValidationError,
    Rule,
    policy_to_dict,
    validate_policy,
)


REPORT_SCHEMA_VERSION = "1.0"
BASELINE_REPEATS = 3
ORDER_REPEATS = BASELINE_REPEATS
MIN_EXHAUSTIVE_RULES = 2
MAX_EXHAUSTIVE_RULES = 7
MAX_EXHAUSTIVE_WORK_BYTES = 100_000_000
MAX_EVALUATOR_RESULT_BYTES = 1_000_000
MAX_REPORT_BYTES = 1_000_000

Evaluator = Callable[[Policy, Any], dict[str, Any]]


class PrecedenceTraceError(TestbenchError):
    """Raised when an order-conformance check cannot be performed safely."""

    code = "ORDER_CHECK_INVALID"


class OrderCheckTooLargeError(PrecedenceTraceError):
    """Raised when exhaustive enumeration would exceed the public bound."""

    code = "ORDER_CHECK_TOO_LARGE"


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _validate_evaluation(result: Any, policy: Policy) -> tuple[dict[str, Any], int]:
    if not isinstance(result, dict) or not isinstance(result.get("passed"), bool):
        raise PrecedenceTraceError(
            "Evaluator result must be an object with a boolean passed field."
        )
    if set(result) != {"passed", "policy_id", "rule_results"} or not isinstance(
        result.get("policy_id"), str
    ):
        raise PrecedenceTraceError(
            "Evaluator result must match the exact CAT result contract."
        )
    rule_results = result.get("rule_results")
    if not isinstance(rule_results, list):
        raise PrecedenceTraceError("Evaluator result must contain rule_results.")
    declared_rules = {rule.rule_id: rule for rule in policy.rules}
    seen_rule_ids: set[str] = set()
    for item in rule_results:
        if not isinstance(item, dict):
            raise PrecedenceTraceError("Every rule result must be an object.")
        if set(item) != {"kind", "passed", "path", "reason_code", "rule_id"}:
            raise PrecedenceTraceError(
                "Every rule result must match the exact CAT rule-result contract."
            )
        if not isinstance(item.get("rule_id"), str) or not isinstance(
            item.get("passed"), bool
        ):
            raise PrecedenceTraceError(
                "Every rule result must identify a rule and boolean pass state."
            )
        for field in ("kind", "path", "reason_code"):
            if not isinstance(item.get(field), str):
                raise PrecedenceTraceError(
                    f"Every rule result must contain string field {field}."
                )
        if not 1 <= len(item["reason_code"]) <= 128:
            raise PrecedenceTraceError(
                "Every rule result reason_code must contain 1 to 128 characters."
            )
        rule_id = item["rule_id"]
        if rule_id not in declared_rules:
            raise PrecedenceTraceError(
                "Evaluator result contains an undeclared rule_id."
            )
        if rule_id in seen_rule_ids:
            raise PrecedenceTraceError(
                "Evaluator result repeats a declared rule_id."
            )
        seen_rule_ids.add(rule_id)
        declared_rule = declared_rules[rule_id]
        if item["kind"] != declared_rule.kind or item["path"] != declared_rule.path:
            raise PrecedenceTraceError(
                "Evaluator result kind and path must match the declared rule."
            )
    complete = seen_rule_ids == set(declared_rules)
    expected_passed = complete and all(item["passed"] for item in rule_results)
    if result["passed"] != expected_passed:
        raise PrecedenceTraceError(
            "Evaluator result passed field is inconsistent with rule coverage and results."
        )
    try:
        ensure_json_value(result, label="Evaluator result")
    except (OverflowError, RecursionError, TypeError, ValueError) as exc:
        raise PrecedenceTraceError("Evaluator result is not strict JSON.") from exc
    try:
        result_bytes = bounded_canonical_json_size(
            result,
            label="Evaluator result",
            limit=MAX_EVALUATOR_RESULT_BYTES,
        )
    except ValueError as exc:
        raise OrderCheckTooLargeError(
            "Evaluator result exceeds the per-result byte limit."
        ) from exc
    return deepcopy(result), result_bytes


def _run_evaluator(
    evaluator: Evaluator,
    policy: Policy,
    response: Any,
) -> tuple[dict[str, Any], int]:
    try:
        result = evaluator(deepcopy(policy), deepcopy(response))
    except TestbenchError:
        raise
    except Exception as exc:
        raise PrecedenceTraceError("Evaluator failed during order checking.") from exc
    validated_result, result_bytes = _validate_evaluation(result, policy)
    if validated_result["policy_id"] != policy.policy_id:
        raise PrecedenceTraceError(
            "Evaluator result policy_id does not match the requested policy."
        )
    return validated_result, result_bytes


def _counter_projection(counter: Counter[Any], labels: tuple[str, ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, count in sorted(counter.items()):
        values = key if isinstance(key, tuple) else (key,)
        row = {label: value for label, value in zip(labels, values, strict=True)}
        row["count"] = count
        rows.append(row)
    return rows


def _projections(
    result: dict[str, Any], requested_order: tuple[str, ...]
) -> dict[str, Any]:
    rule_results = result["rule_results"]
    participation = Counter(item["rule_id"] for item in rule_results)
    expected_participation = Counter(requested_order)
    presentation = tuple(item["rule_id"] for item in rule_results)
    requested_positions = {rule_id: index for index, rule_id in enumerate(requested_order)}
    follows_requested_order = (
        len(presentation) == len(set(presentation))
        and all(rule_id in requested_positions for rule_id in presentation)
        and list(presentation)
        == sorted(presentation, key=requested_positions.__getitem__)
    )
    return {
        "overall_pass": result["passed"],
        "rule_passes": {
            item["rule_id"]: item["passed"] for item in rule_results
        },
        "reason_by_rule": {
            item["rule_id"]: (item["kind"], item["path"], item["reason_code"])
            for item in rule_results
        },
        "participation": _counter_projection(participation, ("rule_id",)),
        "participation_complete": participation == expected_participation,
        "presentation": {
            "rule_ids": list(presentation),
        },
        "presentation_follows_requested_order": follows_requested_order,
    }


def _different(left: Any, right: Any) -> bool:
    return canonical_json(left) != canonical_json(right)


def _dimension_projection_pair(
    dimension: str,
    left: dict[str, Any],
    right: dict[str, Any],
) -> tuple[Any, Any]:
    if dimension == "outcome":
        shared_rule_ids = sorted(
            set(left["rule_passes"]) & set(right["rule_passes"])
        )
        left_projection = {
            "shared_rule_passes": {
                rule_id: left["rule_passes"][rule_id]
                for rule_id in shared_rule_ids
            },
        }
        right_projection = {
            "shared_rule_passes": {
                rule_id: right["rule_passes"][rule_id]
                for rule_id in shared_rule_ids
            },
        }
        if not _different(left["participation"], right["participation"]):
            left_projection["overall_pass"] = left["overall_pass"]
            right_projection["overall_pass"] = right["overall_pass"]
        return left_projection, right_projection
    if dimension == "reason_evidence":
        shared_rule_ids = sorted(
            set(left["reason_by_rule"]) & set(right["reason_by_rule"])
        )
        return (
            {
                "shared_rule_evidence": {
                    rule_id: list(left["reason_by_rule"][rule_id])
                    for rule_id in shared_rule_ids
                },
            },
            {
                "shared_rule_evidence": {
                    rule_id: list(right["reason_by_rule"][rule_id])
                    for rule_id in shared_rule_ids
                },
            },
        )
    if dimension == "participation":
        return left["participation"], right["participation"]
    if dimension == "presentation":
        return left["presentation"], right["presentation"]
    raise ValueError(f"Unsupported precedence dimension: {dimension}")


def _adjacent_witness(
    dimension: str,
    orders: list[tuple[str, ...]],
    observations: dict[tuple[str, ...], dict[str, Any]],
) -> dict[str, Any] | None:
    known_orders = set(observations)
    for left_order in orders:
        for swap_index in range(len(left_order) - 1):
            right = list(left_order)
            right[swap_index], right[swap_index + 1] = (
                right[swap_index + 1],
                right[swap_index],
            )
            right_order = tuple(right)
            if right_order not in known_orders:
                continue
            left_projection, right_projection = _dimension_projection_pair(
                dimension,
                observations[left_order]["projections"],
                observations[right_order]["projections"],
            )
            if not _different(left_projection, right_projection):
                continue
            return {
                "comparison": "adjacent_swap",
                "dimension": dimension,
                "left_order": list(left_order),
                "left_projection": left_projection,
                "right_order": list(right_order),
                "right_projection": right_projection,
                "swap_index": swap_index,
                "swapped_rule_ids": [
                    left_order[swap_index],
                    left_order[swap_index + 1],
                ],
            }
    return None


def _adjacent_swap_path(
    left_order: tuple[str, ...],
    right_order: tuple[str, ...],
) -> list[list[str]]:
    """Return a deterministic adjacent-swap path between two permutations."""

    current = list(left_order)
    path = [list(current)]
    for target_index, rule_id in enumerate(right_order):
        current_index = current.index(rule_id)
        while current_index > target_index:
            current[current_index - 1], current[current_index] = (
                current[current_index],
                current[current_index - 1],
            )
            current_index -= 1
            path.append(list(current))
    return path


def _endpoint_path_witness(
    dimension: str,
    reason: str,
    left_order: tuple[str, ...],
    left_projection: dict[str, Any],
    right_order: tuple[str, ...],
    right_projection: dict[str, Any],
) -> dict[str, Any]:
    return {
        "adjacent_swap_path": _adjacent_swap_path(left_order, right_order),
        "comparison": "endpoint_path",
        "dimension": dimension,
        "left_order": list(left_order),
        "left_projection": left_projection,
        "reason": reason,
        "right_order": list(right_order),
        "right_projection": right_projection,
    }


def _global_identity_witness(
    dimension: str,
    orders: list[tuple[str, ...]],
    observations: dict[tuple[str, ...], dict[str, Any]],
) -> dict[str, Any] | None:
    """Find identity-level drift even when co-presence regions are disconnected."""

    if dimension == "outcome":
        first_pass_by_rule: dict[str, tuple[bool, tuple[str, ...]]] = {}
        for order in orders:
            projections = observations[order]["projections"]
            for rule_id, passed in sorted(projections["rule_passes"].items()):
                prior = first_pass_by_rule.get(rule_id)
                if prior is None:
                    first_pass_by_rule[rule_id] = (passed, order)
                    continue
                prior_passed, prior_order = prior
                if passed != prior_passed:
                    return _endpoint_path_witness(
                        dimension,
                        "shared_rule_pass",
                        prior_order,
                        {"passed": prior_passed, "rule_id": rule_id},
                        order,
                        {"passed": passed, "rule_id": rule_id},
                    )

        first_overall_by_participation: dict[
            str, tuple[bool, tuple[str, ...], list[dict[str, Any]]]
        ] = {}
        for order in orders:
            projections = observations[order]["projections"]
            participation = projections["participation"]
            participation_key = canonical_json(participation)
            prior = first_overall_by_participation.get(participation_key)
            if prior is None:
                first_overall_by_participation[participation_key] = (
                    projections["overall_pass"],
                    order,
                    participation,
                )
                continue
            prior_passed, prior_order, prior_participation = prior
            if projections["overall_pass"] != prior_passed:
                return _endpoint_path_witness(
                    dimension,
                    "aggregate_with_equal_participation",
                    prior_order,
                    {
                        "overall_pass": prior_passed,
                        "participation": prior_participation,
                    },
                    order,
                    {
                        "overall_pass": projections["overall_pass"],
                        "participation": participation,
                    },
                )
        return None

    if dimension == "reason_evidence":
        first_evidence_by_rule: dict[
            str, tuple[tuple[str, str, str], tuple[str, ...]]
        ] = {}
        for order in orders:
            evidence_by_rule = observations[order]["projections"]["reason_by_rule"]
            for rule_id, evidence in sorted(evidence_by_rule.items()):
                prior = first_evidence_by_rule.get(rule_id)
                if prior is None:
                    first_evidence_by_rule[rule_id] = (evidence, order)
                    continue
                prior_evidence, prior_order = prior
                if evidence != prior_evidence:
                    return _endpoint_path_witness(
                        dimension,
                        "shared_rule_evidence",
                        prior_order,
                        {
                            "kind": prior_evidence[0],
                            "path": prior_evidence[1],
                            "reason_code": prior_evidence[2],
                            "rule_id": rule_id,
                        },
                        order,
                        {
                            "kind": evidence[0],
                            "path": evidence[1],
                            "reason_code": evidence[2],
                            "rule_id": rule_id,
                        },
                    )
        return None

    raise ValueError(f"Unsupported global precedence dimension: {dimension}")


def _nondeterministic_report(
    policy: Policy,
    repeated_order: tuple[str, ...],
    repeated_results: list[dict[str, Any]],
    estimated_work_bytes: int,
    orders_evaluated: int,
    evaluator_runs: int,
    observed_result_bytes: int,
    charged_work_bytes: int,
) -> dict[str, Any]:
    differing_pair = next(
        (index for index in range(1, len(repeated_results))
         if _different(repeated_results[0], repeated_results[index])),
        1,
    )
    return {
        "baseline_repeats": BASELINE_REPEATS,
        "evaluation_repeats_per_order": ORDER_REPEATS,
        "conforms_within_coverage": None,
        "coverage": {
            "mode": "incomplete",
            "evaluator_runs": evaluator_runs,
            "evaluations_performed": evaluator_runs,
            "evaluations_per_order": ORDER_REPEATS,
            "orders_evaluated": orders_evaluated,
            "orders_completed": orders_evaluated - 1,
            "orders_attempted": orders_evaluated,
            "orders_total": factorial(len(policy.rules)),
            "rule_count": len(policy.rules),
            "estimated_work_bytes": estimated_work_bytes,
            "estimated_input_work_bytes": estimated_work_bytes,
            "observed_result_bytes": observed_result_bytes,
            "charged_work_bytes": charged_work_bytes,
            "result_byte_limit": MAX_EVALUATOR_RESULT_BYTES,
            "report_byte_limit": MAX_REPORT_BYTES,
            "work_budget_bytes": MAX_EXHAUSTIVE_WORK_BYTES,
        },
        "policy_id": policy.policy_id,
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "status": "INCONCLUSIVE_NONDETERMINISTIC",
        "variance": None,
        "witnesses": [
            {
                "dimension": "evaluator_result",
                "left_fingerprint": _fingerprint(repeated_results[0]),
                "left_repeat": 1,
                "order": list(repeated_order),
                "right_fingerprint": _fingerprint(
                    repeated_results[differing_pair]
                ),
                "right_repeat": differing_pair + 1,
            }
        ],
    }


def _bounded_report(report: dict[str, Any]) -> dict[str, Any]:
    try:
        bounded_canonical_json_size(
            report,
            label="Order-conformance report",
            limit=MAX_REPORT_BYTES,
        )
    except ValueError as exc:
        raise OrderCheckTooLargeError(
            "Order-conformance report exceeds the public byte limit."
        ) from exc
    return report


def check_order_conformance(
    policy: Policy | dict[str, Any],
    response: Any,
    *,
    evaluator: Evaluator = evaluate_response,
) -> dict[str, Any]:
    """Exhaustively check semantic order variance for two to seven rules.

    A clean report establishes only that no variance was observed for this
    fixed response, trusted in-process evaluator, and complete permutation set.

    A custom evaluator is executable Python code. This function validates and
    bounds only the JSON value returned after the evaluator completes; it does
    not sandbox, time-limit, or roll back that callable.
    """

    try:
        validated_policy = validate_policy(policy)
    except PolicyValidationError as exc:
        raise PrecedenceTraceError(str(exc)) from exc
    rule_count = len(validated_policy.rules)
    if rule_count < MIN_EXHAUSTIVE_RULES:
        raise PrecedenceTraceError(
            "Order checking requires at least two declared peer rules."
        )
    if rule_count > MAX_EXHAUSTIVE_RULES:
        raise OrderCheckTooLargeError(
            "Exhaustive order checking supports at most seven rules."
        )
    if not isinstance(response, dict):
        raise PrecedenceTraceError("Candidate response must be a JSON object.")
    try:
        ensure_json_value(response, label="Candidate response")
        response_bytes = bounded_canonical_json_size(
            response,
            label="Candidate response",
            limit=MAX_JSON_INPUT_BYTES,
        )
    except (RecursionError, TypeError, ValueError) as exc:
        raise PrecedenceTraceError(str(exc)) from exc

    order_count = factorial(rule_count)
    try:
        policy_bytes = bounded_canonical_json_size(
            policy_to_dict(validated_policy),
            label="Policy",
            limit=MAX_JSON_INPUT_BYTES,
        )
    except ValueError as exc:
        raise PrecedenceTraceError(str(exc)) from exc
    serialized_input_bytes = policy_bytes + response_bytes
    total_planned_runs = order_count * ORDER_REPEATS
    estimated_work_bytes = serialized_input_bytes * total_planned_runs
    if estimated_work_bytes > MAX_EXHAUSTIVE_WORK_BYTES:
        raise OrderCheckTooLargeError(
            "Exhaustive order checking exceeds the deterministic work budget."
        )

    rule_orders = list(permutations(validated_policy.rules))
    id_orders = [tuple(rule.rule_id for rule in order) for order in rule_orders]
    observations: dict[tuple[str, ...], dict[str, Any]] = {}
    evaluator_runs = 0
    observed_result_bytes = 0
    charged_work_bytes = 0
    for rules, order_ids in zip(rule_orders, id_orders, strict=True):
        permuted_policy = Policy(
            policy_id=validated_policy.policy_id,
            rules=rules,
            schema_version=validated_policy.schema_version,
        )
        repeated_results: list[dict[str, Any]] = []
        for _ in range(ORDER_REPEATS):
            result, result_bytes = _run_evaluator(
                evaluator, permuted_policy, response
            )
            evaluator_runs += 1
            observed_result_bytes += result_bytes
            charged_work_bytes = (
                evaluator_runs * serialized_input_bytes + observed_result_bytes
            )
            if charged_work_bytes > MAX_EXHAUSTIVE_WORK_BYTES:
                raise OrderCheckTooLargeError(
                    "Exhaustive order checking exceeds the deterministic work budget."
                )
            repeated_results.append(result)
        if any(
            _different(repeated_results[0], result)
            for result in repeated_results[1:]
        ):
            return _bounded_report(_nondeterministic_report(
                validated_policy,
                order_ids,
                repeated_results,
                estimated_work_bytes,
                len(observations) + 1,
                evaluator_runs,
                observed_result_bytes,
                charged_work_bytes,
            ))
        result = repeated_results[0]
        observations[order_ids] = {
            "projections": _projections(result, order_ids),
            "result_fingerprint": _fingerprint(result),
        }

    dimensions = ("outcome", "reason_evidence", "participation", "presentation")
    adjacent_witnesses = {
        dimension: _adjacent_witness(
            dimension,
            id_orders,
            observations,
        )
        for dimension in dimensions
    }
    global_identity_witnesses = {
        dimension: _global_identity_witness(
            dimension,
            id_orders,
            observations,
        )
        for dimension in ("outcome", "reason_evidence")
    }
    variance = {
        "outcome": global_identity_witnesses["outcome"] is not None,
        "reason_evidence": (
            global_identity_witnesses["reason_evidence"] is not None
        ),
        "participation": adjacent_witnesses["participation"] is not None,
        "presentation": adjacent_witnesses["presentation"] is not None,
    }
    dimension_witnesses = {
        dimension: (
            adjacent_witnesses[dimension]
            or global_identity_witnesses.get(dimension)
        )
        for dimension in dimensions
    }
    presentation_follows_requested_order = all(
        observation["projections"]["presentation_follows_requested_order"]
        for observation in observations.values()
    )
    incomplete_participation = any(
        not observation["projections"]["participation_complete"]
        for observation in observations.values()
    )

    semantic_variance_count = sum(
        variance[dimension]
        for dimension in ("outcome", "reason_evidence", "participation")
    )
    if semantic_variance_count > 1:
        status = "COMPOUND_ORDER_DRIFT"
    elif variance["participation"]:
        status = "PARTICIPATION_ORDER_DRIFT"
    elif variance["outcome"]:
        status = "SEMANTIC_ORDER_DRIFT"
    elif variance["reason_evidence"]:
        status = "EVIDENCE_ORDER_DRIFT"
    elif incomplete_participation:
        status = "INCOMPLETE_RULE_COVERAGE"
    elif variance["presentation"]:
        status = "PRESENTATION_ONLY_DRIFT"
    else:
        status = "NO_VARIANCE_OBSERVED"

    witnesses = [
        dimension_witnesses[dimension]
        for dimension in dimensions
        if dimension_witnesses[dimension] is not None
    ]
    incomplete_orders = [
        order
        for order, observation in observations.items()
        if not observation["projections"]["participation_complete"]
    ]
    if incomplete_orders:
        first_incomplete = incomplete_orders[0]
        reported = set(
            observations[first_incomplete]["projections"]["rule_passes"]
        )
        witnesses.append({
            "dimension": "rule_coverage",
            "order": list(first_incomplete),
            "missing_rule_ids": [
                rule_id for rule_id in first_incomplete if rule_id not in reported
            ],
        })
    semantic_drift = incomplete_participation or any(
        variance[dimension]
        for dimension in ("outcome", "reason_evidence", "participation")
    )

    report = {
        "baseline_repeats": BASELINE_REPEATS,
        "evaluation_repeats_per_order": ORDER_REPEATS,
        "conforms_within_coverage": not semantic_drift,
        "coverage": {
            "evaluator_runs": evaluator_runs,
            "evaluations_performed": evaluator_runs,
            "evaluations_per_order": ORDER_REPEATS,
            "mode": "exhaustive",
            "orders_evaluated": len(observations),
            "orders_total": order_count,
            "rule_count": rule_count,
            "estimated_work_bytes": estimated_work_bytes,
            "estimated_input_work_bytes": estimated_work_bytes,
            "observed_result_bytes": observed_result_bytes,
            "charged_work_bytes": charged_work_bytes,
            "observed_work_bytes": charged_work_bytes,
            "result_byte_limit": MAX_EVALUATOR_RESULT_BYTES,
            "report_byte_limit": MAX_REPORT_BYTES,
            "rule_results_complete": not incomplete_participation,
            "incomplete_orders": len(incomplete_orders),
            "work_budget_bytes": MAX_EXHAUSTIVE_WORK_BYTES,
        },
        "policy_id": validated_policy.policy_id,
        "presentation_follows_requested_order": presentation_follows_requested_order,
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "status": status,
        "variance": variance,
        "witnesses": witnesses,
    }
    return _bounded_report(report)
