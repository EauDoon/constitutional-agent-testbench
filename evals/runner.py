"""Run the eval scenario suite derived from examples/assertion-suite.json.

Each JSON case file in evals/cases/ describes one input response plus the
expected verdict (overall pass and per-rule outcome plus reason code). The
runner loads the declared policy, evaluates the response with the testbench
library, and compares the actual result against the expected one. Every case must
name every rule its policy declares, so a partial expectation fails the run instead
of leaving rules unobserved. Exits 0 when every case matches, non-zero when any
case diverges.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = Path(__file__).resolve().parent / "cases"
sys.path.insert(0, str(REPO_ROOT / "src"))

from constitutional_agent_testbench import evaluate_response, validate_policy  # noqa: E402


class EvalCaseError(Exception):
    """Raised when an eval case file is not a usable JSON object."""


def load_case_document(path: Path) -> dict:
    """Load one case file. Non-object fixtures are rejected before subscripting."""

    with path.open("r", encoding="utf-8") as handle:
        document = json.load(handle)
    name = path.name
    if not isinstance(document, dict):
        raise EvalCaseError(f"{name} must be a JSON object")
    expected = document.get("expected")
    if not isinstance(expected, dict):
        raise EvalCaseError(f"{name} expected must be a JSON object")
    rules = expected.get("rules", {})
    if not isinstance(rules, dict):
        raise EvalCaseError(f"{name} expected.rules must be a JSON object")
    if "policy_path" not in document or "input" not in document:
        raise EvalCaseError(f"{name} requires policy_path and input")
    return document


def _load_case(path: Path) -> dict:
    return load_case_document(path)


class _CaseAssertion(unittest.TestCase):
    longMessage = True

    def setUp(self) -> None:
        self.case_path = Path(getattr(self, "_case_path"))
        self.case = _load_case(self.case_path)
        self.policy_path = REPO_ROOT / self.case["policy_path"]
        with self.policy_path.open("r", encoding="utf-8") as handle:
            self.policy = validate_policy(json.load(handle))
        self.result = evaluate_response(self.policy, self.case["input"])

    def test_overall_verdict_matches_expected(self) -> None:
        expected = self.case["expected"]
        self.assertEqual(
            self.result["passed"],
            expected["passed"],
            msg=f"overall verdict: expected={expected['passed']}, actual={self.result['passed']}",
        )

    def test_every_declared_rule_is_covered(self) -> None:
        expected_rules = self.case["expected"].get("rules", {})
        declared = [rule.rule_id for rule in self.policy.rules]
        self.assertEqual(
            sorted(expected_rules),
            sorted(declared),
            msg=(
                "expected.rules must name every rule the policy declares: "
                f"missing={sorted(set(declared) - set(expected_rules))}, "
                f"undeclared={sorted(set(expected_rules) - set(declared))}"
            ),
        )

    def test_rule_outcomes_match_expected(self) -> None:
        expected_rules = self.case["expected"].get("rules", {})
        results_by_id = {
            entry["rule_id"]: entry for entry in self.result["rule_results"]
        }
        for rule_id, expectation in expected_rules.items():
            self.assertIn(
                rule_id,
                results_by_id,
                msg=f"expected rule {rule_id!r} not present in evaluation results",
            )
            actual = results_by_id[rule_id]
            self.assertEqual(
                actual["passed"],
                expectation["passed"],
                msg=(
                    f"rule {rule_id!r} pass state: "
                    f"expected={expectation['passed']}, actual={actual['passed']}"
                ),
            )
            self.assertEqual(
                actual["reason_code"],
                expectation["reason_code"],
                msg=(
                    f"rule {rule_id!r} reason code: "
                    f"expected={expectation['reason_code']}, actual={actual['reason_code']}"
                ),
            )


def _load_suite(loader: unittest.TestLoader) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    case_files = sorted(CASES_DIR.glob("*.json"))
    if not case_files:
        raise SystemExit(f"no case files found under {CASES_DIR}")
    for case_path in case_files:
        cls_name = f"Case_{case_path.stem}"
        cls = type(
            cls_name,
            (_CaseAssertion,),
            {"_case_path": str(case_path)},
        )
        tests = loader.loadTestsFromTestCase(cls)
        suite.addTests(tests)
    return suite


def main() -> int:
    loader = unittest.TestLoader()
    suite = _load_suite(loader)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
