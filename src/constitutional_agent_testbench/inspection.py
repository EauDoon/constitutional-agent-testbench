"""Value-free inspection for policy and fixture authors."""

from collections import Counter

from .policy import validate_policy
from .workflow import WorkflowInputError, bounded_artifact


def inspect_policy(policy):
    """Inventory declared paths and relationships without copying constraint values."""
    current = validate_policy(policy)
    if len(current.rules) > 256:
        raise WorkflowInputError("Policy inspection supports at most 256 rules.")
    paths = sorted({rule.path for rule in current.rules})
    return bounded_artifact({"policy_id": current.policy_id, "schema_version": current.schema_version,
            "rule_count": len(current.rules), "path_count": len(paths),
            "kind_counts": dict(sorted(Counter(rule.kind for rule in current.rules).items())),
            "paths": [{"path": path,
                       "rule_ids": [r.rule_id for r in current.rules if r.path == path],
                       "ancestor_paths": [p for p in paths if path.startswith(p + ".")]}
                      for path in paths]})
