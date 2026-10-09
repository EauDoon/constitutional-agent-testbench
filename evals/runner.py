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

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = Path(__file__).resolve().parent / "cases"
sys.path.insert(0, str(REPO_ROOT / "src"))

from constitutional_agent_testbench import evaluate_response, validate_policy  # noqa: E402
from constitutional_agent_testbench.common import load_json  # noqa: E402


class EvalCaseError(Exception):
    """Raised when an eval case file is not a usable case document."""


CASE_KEYS = frozenset({"id", "source", "policy_path", "input", "expected"})
EXPECTED_KEYS = frozenset({"passed", "rules"})
RULE_EXPECTATION_KEYS = frozenset({"passed", "reason_code"})


def case_policy_path(value, name: str) -> Path:
    """Resolve a case's policy_path, refusing anything outside the repository."""

    if not isinstance(value, str) or not value:
        raise EvalCaseError(f"{name} policy_path must be a non-empty string")
    if Path(value).is_absolute() or Path(value).anchor:
        raise EvalCaseError(f"{name} policy_path must be relative to the repository root")
    root = REPO_ROOT.resolve()
    resolved = (root / value).resolve()
    if not resolved.is_relative_to(root):
        raise EvalCaseError(f"{name} policy_path must stay inside the repository")
    return resolved


def load_case_document(path: Path) -> dict:
    """Load one case file and reject malformed fields before they are used.

    Non-object fixtures are rejected before subscripting, unknown keys are
    refused, and every field the runner reads is type-checked here so a bad
    fixture raises EvalCaseError naming the file and field.
    """

    document = load_json(path)
    name = path.name
    if not isinstance(document, dict):
        raise EvalCaseError(f"{name} must be a JSON object")
    unknown = sorted(set(document) - CASE_KEYS)
    if unknown:
        raise EvalCaseError(f"{name} has unsupported keys: {', '.join(unknown)}")
    expected = document.get("expected")
    if not isinstance(expected, dict):
        raise EvalCaseError(f"{name} expected must be a JSON object")
    unknown = sorted(set(expected) - EXPECTED_KEYS)
    if unknown:
        raise EvalCaseError(f"{name} expected has unsupported keys: {', '.join(unknown)}")
    rules = expected.get("rules", {})
    if not isinstance(rules, dict):
        raise EvalCaseError(f"{name} expected.rules must be a JSON object")
    for rule_id, expectation in rules.items():
        if not isinstance(expectation, dict) or set(expectation) != RULE_EXPECTATION_KEYS:
            raise EvalCaseError(
                f"{name} expected.rules.{rule_id} must be a JSON object with exactly "
                "passed and reason_code"
            )
        if not isinstance(expectation["reason_code"], str):
            raise EvalCaseError(f"{name} expected.rules.{rule_id}.reason_code must be a string")
    if "passed" not in expected:
        raise EvalCaseError(f"{name} expected.passed is required")
    if "policy_path" not in document or "input" not in document:
        raise EvalCaseError(f"{name} requires policy_path and input")
    if document.get("id") != path.stem:
        raise EvalCaseError(f"{name} id must be the string {path.stem!r}")
    if "source" in document and not isinstance(document["source"], str):
        raise EvalCaseError(f"{name} source must be a string")
    case_policy_path(document["policy_path"], name)
    if not isinstance(document["input"], dict):
        raise EvalCaseError(f"{name} input must be a JSON object")
    return document


def load_policy_document(path: Path):
    """Load a case policy through the same strict JSON boundary as the CLI."""

    return validate_policy(load_json(path))


def _load_case(path: Path) -> dict:
    return load_case_document(path)


def passed_states_match(actual, expected, label: str) -> None:
    """Compare pass states without treating JSON numbers as booleans.

    ``True == 1`` and ``False == 0`` in Python, so a numeric expectation would
    otherwise match a real boolean verdict.
    """

    if type(actual) is not bool or type(expected) is not bool or actual is not expected:
        raise AssertionError(f"{label}: expected={expected!r}, actual={actual!r}")


class _CaseAssertion(unittest.TestCase):
    longMessage = True

    def setUp(self) -> None:
        self.case_path = Path(getattr(self, "_case_path"))
        self.case = _load_case(self.case_path)
        self.policy_path = case_policy_path(self.case["policy_path"], self.case_path.name)
        self.policy = load_policy_document(self.policy_path)
        self.result = evaluate_response(self.policy, self.case["input"])

    def test_overall_verdict_matches_expected(self) -> None:
        expected = self.case["expected"]
        passed_states_match(
            self.result["passed"],
            expected["passed"],
            f"overall verdict: expected={expected['passed']}, actual={self.result['passed']}",
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
            passed_states_match(
                actual["passed"],
                expectation["passed"],
                (
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
