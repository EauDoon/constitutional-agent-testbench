# Changelog

## Version 0.5.18 - 28-09-2026

- Reject duplicate JSON object members in eval case and policy files. The
  runner used `json.load`, which keeps the last duplicate and continues, so a
  repeated `policy_path`, response field, or `passed` flag was silently
  dropped. Those files now use the strict loader. A boolean case file is still
  `EvalCaseError`, not a JSON syntax error.

## Version 0.5.17 - 28-09-2026

- Reject a non-object eval case before the runner subscripts it. A boolean,
  null, array, number, or string case file raised `TypeError`. An `expected`
  value or `expected.rules` value that is not an object failed the same way
  later in the case. Those fixtures now raise `EvalCaseError`. Checked-in
  object cases are unchanged.

## Version 0.5.16 - 28-09-2026

- Do not report a reordered `one_of` allowed set as a modified rule.
  Membership does not depend on order, but `compare-policies` compared the
  arrays as sequences, so `[1, 2]` and `[2, 1]` were `modified`. A strictly
  wider set is still modified. An `equals` array reorder is still modified,
  because array order is part of that constraint. Added rules stay in `added`.

## Version 0.5.15 - 28-09-2026

- Copy each nested constraint value on its own. `deepcopy` memos a repeated
  object, so one nested object used in two places inside an `equals` value or
  across `one_of` values stayed shared after validation. Editing one occurrence
  changed the other and could change a later evaluation. The caller's original
  objects stay untouched, and exported rules are copied the same way.

## Version 0.5.14 - 28-09-2026

- Copy each nested JSON value inside a validated suite case on its own.
  `deepcopy` memos a repeated object, so one nested object stored under two
  response keys stayed shared after the per-case copy. Editing one key changed
  the other and could change a later evaluation. The caller's original objects
  stay untouched.

## Version 0.5.13 - 28-09-2026

- List only finite-domain rules in a `DISJOINT_CONSTRAINTS` finding. A
  `required_field` on the same path was included even though it has no allowed
  set and does not make the domains disjoint. The conflict is unchanged, so
  `--strict-exit` still fails. Duplicate-only findings still do not.

## Version 0.5.12 - 28-09-2026

- Classify an unknown option before a missing `--output` value or an invalid
  command. `evaluate policy response --output --bogus` was reported as a missing
  argument, and `--output not-a-command` was reported as an unknown command.
  `--output --strict-exit` is still a missing argument because both flags are
  real. Help text and exit code 2 are unchanged.

## Version 0.5.11 - 28-09-2026

- Report an overflowing numeric literal as invalid strict JSON. `1e309` becomes
  a non-finite float after parsing, so it never hits the `Infinity` token
  rejection and was labeled as a structural size limit. Nesting, node, and byte
  limits still use the structural-limit error. The `Infinity` token is unchanged.

## Version 0.5.10 - 28-09-2026

- Reject a whitespace-only `--output` path. An empty string was already an
  error, but a path of spaces, tabs, newlines, Unicode spaces, a zero-width
  space, or a BOM was accepted and written as a filename. Those paths now use
  the same empty-path error, and the check still happens before any JSON input
  is read.
- A path that contains a real filename character, including spaces around that
  name, is unchanged. `-` remains the separate dash error.

## Version 0.5.9 - 28-09-2026

- Report `diff-suites` `order_changed` from the relative order of case ids that
  exist in both corpora. Adding or removing a case made the full id lists
  differ, so the diff said the corpus was reordered when the shared cases kept
  their order. Added and removed ids stay in their own fields. Reversing shared
  cases is still an order change. Strict exit still follows `identical`.

## Version 0.5.8 - 28-09-2026

- Report `order_changed` from the relative order of rules that exist in both
  policies. Adding or inserting a rule made the full identifier lists differ, so
  the migration report said the rules were reordered when the shared rules kept
  their order. Added and removed rules stay in their own fields. A real swap of
  shared rules is still `order_changed`.

## Version 0.5.7 - 28-09-2026

- Treat `one_of` rules with the same allowed set as duplicate constraints even
  when the values are listed in different orders. Membership does not depend on
  order, but the duplicate check compared the arrays as sequences, so `[1, 2]`
  and `[2, 1]` produced no finding. Object key order was already ignored.
- A strictly wider allowed set is still a different constraint. Duplicate-only
  findings still do not fail `--strict-exit`.

## Version 0.5.6 - 28-09-2026

- Copy each suite case on its own. `validate_suite` used one `deepcopy`, which
  keeps a repeated object shared, so two cases built from the same response
  stayed aliased. Editing one owned case changed the other and could change a
  later evaluation of both.
- The caller's original objects stay untouched, and JSON-loaded suites are unchanged.

## Version 0.5.5 - 28-09-2026

- Keep an unknown assertion identifier out of `contradictory_verdict`. A stale
  rule asserted as failed was treated as a verdict contradiction even when every
  declared rule agreed with `expected_passed`. Unknown identifiers stay in
  `unknown_rule_ids`, so the assertion gate still fails.
- A declared rule that disagrees with the overall verdict is still contradictory.

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
