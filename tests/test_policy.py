from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from constitutional_agent_testbench.common import JsonInputError, load_json
from constitutional_agent_testbench.policy import (
    Policy,
    PolicyValidationError,
    Rule,
    policy_to_dict,
    validate_policy,
)


def valid_policy() -> dict:
    return {
        "schema_version": "1.0",
        "policy_id": "test-policy",
        "rules": [
            {
                "rule_id": "summary-present",
                "kind": "required_field",
                "path": "summary",
            },
            {
                "rule_id": "mode-equals",
                "kind": "equals",
                "path": "settings.mode",
                "value": "synthetic",
            },
            {
                "rule_id": "level-allowed",
                "kind": "one_of",
                "path": "level",
                "values": ["low", "moderate"],
            },
            {"rule_id": "blocked-false", "kind": "false", "path": "blocked"},
            {
                "rule_id": "actions-empty",
                "kind": "empty_list",
                "path": "actions",
            },
        ],
    }


class PolicyValidationTests(unittest.TestCase):
    def test_accepts_and_round_trips_valid_policy(self) -> None:
        raw = valid_policy()
        policy = validate_policy(raw)
        self.assertEqual(policy.policy_id, "test-policy")
        self.assertEqual(policy_to_dict(policy), raw)

    def test_rejects_unknown_rule_kind(self) -> None:
        raw = valid_policy()
        raw["rules"][0]["kind"] = "undeclared"
        with self.assertRaises(PolicyValidationError):
            validate_policy(raw)

    def test_rejects_unknown_top_level_field(self) -> None:
        raw = valid_policy()
        raw["extra"] = True
        with self.assertRaises(PolicyValidationError):
            validate_policy(raw)

    def test_rejects_unknown_rule_field(self) -> None:
        raw = valid_policy()
        raw["rules"][0]["extra"] = True
        with self.assertRaises(PolicyValidationError):
            validate_policy(raw)

    def test_rejects_duplicate_rule_identifiers(self) -> None:
        raw = valid_policy()
        raw["rules"][1]["rule_id"] = raw["rules"][0]["rule_id"]
        with self.assertRaises(PolicyValidationError):
            validate_policy(raw)

    def test_rejects_empty_and_duplicate_one_of_values(self) -> None:
        raw = valid_policy()
        raw["rules"][2]["values"] = []
        with self.assertRaises(PolicyValidationError):
            validate_policy(raw)

        raw = valid_policy()
        raw["rules"][2]["values"] = [False, False]
        with self.assertRaises(PolicyValidationError):
            validate_policy(raw)

    def test_rejects_malformed_path(self) -> None:
        raw = valid_policy()
        raw["rules"][0]["path"] = "summary..text"
        with self.assertRaises(PolicyValidationError):
            validate_policy(raw)

    def test_rejects_duplicate_json_object_members(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"value": 1, "value": 2}', encoding="utf-8")
            with self.assertRaises(JsonInputError):
                load_json(path)

    def test_revalidates_manually_constructed_policy(self) -> None:
        raw_policy = Policy(
            policy_id="manual-policy",
            rules=(Rule(rule_id="invalid-rule", kind="undeclared", path="value"),),
        )
        with self.assertRaises(PolicyValidationError):
            validate_policy(raw_policy)

    def test_nested_values_do_not_alias_input_or_export(self) -> None:
        raw_policy = {
            "schema_version": "1.0",
            "policy_id": "alias-policy",
            "rules": [
                {
                    "rule_id": "object-equals",
                    "kind": "equals",
                    "path": "object",
                    "value": {"items": ["original"]},
                },
                {
                    "rule_id": "object-allowed",
                    "kind": "one_of",
                    "path": "allowed",
                    "values": [{"mode": "safe"}],
                },
            ],
        }
        policy = validate_policy(raw_policy)

        raw_policy["rules"][0]["value"]["items"].append("input-change")
        raw_policy["rules"][1]["values"][0]["mode"] = "input-change"
        first_export = policy_to_dict(policy)
        self.assertEqual(first_export["rules"][0]["value"], {"items": ["original"]})
        self.assertEqual(first_export["rules"][1]["values"], [{"mode": "safe"}])

        first_export["rules"][0]["value"]["items"].append("export-change")
        first_export["rules"][1]["values"][0]["mode"] = "export-change"
        second_export = policy_to_dict(policy)
        self.assertEqual(second_export["rules"][0]["value"], {"items": ["original"]})
        self.assertEqual(second_export["rules"][1]["values"], [{"mode": "safe"}])


if __name__ == "__main__":
    unittest.main()
