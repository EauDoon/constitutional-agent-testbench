"""Replay another policy engine's decision log against a Testbench policy.

An engine such as Open Policy Agent or Cedar logs each input it saw and the
allow or deny it returned. These functions read such a log, pair each input
with the engine's verdict, and either import the pairs as a fixture suite or
compare them with a Testbench policy evaluated on the same inputs. A
disagreement means the two policies, which are meant to say the same thing,
do not. Reports carry identifiers, verdicts and rule IDs, never input values.
"""

from __future__ import annotations

import re
from typing import Any

from .common import (MAX_JSON_INPUT_BYTES, JsonInputError, TestbenchError,
                     bounded_canonical_json_size, copy_json_tree, ensure_json_value,
                     get_field, parse_json_text)
from .evaluator import _compile, _evaluate_compiled
from .policy import Policy, validate_policy
from .suite import MAX_SUITE_CASES, validate_suite

DECISION_LOG_FORMATS = ("generic", "opa", "cedar")
DECISION_LOG_VERSION = "1.0"
DECISION_LOG_REPORT_VERSION = "1.0"
MAX_LOG_DECISIONS = 10_000
MAX_REPORTED_DISAGREEMENTS = 256

_PATH_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*$")
_CASE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_GENERIC_ENTRY_KEYS = {"input", "allow"}
_CEDAR_DECISIONS = {"allow": True, "deny": False}


class DecisionLogInputError(TestbenchError):
    code = "INVALID_DECISION_LOG"


def parse_decision_log_text(text: str) -> Any:
    """Parse a decision log as one strict JSON document or as JSON Lines.

    OPA writes one event per line, so a file that is not a single JSON value
    is read line by line. Blank lines are ignored. Every line must be strict
    JSON, and the whole text stays within the 1,000,000-byte input limit.
    """

    try:
        oversized = len(text.encode("utf-8")) > MAX_JSON_INPUT_BYTES
    except (AttributeError, UnicodeError) as exc:
        raise DecisionLogInputError("The decision log is not valid UTF-8 text.") from exc
    if oversized:
        raise DecisionLogInputError(
            "The decision log exceeds the 1,000,000-byte file-size limit.")
    try:
        return parse_json_text(text)
    except JsonInputError as exc:
        if "\n" not in text.strip():
            raise DecisionLogInputError(
                "The decision log is neither strict JSON nor JSON Lines.") from exc
    entries = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entries.append(parse_json_text(line))
        except JsonInputError as exc:
            raise DecisionLogInputError(
                f"Decision log line {number} is not strict JSON.") from exc
    if not entries:
        raise DecisionLogInputError("The decision log has no entries.")
    return entries


def _check_option_path(value: str | None, *, label: str) -> str | None:
    if value is not None and (not isinstance(value, str) or not _PATH_PATTERN.fullmatch(value)):
        raise DecisionLogInputError(f"{label} must be a dot-separated object field path.")
    return value


def _entries(log: Any, log_format: str) -> list[Any]:
    if log_format == "generic":
        if (not isinstance(log, dict) or set(log) != {"log_version", "decisions"}
                or log["log_version"] != DECISION_LOG_VERSION):
            raise DecisionLogInputError(
                'A generic decision log is {"log_version": "1.0", "decisions": [...]}.')
        entries = log["decisions"]
        if not isinstance(entries, list):
            raise DecisionLogInputError("Generic decisions must be an array.")
        return entries
    if isinstance(log, dict):
        return [log]
    if isinstance(log, list):
        return log
    raise DecisionLogInputError("A decision log must be an array, an object or JSON Lines.")


