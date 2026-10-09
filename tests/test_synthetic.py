from __future__ import annotations

import unittest
from unittest.mock import patch

from constitutional_agent_testbench import synthetic
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

    def test_compatibility_budget_charges_inner_one_of_comparisons(self) -> None:
        policy = {
            "schema_version": "1.0",
            "policy_id": "nested-one-of-work-policy",
            "rules": [
                {
                    "rule_id": "config-choice",
                    "kind": "one_of",
                    "path": "config",
                    "values": [{"label": "approved", "mode": "safe"}],
                },
                {
                    "rule_id": "mode-choice",
                    "kind": "one_of",
                    "path": "config.mode",
                    "values": ["safe", "review", "blocked"],
                },
            ],
        }

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


def path_policy(*rules: dict) -> dict:
    return {
        "schema_version": "1.0",
        "policy_id": "constraint-policy",
        "rules": [
            {"rule_id": f"rule-{index}", **rule} for index, rule in enumerate(rules)
        ],
    }


class ConstraintIntersectionTests(unittest.TestCase):
    """Fail-closed branches of per-path candidate selection."""

    def test_several_one_of_sets_use_the_first_common_candidate(self) -> None:
        cases = generate_synthetic_cases(
            path_policy(
                {"kind": "one_of", "path": "x", "values": [1, 2, 3]},
                {"kind": "one_of", "path": "x", "values": [3, 2]},
            )
        )
        # 2 is the first value of the first group that every group allows.
        self.assertEqual(cases["passing_case"]["response"], {"x": 2})
        self.assertTrue(cases["passing_case"]["evaluation"]["passed"])

    def test_disjoint_one_of_sets_fail_closed(self) -> None:
        with self.assertRaisesRegex(SyntheticGenerationError, "conflicting constraints"):
            generate_synthetic_cases(
                path_policy(
                    {"kind": "one_of", "path": "x", "values": [1, 2]},
                    {"kind": "one_of", "path": "x", "values": [3, 4]},
                )
            )

    def test_fixed_value_outside_a_one_of_set_fails_closed(self) -> None:
        with self.assertRaisesRegex(SyntheticGenerationError, "conflicting constraints"):
            generate_synthetic_cases(
                path_policy(
                    {"kind": "equals", "path": "x", "value": 5},
                    {"kind": "one_of", "path": "x", "values": [1, 2]},
                )
            )

    def test_ancestor_already_satisfied_by_a_descendant_is_kept(self) -> None:
        cases = generate_synthetic_cases(
            path_policy(
                {"kind": "required_field", "path": "x.y"},
                {"kind": "required_field", "path": "x"},
            )
        )
        self.assertEqual(cases["passing_case"]["response"], {"x": {"y": None}})
        self.assertTrue(cases["passing_case"]["evaluation"]["passed"])

    def test_assign_path_refuses_to_descend_through_a_scalar(self) -> None:
        # Paths are processed deepest first, so no public policy reaches this
        # guard; it is exercised directly to keep the fail-closed branch honest.
        document = {"a": 1}
        with self.assertRaisesRegex(SyntheticGenerationError, "incompatible nested paths"):
            synthetic._assign_path(document, "a.b", 0)
        self.assertEqual(document, {"a": 1})


if __name__ == "__main__":
    unittest.main()
