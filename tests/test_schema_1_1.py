"""Policy schema 1.1: the type, range and length rule kinds."""

import os
import subprocess
import sys
import unittest
from dataclasses import replace
from pathlib import Path

from constitutional_agent_testbench.authoring import lint_policy
from constitutional_agent_testbench.common import load_json, stable_json
from constitutional_agent_testbench.compare import compare_policies
from constitutional_agent_testbench.evaluator import evaluate_response
from constitutional_agent_testbench.inspection import audit_assertions
from constitutional_agent_testbench.policy import (
    Policy,
    PolicyValidationError,
    Rule,
    policy_to_dict,
    validate_policy,
)
from constitutional_agent_testbench.probes import generate_rule_probes
from constitutional_agent_testbench.receipt import create_receipt
from constitutional_agent_testbench.suite import SuiteInputError, evaluate_suite, validate_suite
from constitutional_agent_testbench.synthetic import (
    SyntheticGenerationError,
    generate_synthetic_cases,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def policy(*rules, version="1.1"):
    return {"schema_version": version, "policy_id": "typed", "rules": list(rules)}


def rule(identifier, kind, path="field", **fields):
    return {"rule_id": identifier, "kind": kind, "path": path, **fields}


def outcome(raw_rule, response):
    row = evaluate_response(policy(raw_rule), response)["rule_results"][0]
    return row["passed"], row["reason_code"]


class ValidationTests(unittest.TestCase):
    def assert_invalid(self, raw, message=None):
        with self.assertRaises(PolicyValidationError) as raised:
            validate_policy(raw)
        if message is not None:
            self.assertIn(message, str(raised.exception))
        return raised.exception

    def test_each_new_kind_accepts_its_fields(self):
        validated = validate_policy(policy(
            rule("t", "type", types=["string", "null"]),
            rule("r", "range", minimum=0, maximum=1.5),
            rule("r-min", "range", minimum=-3),
            rule("r-max", "range", maximum=1e300),
            rule("l", "length", minimum=1, maximum=5),
            rule("l-min", "length", minimum=0),
            rule("l-max", "length", maximum=1_000_000),
        ))
        self.assertEqual(validated.schema_version, "1.1")
        by_id = {item.rule_id: item for item in validated.rules}
        self.assertEqual(by_id["t"].types, ("string", "null"))
        self.assertEqual((by_id["r"].minimum, by_id["r"].maximum), (0, 1.5))
        self.assertEqual((by_id["r-min"].minimum, by_id["r-min"].maximum), (-3, None))
        self.assertEqual((by_id["l-max"].minimum, by_id["l-max"].maximum), (None, 1_000_000))

    def test_missing_and_unknown_fields_are_rejected(self):
        for raw in (rule("t", "type"), rule("t", "type", types=["string"], value=1),
                    rule("r", "range"), rule("r", "range", minimum=0, types=["string"]),
                    rule("l", "length"), rule("l", "length", maximum=1, value=None),
                    rule("r", "range", minimum=0, extra=1)):
            with self.subTest(raw=raw):
                self.assert_invalid(policy(raw))

    def test_type_lists_are_checked(self):
        cases = [
            ([], "non-empty"), ("string", "non-empty"), ([1], "non-empty"),
            (["text"], "must name only"), (["string", "string"], "duplicates"),
            (["integer", "number"], "integer beside number"),
            (["array", "boolean", "null", "number", "object", "string"], "every JSON value"),
        ]
        for types, message in cases:
            with self.subTest(types=types):
                self.assert_invalid(policy(rule("t", "type", types=types)), message)
        # Every value except fractional numbers is admissible, so it stays valid.
        validate_policy(policy(rule("t", "type", types=[
            "array", "boolean", "null", "integer", "object", "string"])))

    def test_range_bounds_are_checked(self):
        for fields in ({"minimum": True}, {"maximum": "1"}, {"minimum": None},
                       {"minimum": [0]}, {"minimum": float("inf")},
                       {"minimum": 2, "maximum": 1}, {"minimum": 0.5, "maximum": 0.25}):
            with self.subTest(fields=fields):
                self.assert_invalid(policy(rule("r", "range", **fields)))
        self.assert_invalid(policy(rule("r", "range")), "minimum, maximum or both")
        validate_policy(policy(rule("r", "range", minimum=0, maximum=0.0)))

    def test_length_bounds_are_checked(self):
        for fields in ({"minimum": 1.0}, {"maximum": True}, {"minimum": -1},
                       {"maximum": 1_000_001}, {"minimum": 3, "maximum": 2},
                       {"minimum": "1"}):
            with self.subTest(fields=fields):
                self.assert_invalid(policy(rule("l", "length", **fields)))
        self.assert_invalid(policy(rule("l", "length", maximum=1_000_001)),
                            "integer from 0 to 1,000,000")

    def test_schema_1_0_rejects_the_new_kinds_with_the_existing_message(self):
        for raw in (rule("t", "type", types=["string"]), rule("r", "range", minimum=0),
                    rule("l", "length", minimum=0)):
            with self.subTest(kind=raw["kind"]):
                error = self.assert_invalid(policy(raw, version="1.0"), "unknown rule kind")
                self.assertEqual(error.rule_index, 0)

    def test_schema_1_1_accepts_every_1_0_kind(self):
        raw = load_json(EXAMPLES / "policy.json")
        raw["schema_version"] = "1.1"
        validated = validate_policy(raw)
        self.assertEqual(validated.schema_version, "1.1")
        self.assertEqual(policy_to_dict(validated), raw | {"rules": policy_to_dict(validated)["rules"]})

    def test_unsupported_version_message_names_both_versions(self):
        self.assert_invalid(policy(rule("t", "required_field"), version="1.2"),
                            "must be 1.0 or 1.1")

    def test_policy_to_dict_round_trips_and_omits_absent_bounds(self):
        raw = policy(rule("t", "type", types=["number", "null"]),
                     rule("r", "range", maximum=3), rule("l", "length", minimum=2))
        emitted = policy_to_dict(validate_policy(raw))
        self.assertEqual(validate_policy(emitted), validate_policy(raw))
        by_id = {item["rule_id"]: item for item in emitted["rules"]}
        self.assertEqual(by_id["t"]["types"], ["number", "null"])
        self.assertEqual(by_id["r"], {"kind": "range", "maximum": 3, "path": "field", "rule_id": "r"})
        self.assertNotIn("maximum", by_id["l"])
        self.assertEqual(emitted["schema_version"], "1.1")

    def test_policy_object_revalidation_rejects_fields_the_kind_does_not_use(self):
        base = Rule("r", "required_field", "field")
        for bad in (replace(base, types=("string",)), replace(base, minimum=1),
                    replace(base, maximum=1),
                    Rule("t", "type", "field", types=("string",), minimum=0)):
            with self.subTest(rule=bad):
                with self.assertRaises(PolicyValidationError):
                    validate_policy(Policy("typed", (bad,), "1.1"))
        good = Policy("typed", (Rule("t", "type", "field", types=("string",)),), "1.1")
        self.assertEqual(validate_policy(good), good)
        # A 1.1 kind inside a Policy object that claims schema 1.0 is still refused.
        with self.assertRaises(PolicyValidationError):
            validate_policy(replace(good, schema_version="1.0"))

    def test_five_argument_rule_construction_still_works(self):
        positional = Rule("r", "one_of", "field", None, ("a",))
        self.assertEqual(positional, Rule(rule_id="r", kind="one_of", path="field", values=("a",)))
        self.assertEqual((positional.types, positional.minimum, positional.maximum), ((), None, None))


class EvaluationTests(unittest.TestCase):
    def test_type_matrix(self):
        number = rule("t", "type", types=["number"])
        integer = rule("t", "type", types=["integer"])
        cases = [
            (number, True, False), (number, 1, True), (number, 1.0, True), (number, -0.0, True),
            (integer, 1, True), (integer, 1.0, False), (integer, 1e2, False), (integer, True, False),
            (rule("t", "type", types=["boolean"]), 0, False),
            (rule("t", "type", types=["null"]), None, True),
            (rule("t", "type", types=["string"]), "", True),
            (rule("t", "type", types=["array", "object"]), {}, True),
            (rule("t", "type", types=["array", "object"]), "[]", False),
        ]
        for raw, value, passed in cases:
            with self.subTest(types=raw["types"], value=value):
                expected = (passed, "RULE_SATISFIED" if passed else "VALUE_WRONG_TYPE")
                self.assertEqual(outcome(raw, {"field": value}), expected)

    def test_range_is_numeric_and_inclusive(self):
        zero = rule("r", "range", minimum=0, maximum=0)
        for value in (0, 0.0, -0.0):
            with self.subTest(value=value):
                self.assertEqual(outcome(zero, {"field": value}), (True, "RULE_SATISFIED"))
        bounded = rule("r", "range", minimum=0, maximum=1)
        for value, passed in ((1, True), (1.0000001, False), (-1e-300, False), (True, False),
                              (False, False), ("0.5", False), (None, False), ([0], False)):
            with self.subTest(value=value):
                expected = (passed, "RULE_SATISFIED" if passed else "VALUE_OUT_OF_RANGE")
                self.assertEqual(outcome(bounded, {"field": value}), expected)

    def test_range_compares_big_integers_exactly_against_float_bounds(self):
        # 2**53 + 1 rounds to 2**53 as a float; an exact comparison keeps it above.
        tight = rule("r", "range", maximum=float(2**53))
        self.assertEqual(outcome(tight, {"field": 2**53}), (True, "RULE_SATISFIED"))
        self.assertEqual(outcome(tight, {"field": 2**53 + 1}), (False, "VALUE_OUT_OF_RANGE"))
        self.assertEqual(outcome(rule("r", "range", minimum=1e300), {"field": 10**301}),
                         (True, "RULE_SATISFIED"))

    def test_length_counts_code_points_items_and_members(self):
        one = rule("l", "length", minimum=1, maximum=1)
        for value, passed in (("\U0001f4a1", True), ("ab", False), ("", False),
                              ([None], True), ([], False), ({"a": 1}, True),
                              ({"a": 1, "b": 2}, False), (1, False), (None, False), (True, False)):
            with self.subTest(value=value):
                expected = (passed, "RULE_SATISFIED" if passed else "VALUE_LENGTH_OUT_OF_RANGE")
                self.assertEqual(outcome(one, {"field": value}), expected)

    def test_missing_paths_report_field_missing_for_every_new_kind(self):
        for raw in (rule("t", "type", "a.b", types=["string"]),
                    rule("r", "range", "a.b", minimum=0),
                    rule("l", "length", "a.b", maximum=3)):
            for response in ({}, {"a": 1}, {"a": {}}):
                with self.subTest(kind=raw["kind"], response=response):
                    self.assertEqual(outcome(raw, response), (False, "FIELD_MISSING"))

    def test_the_bundled_typed_example(self):
        raw = load_json(EXAMPLES / "typed-policy.json")
        passing = evaluate_response(raw, load_json(EXAMPLES / "typed-passing-response.json"))
        failing = evaluate_response(raw, load_json(EXAMPLES / "typed-failing-response.json"))
        self.assertTrue(passing["passed"])
        self.assertFalse(failing["passed"])
        codes = {row["reason_code"] for row in failing["rule_results"]}
        self.assertTrue({"VALUE_WRONG_TYPE", "VALUE_OUT_OF_RANGE",
                         "VALUE_LENGTH_OUT_OF_RANGE"} <= codes)


class CompatibilityTests(unittest.TestCase):
    def test_schema_1_0_receipt_digests_are_unchanged(self):
        receipt = create_receipt(load_json(EXAMPLES / "policy.json"),
                                 load_json(EXAMPLES / "passing-response.json"))
        self.assertEqual(receipt["policy_digest"],
                         "79856f8a0ea493b273751e2b2398c7a686e72c5b05eb7255e5296518c2ae4df9")
        self.assertEqual(receipt["response_digest"],
                         "d02307591efde081f17e4e166d336c64d24112e880a50f58e67fb0256a37d507")

    def test_suite_assertions_may_name_the_new_codes(self):
        fixtures = {"suite_version": "1.1", "cases": [{
            "case_id": "wrong-type", "response": {"field": 1}, "expected_passed": False,
            "expected_rules": {"t": {"passed": False, "reason_code": "VALUE_WRONG_TYPE"}}}]}
        validate_suite(fixtures)
        raw = policy(rule("t", "type", types=["string"]))
        self.assertTrue(evaluate_suite(raw, fixtures)["matches_expectations"])
        with self.assertRaises(SuiteInputError):
            validate_suite({"suite_version": "1.1", "cases": [{
                "case_id": "x", "response": {}, "expected_passed": False,
                "expected_rules": {"t": {"passed": True, "reason_code": "VALUE_WRONG_TYPE"}}}]})

    def test_audit_accepts_new_codes_only_for_their_own_kind(self):
        raw = policy(rule("t", "type", "a", types=["string"]),
                     rule("r", "range", "b", minimum=0),
                     rule("l", "length", "c", maximum=1))
        cases = []
        for target, code in (("t", "VALUE_OUT_OF_RANGE"), ("r", "VALUE_LENGTH_OUT_OF_RANGE"),
                             ("l", "VALUE_WRONG_TYPE"), ("t", "VALUE_WRONG_TYPE")):
            cases.append({"case_id": f"{target}-{code}", "response": {}, "expected_passed": False,
                          "expected_rules": {target: {"passed": False, "reason_code": code}}})
        report = audit_assertions(raw, {"suite_version": "1.1", "cases": cases})
        flagged = [case["incompatible_reason_rule_ids"] for case in report["cases"]]
        self.assertEqual(flagged, [["t"], ["r"], ["l"], []])

    def test_compare_treats_reordered_types_as_unmodified(self):
        before = policy(rule("t", "type", types=["string", "null"]))
        after = policy(rule("t", "type", types=["null", "string"]))
        fixtures = {"suite_version": "1.0", "cases": [
            {"case_id": "c", "response": {"field": None}, "expected_passed": True}]}
        changes = compare_policies(before, after, fixtures)["rule_changes"]
        self.assertEqual(changes["modified"], [])
        widened = policy(rule("t", "type", types=["string"]))
        self.assertEqual(compare_policies(before, widened, fixtures)["rule_changes"]["modified"], ["t"])


class SyntheticTests(unittest.TestCase):
    def passing(self, *rules):
        bundle = generate_synthetic_cases(policy(*rules))
        self.assertTrue(bundle["passing_case"]["evaluation"]["passed"])
        self.assertFalse(bundle["failing_case"]["evaluation"]["passed"])
        return bundle["passing_case"]["response"]

    def test_each_kind_alone(self):
        self.assertEqual(self.passing(rule("t", "type", types=["string"])), {"field": ""})
        self.assertEqual(self.passing(rule("t", "type", types=["object"])), {"field": {}})
        self.assertEqual(self.passing(rule("r", "range", minimum=5)), {"field": 5})
        self.assertEqual(self.passing(rule("r", "range", maximum=-2.5)), {"field": -3})
        self.assertEqual(self.passing(rule("l", "length", maximum=3)), {"field": ""})
        self.assertEqual(self.passing(rule("l", "length", minimum=3)), {"field": "sss"})

    def test_combinations_filter_the_menu(self):
        self.assertEqual(self.passing(rule("t", "type", types=["number"]),
                                      rule("r", "range", minimum=0.25, maximum=0.75)),
                         {"field": 0.25})
        self.assertEqual(self.passing(rule("t", "type", types=["array"]),
                                      rule("l", "length", minimum=2)),
                         {"field": [None, None]})
        self.assertEqual(self.passing(rule("t", "type", types=["integer"]),
                                      rule("r", "range", minimum=1.5, maximum=9)),
                         {"field": 2})

    def test_finite_domains_are_filtered_by_range_and_type(self):
        self.assertEqual(self.passing(rule("o", "one_of", values=[10, 2, 3]),
                                      rule("r", "range", maximum=5)), {"field": 2})
        self.assertEqual(self.passing(rule("o", "one_of", values=[1, "a"]),
                                      rule("t", "type", types=["string"])), {"field": "a"})

    def test_nested_paths_keep_descendants(self):
        response = self.passing(rule("t", "type", "meta", types=["object"]),
                                rule("l", "length", "meta", minimum=1),
                                rule("n", "range", "meta.score", minimum=0, maximum=1))
        self.assertEqual(response, {"meta": {"score": 0}})

    def test_unsatisfiable_or_unsupported_combinations_fail_closed(self):
        for rules in (
            (rule("e", "equals", value="x"), rule("t", "type", types=["number"])),
            (rule("t", "type", types=["integer"]), rule("r", "range", minimum=0.25, maximum=0.75)),
            (rule("e", "empty_list"), rule("l", "length", minimum=1)),
            (rule("l", "length", "meta", minimum=2), rule("c", "required_field", "meta.child")),
            (rule("t", "type", types=["array"]), rule("l", "length", minimum=100_000)),
            (rule("t", "type", types=["string"]), rule("l", "length", minimum=1_000_000)),
        ):
            with self.subTest(rules=[item["rule_id"] for item in rules]):
                with self.assertRaises(SyntheticGenerationError):
                    generate_synthetic_cases(policy(*rules))

    def test_schema_1_0_synthetic_output_is_unchanged_under_1_1(self):
        raw = load_json(EXAMPLES / "policy.json")
        before = generate_synthetic_cases(raw)
        raw["schema_version"] = "1.1"
        self.assertEqual(stable_json(generate_synthetic_cases(raw)), stable_json(before))


class ProbeTests(unittest.TestCase):
    def probe_values(self, *rules):
        report = generate_rule_probes(policy(*rules))
        cases = {case["case_id"]: case["response"] for case in report["suite"]["cases"]}
        for probe in report["probes"]:
            self.assertIn(probe["target_rule_id"], probe["failed_rule_ids"])
        return {probe["target_rule_id"]: cases[probe["case_id"]]
                for probe in report["probes"] if probe["mutation"] == "wrong_value"}

    def test_boundary_values_come_first(self):
        values = self.probe_values(rule("r", "range", "a", minimum=0, maximum=10),
                                   rule("l", "length", "b", minimum=1, maximum=2),
                                   rule("m", "range", "c", minimum=3))
        self.assertEqual(values["r"]["a"], 11)
        self.assertEqual(values["l"]["b"], "sss")
        self.assertEqual(values["m"]["c"], 2)

    def test_the_menu_takes_over_when_a_boundary_does_not_fail(self):
        values = self.probe_values(rule("r", "range", "a", maximum=1e300),
                                   rule("l", "length", "b", maximum=5000),
                                   rule("t", "type", "c", types=["null"]),
                                   rule("u", "type", "d", types=["array", "boolean", "null",
                                                                 "integer", "object", "string"]))
        self.assertIsNone(values["r"]["a"])
        self.assertIsNone(values["l"]["b"])
        self.assertIs(values["t"]["c"], False)
        self.assertEqual(values["u"]["d"], 0.5)

    def test_bundled_typed_example_probes_verify(self):
        report = generate_rule_probes(load_json(EXAMPLES / "typed-policy.json"))
        self.assertEqual(len(report["probes"]),
                         sum(1 if item["kind"] == "required_field" else 2
                             for item in load_json(EXAMPLES / "typed-policy.json")["rules"]))


class LintTests(unittest.TestCase):
    def codes(self, *rules):
        return [(item["code"], item["rule_ids"]) for item in lint_policy(policy(*rules))["findings"]]

    def test_different_bounds_are_not_duplicates(self):
        self.assertEqual(self.codes(rule("a", "range", minimum=0), rule("b", "range", minimum=1)), [])
        self.assertEqual(self.codes(rule("a", "range", minimum=0), rule("b", "range", minimum=0)),
                         [("DUPLICATE_CONSTRAINT", ["a", "b"])])
        self.assertEqual(self.codes(rule("a", "type", types=["string", "null"]),
                                    rule("b", "type", types=["null", "string"])),
                         [("DUPLICATE_CONSTRAINT", ["a", "b"])])
        self.assertEqual(self.codes(rule("a", "range", minimum=1), rule("b", "length", minimum=1)), [])

    def test_finite_domains_narrowed_to_nothing_are_disjoint(self):
        self.assertEqual(self.codes(rule("e", "equals", value=5), rule("m", "range", maximum=3)),
                         [("DISJOINT_CONSTRAINTS", ["e", "m"])])
        self.assertEqual(self.codes(rule("o", "one_of", values=[1, "a"]),
                                    rule("t", "type", types=["boolean"]),
                                    rule("q", "required_field")),
                         [("DISJOINT_CONSTRAINTS", ["o", "t"])])
        self.assertEqual(self.codes(rule("o", "one_of", values=[1, "a"]),
                                    rule("t", "type", types=["string"])), [])

    def test_descendant_checks_keep_the_new_fields(self):
        # An equals ancestor whose descendant is a range rule must use the bounds.
        compatible = (rule("p", "equals", "a", value={"n": 5}), rule("c", "range", "a.n", maximum=9))
        self.assertEqual(self.codes(*compatible), [])
        conflict = (rule("p", "equals", "a", value={"n": 5}), rule("c", "range", "a.n", maximum=3))
        self.assertEqual(self.codes(*conflict), [("INCOMPATIBLE_DESCENDANTS", ["c", "p"])])

    def test_narrowing_work_is_charged_to_the_lint_budget(self):
        from unittest.mock import patch

        from constitutional_agent_testbench.authoring import AuthoringLimitError

        # The equals value serializes to one byte, checked against one filter.
        with patch("constitutional_agent_testbench.authoring.MAX_AUTHORING_WORK_BYTES", 0):
            with self.assertRaises(AuthoringLimitError):
                lint_policy(policy(rule("e", "equals", value=5), rule("m", "range", maximum=3)))

    def test_paths_without_a_finite_domain_are_not_analysed(self):
        self.assertEqual(self.codes(rule("t", "type", types=["string"]),
                                    rule("r", "range", minimum=0)), [])


class CliTests(unittest.TestCase):
    def run_cli(self, *arguments):
        import io
        import json
        from contextlib import redirect_stderr, redirect_stdout

        from constitutional_agent_testbench.cli import main

        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(list(arguments))
        return code, json.loads(stdout.getvalue() or stderr.getvalue())

    def test_typed_example_commands_and_exit_codes(self):
        typed = str(EXAMPLES / "typed-policy.json")
        code, report = self.run_cli("validate-policy", typed)
        self.assertEqual((code, report["schema_version"]), (0, "1.1"))
        code, _ = self.run_cli("evaluate", typed, str(EXAMPLES / "typed-passing-response.json"),
                               "--strict-exit")
        self.assertEqual(code, 0)
        code, report = self.run_cli("evaluate", typed, str(EXAMPLES / "typed-failing-response.json"),
                                    "--strict-exit")
        self.assertEqual(code, 1)
        self.assertFalse(report["passed"])
        for command in ("generate-synthetic", "generate-probes"):
            with self.subTest(command=command):
                self.assertEqual(self.run_cli(command, typed)[0], 0)
        self.assertEqual(self.run_cli("lint-policy", typed, "--strict-exit")[0], 0)

    def test_help_names_both_policy_schemas(self):
        import io
        from contextlib import redirect_stdout

        from constitutional_agent_testbench.cli import main

        for command in ("validate-policy", "evaluate"):
            stdout = io.StringIO()
            with self.subTest(command=command), redirect_stdout(stdout):
                self.assertEqual(main([command, "--help"]), 0)
            self.assertIn("1.0 or 1.1", " ".join(stdout.getvalue().split()))


class DeterminismTests(unittest.TestCase):
    def test_typed_example_outputs_do_not_depend_on_hash_seed(self):
        script = (
            "import sys; sys.path.insert(0, sys.argv[1]);"
            "from constitutional_agent_testbench import *;"
            "from constitutional_agent_testbench.common import load_json, stable_json;"
            "p = load_json(sys.argv[2]);"
            "print(stable_json([generate_synthetic_cases(p), generate_rule_probes(p), lint_policy(p)]))"
        )
        outputs = set()
        for seed in ("0", "1", "4242"):
            environment = dict(os.environ, PYTHONHASHSEED=seed)
            completed = subprocess.run(
                [sys.executable, "-c", script, str(ROOT / "src"), str(EXAMPLES / "typed-policy.json")],
                capture_output=True, text=True, encoding="utf-8", env=environment, check=True)
            outputs.add(completed.stdout)
        self.assertEqual(len(outputs), 1)


if __name__ == "__main__":
    unittest.main()
