"""Conservative diagnostics for declared rules, without rewriting authority."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .common import TestbenchError, canonical_json
from .evaluator import _evaluate_rule
from .policy import Policy, Rule, validate_policy

MAX_AUTHORING_WORK_BYTES = 32_000_000
#: Schema 1.1 kinds with no finite domain; they narrow a finite domain instead.
_FILTER_KINDS = frozenset({"type", "range", "length"})


class AuthoringLimitError(TestbenchError):
    code = "AUTHORING_LIMIT_EXCEEDED"


def _constraint_marker(rule: Rule) -> str:
    """Identity of a constraint. ``one_of`` is a set, so value order is ignored."""

    if rule.kind == "type":
        return canonical_json([rule.kind, sorted(rule.types)])
    if rule.kind in ("range", "length"):
        return canonical_json([rule.kind, rule.minimum, rule.maximum])
    domain = _domain(rule)
    if rule.kind == "one_of" and domain is not None:
        domain = sorted(canonical_json(value) for value in domain)
    return canonical_json([rule.kind, domain])


def _domain(rule: Rule) -> list[Any] | None:
    if rule.kind == "equals":
        return [rule.value]
    if rule.kind == "one_of":
        return list(rule.values)
    if rule.kind == "false":
        return [False]
    if rule.kind == "empty_list":
        return [[]]
    return None


def lint_policy(policy: Policy | dict[str, Any]) -> dict[str, Any]:
    """Find exact-path contradictions and ancestor incompatibilities.

    Absence of a finding is not proof of satisfiability. This bounded analysis
    examines each finite domain once per related rule, not a Cartesian search.
    """
    current = validate_policy(policy)
    work_bytes = 0
    findings = []
    groups: dict[str, list[Rule]] = {}
    for rule in current.rules:
        groups.setdefault(rule.path, []).append(rule)
    for path, rules in sorted(groups.items()):
        domains = [_domain(rule) for rule in rules]
        finite = [(rule, domain) for rule, domain in zip(rules, domains, strict=True)
                  if domain is not None]
        if finite:
            allowed = set(map(canonical_json, finite[0][1]))
            for _rule, domain in finite[1:]:
                allowed.intersection_update(map(canonical_json, domain))
            filters = [rule for rule in rules if rule.kind in _FILTER_KINDS]
            if not allowed:
                # A required_field has no finite domain, so it cannot be one of
                # the constraints that failed to intersect.
                findings.append({"code": "DISJOINT_CONSTRAINTS", "path": path,
                                 "rule_ids": sorted(rule.rule_id for rule, _domain in finite)})
            elif filters:
                # Narrow the shared finite domain through the path's type, range
                # and length rules, charging every value checked to the budget.
                survivors = [value for value in finite[0][1] if canonical_json(value) in allowed]
                work_bytes += len(filters) * sum(
                    len(canonical_json(value).encode("utf-8")) for value in survivors)
                if work_bytes > MAX_AUTHORING_WORK_BYTES:
                    raise AuthoringLimitError(
                        "Authoring comparison work exceeds the 32,000,000-byte limit.")
                if not any(all(_evaluate_rule(replace(rule, path="value"), {"value": value})["passed"]
                               for rule in filters) for value in survivors):
                    findings.append({"code": "DISJOINT_CONSTRAINTS", "path": path,
                                     "rule_ids": sorted([rule.rule_id for rule, _domain in finite]
                                                        + [rule.rule_id for rule in filters])})
        seen: dict[str, str] = {}
        for rule in rules:
            marker = _constraint_marker(rule)
            if marker in seen:
                findings.append({"code": "DUPLICATE_CONSTRAINT", "path": path,
                                 "rule_ids": sorted([seen[marker], rule.rule_id])})
            else:
                seen[marker] = rule.rule_id
        for rule in rules:
            domain = _domain(rule)
            if domain is None:
                continue
            descendants = [child for child in current.rules
                           if child.path.startswith(path + ".")]
            # Charge both compared values and every allowed candidate before work.
            domain_bytes = sum(len(canonical_json(v).encode("utf-8")) for v in domain)
            child_bytes = sum(len(canonical_json(_domain(child)).encode("utf-8"))
                              for child in descendants)
            comparisons = sum(len(child.values) if child.kind == "one_of" else 1
                              for child in descendants)
            work_bytes += domain_bytes * comparisons + child_bytes * len(domain)
            if work_bytes > MAX_AUTHORING_WORK_BYTES:
                raise AuthoringLimitError("Authoring comparison work exceeds the 32,000,000-byte limit.")
            if descendants and not any(
                isinstance(value, dict) and all(
                    # replace() keeps every field, including 1.1 types and bounds.
                    _evaluate_rule(replace(child, path=child.path[len(path) + 1:]),
                                   value)["passed"]
                    for child in descendants)
                for value in domain
            ):
                findings.append({"code": "INCOMPATIBLE_DESCENDANTS", "path": path,
                                 "rule_ids": sorted([rule.rule_id] +
                                                    [r.rule_id for r in descendants])})
    findings.sort(key=lambda item: (item["path"], item["code"], item["rule_ids"]))
    return {"policy_id": current.policy_id, "findings": findings,
            "has_conflicts": any(f["code"] != "DUPLICATE_CONSTRAINT" for f in findings),
            "coverage": "finite domains at identical and ancestor paths; not a satisfiability proof"}
