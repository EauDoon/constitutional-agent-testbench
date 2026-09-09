# Changelog

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
