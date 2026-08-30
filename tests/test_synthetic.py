from __future__ import annotations

import unittest
from unittest.mock import patch

import constitutional_agent_testbench.synthetic as synthetic
from constitutional_agent_testbench.evaluator import evaluate_response
from constitutional_agent_testbench.policy import (
    MAX_ONE_OF_VALUES,
    MAX_POLICY_RULES,
)
from constitutional_agent_testbench.synthetic import (
    SyntheticGenerationError,
    generate_synthetic_cases,
)


class SyntheticGenerationTests(unittest.TestCase):
    def test_selects_nested_compatible_ancestor_one_of_value(self) -> None:
        policy = {
            "schema_version": "1.0",
            "policy_id": "nested-choice-policy",
            "rules": [
                {
                    "rule_id": "config-choice",
                    "kind": "one_of",
                    "path": "config",
                    "values": [
                        0,
                        {"label": "approved", "mode": "safe"},
                    ],
                },
                {
                    "rule_id": "mode-safe",
                    "kind": "equals",
                    "path": "config.mode",
                    "value": "safe",
                },
            ],
        }
        expected_response = {
            "config": {"label": "approved", "mode": "safe"}
        }

        self.assertTrue(evaluate_response(policy, expected_response)["passed"])

        generated = generate_synthetic_cases(policy)

        self.assertEqual(generated["passing_case"]["response"], expected_response)
        self.assertTrue(generated["passing_case"]["evaluation"]["passed"])

    def test_rejects_nested_ancestor_choices_that_cannot_preserve_descendants(
        self,
    ) -> None:
        policy = {
            "schema_version": "1.0",
            "policy_id": "nested-conflict-policy",
            "rules": [
                {
                    "rule_id": "config-choice",
                    "kind": "one_of",
                    "path": "config",
                    "values": [0, {"mode": "unsafe"}],
                },
                {
                    "rule_id": "mode-safe",
                    "kind": "equals",
                    "path": "config.mode",
                    "value": "safe",
                },
            ],
        }

        with self.assertRaises(SyntheticGenerationError):
            generate_synthetic_cases(policy)

    def test_checks_256_candidates_without_repeated_full_evaluation(self) -> None:
        compatible = {"label": "approved", "mode": "safe"}
        policy = {
            "schema_version": "1.0",
            "policy_id": "bounded-nested-choice-policy",
            "rules": [
                {
                    "rule_id": "config-choice",
                    "kind": "one_of",
                    "path": "config",
                    "values": [*range(255), compatible],
                },
                {
                    "rule_id": "mode-safe",
                    "kind": "equals",
                    "path": "config.mode",
                    "value": "safe",
                },
            ],
        }

        with (
            patch.object(
                synthetic,
                "evaluate_response",
                wraps=synthetic.evaluate_response,
            ) as full_evaluation,
            patch.object(
                synthetic,
                "deepcopy",
                wraps=synthetic.deepcopy,
            ) as response_copy,
        ):
            generated = generate_synthetic_cases(policy)

        self.assertEqual(full_evaluation.call_count, 2)
        self.assertEqual(response_copy.call_count, 3)
        self.assertEqual(generated["passing_case"]["response"], {"config": compatible})
        self.assertTrue(generated["passing_case"]["evaluation"]["passed"])
        self.assertFalse(generated["failing_case"]["evaluation"]["passed"])

    def test_compatibility_work_budget_fails_closed_without_full_evaluation(
        self,
    ) -> None:
        policy = {
            "schema_version": "1.0",
            "policy_id": "compatibility-budget-policy",
            "rules": [
                {
                    "rule_id": "config-choice",
                    "kind": "one_of",
                    "path": "config",
                    "values": [
                        0,
                        1,
                        {"label": "approved", "mode": "safe"},
                    ],
                },
                {
                    "rule_id": "mode-safe",
                    "kind": "equals",
                    "path": "config.mode",
                    "value": "safe",
                },
            ],
        }

        self.assertEqual(
            synthetic._MAX_COMPATIBILITY_WORK,
            MAX_POLICY_RULES * MAX_ONE_OF_VALUES,
        )
        with (
            patch.object(synthetic, "_MAX_COMPATIBILITY_WORK", 3),
            patch.object(
                synthetic,
                "evaluate_response",
                wraps=synthetic.evaluate_response,
            ) as full_evaluation,
            self.assertRaisesRegex(
                SyntheticGenerationError,
                "compatibility work exceeds",
            ),
        ):
            generate_synthetic_cases(policy)

        self.assertEqual(full_evaluation.call_count, 0)


if __name__ == "__main__":
    unittest.main()
