from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from constitutional_agent_testbench.common import (
    MAX_JSON_INPUT_BYTES,
    MAX_JSON_NESTING,
    MAX_JSON_NODES,
    JsonInputError,
    ensure_json_value,
    load_json,
)
from constitutional_agent_testbench.evaluator import (
    EvaluationInputError,
    evaluate_response,
)
from constitutional_agent_testbench.policy import (
    MAX_ONE_OF_VALUES,
    MAX_POLICY_RULES,
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

    def test_rejects_input_larger_than_the_file_size_limit(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "large.json"
            path.write_bytes(b" " * (MAX_JSON_INPUT_BYTES + 1))
            with self.assertRaises(JsonInputError):
                load_json(path)

    def test_rejects_response_beyond_the_nesting_limit(self) -> None:
        response: dict = {}
        current = response
        for _ in range(MAX_JSON_NESTING):
            child: dict = {}
            current["nested"] = child
            current = child

        with self.assertRaises(EvaluationInputError):
            evaluate_response(valid_policy(), response)

    def test_accepts_the_node_limit_and_rejects_one_more(self) -> None:
        ensure_json_value(
            [None] * (MAX_JSON_NODES - 1),
            label="Boundary value",
        )
        with self.assertRaises(ValueError):
            ensure_json_value(
                [None] * MAX_JSON_NODES,
                label="Boundary value",
            )

    def test_accepts_the_rule_limit_and_rejects_one_more(self) -> None:
        raw = {
            "schema_version": "1.0",
            "policy_id": "bounded-policy",
            "rules": [
                {
                    "rule_id": f"rule-{index}",
                    "kind": "required_field",
                    "path": f"value{index}",
                }
                for index in range(MAX_POLICY_RULES)
            ],
        }
        self.assertEqual(len(validate_policy(raw).rules), MAX_POLICY_RULES)

        raw["rules"].append(
            {
                "rule_id": "one-too-many",
                "kind": "required_field",
                "path": "overflow",
            }
        )
        with self.assertRaises(PolicyValidationError):
            validate_policy(raw)

    def test_rejects_an_aggregate_policy_beyond_the_node_limit(self) -> None:
        raw = {
            "schema_version": "1.0",
            "policy_id": "aggregate-limit-policy",
            "rules": [
                {
                    "rule_id": f"rule-{index}",
                    "kind": "equals",
                    "path": f"value{index}",
                    "value": [0] * 1_000,
                }
                for index in range(100)
            ],
        }
        with self.assertRaises(PolicyValidationError):
            validate_policy(raw)

    def test_deep_equals_value_preserves_the_policy_error_contract(self) -> None:
        value: dict = {}
        current = value
        for _ in range(MAX_JSON_NESTING):
            child: dict = {}
            current["nested"] = child
            current = child
        raw = {
            "schema_version": "1.0",
            "policy_id": "deep-value-policy",
            "rules": [
                {
                    "rule_id": "deep-value",
                    "kind": "equals",
                    "path": "value",
                    "value": value,
                }
            ],
        }
        with self.assertRaises(PolicyValidationError):
            validate_policy(raw)

    def test_accepts_the_one_of_limit_and_rejects_one_more(self) -> None:
        raw = valid_policy()
        raw["rules"][2]["values"] = list(range(MAX_ONE_OF_VALUES))
        validate_policy(raw)

        raw["rules"][2]["values"].append(MAX_ONE_OF_VALUES)
        with self.assertRaises(PolicyValidationError):
            validate_policy(raw)

    def test_rejects_a_path_beyond_the_nesting_limit(self) -> None:
        raw = valid_policy()
        raw["rules"][0]["path"] = ".".join(
            f"field{index}" for index in range(MAX_JSON_NESTING + 1)
        )
        with self.assertRaises(PolicyValidationError):
            validate_policy(raw)

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
