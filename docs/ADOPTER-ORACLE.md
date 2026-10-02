# Independent synthetic adopter oracle

The [release-approval fixtures](../examples/release-approval/) describe a small
consumer contract: a summary must be present, status must be allowed, `dry_run`
must be the JSON boolean `false`, and `queued_actions` must be an empty JSON list.
The candidate policy widens status membership from `approved` to also allow
`approved-with-conditions`. These are synthetic data. No release, approval, or
queued action executes, and this is not evidence from a production adopter.

An independent AI review agent authored the policies, both suites, and migration
expectations on 02-10-2026 before running any evaluator against these cases. The
review used the public rule and report contracts at commit
`99c53f96ed7e746c2298e803960c78f6d591b6c8`, including `evaluator.py`, `compare.py`,
`suite.py`, and existing policy/assertion examples. No evaluator or
`capture-assertions` output supplied the expected answers. This separates
expectation authoring from execution; the oracle is AI-authored, not a human or
external security audit, and does not come from a production adopter.

Each suite contains twelve cases with a verdict and all four rule outcomes
explicitly specified, including reason codes. The cases distinguish `false`
from `0`, `true`, and `"false"`, and an empty list from an empty object. A null
summary passes because `required_field` tests presence only; a missing summary
fails. Missing all fields fails all four rules. The candidate still rejects
`rejected` status.

The independently expected migration has **one verdict change and two
expectation regressions**. `conditional-status` changes from fail to pass.
`conditional-status-with-queue` stays fail because its queue is nonempty, but
its status reason changes from `VALUE_NOT_ALLOWED` to `RULE_SATISFIED`.
Regressions describe disagreement with the initial assertions, not a policy
recommendation. The separately authored candidate suite matches the changed
contract explicitly.

Run `python scripts/verify_installed_workflow.py` after installing the package.
The existing installed workflow copies these fixtures to a temporary directory,
validates both policy/suite pairs, checks every verdict and reason code through
the installed console command, verifies strict exits, compares both full
migration reports, and round-trips receipts and replay bundles. It compares JSON
types strictly, so boolean and number outcomes cannot substitute for one another.
The source distribution includes the fixtures and runner; they are not runtime
dependencies or bundled wheel package data.

If actual output disagrees, preserve the original fixtures and investigate the
contract discrepancy. Do not overwrite the oracle with captured observations
to make the check pass. Further cases require separately reviewed expectations.
The twelve cases do not claim exhaustive coverage or establish policy safety.
