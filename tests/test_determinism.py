"""Prove evaluation output does not depend on Python's hash seed.

The package advertises deterministic evaluation and stable JSON output. Set and
dict iteration order is the obvious way that promise could quietly break, so this
module recomputes the public results in a fresh interpreter under several
``PYTHONHASHSEED`` values and requires byte-identical serialized output.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HASH_SEEDS = ("0", "1", "12345")

_CHILD_PROGRAM = """
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "src"))

from constitutional_agent_testbench import (
    check_order_conformance,
    check_suite,
    compare_policies,
    deduplicate_suite,
    evaluate_response,
    generate_rule_probes,
    generate_synthetic_cases,
    lint_policy,
    reduce_suite,
    suite_coverage,
    triage_suite,
    validate_policy,
)

def load(relative):
    with (root / relative).open(encoding="utf-8") as handle:
        return json.load(handle)

policy = validate_policy(load("examples/policy.json"))
passing = load("examples/passing-response.json")
failing = load("examples/failing-response.json")
suite = load("examples/assertion-suite.json")
migration = load("examples/migration-policy.json")
captured = load("examples/assertion-suite.json")

artifacts = {
    "evaluate_passing": evaluate_response(policy, passing),
    "evaluate_failing": evaluate_response(policy, failing),
    "check_order_passing": check_order_conformance(policy, passing),
    "check_order_failing": check_order_conformance(policy, failing),
    "synthetic": generate_synthetic_cases(policy),
    "probes": generate_rule_probes(policy),
    "lint": lint_policy(policy),
    "coverage": suite_coverage(policy, suite),
    "compare": compare_policies(policy, migration, suite),
    "triage": triage_suite(policy, suite),
    "check_suite": check_suite(policy, suite),
    "reduce": reduce_suite(policy, captured),
    "deduplicate": deduplicate_suite(captured),
}

serialized = json.dumps(artifacts, sort_keys=True, ensure_ascii=False)
print(hashlib.sha256(serialized.encode("utf-8")).hexdigest())
"""


def _run_child(hash_seed):
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = hash_seed
    completed = subprocess.run(
        [sys.executable, "-c", _CHILD_PROGRAM, str(ROOT)],
        capture_output=True,
        text=True,
        env=environment,
        cwd=ROOT,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"child run under PYTHONHASHSEED={hash_seed} failed with "
            f"{completed.returncode}:\n{completed.stderr}"
        )
    return completed.stdout.strip()


class HashSeedDeterminismTests(unittest.TestCase):
    """A fixed policy, response, and corpus must serialize identically."""

    def test_artifacts_are_identical_across_hash_seeds(self):
        digests = {seed: _run_child(seed) for seed in HASH_SEEDS}
        baseline = digests[HASH_SEEDS[0]]
        self.assertTrue(baseline)
        for seed in HASH_SEEDS[1:]:
            with self.subTest(hash_seed=seed):
                self.assertEqual(
                    digests[seed],
                    baseline,
                    msg=(
                        f"output changed between PYTHONHASHSEED="
                        f"{HASH_SEEDS[0]} and {seed}; set or dict iteration "
                        f"order is leaking into a result, trace, or report"
                    ),
                )


if __name__ == "__main__":
    unittest.main()
