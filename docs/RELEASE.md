# Constitutional Agent Testbench v0.5.17 release assets

The v0.5.17 package metadata is recorded in
`release/v0.5.17-manifest.json`. The pinned release workflow builds a wheel and
source distribution, lists both archives, writes SHA-256 files, and retains the
assets for 14 days. It does not create or publish a remote release.

The eval runner rejects a case file that is not a JSON object, including a boolean document and a non-object `expected` or `expected.rules` value, instead of raising `TypeError`.

`compare-policies` treats a reordered `one_of` allowed set as the same rule. A wider set is still modified, and an `equals` array reorder is still modified.

Validated `equals` and `one_of` values copy each nested occurrence separately, so a repeated object does not stay shared inside the policy.

A validated suite case copies each nested value separately. A repeated object under two response keys no longer stays shared.

A disjoint-constraint finding names only the rules that have finite domains. A presence rule on the same path stays out of that finding. The conflict itself still fails `--strict-exit`.

An unknown option is reported as an unknown option when it follows `--output`
or appears before a token that is not a command. A real flag such as
`--strict-exit` without its value is still a missing argument.

A numeric literal that overflows to a non-finite value, such as `1e309`, is
rejected as invalid strict JSON. It is not reported as a structural size limit.
The `Infinity` token stays invalid strict JSON as well.

`--output` rejects a whitespace-only path, including Unicode spaces and format
characters, with the same empty-path error as `""`. The check happens before
any JSON input is read.

`diff-suites` sets `order_changed` only when case ids present in both corpora
change relative order. Adding or removing a case is not a reorder.

The exhaustive and `INCONCLUSIVE_NONDETERMINISTIC` PrecedenceTrace reports share one
`coverage` contract, so a consumer can read the same fields from either. Values that
cannot be known after an early stop, such as incomplete-order counts, are reported as
`null` alongside the unresolved `conforms_within_coverage`.

The distribution installs two console commands, `constitutional-agent-testbench`
and `constitutional-agent-testbench-playground`. A third entry point that pointed
at the repository-only `evals` package was removed in 0.5.2 because the package is
outside `src/` and ships in neither archive; the evaluation runner stays available
inside a checkout as `python -m evals.runner`.

The strict-exit contract is backwards compatible: existing commands keep exit code zero for valid output unless `--strict-exit` is supplied. With the flag, conformance is zero, valid nonconformance or drift is one, and invalid or unresolved input is two.

The offline playground uses the same policy and evaluator semantics. Labeled
editors show a live pass/fail verdict plus the JSON result. It never writes
during evaluation. The Export result button opens an explicit save dialog and
is the only write path.
