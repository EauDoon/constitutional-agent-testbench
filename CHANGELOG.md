# Changelog

## Version 0.5.4 - 28-09-2026

- Report an unknown option as an unknown option even when a required path is also
  absent. argparse mentions the missing positional first, so `evaluate --bogus`
  was classified as a missing argument and the invalid flag looked accepted until
  the paths were supplied.
- Preserve exit code 2, the path-free `INVALID_COMMAND` contract, and the missing-argument
  message for a real flag such as `--strict-exit` that is present without its paths.

## Version 0.5.3 - 28-09-2026

- Give the exhaustive and `INCONCLUSIVE_NONDETERMINISTIC` PrecedenceTrace reports one
  `coverage` contract. Both are stamped `report_schema_version` 1.0, but the
  incomplete report omitted `incomplete_orders`, `observed_work_bytes` and
  `rule_results_complete`, while the exhaustive report omitted `orders_completed` and
  `orders_attempted`, so a consumer written against one shape raised `KeyError` on the
  other. Fields that cannot be known after a run stops early are now reported as
  `null`, which matches the unresolved `conforms_within_coverage` convention the module
  already uses. No existing field changed value and no key was removed.
- Add a test that pins the shared key set and the field values for both report shapes.
- Preserve policy and suite schemas, evaluation semantics, reason codes, PrecedenceTrace
  verdicts, witnesses, and the two console commands. This patch changes the reported
  `coverage` fields of `check-order` only.

## Version 0.5.2 - 28-09-2026

- Remove the `constitutional-agent-testbench-evals` console script. It pointed at
  the repository-only `evals` package, which is outside `src/` and ships in neither
  the wheel nor the source distribution, so the installed command always failed with
  `ModuleNotFoundError: No module named 'evals'`. The evaluation runner remains
  available in a checkout as `python -m evals.runner`.
- Add a packaging test that fails when a declared console script targets a
  top-level package the distribution does not ship.
- Preserve policy and suite schemas, evaluation semantics, reason codes, and the two
  remaining console commands. This patch changes the installed command surface only.

## Version 0.5.1 - 26-09-2026

- Emit CLI JSON as UTF-8 with LF directly to binary process streams, preserving
  Unicode fixtures and receipt bindings even when the terminal encoding would
  replace, drop, or reject characters. Text-only embedding remains supported.
- Verify the installed adopter workflow outside the checkout, including
  assertion-sensitive migration, deterministic exports, independent replay,
  altered-evidence rejection, strict JSON, and value-free reports.
- Preserve policy/suite formats, receipt digests, public reason codes and strict
  regression exit semantics. This patch changes transport, not evaluation.

## Version 0.5.0 - 11-09-2026

- Validate and import explicit fixture batches without deriving expected outcomes.
- Capture complete rule assertions only after existing expectations match.
- Review corpus revisions without copying values, and deduplicate exact fixtures.
- Shard suites deterministically and select observed regression or verdict cohorts.
- Audit stale assertion IDs, incompatible reason codes, and contradictory verdicts.
- Classify migration regressions and recoveries including reason-code-only drift.
- Preflight policy conflicts, fixture consistency, assertions, and regressions together.
- Exercise preparation through replay with CLI error, recovery, and export protection checks.
- Preserve policy and suite schemas, evaluator behavior, offline runtime, and atomic export permissions.

## Version 0.4.0 - 10-09-2026

- Inspect policy structure and fixture duplication without candidate values.
- Merge, select, triage, and deterministically reduce regression corpora.
- Assert exact rule outcomes and reasons in opt-in suite 1.1, preserving 1.0 reports.
- Bind full corpora to recomputable receipts and portable replay bundles.
- Export JSON atomically while rejecting input-path aliases before reading inputs.
- Preserve policy/evaluator semantics, standard-library runtime, and offline operation.

## Version 0.3.0 - 09-09-2026

- Added conservative authoring diagnostics and value-free traversal explanations.
- Added strict, bounded fixture suites, observed outcome coverage, and policy migration comparisons.
- Added verified missing-field and wrong-value probes with collateral failures reported explicitly.
- Added SHA-256 digest-bound evaluation receipts and full recomputation verification.
- Added eight CLI commands and public library APIs for the operator workflow.
- Preserved policy schema 1.0, existing evaluation results, and PrecedenceTrace semantics.
- Added executable synthetic fixtures and documented limits, strict exits, and receipt trust boundaries.

## Version 0.2.0 - 27 July 2026

- Added PrecedenceTrace as an exhaustive peer-rule order-conformance mode.
- Added separate projections for semantic outcome, reason evidence,
  participation and presentation order.
- Added three-run nondeterminism screening for every permutation and
  fail-closed refusal above seven rules.
- Added deterministic adjacent-swap witnesses where a drift is locally
  visible, with bounded endpoint and adjacent-swap-path evidence when shared
  rule identities occur only in disconnected order regions.
- Added the `check_order_conformance` library API and `check-order`
  command-line interface.
- Bound evaluator participation to declared rules and made stable incomplete
  participation `INCOMPLETE_RULE_COVERAGE` rather than conforming.
- Rejected foreign, duplicate, kind/path-mismatched, and aggregate-incoherent
  evaluator results.
- Added bounded in-memory inputs and evaluator results plus compound-drift
  reporting and explicit input, result, call-count, incomplete-order, and
  charged-work accounting.
- Made participation, outcome, and reason-evidence comparisons orthogonal for
  shared rule identities and aggregate pass comparisons conditional on equal
  participation; generalized nondeterminism witnesses to every order; and
  added an explicit 1,000,000-byte report cap with coverage accounting.
- Added planted last-writer, evidence-overwrite, short-circuit,
  nondeterministic and three-way-interaction controls.

Public source release on 27 July 2026.

## Version 0.1.0

- Added strict version 1.0 policy validation.
- Added deterministic complete rule evaluation and stable reason codes.
- Added verified synthetic passing and failing case generation.
- Added the local standard-library-only command-line interface.
