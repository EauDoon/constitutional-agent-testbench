"""Conservative diagnostics for declared rules, without rewriting authority."""

from __future__ import annotations

from typing import Any

from .common import canonical_json, get_field
from .evaluator import _evaluate_rule
from .policy import Policy, Rule, validate_policy


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
    findings = []
    groups: dict[str, list[Rule]] = {}
    for rule in current.rules:
        groups.setdefault(rule.path, []).append(rule)
    for path, rules in sorted(groups.items()):
        domains = [_domain(rule) for rule in rules]
        finite = [domain for domain in domains if domain is not None]
        if finite:
            allowed = set(map(canonical_json, finite[0]))
            for domain in finite[1:]:
                allowed.intersection_update(map(canonical_json, domain))
            if not allowed:
                findings.append({"code": "DISJOINT_CONSTRAINTS", "path": path,
                                 "rule_ids": sorted(rule.rule_id for rule in rules)})
        seen: dict[str, str] = {}
        for rule in rules:
            marker = canonical_json([rule.kind, _domain(rule)])
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
            if descendants and not any(
                isinstance(value, dict) and all(
                    _evaluate_rule(Rule(child.rule_id, child.kind,
                                        child.path[len(path) + 1:], child.value,
                                        child.values), value)["passed"]
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
