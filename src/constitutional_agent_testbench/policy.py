"""Strict version 1.0 policy parsing and validation."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .common import (
    MAX_JSON_INPUT_BYTES,
    MAX_JSON_NESTING,
    TestbenchError,
    bounded_canonical_json_size,
    canonical_json,
    ensure_json_value,
)


SCHEMA_VERSION = "1.0"
MAX_POLICY_RULES = 256
MAX_ONE_OF_VALUES = 256
SUPPORTED_RULE_KINDS = frozenset(
    {"required_field", "equals", "one_of", "false", "empty_list"}
)

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PATH_PATTERN = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*$"
)


class PolicyValidationError(TestbenchError):
    """Raised when a policy does not match the public schema."""

    code = "INVALID_POLICY"

    def __init__(
        self,
        message: str,
        *,
        policy_id: str | None = None,
        rule_id: str | None = None,
        rule_index: int | None = None,
    ) -> None:
        super().__init__(message)
        self.policy_id = policy_id
        self.rule_id = rule_id
        self.rule_index = rule_index

    def public_error(self) -> dict[str, Any]:
        error = super().public_error()
        if self.policy_id is not None:
            error["policy_id"] = self.policy_id
        if self.rule_id is not None:
            error["rule_id"] = self.rule_id
        if self.rule_index is not None:
            error["rule_index"] = self.rule_index
        return error


@dataclass(frozen=True, slots=True)
class Rule:
    """A validated policy rule."""

    rule_id: str
    kind: str
    path: str
    value: Any = None
    values: tuple[Any, ...] = ()


@dataclass(frozen=True, slots=True)
class Policy:
    """A validated version 1.0 policy."""

    policy_id: str
    rules: tuple[Rule, ...]
    schema_version: str = SCHEMA_VERSION


def _safe_identifier(value: Any) -> str | None:
    if isinstance(value, str) and _IDENTIFIER_PATTERN.fullmatch(value):
        return value
    return None


def _rule_label(index: int, rule_id: str | None) -> str:
    if rule_id is None:
        return f"Rule at index {index}"
    return f"Rule {rule_id!r} at index {index}"


def _invalid(
    message: str,
    cause: Exception | None = None,
    *,
    policy_id: str | None = None,
    rule_id: str | None = None,
    rule_index: int | None = None,
) -> PolicyValidationError:
    error = PolicyValidationError(
        message,
        policy_id=policy_id,
        rule_id=rule_id,
        rule_index=rule_index,
    )
    if cause is not None:
        error.__cause__ = cause
    return error


def _check_exact_keys(
    value: dict[str, Any],
    expected: set[str],
    *,
    label: str,
    policy_id: str | None = None,
    rule_id: str | None = None,
    rule_index: int | None = None,
) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if not missing and not unknown:
        return
    details: list[str] = []
    if missing:
        details.append("missing " + ", ".join(missing))
    if unknown:
        details.append("unknown " + ", ".join(unknown))
    raise _invalid(
        f"{label} has invalid fields: {'; '.join(details)}.",
        policy_id=policy_id,
        rule_id=rule_id,
        rule_index=rule_index,
    )


def _check_identifier(
    value: Any,
    *,
    label: str,
    policy_id: str | None = None,
    rule_id: str | None = None,
    rule_index: int | None = None,
) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value):
        raise _invalid(
            f"{label} is not a valid identifier.",
            policy_id=policy_id,
            rule_id=rule_id,
            rule_index=rule_index,
        )
    return value


def _check_path(
    value: Any,
    *,
    label: str,
    policy_id: str | None = None,
    rule_id: str | None = None,
    rule_index: int | None = None,
) -> str:
    if not isinstance(value, str) or not _PATH_PATTERN.fullmatch(value):
        raise _invalid(
            f"{label} is not a valid object field path.",
            policy_id=policy_id,
            rule_id=rule_id,
            rule_index=rule_index,
        )
    if len(value.split(".")) > MAX_JSON_NESTING:
        raise _invalid(
            f"{label} exceeds the {MAX_JSON_NESTING}-segment path limit.",
            policy_id=policy_id,
            rule_id=rule_id,
            rule_index=rule_index,
        )
    return value


def _check_json_value(
    value: Any,
    *,
    label: str,
    policy_id: str | None = None,
    rule_id: str | None = None,
    rule_index: int | None = None,
) -> None:
    try:
        ensure_json_value(value, label=label)
        canonical_json(value)
    except (OverflowError, RecursionError, TypeError, ValueError) as exc:
        raise _invalid(
            str(exc),
            exc,
            policy_id=policy_id,
            rule_id=rule_id,
            rule_index=rule_index,
        )


def validate_policy(raw_policy: Any) -> Policy:
    """Validate and normalize a policy, rejecting every undeclared field."""

    if isinstance(raw_policy, Policy):
        try:
            for index, rule in enumerate(raw_policy.rules):
                has_irrelevant_value = rule.kind != "equals" and rule.value is not None
                has_irrelevant_values = rule.kind != "one_of" and rule.values != ()
                if has_irrelevant_value or has_irrelevant_values:
                    rule_id = _safe_identifier(rule.rule_id)
                    raise _invalid(
                        f"{_rule_label(index, rule_id)} contains fields "
                        "not supported by its rule kind.",
                        policy_id=_safe_identifier(raw_policy.policy_id),
                        rule_id=rule_id,
                        rule_index=index,
                    )
            raw_policy = policy_to_dict(raw_policy)
        except (AttributeError, RecursionError, TypeError, ValueError) as exc:
            raise _invalid("Policy object is invalid.", exc)

    if not isinstance(raw_policy, dict):
        raise _invalid("Policy must be a JSON object.")

    try:
        ensure_json_value(raw_policy, label="Policy")
        bounded_canonical_json_size(
            raw_policy,
            label="Policy",
            limit=MAX_JSON_INPUT_BYTES,
        )
    except (RecursionError, TypeError, ValueError) as exc:
        raise _invalid(str(exc), exc)

    _check_exact_keys(
        raw_policy,
        {"schema_version", "policy_id", "rules"},
        label="Policy",
    )

    if raw_policy["schema_version"] != SCHEMA_VERSION:
        raise _invalid("Policy schema_version must be 1.0.")

    policy_id = _check_identifier(raw_policy["policy_id"], label="policy_id")
    raw_rules = raw_policy["rules"]
    if not isinstance(raw_rules, list) or not raw_rules:
        raise _invalid(
            f"Policy {policy_id!r} rules must be a non-empty JSON array.",
            policy_id=policy_id,
        )
    if len(raw_rules) > MAX_POLICY_RULES:
        raise _invalid(
            f"Policy {policy_id!r} rules must not contain more than "
            f"{MAX_POLICY_RULES} items.",
            policy_id=policy_id,
        )

    rules: list[Rule] = []
    seen_rule_ids: set[str] = set()
    for index, raw_rule in enumerate(raw_rules):
        rule_id_hint = _safe_identifier(
            raw_rule.get("rule_id") if isinstance(raw_rule, dict) else None
        )
        label = _rule_label(index, rule_id_hint)
        location = {
            "policy_id": policy_id,
            "rule_id": rule_id_hint,
            "rule_index": index,
        }
        if not isinstance(raw_rule, dict):
            raise _invalid(f"{label} must be a JSON object.", **location)

        kind = raw_rule.get("kind")
        if not isinstance(kind, str) or kind not in SUPPORTED_RULE_KINDS:
            raise _invalid(f"{label} has an unknown rule kind.", **location)

        expected_keys = {"rule_id", "kind", "path"}
        if kind == "equals":
            expected_keys.add("value")
        elif kind == "one_of":
            expected_keys.add("values")
        _check_exact_keys(raw_rule, expected_keys, label=label, **location)

        rule_id = _check_identifier(
            raw_rule["rule_id"],
            label=f"{label} rule_id",
            **location,
        )
        if rule_id in seen_rule_ids:
            raise _invalid(f"{label} repeats a rule_id.", **location)
        seen_rule_ids.add(rule_id)
        path = _check_path(
            raw_rule["path"],
            label=f"{label} path",
            **location,
        )

        if kind == "equals":
            _check_json_value(
                raw_rule["value"],
                label=f"{label} value",
                **location,
            )
            rule_value = deepcopy(raw_rule["value"])
            rules.append(Rule(rule_id=rule_id, kind=kind, path=path, value=rule_value))
            continue

        if kind == "one_of":
            raw_values = raw_rule["values"]
            if not isinstance(raw_values, list) or not raw_values:
                raise _invalid(
                    f"{label} values must be a non-empty JSON array.",
                    **location,
                )
            if len(raw_values) > MAX_ONE_OF_VALUES:
                raise _invalid(
                    f"{label} values must not contain more than "
                    f"{MAX_ONE_OF_VALUES} items.",
                    **location,
                )
            canonical_values: set[str] = set()
            for value in raw_values:
                _check_json_value(value, label=f"{label} values", **location)
                marker = canonical_json(value)
                if marker in canonical_values:
                    raise _invalid(
                        f"{label} values must not contain duplicates.",
                        **location,
                    )
                canonical_values.add(marker)
            rules.append(
                Rule(
                    rule_id=rule_id,
                    kind=kind,
                    path=path,
                    values=tuple(deepcopy(raw_values)),
                )
            )
            continue

        rules.append(Rule(rule_id=rule_id, kind=kind, path=path))

    return Policy(policy_id=policy_id, rules=tuple(rules))


def policy_to_dict(policy: Policy) -> dict[str, Any]:
    """Convert a validated policy to its public JSON representation."""

    raw_rules: list[dict[str, Any]] = []
    for rule in policy.rules:
        raw_rule: dict[str, Any] = {
            "kind": rule.kind,
            "path": rule.path,
            "rule_id": rule.rule_id,
        }
        if rule.kind == "equals":
            raw_rule["value"] = deepcopy(rule.value)
        elif rule.kind == "one_of":
            raw_rule["values"] = deepcopy(list(rule.values))
        raw_rules.append(raw_rule)
    return {
        "policy_id": policy.policy_id,
        "rules": raw_rules,
        "schema_version": policy.schema_version,
    }
