from __future__ import annotations

import unittest

import constitutional_agent_testbench.precedence as precedence_module
from constitutional_agent_testbench.evaluator import evaluate_response
from constitutional_agent_testbench.precedence import (
    OrderCheckTooLargeError,
    PrecedenceTraceError,
    check_order_conformance,
)


def three_rule_policy() -> dict:
    return {
        "schema_version": "1.0",
        "policy_id": "peer-rule-policy",
        "rules": [
            {
                "rule_id": "alpha",
                "kind": "equals",
                "path": "alpha",
                "value": "pass",
            },
            {
                "rule_id": "beta",
                "kind": "equals",
                "path": "beta",
                "value": "pass",
            },
            {
                "rule_id": "gamma",
                "kind": "equals",
                "path": "gamma",
                "value": "pass",
            },
        ],
    }


def passing_response() -> dict:
    return {"alpha": "pass", "beta": "pass", "gamma": "pass"}


def one_failure_response() -> dict:
    return {"alpha": "fail", "beta": "pass", "gamma": "pass"}


class PrecedenceTraceTests(unittest.TestCase):
    def test_exhausts_three_rule_permutations_without_semantic_drift(self) -> None:
        report = check_order_conformance(three_rule_policy(), passing_response())

        self.assertEqual(report["coverage"]["mode"], "exhaustive")
        self.assertEqual(report["coverage"]["orders_evaluated"], 6)
        self.assertEqual(report["coverage"]["orders_total"], 6)
        self.assertEqual(report["baseline_repeats"], 3)
        self.assertEqual(report["evaluation_repeats_per_order"], 3)
        self.assertEqual(report["coverage"]["evaluator_runs"], 18)
        self.assertEqual(report["status"], "PRESENTATION_ONLY_DRIFT")
        self.assertTrue(report["conforms_within_coverage"])
        self.assertFalse(report["variance"]["outcome"])
        self.assertFalse(report["variance"]["reason_evidence"])
        self.assertFalse(report["variance"]["participation"])
        self.assertTrue(report["variance"]["presentation"])
        self.assertTrue(report["presentation_follows_requested_order"])
        self.assertEqual(report["coverage"]["evaluations_performed"], 18)
        self.assertEqual(report["coverage"]["evaluations_per_order"], 3)
        self.assertTrue(report["coverage"]["rule_results_complete"])
        self.assertEqual(report["coverage"]["incomplete_orders"], 0)
        self.assertGreater(report["coverage"]["observed_result_bytes"], 0)
        self.assertGreater(
            report["coverage"]["charged_work_bytes"],
            report["coverage"]["estimated_input_work_bytes"],
        )
        self.assertEqual(
            report["coverage"]["report_byte_limit"],
            precedence_module.MAX_REPORT_BYTES,
        )

    def test_deterministic_evaluator_runs_three_times_for_every_order(self) -> None:
        calls = 0

        def counted(policy, response):
            nonlocal calls
            calls += 1
            return evaluate_response(policy, response)

        report = check_order_conformance(
            three_rule_policy(),
            passing_response(),
            evaluator=counted,
        )

        self.assertEqual(calls, 18)
        self.assertEqual(report["coverage"]["evaluations_performed"], calls)

    def test_failure_reason_evidence_remains_bound_to_rule_identity(self) -> None:
        report = check_order_conformance(
            three_rule_policy(), one_failure_response()
        )

        self.assertEqual(report["status"], "PRESENTATION_ONLY_DRIFT")
        self.assertFalse(report["variance"]["reason_evidence"])

    def test_reports_no_variance_when_evaluator_stabilizes_presentation(self) -> None:
        def stable_presentation(policy, response):
            result = evaluate_response(policy, response)
            result["rule_results"].sort(key=lambda item: item["rule_id"])
            return result

        report = check_order_conformance(
            three_rule_policy(),
            one_failure_response(),
            evaluator=stable_presentation,
        )

        self.assertEqual(report["status"], "NO_VARIANCE_OBSERVED")
        self.assertTrue(report["conforms_within_coverage"])
        self.assertFalse(any(report["variance"].values()))

    def test_baseline_nondeterminism_stops_before_permutations(self) -> None:
        calls = 0

        def alternating(policy, response):
            nonlocal calls
            calls += 1
            result = evaluate_response(policy, response)
            if calls % 2 == 0:
                result["rule_results"][0]["passed"] = False
                result["rule_results"][0]["reason_code"] = "ALTERNATING_RESULT"
                result["passed"] = all(
                    item["passed"] for item in result["rule_results"]
                )
            return result

        report = check_order_conformance(
            three_rule_policy(),
            passing_response(),
            evaluator=alternating,
        )

        self.assertEqual(report["status"], "INCONCLUSIVE_NONDETERMINISTIC")
        self.assertIsNone(report["conforms_within_coverage"])
        self.assertEqual(report["coverage"]["mode"], "incomplete")
        self.assertEqual(report["coverage"]["orders_evaluated"], 1)
        self.assertEqual(calls, 3)

    def test_nondeterminism_in_a_nonbaseline_order_is_inconclusive(self) -> None:
        calls_by_order: dict[tuple[str, ...], int] = {}

        def later_alternating(policy, response):
            result = evaluate_response(policy, response)
            order = tuple(rule.rule_id for rule in policy.rules)
            calls_by_order[order] = calls_by_order.get(order, 0) + 1
            if order != ("alpha", "beta", "gamma") and calls_by_order[order] == 2:
                result["rule_results"][0]["passed"] = False
                result["rule_results"][0]["reason_code"] = "ALTERNATING_RESULT"
                result["passed"] = all(
                    item["passed"] for item in result["rule_results"]
                )
            return result

        report = check_order_conformance(
            three_rule_policy(),
            passing_response(),
            evaluator=later_alternating,
        )

        self.assertEqual(report["status"], "INCONCLUSIVE_NONDETERMINISTIC")
        self.assertIsNone(report["conforms_within_coverage"])
        self.assertGreater(report["coverage"]["orders_evaluated"], 1)
        self.assertEqual(report["coverage"]["evaluator_runs"], 6)
        self.assertEqual(report["witnesses"][0]["dimension"], "evaluator_result")
        self.assertEqual(
            report["witnesses"][0]["order"],
            ["alpha", "gamma", "beta"],
        )

    def test_last_writer_behavior_produces_semantic_order_drift(self) -> None:
        def last_writer(policy, response):
            result = evaluate_response(policy, response)
            alpha = next(
                item for item in result["rule_results"] if item["rule_id"] == "alpha"
            )
            alpha["passed"] = policy.rules[-1].rule_id != "alpha"
            result["passed"] = all(
                item["passed"] for item in result["rule_results"]
            )
            return result

        report = check_order_conformance(
            three_rule_policy(),
            one_failure_response(),
            evaluator=last_writer,
        )

        self.assertEqual(report["status"], "SEMANTIC_ORDER_DRIFT")
        self.assertFalse(report["conforms_within_coverage"])
        self.assertTrue(report["variance"]["outcome"])
        self.assertAdjacentWitness(report, "outcome")

    def test_reason_overwrite_produces_evidence_order_drift(self) -> None:
        def reason_overwrite(policy, response):
            result = evaluate_response(policy, response)
            last_rule_id = policy.rules[-1].rule_id.upper()
            for item in result["rule_results"]:
                item["reason_code"] = f"ORDER_{last_rule_id}"
            return result

        report = check_order_conformance(
            three_rule_policy(),
            passing_response(),
            evaluator=reason_overwrite,
        )

        self.assertEqual(report["status"], "EVIDENCE_ORDER_DRIFT")
        self.assertFalse(report["variance"]["outcome"])
        self.assertTrue(report["variance"]["reason_evidence"])
        self.assertAdjacentWitness(report, "reason_evidence")

    def test_short_circuit_behavior_produces_participation_order_drift(self) -> None:
        def short_circuit(policy, response):
            result = evaluate_response(policy, response)
            participating = []
            for item in result["rule_results"]:
                participating.append(item)
                if not item["passed"]:
                    break
            result["rule_results"] = participating
            result["passed"] = all(item["passed"] for item in participating)
            return result

        report = check_order_conformance(
            three_rule_policy(),
            one_failure_response(),
            evaluator=short_circuit,
        )

        self.assertEqual(report["status"], "PARTICIPATION_ORDER_DRIFT")
        self.assertFalse(report["conforms_within_coverage"])
        self.assertFalse(report["variance"]["outcome"])
        self.assertFalse(report["variance"]["reason_evidence"])
        self.assertTrue(report["variance"]["participation"])
        self.assertAdjacentWitness(report, "participation")

    def test_omission_aggregate_failure_is_only_participation_drift(self) -> None:
        def omit_one(policy, response):
            result = evaluate_response(policy, response)
            if policy.rules[0].rule_id == "beta":
                result["rule_results"] = result["rule_results"][:-1]
                result["passed"] = False
            return result

        report = check_order_conformance(
            three_rule_policy(),
            passing_response(),
            evaluator=omit_one,
        )

        self.assertEqual(report["status"], "PARTICIPATION_ORDER_DRIFT")
        self.assertFalse(report["variance"]["outcome"])
        self.assertFalse(report["variance"]["reason_evidence"])
        self.assertTrue(report["variance"]["participation"])

    def test_disconnected_rule_pass_drift_gets_endpoint_path_witness(self) -> None:
        def disconnected_pass(policy, response):
            result = evaluate_response(policy, response)
            order = tuple(rule.rule_id for rule in policy.rules)
            alpha = next(
                item for item in result["rule_results"]
                if item["rule_id"] == "alpha"
            )
            if order == ("beta", "alpha", "gamma"):
                alpha["passed"] = True
                alpha["reason_code"] = "STABLE_EVIDENCE"
                result["rule_results"] = [alpha]
            elif order == ("gamma", "alpha", "beta"):
                alpha["passed"] = False
                alpha["reason_code"] = "STABLE_EVIDENCE"
                result["rule_results"] = [alpha]
            else:
                result["rule_results"] = []
            result["passed"] = False
            return result

        report = check_order_conformance(
            three_rule_policy(),
            passing_response(),
            evaluator=disconnected_pass,
        )

        self.assertEqual(report["status"], "COMPOUND_ORDER_DRIFT")
        self.assertTrue(report["variance"]["outcome"])
        self.assertFalse(report["variance"]["reason_evidence"])
        self.assertTrue(report["variance"]["participation"])
        self.assertEndpointPathWitness(report, "outcome")

    def test_disconnected_rule_evidence_drift_gets_endpoint_path_witness(self) -> None:
        def disconnected_evidence(policy, response):
            result = evaluate_response(policy, response)
            order = tuple(rule.rule_id for rule in policy.rules)
            alpha = next(
                item for item in result["rule_results"]
                if item["rule_id"] == "alpha"
            )
            if order == ("beta", "alpha", "gamma"):
                alpha["passed"] = False
                alpha["reason_code"] = "LEFT_EVIDENCE"
                result["rule_results"] = [alpha]
            elif order == ("gamma", "alpha", "beta"):
                alpha["passed"] = False
                alpha["reason_code"] = "RIGHT_EVIDENCE"
                result["rule_results"] = [alpha]
            else:
                result["rule_results"] = []
            result["passed"] = False
            return result

        report = check_order_conformance(
            three_rule_policy(),
            passing_response(),
            evaluator=disconnected_evidence,
        )

        self.assertEqual(report["status"], "COMPOUND_ORDER_DRIFT")
        self.assertFalse(report["variance"]["outcome"])
        self.assertTrue(report["variance"]["reason_evidence"])
        self.assertTrue(report["variance"]["participation"])
        self.assertEndpointPathWitness(report, "reason_evidence")

    def test_stable_incomplete_results_never_conform(self) -> None:
        def empty_failure(policy, response):
            return {
                "passed": False,
                "policy_id": policy.policy_id,
                "rule_results": [],
            }

        report = check_order_conformance(
            three_rule_policy(),
            passing_response(),
            evaluator=empty_failure,
        )

        self.assertEqual(report["status"], "INCOMPLETE_RULE_COVERAGE")
        self.assertFalse(report["conforms_within_coverage"])
        self.assertFalse(report["coverage"]["rule_results_complete"])
        self.assertEqual(report["coverage"]["incomplete_orders"], 6)
        witness = next(
            item for item in report["witnesses"]
            if item["dimension"] == "rule_coverage"
        )
        self.assertEqual(witness["missing_rule_ids"], ["alpha", "beta", "gamma"])

    def test_stable_fixed_subset_never_conforms(self) -> None:
        def fixed_subset(policy, response):
            result = evaluate_response(policy, response)
            result["rule_results"] = [
                item for item in result["rule_results"] if item["rule_id"] == "alpha"
            ]
            result["passed"] = False
            return result

        report = check_order_conformance(
            three_rule_policy(),
            passing_response(),
            evaluator=fixed_subset,
        )

        self.assertEqual(report["status"], "INCOMPLETE_RULE_COVERAGE")
        self.assertFalse(report["conforms_within_coverage"])
        self.assertEqual(report["coverage"]["incomplete_orders"], 6)

    def test_incomplete_passing_result_fails_closed(self) -> None:
        def empty_pass(policy, response):
            return {
                "passed": True,
                "policy_id": policy.policy_id,
                "rule_results": [],
            }

        with self.assertRaises(PrecedenceTraceError):
            check_order_conformance(
                three_rule_policy(),
                passing_response(),
                evaluator=empty_pass,
            )

    def test_incoherent_complete_aggregate_fails_closed(self) -> None:
        def incoherent(policy, response):
            result = evaluate_response(policy, response)
            result["passed"] = False
            return result

        with self.assertRaises(PrecedenceTraceError):
            check_order_conformance(
                three_rule_policy(),
                passing_response(),
                evaluator=incoherent,
            )

    def test_foreign_duplicate_and_mismatched_rule_results_fail_closed(self) -> None:
        mutations = (
            lambda rows: rows.__setitem__(0, {**rows[0], "rule_id": "foreign"}),
            lambda rows: rows.__setitem__(1, {**rows[1], "rule_id": rows[0]["rule_id"]}),
            lambda rows: rows.__setitem__(0, {**rows[0], "path": "wrong"}),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                def invalid(policy, response):
                    result = evaluate_response(policy, response)
                    mutate(result["rule_results"])
                    return result

                with self.assertRaises(PrecedenceTraceError):
                    check_order_conformance(
                        three_rule_policy(),
                        passing_response(),
                        evaluator=invalid,
                    )

    def test_compound_semantic_drift_is_not_collapsed(self) -> None:
        def compound(policy, response):
            result = evaluate_response(policy, response)
            if policy.rules[0].rule_id == "beta":
                result["rule_results"] = result["rule_results"][:-1]
                result["rule_results"][0]["passed"] = False
                result["rule_results"][0]["reason_code"] = "COMPOUND_CHANGE"
                result["passed"] = False
            return result

        report = check_order_conformance(
            three_rule_policy(),
            passing_response(),
            evaluator=compound,
        )

        self.assertEqual(report["status"], "COMPOUND_ORDER_DRIFT")
        self.assertFalse(report["conforms_within_coverage"])
        self.assertTrue(report["variance"]["outcome"])
        self.assertTrue(report["variance"]["reason_evidence"])
        self.assertTrue(report["variance"]["participation"])

    def test_oversized_evaluator_result_fails_closed(self) -> None:
        def oversized(policy, response):
            result = evaluate_response(policy, response)
            result["policy_id"] = "x" * 1_000_001
            return result

        with self.assertRaises(OrderCheckTooLargeError):
            check_order_conformance(
                three_rule_policy(),
                passing_response(),
                evaluator=oversized,
            )

    def test_oversized_report_fails_closed(self) -> None:
        original_limit = precedence_module.MAX_REPORT_BYTES
        precedence_module.MAX_REPORT_BYTES = 1
        try:
            with self.assertRaisesRegex(
                OrderCheckTooLargeError,
                "report exceeds the public byte limit",
            ):
                check_order_conformance(
                    three_rule_policy(),
                    passing_response(),
                )
        finally:
            precedence_module.MAX_REPORT_BYTES = original_limit

    def test_three_way_interaction_is_found_by_complete_enumeration(self) -> None:
        def three_way(policy, response):
            result = evaluate_response(policy, response)
            order = tuple(rule.rule_id for rule in policy.rules)
            if order == ("gamma", "alpha", "beta"):
                result["rule_results"][0]["passed"] = False
                result["passed"] = all(
                    item["passed"] for item in result["rule_results"]
                )
            return result

        report = check_order_conformance(
            three_rule_policy(),
            passing_response(),
            evaluator=three_way,
        )

        self.assertEqual(report["coverage"]["orders_evaluated"], 6)
        self.assertEqual(report["status"], "SEMANTIC_ORDER_DRIFT")
        self.assertAdjacentWitness(report, "outcome")

    def test_cumulative_evaluator_output_is_charged_to_the_work_budget(self) -> None:
        baseline = check_order_conformance(
            three_rule_policy(),
            passing_response(),
        )
        original_budget = precedence_module.MAX_EXHAUSTIVE_WORK_BYTES
        precedence_module.MAX_EXHAUSTIVE_WORK_BYTES = (
            baseline["coverage"]["estimated_input_work_bytes"] + 1
        )
        try:
            with self.assertRaises(OrderCheckTooLargeError):
                check_order_conformance(
                    three_rule_policy(),
                    passing_response(),
                )
        finally:
            precedence_module.MAX_EXHAUSTIVE_WORK_BYTES = original_budget

    def test_order_dependent_fields_outside_cat_schema_fail_closed(self) -> None:
        def hidden_decision(policy, response):
            result = evaluate_response(policy, response)
            result["decision"] = policy.rules[-1].rule_id
            return result

        with self.assertRaises(PrecedenceTraceError):
            check_order_conformance(
                three_rule_policy(),
                passing_response(),
                evaluator=hidden_decision,
            )

    def test_mismatched_result_policy_identity_fails_closed(self) -> None:
        def changed_policy_id(policy, response):
            result = evaluate_response(policy, response)
            result["policy_id"] = policy.rules[-1].rule_id
            return result

        with self.assertRaises(PrecedenceTraceError):
            check_order_conformance(
                three_rule_policy(),
                passing_response(),
                evaluator=changed_policy_id,
            )

    def test_eight_rules_fail_closed_instead_of_silently_sampling(self) -> None:
        policy = three_rule_policy()
        policy["rules"] = [
            {
                "rule_id": f"rule-{index}",
                "kind": "required_field",
                "path": f"value{index}",
            }
            for index in range(8)
        ]
        with self.assertRaises(OrderCheckTooLargeError):
            check_order_conformance(policy, {})

    def test_large_seven_rule_inputs_fail_the_work_budget_before_evaluation(self) -> None:
        policy = three_rule_policy()
        policy["rules"] = [
            {
                "rule_id": f"rule-{index}",
                "kind": "required_field",
                "path": f"value{index}",
            }
            for index in range(7)
        ]
        with self.assertRaises(OrderCheckTooLargeError):
            check_order_conformance(policy, {"unused": "x" * 20_000})

    def test_one_rule_is_not_misrepresented_as_an_order_check(self) -> None:
        policy = three_rule_policy()
        policy["rules"] = policy["rules"][:1]
        with self.assertRaises(PrecedenceTraceError):
            check_order_conformance(policy, passing_response())

    def assertAdjacentWitness(self, report: dict, dimension: str) -> None:
        witness = next(
            item for item in report["witnesses"] if item["dimension"] == dimension
        )
        left = witness["left_order"]
        right = witness["right_order"]
        differing = [
            index for index, pair in enumerate(zip(left, right)) if pair[0] != pair[1]
        ]
        self.assertEqual(differing, [witness["swap_index"], witness["swap_index"] + 1])

    def assertEndpointPathWitness(self, report: dict, dimension: str) -> None:
        witness = next(
            item for item in report["witnesses"] if item["dimension"] == dimension
        )
        self.assertEqual(witness["comparison"], "endpoint_path")
        path = witness["adjacent_swap_path"]
        self.assertEqual(path[0], witness["left_order"])
        self.assertEqual(path[-1], witness["right_order"])
        for left, right in zip(path, path[1:]):
            differing = [
                index
                for index, pair in enumerate(zip(left, right))
                if pair[0] != pair[1]
            ]
            self.assertEqual(len(differing), 2)
            self.assertEqual(differing[1], differing[0] + 1)


if __name__ == "__main__":
    unittest.main()
