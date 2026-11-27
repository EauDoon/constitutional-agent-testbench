"""Strict version 1.0, 1.1 and 1.2 policy parsing and validation."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from .common import (
    MAX_JSON_INPUT_BYTES,
    MAX_JSON_NESTING,
    TestbenchError,
    bounded_canonical_json_size,
    canonical_json,
    copy_json_tree,
    ensure_json_value,
)

SCHEMA_VERSION = "1.0"
SUPPORTED_SCHEMA_VERSIONS = ("1.0", "1.1", "1.2")
MAX_POLICY_RULES = 256
MAX_ONE_OF_VALUES = 256
#: The largest length bound. No valid response can hold a longer string, array
#: or object, because every input is capped at 1,000,000 UTF-8 bytes.
MAX_LENGTH_BOUND = MAX_JSON_INPUT_BYTES
#: The JSON type names a ``type`` rule may list. ``integer`` is a JSON integer
#: literal; ``number`` is any number literal, so it already admits integers.
JSON_TYPE_NAMES = ("array", "boolean", "integer", "null", "number", "object", "string")
SCHEMA_1_0_RULE_KINDS = frozenset(
    {"required_field", "equals", "one_of", "false", "empty_list"}
)
SCHEMA_1_1_RULE_KINDS = SCHEMA_1_0_RULE_KINDS | {"type", "range", "length"}
#: Schema 1.2 adds a cross-field comparison and a per-item array check. Every
#: 1.2 rule may also carry a ``when`` guard.
SCHEMA_1_2_RULE_KINDS = SCHEMA_1_1_RULE_KINDS | {"compare", "each"}
RULE_KINDS_BY_SCHEMA_VERSION = {
    "1.0": SCHEMA_1_0_RULE_KINDS,
    "1.1": SCHEMA_1_1_RULE_KINDS,
    "1.2": SCHEMA_1_2_RULE_KINDS,
}
#: Every rule kind this package can evaluate, across supported schema versions.
SUPPORTED_RULE_KINDS = SCHEMA_1_2_RULE_KINDS
#: Kinds an ``each`` rule may apply to every array item.
ITEM_RULE_KINDS = SCHEMA_1_1_RULE_KINDS
COMPARE_OPERATORS = ("eq", "ne", "lt", "lte", "gt", "gte")
MAX_WHEN_CONDITIONS = 8
_BOUND_FIELDS = ("minimum", "maximum")
_ALL_VALUE_TYPES = frozenset({"array", "boolean", "null", "number", "object", "string"})

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
    #: JSON type names for a schema 1.1 ``type`` rule, in declared order.
    types: tuple[str, ...] = ()
    #: Inclusive bounds for a schema 1.1 ``range`` or ``length`` rule.
    minimum: int | float | None = None
    maximum: int | float | None = None
    #: Schema 1.2 guard: every condition must hold for the rule to apply.
    when: tuple[Condition, ...] = ()
    #: Schema 1.2 ``compare``: the operator and the path compared against.
    op: str | None = None
    other_path: str | None = None
    #: Schema 1.2 ``each``: the constraint every array item must meet. Its
    #: ``path`` is ``value`` or ``value.<item_path>``, evaluated on ``{"value": item}``.
    item: Rule | None = None
    item_path: str | None = None


@dataclass(frozen=True, slots=True)
class Condition:
    """One ``when`` condition: the value at ``path`` equals one of ``values``."""

    path: str
    values: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class Policy:
    """A validated version 1.0, 1.1 or 1.2 policy."""

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


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_types(raw_types: Any, *, label: str, **location: Any) -> tuple[str, ...]:
    if (not isinstance(raw_types, list) or not raw_types
            or any(not isinstance(name, str) for name in raw_types)):
        raise _invalid(f"{label} types must be a non-empty JSON array of type names.",
                       **location)
    if any(name not in JSON_TYPE_NAMES for name in raw_types):
        raise _invalid(f"{label} types must name only {', '.join(JSON_TYPE_NAMES)}.",
                       **location)
    if len(set(raw_types)) != len(raw_types):
        raise _invalid(f"{label} types must not contain duplicates.", **location)
    if "integer" in raw_types and "number" in raw_types:
        raise _invalid(f"{label} types must not list integer beside number, "
                       "which already admits every integer.", **location)
    if _ALL_VALUE_TYPES <= set(raw_types):
        raise _invalid(f"{label} types admit every JSON value; use required_field "
                       "to require only presence.", **location)
    return tuple(raw_types)


def _check_bounds(raw_rule: dict[str, Any], kind: str, *, label: str,
                  **location: Any) -> tuple[int | float | None, int | float | None]:
    bounds: dict[str, int | float | None] = {}
    for field in _BOUND_FIELDS:
        if field not in raw_rule:
            bounds[field] = None
            continue
        bound = raw_rule[field]
        if kind == "range":
            if not _is_number(bound) or (isinstance(bound, float) and not math.isfinite(bound)):
                raise _invalid(f"{label} {field} must be a finite JSON number.", **location)
        elif type(bound) is not int or not 0 <= bound <= MAX_LENGTH_BOUND:
            raise _invalid(f"{label} {field} must be an integer from 0 to "
                           f"{MAX_LENGTH_BOUND:,}.", **location)
        bounds[field] = bound
    minimum, maximum = bounds["minimum"], bounds["maximum"]
    if minimum is None and maximum is None:
        raise _invalid(f"{label} must declare minimum, maximum or both.", **location)
    if minimum is not None and maximum is not None and minimum > maximum:
        raise _invalid(f"{label} minimum must not exceed maximum.", **location)
    return minimum, maximum


def _constraint_keys(raw_rule: dict[str, Any], kind: str) -> set[str]:
    """Kind-specific fields a rule or ``each`` item must carry."""

    if kind == "equals":
        return {"value"}
    if kind == "one_of":
        return {"values"}
    if kind == "type":
        return {"types"}
    if kind in ("range", "length"):
        # At least one bound is required; that is checked after the field set.
        return set(_BOUND_FIELDS) & set(raw_rule)
    if kind == "compare":
        return {"op", "other_path"}
    if kind == "each":
        return {"item"}
    return set()


def _check_values(raw_values: Any, *, label: str, **location: Any) -> tuple[Any, ...]:
    if not isinstance(raw_values, list) or not raw_values:
        raise _invalid(f"{label} values must be a non-empty JSON array.", **location)
    if len(raw_values) > MAX_ONE_OF_VALUES:
        raise _invalid(
            f"{label} values must not contain more than {MAX_ONE_OF_VALUES} items.",
            **location,
        )
    canonical_values: set[str] = set()
    for value in raw_values:
        _check_json_value(value, label=f"{label} values", **location)
        marker = canonical_json(value)
        if marker in canonical_values:
            raise _invalid(f"{label} values must not contain duplicates.", **location)
        canonical_values.add(marker)
    return tuple(copy_json_tree(value) for value in raw_values)


def _parse_constraint(raw_rule: dict[str, Any], kind: str, *, label: str,
                      **location: Any) -> dict[str, Any]:
    """Validate the kind-specific fields and return them as ``Rule`` keywords."""

    if kind == "equals":
        _check_json_value(raw_rule["value"], label=f"{label} value", **location)
        return {"value": copy_json_tree(raw_rule["value"])}
    if kind == "one_of":
        return {"values": _check_values(raw_rule["values"], label=label, **location)}
    if kind == "type":
        return {"types": _check_types(raw_rule["types"], label=label, **location)}
    if kind in ("range", "length"):
        minimum, maximum = _check_bounds(raw_rule, kind, label=label, **location)
        return {"minimum": minimum, "maximum": maximum}
    if kind == "compare":
        if raw_rule["op"] not in COMPARE_OPERATORS:
            raise _invalid(f"{label} op must be one of {', '.join(COMPARE_OPERATORS)}.",
                           **location)
        return {"op": raw_rule["op"],
                "other_path": _check_path(raw_rule["other_path"],
                                          label=f"{label} other_path", **location)}
    return {}


def _parse_when(raw_when: Any, *, label: str, **location: Any) -> tuple[Condition, ...]:
    if (not isinstance(raw_when, list) or not raw_when
            or len(raw_when) > MAX_WHEN_CONDITIONS):
        raise _invalid(f"{label} when must be a JSON array of 1 to "
                       f"{MAX_WHEN_CONDITIONS} conditions.", **location)
    conditions: list[Condition] = []
    for raw_condition in raw_when:
        condition_label = f"{label} when condition"
        if not isinstance(raw_condition, dict):
            raise _invalid(f"{condition_label} must be a JSON object.", **location)
        _check_exact_keys(raw_condition, {"path", "values"}, label=condition_label, **location)
        conditions.append(Condition(
            path=_check_path(raw_condition["path"], label=f"{condition_label} path", **location),
            values=_check_values(raw_condition["values"], label=condition_label, **location)))
    return tuple(conditions)


def _constraint_to_dict(rule: Rule, raw_rule: dict[str, Any]) -> None:
    if rule.kind == "equals":
        raw_rule["value"] = copy_json_tree(rule.value)
    elif rule.kind == "one_of":
        raw_rule["values"] = [copy_json_tree(value) for value in rule.values]
    elif rule.kind == "type":
        raw_rule["types"] = list(rule.types)
    elif rule.kind in ("range", "length"):
        # Only declared bounds are emitted, so a missing bound stays absent.
        for field in _BOUND_FIELDS:
            bound = getattr(rule, field)
            if bound is not None:
                raw_rule[field] = bound
    elif rule.kind == "compare":
        raw_rule["op"] = rule.op
        raw_rule["other_path"] = rule.other_path


def validate_policy(raw_policy: Any) -> Policy:
    """Validate and normalize a policy, rejecting every undeclared field."""

    if isinstance(raw_policy, Policy):
        try:
            for index, rule in enumerate(raw_policy.rules):
                has_irrelevant_value = rule.kind != "equals" and rule.value is not None
                has_irrelevant_values = rule.kind != "one_of" and rule.values != ()
                has_irrelevant_types = rule.kind != "type" and rule.types != ()
                has_irrelevant_bounds = rule.kind not in ("range", "length") and (
                    rule.minimum is not None or rule.maximum is not None
                )
                has_irrelevant_compare = rule.kind != "compare" and (
                    rule.op is not None or rule.other_path is not None)
                has_irrelevant_item = rule.kind != "each" and (
                    rule.item is not None or rule.item_path is not None)
                if (has_irrelevant_value or has_irrelevant_values
                        or has_irrelevant_types or has_irrelevant_bounds
                        or has_irrelevant_compare or has_irrelevant_item):
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

    schema_version = raw_policy["schema_version"]
    if not isinstance(schema_version, str) or schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise _invalid("Policy schema_version must be 1.0, 1.1 or 1.2.")
    allowed_kinds = RULE_KINDS_BY_SCHEMA_VERSION[schema_version]

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
        if not isinstance(kind, str) or kind not in allowed_kinds:
            raise _invalid(f"{label} has an unknown rule kind.", **location)

        expected_keys = {"rule_id", "kind", "path"} | _constraint_keys(raw_rule, kind)
        if schema_version == "1.2" and "when" in raw_rule:
            expected_keys.add("when")
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
        fields = _parse_constraint(raw_rule, kind, label=label, **location)
        if kind == "compare":
            if fields["other_path"] == path:
                raise _invalid(f"{label} other_path must differ from path.", **location)
        if kind == "each":
            raw_item = raw_rule["item"]
            item_label = f"{label} item"
            if not isinstance(raw_item, dict):
                raise _invalid(f"{item_label} must be a JSON object.", **location)
            item_kind = raw_item.get("kind")
            if not isinstance(item_kind, str) or item_kind not in ITEM_RULE_KINDS:
                raise _invalid(f"{item_label} kind must be one of "
                               f"{', '.join(sorted(ITEM_RULE_KINDS))}.", **location)
            item_keys = {"kind"} | _constraint_keys(raw_item, item_kind)
            if "path" in raw_item:
                item_keys.add("path")
            _check_exact_keys(raw_item, item_keys, label=item_label, **location)
            item_path = (_check_path(raw_item["path"], label=f"{item_label} path", **location)
                         if "path" in raw_item else None)
            if item_path is not None and len(item_path.split(".")) >= MAX_JSON_NESTING:
                raise _invalid(f"{item_label} path exceeds the path limit.", **location)
            item_fields = _parse_constraint(raw_item, item_kind, label=item_label, **location)
            fields["item"] = Rule(rule_id=rule_id, kind=item_kind,
                                  path="value" if item_path is None else f"value.{item_path}",
                                  **item_fields)
            fields["item_path"] = item_path
        if "when" in raw_rule:
            fields["when"] = _parse_when(raw_rule["when"], label=label, **location)
        rules.append(Rule(rule_id=rule_id, kind=kind, path=path, **fields))

    return Policy(policy_id=policy_id, rules=tuple(rules), schema_version=schema_version)


def policy_to_dict(policy: Policy) -> dict[str, Any]:
    """Convert a validated policy to its public JSON representation."""

    raw_rules: list[dict[str, Any]] = []
    for rule in policy.rules:
        raw_rule: dict[str, Any] = {
            "kind": rule.kind,
            "path": rule.path,
            "rule_id": rule.rule_id,
        }
        _constraint_to_dict(rule, raw_rule)
        if rule.kind == "each" and rule.item is not None:
            raw_item: dict[str, Any] = {"kind": rule.item.kind}
            if rule.item_path is not None:
                raw_item["path"] = rule.item_path
            _constraint_to_dict(rule.item, raw_item)
            raw_rule["item"] = raw_item
        if rule.when:
            raw_rule["when"] = [{"path": condition.path,
                                 "values": [copy_json_tree(value) for value in condition.values]}
                                for condition in rule.when]
        raw_rules.append(raw_rule)
    return {
        "policy_id": policy.policy_id,
        "rules": raw_rules,
        "schema_version": policy.schema_version,
    }
