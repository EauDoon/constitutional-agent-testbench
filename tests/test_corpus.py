"""Corpus authoring contracts, including privacy and compatibility."""
import copy
import unittest

from constitutional_agent_testbench.inspection import inspect_policy
from constitutional_agent_testbench.inspection import inspect_suite


def policy():
    return {"schema_version": "1.0", "policy_id": "corpus", "rules": [
        {"rule_id": "r", "kind": "false", "path": "action"}]}


def suite():
    return {"suite_version": "1.0", "cases": [
        {"case_id": "pass", "response": {"action": False}, "expected_passed": True},
        {"case_id": "missing", "response": {}, "expected_passed": False},
        {"case_id": "wrong", "response": {"action": True}, "expected_passed": False}]}


class InspectionTests(unittest.TestCase):
    def test_duplicate_responses_and_conflicting_expectations(self):
        raw = suite()
        duplicate = copy.deepcopy(raw["cases"][0])
        duplicate.update(case_id="contradiction", expected_passed=False)
        raw["cases"].append(duplicate)
        result = inspect_suite(raw)
        self.assertFalse(result["consistent_expectations"])
        self.assertEqual(result["duplicate_responses"][0]["case_ids"], ["pass", "contradiction"])
        self.assertNotIn("response", result["duplicate_responses"][0])
        duplicate["response"]["action"] = 0
        self.assertTrue(inspect_suite(raw)["consistent_expectations"])

    def test_policy_inventory_does_not_copy_values(self):
        raw = policy()
        raw["rules"].append({"rule_id": "child", "kind": "equals", "path": "action.name", "value": "SYNTHETIC_PRIVATE"})
        before = copy.deepcopy(raw)
        result = inspect_policy(raw)
        self.assertEqual(result["paths"][1]["ancestor_paths"], ["action"])
        self.assertEqual(result["rule_count"], 2)
        self.assertNotIn("SYNTHETIC_PRIVATE", str(result))
        self.assertEqual(raw, before)
