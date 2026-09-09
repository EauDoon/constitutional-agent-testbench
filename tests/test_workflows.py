import copy
import unittest

from constitutional_agent_testbench.authoring import lint_policy


def policy(*rules):
    return {"schema_version": "1.0", "policy_id": "demo", "rules": list(rules)}


def rule(identifier="r", kind="false", path="action", **fields):
    return {"rule_id": identifier, "kind": kind, "path": path, **fields}


class AuthoringTests(unittest.TestCase):
    def test_strict_types_and_no_mutation(self):
        raw = policy(rule(), rule("n", "equals", value=0))
        before = copy.deepcopy(raw)
        self.assertTrue(lint_policy(raw)["has_conflicts"])
        self.assertEqual(raw, before)

    def test_ancestor_and_duplicates(self):
        raw = policy(rule(), rule("other"), rule("child", "required_field", "action.name"))
        codes = {item["code"] for item in lint_policy(raw)["findings"]}
        self.assertEqual(codes, {"DUPLICATE_CONSTRAINT", "INCOMPATIBLE_DESCENDANTS"})

    def test_valid_nested_domain_and_null_presence(self):
        raw = policy(rule("parent", "one_of", "action", values=[{}, {"name": None}]),
                     rule("child", "required_field", "action.name"))
        self.assertFalse(lint_policy(raw)["has_conflicts"])

    def test_three_way_empty_intersection(self):
        raw = policy(*(rule(str(i), "one_of", values=v) for i, v in
                       enumerate(([1, 2], [2, 3], [1, 3]))))
        self.assertTrue(lint_policy(raw)["has_conflicts"])