def _decision_id(entry: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = entry.get(key)
        if isinstance(value, str):
            return value
    return None


def _opa_entry(entry: dict[str, Any], index: int, result_path: str) -> tuple[Any, bool]:
    if entry.get("erased") or entry.get("masked"):
        raise DecisionLogInputError(
            f"Decision {index} has erased or masked fields, so its input cannot be replayed.")
    if "input" not in entry or "result" not in entry:
        raise DecisionLogInputError(f"Decision {index} needs both input and result.")
    result = entry["result"]
    if isinstance(result, dict):
        found, result = get_field(result, result_path)
        if not found:
            raise DecisionLogInputError(
                f"Decision {index} result has no field at the result path.")
    if type(result) is not bool:
        raise DecisionLogInputError(
            f"Decision {index} result must be a boolean or an object with a boolean "
            "at the result path.")
    return entry["input"], result


def _cedar_entry(entry: dict[str, Any], index: int) -> tuple[Any, bool]:
    if "request" not in entry or "decision" not in entry:
        raise DecisionLogInputError(f"Decision {index} needs both request and decision.")
    decision = entry["decision"]
    if not isinstance(decision, str) or decision.lower() not in _CEDAR_DECISIONS:
        raise DecisionLogInputError(f"Decision {index} decision must be Allow or Deny.")
    return entry["request"], _CEDAR_DECISIONS[decision.lower()]


def _generic_entry(entry: dict[str, Any], index: int) -> tuple[Any, bool]:
    if not _GENERIC_ENTRY_KEYS <= set(entry) <= _GENERIC_ENTRY_KEYS | {"decision_id"}:
        raise DecisionLogInputError(
            f"Decision {index} must have input and allow, and may have decision_id.")
    if type(entry["allow"]) is not bool:
        raise DecisionLogInputError(f"Decision {index} allow must be a boolean.")
    return entry["input"], entry["allow"]


def normalize_decision_log(
    log: Any,
    *,
    log_format: str,
    result_path: str = "allow",
    decision_path: str | None = None,
    input_path: str | None = None,
) -> dict[str, Any]:
    """Return the log's decisions as ``{decision_id, input, allow}`` records.

    ``log_format`` is ``opa`` (decision log events with ``input`` and
    ``result``), ``cedar`` (``request`` and an ``Allow`` or ``Deny``
    ``decision``) or ``generic`` (``{"log_version": "1.0", "decisions":
    [{"decision_id", "input", "allow"}]}``). For OPA, a ``result`` object is
    read at ``result_path``, and ``decision_path`` keeps only events whose
    ``path`` matches, counting the rest as skipped. ``input_path`` replays a
    sub-object of each input, such as a Cedar request's ``context``.
    """

    if log_format not in DECISION_LOG_FORMATS:
        raise DecisionLogInputError("Decision log format must be generic, opa or cedar.")
    _check_option_path(result_path, label="The result path")
    _check_option_path(input_path, label="The input path")
    if decision_path is not None and (not isinstance(decision_path, str) or not decision_path
                                      or len(decision_path) > 256):
        raise DecisionLogInputError("The decision path must be 1 to 256 characters.")
    try:
        ensure_json_value(log, label="Decision log")
        bounded_canonical_json_size(log, label="Decision log", limit=MAX_JSON_INPUT_BYTES)
    except (TypeError, ValueError, RecursionError) as exc:
        raise DecisionLogInputError("The decision log exceeds strict JSON limits.") from exc
    entries = _entries(log, log_format)
    if not 1 <= len(entries) <= MAX_LOG_DECISIONS:
        raise DecisionLogInputError(
            f"A decision log needs 1 to {MAX_LOG_DECISIONS:,} decisions.")
    decisions = []
    skipped = 0
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise DecisionLogInputError(f"Decision {index} must be a JSON object.")
        if log_format == "opa":
            if decision_path is not None and entry.get("path") != decision_path:
                skipped += 1
                continue
            raw_input, allow = _opa_entry(entry, index, result_path)
            decision_id = _decision_id(entry, ("decision_id",))
        elif log_format == "cedar":
            raw_input, allow = _cedar_entry(entry, index)
            decision_id = _decision_id(entry, ("decision_id", "id"))
        else:
            raw_input, allow = _generic_entry(entry, index)
            decision_id = _decision_id(entry, ("decision_id",))
        if input_path is not None:
            found, raw_input = (get_field(raw_input, input_path) if isinstance(raw_input, dict)
                                else (False, None))
            if not found:
                raise DecisionLogInputError(
                    f"Decision {index} input has no field at the input path.")
        if not isinstance(raw_input, dict):
            raise DecisionLogInputError(f"Decision {index} input must be a JSON object.")
        decisions.append({"index": index, "decision_id": decision_id,
                          "input": copy_json_tree(raw_input), "allow": allow})
    if not decisions:
        raise DecisionLogInputError("No decision in the log matched the decision path.")
    return {"engine_format": log_format, "decisions": decisions, "skipped": skipped}


def _case_ids(decisions: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    identifiers = []
    for decision in decisions:
        candidate = decision["decision_id"]
        if not isinstance(candidate, str) or not _CASE_ID_PATTERN.fullmatch(candidate) \
                or candidate in seen:
            candidate = f"decision-{decision['index']:05d}"
        # A generated identifier can still collide with a logged one.
        while candidate in seen:
            candidate = f"{candidate}-dup"
        seen.add(candidate)
        identifiers.append(candidate)
    return identifiers


def import_decision_log(log: Any, *, log_format: str, result_path: str = "allow",
                        decision_path: str | None = None,
                        input_path: str | None = None) -> dict[str, Any]:
    """Import up to 256 logged decisions as a version 1.0 fixture suite.

    Each case's response is the logged input and ``expected_passed`` is the
    engine's verdict, so ``run-suite`` against a Testbench policy reports every
    input where the two policies disagree.
    """

    normalized = normalize_decision_log(log, log_format=log_format, result_path=result_path,
                                        decision_path=decision_path, input_path=input_path)
    decisions = normalized["decisions"]
    if len(decisions) > MAX_SUITE_CASES:
        raise DecisionLogInputError(
            f"A suite holds at most {MAX_SUITE_CASES} cases; use compare-decision-log "
            "for larger logs or split the log.")
    cases = [{"case_id": case_id, "response": decision["input"],
              "expected_passed": decision["allow"]}
             for case_id, decision in zip(_case_ids(decisions), decisions, strict=True)]
    return validate_suite({"suite_version": "1.0", "cases": cases})


def compare_decision_log(policy: Policy | dict[str, Any], log: Any, *, log_format: str,
                         result_path: str = "allow", decision_path: str | None = None,
                         input_path: str | None = None) -> dict[str, Any]:
    """Evaluate every logged input and compare the verdict with the engine's.

    ``agrees`` is true only when every replayed decision matches.
    ``engine_more_permissive`` counts inputs the engine allowed that the
    Testbench policy fails; ``engine_more_restrictive`` counts the reverse.
    The first 256 disagreements are listed with their failed rule IDs.
    """

    current = validate_policy(policy)
    normalized = normalize_decision_log(log, log_format=log_format, result_path=result_path,
                                        decision_path=decision_path, input_path=input_path)
    compiled = _compile(current)
    disagreements: list[dict[str, Any]] = []
    permissive = restrictive = allowed = passed = 0
    decisions = normalized["decisions"]
    for decision in decisions:
        evaluation = _evaluate_compiled(current.policy_id, compiled, decision["input"])
        allowed += decision["allow"]
        passed += evaluation["passed"]
        if evaluation["passed"] == decision["allow"]:
            continue
        if decision["allow"]:
            permissive += 1
        else:
            restrictive += 1
        if len(disagreements) < MAX_REPORTED_DISAGREEMENTS:
            disagreements.append({
                "decision_id": decision["decision_id"],
                "engine_allowed": decision["allow"],
                "failed_rule_ids": [result["rule_id"] for result in evaluation["rule_results"]
                                    if not result["passed"]],
                "index": decision["index"],
                "testbench_passed": evaluation["passed"],
            })
    disagreed = permissive + restrictive
    return {
        "agreed": len(decisions) - disagreed,
        "agrees": disagreed == 0,
        "decisions": len(decisions),
        "disagreed": disagreed,
        "disagreements": disagreements,
        "disagreements_truncated": disagreed > len(disagreements),
        "engine_allowed": allowed,
        "engine_format": log_format,
        "engine_more_permissive": permissive,
        "engine_more_restrictive": restrictive,
        "policy_id": current.policy_id,
        "report_version": DECISION_LOG_REPORT_VERSION,
        "skipped": normalized["skipped"],
        "testbench_passed": passed,
        "values_included": False,
    }
